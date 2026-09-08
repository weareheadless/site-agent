"""Application boundary for typed design runs.

This module owns run creation and lifecycle coordination.  Git, browser, and
provider details stay behind the hands/brain boundaries.
"""

from __future__ import annotations

import os
import re
import uuid
import hashlib
import base64
from dataclasses import replace
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any

from ..core.contracts import Artifact, ArtifactKind, ContractError, safe_payload, utc_now
from ..core.design_contracts import (
    BuildTarget,
    DesignContextSnapshot,
    DesignCandidateReceipt,
    DesignManifest,
    DesignSourceBinding,
    DesignRunStatus,
    DesignBrief,
    PageIntake,
    PageBuildRequest,
    SiteIntake,
    QualityReport,
    VisualCritiqueReport,
    canonical_hash,
    safe_relative_path,
)
from ..core.reflect import approved_notes, effective_persona
from ..brain.self_model import current_self
from ..hands.design_quality import BrowserQualityAdapter, QualityPolicy, run_quality_gates
from ..brain.design_brief import assess_intake, compile_brief
from ..brain.design_guidance import DesignSkillSet, load_design_skills
from ..brain.page_strategy import native_homepage_request
from ..hands.site_build import (
    ASTRO_REACT_PROFILE,
    ASTRO_REACT_TOOLCHAIN_DEPENDENCIES,
    PELICAN_BASELINE_PROFILE,
    build_site,
)


class DesignServiceError(ValueError):
    """A design workflow cannot be safely created or transitioned."""


class DesignRunNotFound(DesignServiceError):
    pass


DEEPSEEK_DESIGN_MODEL = "deepseek/deepseek-v4-flash-vision-exp"


def _resolved(path: str | Path) -> Path | None:
    value = str(path or "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve(strict=False)


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _public_page_path(value: Any) -> str:
    """Map intake route labels to the HTML paths emitted by the site build."""
    path = str(value or "").strip().replace("\\", "/").lstrip("/")
    if path in {"", "."}:
        return "index.html"
    if path.endswith("/"):
        return f"{path}index.html"
    if "." not in Path(path).name:
        return f"{path}.html"
    return path


class DesignService:
    def __init__(
        self,
        memory,
        *,
        config: dict[str, Any] | None = None,
        builder=None,
        skill_set: DesignSkillSet | None = None,
        media_service=None,
    ) -> None:
        self.memory = memory
        self.config = config or {}
        self.builder = builder
        self.skill_set = skill_set
        self.media_service = media_service

    def _record_design_artifact(
        self,
        *,
        kind: ArtifactKind,
        run_id: str,
        title: str,
        summary: str,
        provider_id: str,
        content_hash: str,
        preview_data: Mapping[str, Any],
    ) -> int:
        artifact = self.memory.create_artifact(Artifact(
            kind=kind,
            title=title[:500],
            summary=summary[:500],
            renderer="design_run",
            capability_id="design",
            provider_id=provider_id[:180] or "host",
            content_hash=content_hash,
            preview_data={"run_id": run_id, **dict(preview_data)},
        ))
        if artifact.artifact_id is None:
            raise DesignServiceError("design artifact was created without an id")
        return artifact.artifact_id

    def _transcript_hash(self, transcript_path: str) -> str:
        path = Path(str(self.config.get("data_dir") or ".")) / str(transcript_path or "")
        try:
            if path.is_file():
                return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
        return canonical_hash({"transcript_path": str(transcript_path or "")})

    def create_run(
        self,
        site_intake: SiteIntake,
        *,
        mode: str = "production_candidate",
        base_sha: str = "",
        candidate_ref: str = "",
        publishable: bool | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        operation_kind: str = "initial_build",
        source_candidate_sha: str = "",
        owner_request: str = "",
        conversation_id: int | None = None,
        source_message_id: int | None = None,
        chat_job_id: int | None = None,
        intake_session_id: str | None = None,
        intake_revision_id: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(site_intake, SiteIntake):
            raise DesignServiceError("site_intake must be a validated SiteIntake")
        if mode not in {"production_candidate", "local_experiment"}:
            raise DesignServiceError("mode is invalid")
        run_id = run_id or f"design-{uuid.uuid4().hex}"
        if publishable is None:
            publishable = mode == "production_candidate"
        if mode == "local_experiment" and publishable:
            raise DesignServiceError("local_experiment must not be publishable")
        if not candidate_ref:
            namespace = "refs/ada-design-lab" if mode == "local_experiment" else "refs/ada-design"
            candidate_ref = f"{namespace}/{run_id}"
        try:
            run = self.memory.create_design_run(
                run_id=run_id,
                mode=mode,
                status=DesignRunStatus.CREATED.value,
                intake_json=site_intake.to_dict(),
                intake_hash=site_intake.content_hash,
                base_sha=base_sha,
                publishable=publishable,
                candidate_ref=candidate_ref,
                parent_run_id=parent_run_id,
                operation_kind=operation_kind,
                source_candidate_sha=source_candidate_sha,
                owner_request=owner_request,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                chat_job_id=chat_job_id,
                intake_session_id=intake_session_id,
                intake_revision_id=intake_revision_id,
            )
            self.memory.add_design_run_event(run_id, "created", "Design run created.", {
                "mode": mode,
                "intake_hash": site_intake.content_hash,
            })
        except (ContractError, KeyError, ValueError) as exc:
            raise DesignServiceError(str(exc)) from exc
        return self.get_run(run_id)

    def capture_context_snapshot(
        self,
        run_id: str,
        *,
        owner_request: str | None = None,
        conversation_id: int | None = None,
        source_message_id: int | None = None,
        chat_job_id: int | None = None,
        context_extra: Mapping[str, Any] | None = None,
    ) -> DesignContextSnapshot:
        """Freeze all mutable owner and site context before planning or building."""
        run = self.get_run(run_id)
        if not run.get("base_sha"):
            raise DesignServiceError("an immutable base SHA is required before capturing context")
        skill_set = self.skill_set or load_design_skills()
        intake = SiteIntake.from_dict(run.get("intake_json") or {})
        conversation_id = conversation_id if conversation_id is not None else run.get("conversation_id")
        source_message_id = source_message_id if source_message_id is not None else run.get("source_message_id")
        chat_job_id = chat_job_id if chat_job_id is not None else run.get("chat_job_id")
        request_text = str(owner_request or run.get("owner_request") or "").strip()
        if not request_text:
            request_text = "Create a design candidate from the validated site intake."

        conversation: list[dict[str, Any]] = []
        attachments: list[dict[str, Any]] = []
        if conversation_id is not None:
            try:
                messages = self.memory.get_messages(int(conversation_id), limit=40)
            except (TypeError, ValueError):
                messages = []
            for message in messages:
                item = safe_payload({
                    "ts": message.get("ts"),
                    "role": message.get("role"),
                    "text": str(message.get("text") or "")[:20_000],
                }, max_bytes=30_000)
                conversation.append(item)
                for attachment in message.get("attachments") or ():
                    if isinstance(attachment, Mapping):
                        attachments.append(safe_payload(dict(attachment), max_bytes=10_000))

        observations = self.memory.recent_observations(limit=80)
        private_sources = {"self", "dream", "awaken", "inner_voice", "identity_shift"}
        research_sources = {"rss", "news", "research", "crawlseo", "search", "web"}
        memories = [safe_payload(row, max_bytes=30_000) for row in observations
                    if row.get("source") not in private_sources and row.get("source") not in research_sources]
        research = [safe_payload(row, max_bytes=30_000) for row in observations
                    if row.get("source") in research_sources]
        knowledge = []
        list_knowledge = getattr(self.memory, "list_business_knowledge", None)
        if callable(list_knowledge):
            knowledge = [safe_payload(row, max_bytes=30_000) for row in list_knowledge(status="approved", limit=40)]

        site = self.config.get("site") or {}
        design_engine = self.config.get("design_engine") or {}
        llm = self.config.get("llm") or {}
        persona = self.config.get("persona") or {}
        raw_assets = list(intake.assets) + list(site.get("asset_inventory") or ())
        raw_verified = list(site.get("verified_facts") or ())
        raw_verified.extend([
            f"Business name: {intake.business.get('name')}",
            f"Offer: {intake.business.get('offer_summary')}",
            *[f"Service: {item}" for item in intake.business.get("primary_services") or ()],
        ])
        raw_unknowns = list(intake.unknowns) + list(site.get("unknowns") or ())
        raw_prohibited = list(site.get("prohibited_claims") or ())
        taboo = persona.get("taboo") or ()
        raw_prohibited.extend(taboo if isinstance(taboo, (list, tuple)) else [taboo])
        raw_capabilities = design_engine.get("capabilities") or self.config.get("capabilities") or ()
        if isinstance(raw_capabilities, Mapping):
            raw_capabilities = [{"name": key, **(value if isinstance(value, Mapping) else {"value": value})}
                                for key, value in raw_capabilities.items()]
        if not raw_capabilities:
            try:
                from ..hands.frontend_dependencies import available_frontend_libraries

                raw_capabilities = available_frontend_libraries(self.config)
            except Exception:  # noqa: BLE001 - capability discovery is best effort at capture time
                raw_capabilities = ()
        raw_viewports = design_engine.get("required_viewports") or ((self.config.get("design_engine") or {}).get("quality") or {}).get("viewports") or ()
        model = str(design_engine.get("model") or llm.get("model") or DEEPSEEK_DESIGN_MODEL)
        provider = str(design_engine.get("provider") or llm.get("provider") or "openrouter")
        provider_base_url = str(design_engine.get("base_url") or llm.get("base_url") or "").strip()
        provider_env_name = str(
            design_engine.get("api_key_env")
            or (self.config.get("env") or {}).get("llm_api_key")
            or ""
        ).strip()
        execution_profile = {
            "model": model,
            "provider": provider,
            "repair_attempts": int(design_engine.get("repair_attempts", 0)),
            "max_tokens": int(
                design_engine.get("max_tokens", llm.get("max_tokens", 16_384))
            ),
            "viewports": safe_payload({"items": list(raw_viewports)}, max_bytes=20_000)["items"],
            "builder": {
                key: value
                for key, value in {
                    "timeout_seconds": int((self.config.get("builder") or {}).get("timeout_seconds", 1800)),
                    "provider_timeout_seconds": int((self.config.get("builder") or {}).get("provider_timeout_seconds", 2100)),
                    "provider_chunk_timeout_seconds": int((self.config.get("builder") or {}).get("provider_chunk_timeout_seconds", 180)),
                    "output_tokens": int((self.config.get("builder") or {}).get("output_tokens", 8192)),
                    "reasoning_effort": str((self.config.get("builder") or {}).get("reasoning_effort", "low")),
                }.items()
                if value is not None
            },
            "provider_base_url": provider_base_url,
            "provider_env_name": provider_env_name,
            "target": {
                "mode": run["mode"],
                "candidate_ref": run.get("candidate_ref") or "",
                "publishable": bool(run.get("publishable")),
                "push_mode": "none" if run["mode"] == "local_experiment" else str(design_engine.get("push_mode") or "none"),
            },
        }
        quality_config = design_engine.get("quality") or {}
        if isinstance(quality_config, Mapping):
            configured_content = quality_config.get("required_content")
            if configured_content is None:
                configured_content = [
                    str(intake.business.get("offer_summary") or "").strip(),
                    *(
                        str(item).strip()
                        for item in (intake.business.get("primary_services") or ())
                        if str(item).strip()
                    ),
                ]
            quality_identity = {
                "output_dir": str(quality_config.get("output_dir") or "output"),
                "required_pages": list(quality_config.get("required_pages") or intake.site.get("required_pages") or ()),
                "required_content": list(configured_content or ()),
                "contact_destination_unavailable": intake.conversion.get("not_available") is True
                and not str(intake.conversion.get("contact_destination") or "").strip(),
                "allowed_patterns": list(quality_config.get("allowed_patterns") or site.get("writable_patterns") or ()),
                "allowed_hard_denied_paths": list(quality_config.get("allowed_hard_denied_paths") or ()),
                "prohibited_paths": list(quality_config.get("prohibited_paths") or ()),
                "browser_required": bool(quality_config.get("browser", quality_config.get("browser_required", False))),
                "visual_critic": bool(quality_config.get("visual_critic", False)),
                "native_source_required": bool(quality_config.get("native_source_required", False)),
                "originality_required": bool(quality_config.get("originality_required", False)),
                "internal_scaffold_fingerprints": list(quality_config.get("internal_scaffold_fingerprints") or ()),
                "required_font_families": list(
                    quality_config.get("required_font_families")
                    or quality_config.get("required_fonts")
                    or ()
                ),
                "approved_font_files": [
                    {
                        key: item.get(key)
                        for key in ("path", "destination", "family", "sha256")
                        if item.get(key) is not None
                    }
                    for item in (
                        quality_config.get("approved_font_files")
                        or quality_config.get("approved_fonts")
                        or ()
                    )
                    if isinstance(item, Mapping)
                ],
                "build_command": quality_config.get("build_command"),
                "build_timeout_seconds": int(quality_config.get("build_timeout_seconds", 120)),
                "manifest_path": str(design_engine.get("manifest_path") or quality_config.get("manifest_path") or ""),
                "ignored_pages": list(quality_config.get("ignored_pages") or ()),
                "viewports": list(raw_viewports),
            }
            execution_profile["quality_policy"] = {
                **quality_identity,
                "hash": canonical_hash(quality_identity),
            }
        source_clone = None
        try:
            source_clone = self.clone_path_for_run(run_id)
        except DesignServiceError:
            pass
        site_digest = str(site.get("site_digest") or "configured site intake and route inventory")
        measured_design = dict(site.get("measured_design") or design_engine.get("measured_design") or {})
        if source_clone is not None and (source_clone / ".git").exists():
            try:
                from ..hands.site_digest import cached as cached_site_digest
                from ..hands.template_tokens import cached as cached_template_tokens

                site_digest = cached_site_digest(source_clone, self.memory, ref=run["base_sha"]) or site_digest
                template_tokens = cached_template_tokens(source_clone, self.memory, ref=run["base_sha"])
                if template_tokens:
                    measured_design.setdefault("template_tokens", template_tokens)
            except Exception:  # noqa: BLE001 - a missing optional digest never blocks capture
                pass

        snapshot_data = safe_payload({
            "schema_version": 1,
            "captured_at": utc_now(),
            "conversation_id": conversation_id,
            "source_message_id": source_message_id,
            "chat_job_id": chat_job_id,
            "owner_request": request_text,
            "conversation": conversation,
            "effective_persona": effective_persona(self.config, self.memory),
            "self_model": current_self(self.memory),
            "approved_persona_notes": approved_notes(self.memory),
            "memories": memories,
            "research": research,
            "business_knowledge": knowledge,
            "attachments": attachments,
            "site_facts": {
                "business": intake.business,
                "audience": intake.audience,
                "conversion": intake.conversion,
                "brand": intake.brand,
                "site": intake.site,
                "constraints": intake.constraints,
                "provenance": intake.provenance,
            },
            "source_repository": str(site.get("repository") or site.get("repository_path") or ""),
            "base_sha": run["base_sha"],
            "site_digest": site_digest,
            "route_inventory": list(intake.site.get("required_pages") or ()),
            "current_content": site.get("current_content") or {},
            "asset_inventory": raw_assets,
            "measured_design": measured_design,
            "verified_facts": raw_verified,
            "unknowns": raw_unknowns,
            "prohibited_claims": [item for item in raw_prohibited if str(item).strip()],
            "capabilities": raw_capabilities,
            "execution_profile": execution_profile,
            **dict(context_extra or {}),
            "design_skill_set": skill_set.to_dict(include_content=False),
        }, max_bytes=300_000, preserve_keys={"output_tokens", "max_tokens", "planner_max_tokens", "template_tokens"})
        snapshot = DesignContextSnapshot.from_dict(snapshot_data)
        self.memory.update_design_run(
            run_id,
            context_snapshot=snapshot,
            owner_request=request_text,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            chat_job_id=chat_job_id,
        )
        stored = self.get_run(run_id)
        return DesignContextSnapshot.from_dict(stored["context_snapshot"])

    def create_experiment(
        self,
        site_intake: SiteIntake,
        *,
        experiment_root: str | Path,
        base_sha: str,
        run_id: str | None = None,
        owner_request: str = "",
        conversation_id: int | None = None,
        source_message_id: int | None = None,
        chat_job_id: int | None = None,
        intake_session_id: str | None = None,
        intake_revision_id: int | None = None,
    ) -> dict[str, Any]:
        """Create only local state after proving the experiment cannot overlap live state."""
        root = self.validate_experiment_root(experiment_root)
        try:
            BuildTarget.from_dict({
                "mode": "local_experiment",
                "base_sha": base_sha,
                "candidate_ref": f"refs/ada-design-lab/{run_id or 'pending'}",
                "push_mode": "none",
                "publishable": False,
                "clone_path": str(root),
            })
        except ContractError as exc:
            raise DesignServiceError(str(exc)) from exc
        root.mkdir(parents=True, exist_ok=True)
        run = self.create_run(
            site_intake,
            mode="local_experiment",
            base_sha=base_sha,
            candidate_ref=f"refs/ada-design-lab/{run_id or 'pending'}",
            publishable=False,
            run_id=run_id,
            owner_request=owner_request,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            chat_job_id=chat_job_id,
            intake_session_id=intake_session_id,
            intake_revision_id=intake_revision_id,
        )
        # Replace the temporary ref suffix only when a caller supplied no id.
        if run["candidate_ref"].endswith("/pending"):
            candidate_ref = f"refs/ada-design-lab/{run['run_id']}"
            run = self.memory.update_design_run(run["run_id"], candidate_ref=candidate_ref) or run
        self.memory.add_design_run_event(run["run_id"], "experiment", "Local-only experiment workspace reserved.", {
            "root": str(root),
            "push_mode": "none",
        })
        return self.get_run(run["run_id"])

    def create_technical_repair_run(
        self,
        parent_run_id: str,
        *,
        run_id: str | None = None,
        owner_request: str = "",
    ) -> dict[str, Any]:
        """Create a new run pinned to a retained candidate that needs repair.

        A failed run is intentionally terminal: its evidence remains immutable
        and it cannot be reopened in place.  Technical repair is the explicit
        child operation for a host or builder to repair that retained candidate
        while preserving the original run as the audit record.
        """
        parent = self.get_run(parent_run_id)
        if parent.get("operation_kind") == "technical_repair":
            raise DesignServiceError("a technical repair cannot create another repair child")
        if parent.get("status") not in {
            DesignRunStatus.FAILED.value,
            DesignRunStatus.INTERRUPTED.value,
            DesignRunStatus.INCOMPLETE.value,
            DesignRunStatus.NEEDS_REPAIR.value,
            DesignRunStatus.CANDIDATE_READY.value,
            DesignRunStatus.VALIDATING.value,
            DesignRunStatus.READY_FOR_REVIEW.value,
        }:
            raise DesignServiceError("parent design run is not available for technical repair")
        parent_sha = str(parent.get("candidate_sha") or "").strip().lower()
        if not parent_sha:
            raise DesignServiceError("parent design run has no retained candidate")

        child_id = str(run_id or f"technical-repair-{uuid.uuid4().hex}").strip()
        parent_ref = str(parent.get("candidate_ref") or "").strip()
        ref_prefix = parent_ref.rsplit("/", 1)[0] if "/" in parent_ref else (
            "refs/ada-design-lab" if parent.get("mode") == "local_experiment" else "refs/ada-design"
        )
        child = self.create_run(
            SiteIntake.from_dict(parent.get("intake_json") or {}),
            mode=str(parent.get("mode") or ""),
            base_sha=parent_sha,
            candidate_ref=f"{ref_prefix}/{child_id}",
            publishable=bool(parent.get("publishable")),
            run_id=child_id,
            parent_run_id=parent_run_id,
            operation_kind="technical_repair",
            source_candidate_sha=parent_sha,
            owner_request=str(owner_request or parent.get("owner_request") or "Repair the retained design candidate."),
            conversation_id=parent.get("conversation_id"),
            source_message_id=parent.get("source_message_id"),
            chat_job_id=parent.get("chat_job_id"),
            intake_session_id=parent.get("intake_session_id"),
            intake_revision_id=parent.get("intake_revision_id"),
        )

        if child["mode"] == "local_experiment":
            experiment = next(
                (
                    event for event in reversed(parent.get("events") or ())
                    if event.get("stage") == "experiment"
                ),
                None,
            )
            detail = (experiment or {}).get("detail") if isinstance(experiment, Mapping) else None
            if not isinstance(detail, Mapping) or not str(detail.get("root") or "").strip():
                raise DesignServiceError("parent local experiment has no retained workspace")
            self.memory.add_design_run_event(
                child_id,
                "experiment",
                "Reusing the isolated experiment workspace for technical repair.",
                {**dict(detail), "parent_run_id": parent_run_id, "source_candidate_sha": parent_sha},
            )

        self._advance(child_id, DesignRunStatus.ASSESSING_INTAKE, "Technical repair child created from the retained candidate.")
        request = self.prepare_initial_request(child_id)
        request_data = request.to_dict()
        content = dict(request_data.get("content") or {})
        content["technical_repair"] = {
            "parent_run_id": parent_run_id,
            "parent_candidate_sha": parent_sha,
            "parent_status": str(parent.get("status") or ""),
        }
        request_data["content"] = content
        request = PageBuildRequest.from_dict(request_data)

        planning = dict(self.get_run(child_id).get("planning_json") or {})
        parent_profile = self.build_profile_for_run(parent_run_id)
        if parent_profile:
            planning["build_profile"] = parent_profile
        planning["build_request"] = request.to_dict()
        # Persist the inherited profile before resolving the target. The target
        # owns the Astro allowlist for local repairs, so resolving it against
        # the pre-profile child would incorrectly fall back to Pelican paths.
        self.memory.update_design_run(child_id, planning_json=planning)
        target = self.build_target_for_run(child_id)
        planning["build_target"] = target.to_dict()
        self.memory.update_design_run(child_id, planning_json=planning)
        self.memory.add_design_run_event(child_id, "technical_repair_planned", "Technical repair is pinned to the retained candidate and ready to build.", {
            "parent_run_id": parent_run_id,
            "parent_candidate_sha": parent_sha,
            "candidate_ref": target.candidate_ref,
        })
        return {"run": self.get_run(child_id), "request": request.to_dict(), "target": target.to_dict()}

    def experiment_root_for_run(self, run_id: str) -> Path:
        """Return a dedicated local experiment directory outside live state."""
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id or Path(safe_run_id).name != safe_run_id or ".." in Path(safe_run_id).parts:
            raise DesignServiceError("design run id is unsafe")
        engine = self.config.get("design_engine") or {}
        configured = str(engine.get("experiment_root") or "").strip()
        if configured:
            root = Path(configured).expanduser() / safe_run_id
        else:
            data_path = _resolved(self.config.get("data_dir")) or (Path.cwd() / ".site-agent-data").resolve()
            root = data_path.parent / f"{data_path.name}-design-experiments" / safe_run_id
        return self.validate_experiment_root(root)

    def create_chat_experiment(
        self,
        site_intake: SiteIntake,
        *,
        owner_request: str,
        conversation_id: int | None,
        source_message_id: int | None,
        chat_job_id: int,
        intake_session_id: str | None = None,
        intake_revision_id: int | None = None,
    ) -> dict[str, Any]:
        """Clone the local source and reserve a non-publishable chat experiment."""
        from ..hands.design_experiment import clone_local_repository

        run_id = f"design-{uuid.uuid4().hex}"
        base_sha = self.resolve_base_sha()
        source = str((self.config.get("site") or {}).get("clone_path") or "").strip()
        if not source:
            raise DesignServiceError("site clone is required for a local design experiment")
        experiment_root = self.experiment_root_for_run(run_id)
        clone_local_repository(source, experiment_root, base_sha)
        return self.create_experiment(
            site_intake,
            experiment_root=experiment_root,
            base_sha=base_sha,
            run_id=run_id,
            owner_request=owner_request,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            chat_job_id=chat_job_id,
            intake_session_id=intake_session_id,
            intake_revision_id=intake_revision_id,
        )

    def create_chat_candidate(
        self,
        site_intake: SiteIntake,
        *,
        owner_request: str,
        conversation_id: int | None,
        source_message_id: int | None,
        chat_job_id: int,
        intake_session_id: str | None = None,
        intake_revision_id: int | None = None,
    ) -> dict[str, Any]:
        """Reserve a publishable candidate on the provisioned site's local Git clone.

        The candidate is still isolated in an OpenCode worktree and recorded as
        a pending Review draft after validation. Publishability only permits the
        explicit owner approval path; it never authorizes the build worker to
        change the production branch.
        """
        run_id = f"design-{uuid.uuid4().hex}"
        base_sha = self.resolve_base_sha()
        return self.create_run(
            site_intake,
            mode="production_candidate",
            base_sha=base_sha,
            candidate_ref=f"refs/ada-design/{run_id}",
            publishable=True,
            run_id=run_id,
            owner_request=owner_request,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            chat_job_id=chat_job_id,
            intake_session_id=intake_session_id,
            intake_revision_id=intake_revision_id,
        )

    def validate_experiment_root(self, experiment_root: str | Path) -> Path:
        root = _resolved(experiment_root)
        if root is None:
            raise DesignServiceError("experiment root is required")
        if root == Path(root.anchor):
            raise DesignServiceError("experiment root is too broad")
        site = self.config.get("site") or {}
        live_paths = [
            _resolved(site.get("clone_path")),
            _resolved(self.config.get("data_dir")),
            _resolved(site.get("data_dir")),
            _resolved(site.get("repository_path")),
            _resolved(self.config.get("repository_path")),
        ]
        for live in (path for path in live_paths if path is not None):
            if _overlaps(root, live):
                raise DesignServiceError("experiment root overlaps the live site or data path")
        return root

    @staticmethod
    def experiment_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
        """Remove GitHub and production-adapter credentials, retaining model access."""
        source = os.environ if env is None else env
        blocked_exact = {
            "GH_TOKEN", "GITHUB_TOKEN", "CLOUDFLARE_API_TOKEN", "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY", "CRAWLSEO_SERVICE_TOKEN", "CICERO_API_KEY",
            "SITE_AGENT_ADMIN_PASSWORD", "SITE_AGENT_GITHUB_TOKEN",
        }
        clean: dict[str, str] = {}
        for key, value in source.items():
            upper = str(key).upper()
            if upper in blocked_exact or upper.startswith("GITHUB_") or upper.startswith("GH_"):
                continue
            clean[str(key)] = str(value)
        return clean

    def get_run(self, run_id: str) -> dict[str, Any]:
        result = self.memory.get_design_run(run_id)
        if result is None:
            raise DesignRunNotFound(f"no such design run: {run_id}")
        result["events"] = self.memory.list_design_run_events(run_id)
        return result

    def list_runs(self, *, status: str | None = None, mode: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {**run, "events": self.memory.list_design_run_events(run["run_id"], limit=20)}
            for run in self.memory.list_design_runs(status=status, mode=mode, limit=limit)
        ]

    def prepare_initial_request(self, run_id: str) -> PageBuildRequest:
        """Assess intake and compile one typed homepage request before building."""
        run = self.get_run(run_id)
        if run["status"] == DesignRunStatus.CREATED.value:
            self._advance(run_id, DesignRunStatus.ASSESSING_INTAKE, "Intake accepted for typed design planning.")
            run = self.get_run(run_id)
        if run["status"] not in {
            DesignRunStatus.ASSESSING_INTAKE.value,
            DesignRunStatus.PLANNING.value,
            DesignRunStatus.BUILDING.value,
        }:
            raise DesignServiceError("design run is not available for planning")
        if not run.get("base_sha"):
            raise DesignServiceError("an immutable base SHA is required before planning")
        intake = SiteIntake.from_dict(run.get("intake_json") or {})
        if not run.get("context_snapshot") or not run.get("context_snapshot_hash"):
            self.capture_context_snapshot(
                run_id,
                owner_request=run.get("owner_request") or None,
                conversation_id=run.get("conversation_id"),
                source_message_id=run.get("source_message_id"),
                chat_job_id=run.get("chat_job_id"),
            )
            run = self.get_run(run_id)
        assessment = assess_intake(intake)
        snapshot = DesignContextSnapshot.from_dict(run["context_snapshot"])
        self.memory.update_design_run(run_id, planning_json={
            "assessment": assessment.to_dict(),
            "design_skill_set": snapshot.design_skill_set.to_dict() if snapshot.design_skill_set else {},
        })
        self.memory.add_design_run_event(run_id, "intake_assessment", "Intake completeness and contradictions were assessed.", {
            "complete_enough": assessment.complete_enough,
            "blocking_questions": list(assessment.blocking_questions),
            "unknown_count": len(assessment.non_blocking_unknowns),
        })
        if not assessment.complete_enough:
            raise DesignServiceError(
                "intake needs owner follow-up: "
                + "; ".join(assessment.blocking_questions or assessment.contradictions)
            )
        if run["status"] == DesignRunStatus.ASSESSING_INTAKE.value:
            self._advance(run_id, DesignRunStatus.PLANNING, "Design planning output is ready to compile.")
        # Intake assessment and brief compilation are factual acceptance
        # boundaries.  Do not select an art-direction hypothesis here: the
        # native OpenCode session must own the visual direction and source.
        brief = compile_brief(intake, assessment)
        planning = {
            "assessment": assessment.to_dict(),
            "brief": brief.to_dict(),
            "design_skill_set": snapshot.design_skill_set.to_dict() if snapshot.design_skill_set else {},
            "source_authoring": {
                "builder": "native_opencode",
                "visual_direction": "model_authored",
            },
        }
        self.memory.update_design_run(run_id, planning_json=planning)
        self.memory.add_design_run_event(run_id, "plan_output", "A factual typed brief was recorded; visual direction remains model-authored.", {
            "builder": "native_opencode",
            "visual_direction": "model_authored",
        })
        return native_homepage_request(
            intake,
            brief,
            run_id=run_id,
            base_sha=run["base_sha"],
            context_snapshot=DesignContextSnapshot.from_dict(run["context_snapshot"]),
            creative_prompt=str(run.get("owner_request") or "").strip(),
        )

    def clone_path_for_run(self, run_id: str) -> Path:
        """Resolve the read-only clone used to serve one immutable candidate."""
        run = self.memory.get_design_run(run_id)
        if run is None:
            raise DesignRunNotFound(f"no such design run: {run_id}")
        if run["mode"] == "local_experiment":
            for event in reversed(self.memory.list_design_run_events(run_id, limit=200)):
                if event.get("stage") == "experiment":
                    root = _resolved((event.get("detail") or {}).get("root"))
                    if root is not None:
                        return root
            raise DesignServiceError("local experiment clone is not recorded")
        root = _resolved((self.config.get("site") or {}).get("clone_path"))
        if root is None:
            raise DesignServiceError("site clone is not configured")
        return root

    def resolve_base_sha(self, ref: str | None = None) -> str:
        """Resolve one configured source ref without falling back to another ref."""
        site = self.config.get("site") or {}
        clone_value = str(site.get("clone_path") or "").strip()
        if not clone_value:
            raise DesignServiceError("site clone is not configured")
        clone = Path(clone_value).expanduser().resolve()
        if not (clone / ".git").exists():
            raise DesignServiceError(f"site clone is missing at {clone}")
        source_ref = str(ref or site.get("base_sha") or site.get("branch") or "HEAD").strip()
        try:
            from ..hands.opencode_runner import resolve_commit_sha

            return resolve_commit_sha(clone, source_ref)
        except (OSError, ValueError, RuntimeError) as exc:
            raise DesignServiceError(str(exc)) from exc

    def build_target_for_run(self, run_id: str) -> BuildTarget:
        """Construct the host-owned target for an already-created design run."""
        run = self.get_run(run_id)
        clone = self.clone_path_for_run(run_id)
        site = self.config.get("site") or {}
        engine = self.config.get("design_engine") or {}
        quality = engine.get("quality") or {}
        allowed = quality.get("allowed_patterns") or engine.get("allowed_paths") or site.get("writable_patterns") or ()
        operation_kind = run.get("operation_kind") or "initial_build"
        astro_local_surface = (
            run["mode"] == "local_experiment"
            and (
                operation_kind == "initial_build"
                or self.build_profile_for_run(run_id) == ASTRO_REACT_PROFILE.name
            )
        )
        if astro_local_surface:
            allowed = ASTRO_REACT_PROFILE.writable_patterns
        push_mode = "none" if run["mode"] == "local_experiment" else str(engine.get("push_mode") or "none")
        return BuildTarget.from_dict({
            "mode": run["mode"],
            "repository": str(site.get("repository") or ""),
            "clone_path": str(clone),
            "base_sha": run["base_sha"],
            "candidate_ref": run["candidate_ref"],
            "push_mode": push_mode,
            "publishable": bool(run["publishable"]),
            "allowed_paths": list(allowed),
            "operation_kind": run.get("operation_kind") or "initial_build",
        })

    def build_profile_for_run(self, run_id: str) -> str:
        """Resolve the host-owned profile used to render an immutable run."""
        run = self.get_run(run_id)
        planning = run.get("planning_json") if isinstance(run.get("planning_json"), Mapping) else {}
        profile = str((planning or {}).get("build_profile") or "").strip()
        if profile:
            return profile
        frozen_target = (planning or {}).get("build_target") if isinstance(planning, Mapping) else None
        if isinstance(frozen_target, Mapping):
            frozen_allowed = tuple(str(item) for item in (frozen_target.get("allowed_paths") or ()))
            if frozen_allowed == ASTRO_REACT_PROFILE.writable_patterns:
                return ASTRO_REACT_PROFILE.name
        snapshot = run.get("context_snapshot")
        if isinstance(snapshot, Mapping):
            profile = str((snapshot.get("execution_profile") or {}).get("build_profile") or "").strip()
            if profile:
                return profile
            # Runs created before the explicit profile field was introduced
            # still carry the frozen quality output directory. Use that durable
            # evidence before applying the current default profile.
            quality = (snapshot.get("execution_profile") or {}).get("quality_policy")
            output_dir = str((quality or {}).get("output_dir") or "").strip().lower() if isinstance(quality, Mapping) else ""
            if output_dir == PELICAN_BASELINE_PROFILE.output_dir:
                return PELICAN_BASELINE_PROFILE.name
            if output_dir == ASTRO_REACT_PROFILE.output_dir:
                return ASTRO_REACT_PROFILE.name
        if run.get("mode") == "local_experiment" and (run.get("operation_kind") or "initial_build") == "initial_build":
            return ASTRO_REACT_PROFILE.name
        parent_id = str(run.get("parent_run_id") or "").strip()
        if parent_id and parent_id != run_id:
            return self.build_profile_for_run(parent_id)
        return ""

    def quality_policy_for_run(self, run_id: str) -> QualityPolicy:
        """Resolve site-specific validation settings for a persisted run."""
        run = self.get_run(run_id)
        planning = run.get("planning_json") or {}
        brief = planning.get("brief") if isinstance(planning, Mapping) else {}
        if not isinstance(brief, Mapping):
            build_request = planning.get("build_request") if isinstance(planning, Mapping) else {}
            request_content = build_request.get("content") if isinstance(build_request, Mapping) else {}
            brief = request_content.get("design_brief") if isinstance(request_content, Mapping) else {}
        required_pages = tuple((brief or {}).get("required_pages") or ()) if isinstance(brief, Mapping) else ()
        if not required_pages:
            intake_site = (run.get("intake_json") or {}).get("site")
            required_pages = tuple((intake_site or {}).get("required_pages") or ()) if isinstance(intake_site, Mapping) else ()
        planning = run.get("planning_json") if isinstance(run.get("planning_json"), Mapping) else {}
        raw_request = planning.get("build_request") if isinstance(planning, Mapping) else None
        operation_kind = str(run.get("operation_kind") or "initial_build").strip()
        initial_surface = operation_kind == "initial_build"
        technical_repair = operation_kind == "technical_repair"
        visual_refinement = operation_kind == "visual_refinement"
        astro_local_surface = (
            run.get("mode") == "local_experiment"
            and self.build_profile_for_run(run_id) == ASTRO_REACT_PROFILE.name
        )
        if astro_local_surface:
            # A visual refinement of an initial homepage remains homepage
            # scoped. A visual refinement of a technical repair, however,
            # inherits the repair's complete route inventory so its browser
            # evidence can cover every route the parent just validated.
            if technical_repair:
                initial_surface = False
            elif visual_refinement:
                parent_id = str(run.get("parent_run_id") or "").strip()
                parent = self.get_run(parent_id) if parent_id else None
                parent_kind = str((parent or {}).get("operation_kind") or "").strip()
                initial_surface = parent_kind == "initial_build"
            else:
                initial_surface = True
        if isinstance(raw_request, Mapping):
            if not visual_refinement:
                initial_surface = (
                    str(raw_request.get("mode") or "") == "initial_homepage"
                    and not technical_repair
                )
            if astro_local_surface and not technical_repair and not visual_refinement:
                initial_surface = True
            if initial_surface and raw_request.get("page_path"):
                required_pages = (_public_page_path(raw_request.get("page_path")),)
        if initial_surface and required_pages:
            # The first candidate is intentionally a homepage surface.  Other
            # routes stay in the frozen intake and are validated by a later
            # full-site operation, rather than making untouched source pages
            # block the first useful preview.
            required_pages = (str(required_pages[0]),)
        required_content = tuple(
            item for item in ((brief or {}).get("content_requirements") or ())
            if isinstance(item, str) and not item.lower().startswith("provide the required page:")
        ) if isinstance(brief, Mapping) else ()
        try:
            policy = QualityPolicy.from_config(
                self.config,
                required_pages=required_pages,
                required_content=required_content,
                expected_intake_hash=str(run.get("intake_hash") or ""),
            )
            intake_data = run.get("intake_json") if isinstance(run.get("intake_json"), Mapping) else {}
            conversion = intake_data.get("conversion") if isinstance(intake_data, Mapping) else {}
            policy = replace(
                policy,
                contact_destination_unavailable=(
                    isinstance(conversion, Mapping)
                    and conversion.get("not_available") is True
                    and not str(conversion.get("contact_destination") or "").strip()
                ),
            )
            snapshot = run.get("context_snapshot")
            if snapshot:
                policy = replace(
                    policy,
                    approved_capabilities=DesignContextSnapshot.from_dict(snapshot).capabilities,
                )
            if run.get("design_manifest_path"):
                policy = replace(policy, manifest_path=str(run["design_manifest_path"]))
            if astro_local_surface:
                approved = {
                    str(item.get("package") or item.get("name") or "").strip(): dict(item)
                    for item in policy.approved_capabilities
                    if isinstance(item, Mapping)
                    and str(item.get("package") or item.get("name") or "").strip()
                }
                for item in ASTRO_REACT_TOOLCHAIN_DEPENDENCIES:
                    package = str(item["package"])
                    existing = approved.get(package, {})
                    merged = dict(existing)
                    merged.update(item)
                    approved[package] = merged
                policy = replace(
                    policy,
                    output_dir=ASTRO_REACT_PROFILE.output_dir,
                    allowed_patterns=ASTRO_REACT_PROFILE.writable_patterns,
                    prohibited_paths=tuple(dict.fromkeys((*policy.prohibited_paths, *ASTRO_REACT_PROFILE.prohibited_paths))),
                    allowed_hard_denied_paths=tuple(dict.fromkeys((*policy.allowed_hard_denied_paths, "package.json"))),
                    approved_capabilities=tuple(approved.values()),
                    build_command=None,
                    build_timeout_seconds=900,
                )
            return policy
        except (TypeError, ValueError) as exc:
            raise DesignServiceError(f"quality policy is invalid: {exc}") from exc

    def queue_build(
        self,
        run_id: str,
        request: PageBuildRequest | None,
        target: BuildTarget,
    ) -> dict[str, Any]:
        """Persist a complete typed build job before a worker can execute it."""
        run = self.get_run(run_id)
        if run["status"] in {
            DesignRunStatus.BUILDING.value,
            DesignRunStatus.CANDIDATE_READY.value,
            DesignRunStatus.VALIDATING.value,
        }:
            return run
        if run["status"] not in {
            DesignRunStatus.CREATED.value,
            DesignRunStatus.ASSESSING_INTAKE.value,
            DesignRunStatus.PLANNING.value,
        }:
            raise DesignServiceError("design run is not available for queuing")
        if not isinstance(target, BuildTarget):
            raise DesignServiceError("build target must be validated before queuing")
        if target.mode != run["mode"] or target.publishable != bool(run["publishable"]):
            raise DesignServiceError("build target policy does not match the design run")
        if target.base_sha != run.get("base_sha"):
            raise DesignServiceError("build target base SHA does not match the design run")
        if target.candidate_ref != run.get("candidate_ref"):
            raise DesignServiceError("build target ref does not match the design run")
        if target.operation_kind != (run.get("operation_kind") or "initial_build"):
            raise DesignServiceError("build target operation kind does not match the design run")
        if target.mode == "local_experiment":
            expected_root = self.clone_path_for_run(run_id).resolve()
            if Path(target.clone_path).expanduser().resolve() != expected_root:
                raise DesignServiceError("local build target must use the reserved experiment clone")
        if request is None:
            request = self.prepare_initial_request(run_id)
        if not isinstance(request, PageBuildRequest):
            raise DesignServiceError("build request must be validated before queuing")
        if request.run_id != run_id or request.base_sha != target.base_sha:
            raise DesignServiceError("build request identity does not match the design run")
        if run.get("context_snapshot_hash"):
            if not request.context_snapshot or request.context_snapshot_hash != run["context_snapshot_hash"]:
                raise DesignServiceError("build request context snapshot does not match the design run")
            if request.context_snapshot.content_hash != request.context_snapshot_hash:
                raise DesignServiceError("build request context snapshot hash is invalid")
        if request.site_intake_hash and request.site_intake_hash != run.get("intake_hash"):
            raise DesignServiceError("build request intake hash does not match the design run")
        if request.mode == "derived_page" and run["mode"] != "production_candidate":
            raise DesignServiceError("derived pages cannot run in a local experiment")
        planning = dict(self.get_run(run_id).get("planning_json") or {})
        planning["build_request"] = request.to_dict()
        planning["build_target"] = target.to_dict()
        self.memory.update_design_run(run_id, planning_json=planning)
        if self.get_run(run_id)["status"] == DesignRunStatus.ASSESSING_INTAKE.value:
            self._advance(run_id, DesignRunStatus.PLANNING, "Design planning output is ready to build.")
        self.memory.add_design_run_event(run_id, "queued", "Typed design build queued for the background worker.", {
            "candidate_ref": target.candidate_ref,
            "push_mode": target.push_mode,
            "conversation_id": run.get("conversation_id"),
            "source_message_id": run.get("source_message_id"),
            "chat_job_id": run.get("chat_job_id"),
        })
        return self.get_run(run_id)

    def create_review_draft(self, run_id: str) -> dict[str, Any]:
        """Link a passed production candidate to the existing Review workflow."""
        run = self.get_run(run_id)
        if run["mode"] != "production_candidate" or not run["publishable"]:
            raise DesignServiceError("local experiments cannot enter production review")
        if run["status"] != DesignRunStatus.READY_FOR_REVIEW.value:
            raise DesignServiceError("design run is not ready for review")
        report = run.get("quality_report_json") or {}
        if report.get("state") != "passed":
            raise DesignServiceError("only candidates with passing quality gates can enter review")
        if not run.get("candidate_sha") or not run.get("quality_report_hash") or not run.get("design_manifest_path") or not run.get("design_manifest_hash"):
            raise DesignServiceError("review requires immutable candidate, manifest, and quality identities")
        for draft in self.memory.list_drafts(status="pending", limit=500):
            if draft.get("kind") == "design" and (draft.get("meta") or {}).get("run_id") == run_id:
                return {**run, "draft_id": draft["id"]}
        business = ((run.get("intake_json") or {}).get("business") or {})
        title = f"Design candidate: {str(business.get('name') or run_id)[:100]}"
        meta = {
            "run_id": run_id,
            "base_sha": run["base_sha"],
            "candidate_sha": run["candidate_sha"],
            "candidate_ref": run["candidate_ref"],
            "quality_report_hash": run["quality_report_hash"],
            "manifest_path": run["design_manifest_path"],
            "manifest_hash": run["design_manifest_hash"],
            "publishable": True,
        }
        draft_id = self.memory.save_draft(
            title=title,
            body=f"Immutable design candidate {run['candidate_sha']} is ready for owner review.",
            kind="design",
            meta=meta,
        )
        self.memory.update_design_run(run_id, draft_id=draft_id)
        self.memory.add_design_run_event(run_id, "review", "Candidate linked to the owner Review workflow.", {
            "draft_id": draft_id,
            "candidate_sha": run["candidate_sha"],
        })
        return {**self.get_run(run_id), "draft_id": draft_id}

    def create_derived_page_run(
        self,
        source_run_id: str,
        page_intake: PageIntake,
        *,
        run_id: str | None = None,
        base_sha: str | None = None,
    ) -> dict[str, Any]:
        """Create a page run pinned to an approved homepage design source."""
        if not isinstance(page_intake, PageIntake):
            raise DesignServiceError("page_intake must be a validated PageIntake")
        source = self.get_run(source_run_id)
        if source["mode"] != "production_candidate" or source["status"] != DesignRunStatus.READY_FOR_REVIEW.value:
            raise DesignServiceError("source design run is not an approved production candidate")
        draft_id = source.get("draft_id")
        draft = next((item for item in self.memory.list_drafts(limit=500) if item["id"] == draft_id), None)
        if draft is None or draft.get("kind") != "design" or draft.get("status") != "approved":
            raise DesignServiceError("source design candidate has not been approved")
        manifest_data = source.get("design_manifest_json") or {}
        try:
            manifest = DesignManifest.from_dict(manifest_data)
            binding = DesignSourceBinding.from_dict({
                "candidate_sha": source.get("candidate_sha"),
                "manifest_path": source.get("design_manifest_path"),
                "manifest_hash": source.get("design_manifest_hash"),
            })
            binding.verify_manifest(manifest)
        except (ContractError, TypeError, ValueError) as exc:
            raise DesignServiceError(f"approved design source is invalid: {exc}") from exc
        if manifest.intake_hash != source.get("intake_hash"):
            raise DesignServiceError("approved design manifest does not match the site intake")
        new_run_id = run_id or f"design-{uuid.uuid4().hex}"
        source_sha = source.get("candidate_sha")
        if base_sha and base_sha != source_sha:
            raise DesignServiceError("derived page must start from the exact parent candidate SHA")
        request = PageBuildRequest.from_dict({
            "schema_version": 1,
            "run_id": new_run_id,
            "mode": "derived_page",
            "base_sha": source_sha,
            "site_intake_hash": source["intake_hash"],
            "design_source": binding.to_dict(),
            "page_path": page_intake.desired_url,
            "purpose": page_intake.purpose,
            "acceptance_criteria": [
                f"Preserve these shared regions: {', '.join(manifest.shared_regions) or 'the approved page shell'}.",
                "Use only the approved design system and declared variation points.",
                *page_intake.required_facts,
            ],
            "required_shared_regions": list(manifest.shared_regions or manifest.page_shell_requirements),
            "allowed_variation_points": list(manifest.allowed_variation_points),
            "supplied_media_paths": list(page_intake.supplied_media_ids),
            "content": page_intake.to_dict(),
        })
        intake = SiteIntake.from_dict(source["intake_json"])
        run = self.create_run(
            intake,
            mode="production_candidate",
            base_sha=source_sha,
            run_id=new_run_id,
            parent_run_id=source_run_id,
            operation_kind="derived_page",
            source_candidate_sha=source_sha,
        )
        self.memory.add_design_run_event(new_run_id, "derived_source", "Derived page pinned to the approved design source.", {
            "source_run_id": source_run_id,
            "candidate_sha": binding.candidate_sha,
            "manifest_path": binding.manifest_path,
            "manifest_hash": binding.manifest_hash,
            "page_id": page_intake.page_id,
        })
        return {"run": self.get_run(new_run_id), "request": request.to_dict()}

    def approve_review_draft(
        self,
        draft_id: int,
        merger: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Approve exactly the candidate SHA recorded in a pending design draft."""
        draft = next((item for item in self.memory.list_drafts(limit=500) if item["id"] == draft_id), None)
        if draft is None or draft.get("kind") != "design":
            raise DesignServiceError("no such design review draft")
        if draft.get("status") != "pending":
            raise DesignServiceError(f"design draft already {draft.get('status')}")
        run_id = str((draft.get("meta") or {}).get("run_id") or "")
        run = self.memory.get_design_run(run_id) if run_id else None
        if run is None:
            raise DesignServiceError("design review draft references a missing run")
        if run["mode"] != "production_candidate" or not run["publishable"]:
            raise DesignServiceError("only production candidates can be approved")
        if run["status"] != DesignRunStatus.READY_FOR_REVIEW.value:
            raise DesignServiceError("design run is no longer reviewable")
        meta = draft.get("meta") or {}
        if meta.get("candidate_sha") != run.get("candidate_sha") or meta.get("base_sha") != run.get("base_sha"):
            raise DesignServiceError("design review draft is stale")
        if (run.get("quality_report_json") or {}).get("state") != "passed":
            raise DesignServiceError("design candidate no longer has passing quality gates")
        result = dict(merger(run))
        if not result.get("merged"):
            raise DesignServiceError(str(result.get("reason") or "design candidate merge was rejected"))
        if result.get("candidate_sha") and result["candidate_sha"] != run["candidate_sha"]:
            raise DesignServiceError("merge result does not identify the reviewed candidate")
        self.memory.update_draft_status(draft_id, "approved")
        self.memory.add_design_run_event(run_id, "approved", "Owner approved the immutable design candidate.", {
            "draft_id": draft_id,
            "candidate_sha": run["candidate_sha"],
        })
        return {"run": self.get_run(run_id), "draft_id": draft_id, "published": result}

    def cancel(self, run_id: str) -> dict[str, Any]:
        try:
            result = self.memory.transition_design_run(run_id, DesignRunStatus.CANCELLED.value)
        except ContractError as exc:
            raise DesignServiceError(str(exc)) from exc
        if result is None:
            raise DesignRunNotFound(f"no such design run: {run_id}")
        self.memory.add_design_run_event(run_id, "cancelled", "Design run cancelled by the owner.")
        return self.get_run(run_id)

    def execute_build(
        self,
        run_id: str,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        progress=None,
    ) -> DesignCandidateReceipt:
        """Run one typed build and persist its immutable candidate identity."""
        if not isinstance(request, PageBuildRequest) or not isinstance(target, BuildTarget):
            raise DesignServiceError("execute_build requires typed request and target")
        run = self.memory.get_design_run(run_id)
        if run is None:
            raise DesignRunNotFound(f"no such design run: {run_id}")
        if request.run_id != run_id:
            raise DesignServiceError("page build request run_id does not match the design run")
        if request.base_sha != target.base_sha:
            raise DesignServiceError("page build request base SHA does not match the build target")
        if request.site_intake_hash and request.site_intake_hash != run.get("intake_hash"):
            raise DesignServiceError("page build request intake hash does not match the design run")
        if run.get("context_snapshot_hash"):
            if not request.context_snapshot or request.context_snapshot_hash != run["context_snapshot_hash"]:
                raise DesignServiceError("build request context snapshot does not match the design run")
            if request.context_snapshot.content_hash != request.context_snapshot_hash:
                raise DesignServiceError("build request context snapshot hash is invalid")
        if run.get("base_sha") and run["base_sha"] != target.base_sha:
            raise DesignServiceError("build target base SHA does not match the design run")
        if target.candidate_ref != run.get("candidate_ref"):
            raise DesignServiceError("build target ref does not match the design run")
        if target.operation_kind != (run.get("operation_kind") or "initial_build"):
            raise DesignServiceError("build target operation kind does not match the design run")
        if run["mode"] != target.mode:
            raise DesignServiceError("build target mode does not match the design run")
        if bool(run["publishable"]) != target.publishable:
            raise DesignServiceError("publishable policy cannot be changed during a design run")
        if run["status"] == DesignRunStatus.CREATED.value:
            self._advance(run_id, DesignRunStatus.ASSESSING_INTAKE, "Intake accepted for typed design build.")
            self.prepare_initial_request(run_id)
        current_status = self.memory.get_design_run(run_id)["status"]
        if current_status == DesignRunStatus.PLANNING.value:
            self._advance(run_id, DesignRunStatus.BUILDING, "Starting the isolated design build.")
        elif current_status != DesignRunStatus.BUILDING.value:
            raise DesignServiceError("design run is not ready for building")
        planning = dict((self.memory.get_design_run(run_id) or {}).get("planning_json") or {})
        planning["build_request"] = request.to_dict()
        planning["build_target"] = target.to_dict()
        if run["mode"] == "local_experiment" and target.operation_kind == "initial_build":
            planning["build_profile"] = ASTRO_REACT_PROFILE.name
        elif target.operation_kind == "visual_refinement":
            inherited_profile = self.build_profile_for_run(str(run.get("parent_run_id") or "")) if run.get("parent_run_id") else ""
            if inherited_profile:
                planning["build_profile"] = inherited_profile
        self.memory.update_design_run(run_id, planning_json=planning)
        builder = self.builder
        if builder is None:
            from ..hands.builder import OperationRoutingBuilder

            builder = OperationRoutingBuilder({"config": self.config, "memory": self.memory})

        def build_progress(message: str) -> None:
            if progress:
                progress(str(message))

        try:
            receipt = builder.build_design(request, target, build_progress)
            if not isinstance(receipt, DesignCandidateReceipt):
                raise DesignServiceError("design builder returned an invalid candidate receipt")
            if receipt.run_id != run_id:
                raise DesignServiceError("design builder receipt run_id does not match the design run")
            if receipt.operation_kind != run.get("operation_kind", "initial_build"):
                raise DesignServiceError("design builder receipt operation kind does not match the design run")
            if receipt.base_sha != target.base_sha or receipt.publishable != target.publishable:
                raise DesignServiceError("design builder receipt policy does not match the design run")
            transcript_hash = self._transcript_hash(receipt.transcript_path)
            transcript_artifact_id = receipt.transcript_artifact_id
            if transcript_artifact_id is None:
                transcript_artifact_id = self._record_design_artifact(
                    kind=ArtifactKind.DESIGN_TRANSCRIPT,
                    run_id=run_id,
                    title="OpenCode transcript",
                    summary="Raw OpenCode event transcript for the retained candidate.",
                    provider_id=receipt.provider_id,
                    content_hash=transcript_hash,
                    preview_data={"path": receipt.transcript_path, "sha256": transcript_hash},
                )
                receipt = replace(receipt, transcript_artifact_id=transcript_artifact_id)
            evidence = {
                "candidate_sha": receipt.candidate_sha,
                "candidate_ref": receipt.candidate_ref,
                "design_manifest_path": receipt.manifest_path,
                "design_manifest_hash": receipt.manifest_hash,
                "opencode_session_id": receipt.opencode_session_id,
                "transcript_path": receipt.transcript_path,
                "transcript_artifact_id": transcript_artifact_id,
                "transcript_hash": transcript_hash,
                "provider_id": receipt.provider_id,
                "model_id": receipt.model_id,
                "build_profile": receipt.build_profile,
            }
            if receipt.design_manifest:
                evidence["design_manifest_json"] = receipt.design_manifest
            self.memory.update_design_run(run_id, **evidence)
            if receipt.build_error:
                self.memory.transition_design_run(run_id, DesignRunStatus.FAILED.value, error=receipt.build_error)
                self.memory.add_design_run_event(run_id, "candidate_failed", "An incomplete OpenCode turn produced a retained candidate.", {
                    "candidate_sha": receipt.candidate_sha,
                    "error": receipt.build_error[:500],
                })
                return receipt
            self._advance(run_id, DesignRunStatus.CANDIDATE_READY, "Candidate retained; host validation is a separate operation.")
            self.memory.add_design_run_event(run_id, "candidate_ready", "Immutable candidate recorded.", {
                "candidate_sha": receipt.candidate_sha,
                "candidate_ref": receipt.candidate_ref,
                "operation_kind": receipt.operation_kind,
                "publishable": receipt.publishable,
            })
            return receipt
        except Exception as exc:  # noqa: BLE001 - the durable run records the failure
            try:
                partial = dict(getattr(exc, "result", {}) or {})
                if not partial and getattr(exc, "__cause__", None) is not None:
                    partial = dict(getattr(exc.__cause__, "result", {}) or {})
                transcript_path = str(partial.get("transcript_path") or "").strip()
                if transcript_path:
                    try:
                        transcript_path = safe_relative_path(transcript_path, "transcript_path")
                        transcript_hash = self._transcript_hash(transcript_path)
                        transcript_artifact_id = self._record_design_artifact(
                            kind=ArtifactKind.DESIGN_TRANSCRIPT,
                            run_id=run_id,
                            title="OpenCode transcript",
                            summary="Raw OpenCode event transcript for the failed design turn.",
                            provider_id=str(partial.get("provider_id") or "opencode"),
                            content_hash=transcript_hash,
                            preview_data={"path": transcript_path, "sha256": transcript_hash},
                        )
                        self.memory.update_design_run(
                            run_id,
                            transcript_path=transcript_path,
                            transcript_hash=transcript_hash,
                            transcript_artifact_id=transcript_artifact_id,
                            opencode_session_id=str(partial.get("session_id") or ""),
                        )
                        self.memory.add_design_run_event(run_id, "transcript", "Failed design turn transcript retained.", {
                            "transcript_artifact_id": transcript_artifact_id,
                        })
                    except Exception:
                        pass
                current = self.memory.get_design_run(run_id)
                if current and current["status"] not in {
                    DesignRunStatus.FAILED.value,
                    DesignRunStatus.CANCELLED.value,
                }:
                    self.memory.transition_design_run(run_id, DesignRunStatus.FAILED.value, error=str(exc))
                    self.memory.add_design_run_event(run_id, "failed", "The design build failed.", {"error": str(exc)[:500]})
            except Exception:
                pass
            if isinstance(exc, DesignServiceError):
                raise
            raise DesignServiceError(str(exc)) from exc

    def _advance(self, run_id: str, status: DesignRunStatus, message: str) -> None:
        result = self.memory.transition_design_run(run_id, status.value)
        if result is None:
            raise DesignRunNotFound(f"no such design run: {run_id}")
        self.memory.add_design_run_event(run_id, status.value, message)

    @staticmethod
    def _screenshot_evidence(quality_report: Mapping[str, Any]) -> list[dict[str, Any]]:
        evidence = quality_report.get("evidence") or {}
        browser = evidence.get("browser") or {}
        screenshots: list[dict[str, Any]] = []
        for viewport in browser.get("viewports") or ():
            if not isinstance(viewport, Mapping):
                continue
            viewport_info = viewport.get("viewport") or {}
            result = viewport.get("result") or {}
            for route in result.get("routes") or ():
                if not isinstance(route, Mapping) or not route.get("screenshot_hash"):
                    continue
                screenshots.append({
                    "route": str(route.get("route") or ""),
                    "viewport": dict(viewport_info),
                    "screenshot_path": str(route.get("screenshot_path") or ""),
                    "screenshot_hash": str(route.get("screenshot_hash") or ""),
                })
        return screenshots[:100]

    def _visual_review_evidence(
        self,
        run: Mapping[str, Any],
        quality_report: Mapping[str, Any],
        brief: Mapping[str, Any],
        screenshots: list[dict[str, Any]],
        source_media: Any = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Assemble the bounded evidence view given to the sighted reviewer.

        Screenshots alone are not enough to distinguish an intentional use of
        owner media from a generic placeholder, or to interpret a motion/font
        issue. Keep the review view factual and bounded: metadata comes from
        the immutable run/manifest and rendered evidence, while source images
        are attached separately by the reviewer adapter.
        """
        quality_evidence = quality_report.get("evidence") if isinstance(quality_report, Mapping) else {}
        if not isinstance(quality_evidence, Mapping):
            quality_evidence = {}
        manifest = run.get("design_manifest_json")
        manifest = manifest if isinstance(manifest, Mapping) else {}
        host_metadata = manifest.get("host_metadata")
        host_metadata = host_metadata if isinstance(host_metadata, Mapping) else {}
        native_source = quality_evidence.get("native_source")
        native_source = native_source if isinstance(native_source, Mapping) else {}
        fonts = quality_evidence.get("fonts")
        fonts = fonts if isinstance(fonts, Mapping) else {}
        browser = quality_evidence.get("browser")
        browser = browser if isinstance(browser, Mapping) else {}
        motion = quality_evidence.get("motion")
        motion = motion if isinstance(motion, Mapping) else {}

        changed_source_files = host_metadata.get("changed_source_files")
        if not isinstance(changed_source_files, (list, tuple)):
            manifest_sources = manifest.get("source_files")
            changed_source_files = (
                manifest_sources.get("changed")
                if isinstance(manifest_sources, Mapping)
                else ()
            )
        if not isinstance(changed_source_files, (list, tuple)):
            changed_source_files = native_source.get("source_files") or ()

        raw_assets = ()
        snapshot = run.get("context_snapshot")
        if isinstance(snapshot, Mapping):
            raw_assets = snapshot.get("asset_inventory") or ()
        if not raw_assets:
            intake = run.get("intake_json")
            if isinstance(intake, Mapping):
                raw_assets = intake.get("assets") or ()
        approved_assets: list[dict[str, Any]] = []
        for raw in raw_assets if isinstance(raw_assets, (list, tuple)) else ():
            if not isinstance(raw, Mapping):
                continue
            item = {
                key: raw[key]
                for key in (
                    "id", "asset_id", "usage", "role", "original_name", "description",
                    "width", "height", "source_kind", "provenance",
                )
                if key in raw and raw[key] not in (None, "")
            }
            if item:
                approved_assets.append(item)
            if len(approved_assets) >= 24:
                break

        owner_media_hashes = host_metadata.get("owner_media_hashes")
        owner_media_hashes = owner_media_hashes if isinstance(owner_media_hashes, Mapping) else {}
        source_images: list[dict[str, Any]] = []
        missing_source_files: list[dict[str, str]] = []
        try:
            clone = self.clone_path_for_run(str(run.get("run_id") or ""))
        except Exception:  # noqa: BLE001 - metadata grounding must not strand review
            clone = None
        media = source_media or self.media_service
        media_by_hash: dict[str, tuple[int, bytes, str]] = {}
        if media is not None:
            asset_ids: list[int] = []
            for raw in approved_assets:
                raw_id = raw.get("id") or raw.get("asset_id")
                if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id > 0:
                    asset_ids.append(raw_id)
                elif str(raw_id or "").isdigit() and int(raw_id) > 0:
                    asset_ids.append(int(raw_id))
            for raw_path in owner_media_hashes:
                match = re.search(r"(?:^|/)ada-(\d+)-", str(raw_path))
                if match:
                    asset_ids.append(int(match.group(1)))
            for asset_id in dict.fromkeys(asset_ids):
                try:
                    data, content_type = media.read_preview(asset_id, thumbnail=False)
                    if not isinstance(data, bytes) or not data:
                        continue
                    media_by_hash[hashlib.sha256(data).hexdigest()] = (
                        asset_id,
                        data,
                        str(content_type or "image/webp"),
                    )
                except Exception:  # noqa: BLE001 - an unavailable asset is recorded below
                    continue
        for raw_path, raw_hash in sorted(owner_media_hashes.items(), key=lambda item: str(item[0]))[:24]:
            try:
                relative = safe_relative_path(raw_path, "owner_media_hashes.path")
            except (ContractError, TypeError, ValueError):
                continue
            target = clone / relative if clone is not None else None
            expected_hash = str(raw_hash or "").strip().lower()
            if target is not None and not target.is_symlink() and target.is_file():
                try:
                    actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                except OSError:
                    actual_hash = ""
                if expected_hash and actual_hash != expected_hash:
                    missing_source_files.append({
                        "relative_path": relative,
                        "error": "candidate source media bytes do not match the manifest hash",
                    })
                    continue
                source_images.append({
                    "path": str(target),
                    "relative_path": relative,
                    "sha256": expected_hash or actual_hash,
                    "kind": "owner_media",
                })
                continue
            media_match = media_by_hash.get(expected_hash)
            if media_match is not None:
                asset_id, data, content_type = media_match
                source_images.append({
                    "path": f"media_asset:{asset_id}",
                    "relative_path": relative,
                    "sha256": expected_hash,
                    "kind": "owner_media",
                    "asset_id": asset_id,
                    "data_url": (
                        f"data:{content_type};base64;".replace(";base64;", ";base64,")
                        + base64.b64encode(data).decode("ascii")
                    ),
                })
                continue
            missing_source_files.append({
                "relative_path": relative,
                "error": "candidate source media bytes are unavailable for visual review",
            })

        review_evidence = {
            "brief": dict(brief),
            "screenshots": screenshots[:100],
            "source_media": {
                "approved_assets": approved_assets,
                "materialized_files": [
                    {key: item[key] for key in ("relative_path", "sha256", "kind") if key in item}
                    for item in source_images
                ],
                "missing_files": missing_source_files,
            },
            "source_inventory": {
                "changed_source_files": [str(item) for item in changed_source_files[:200]],
                "imports": native_source.get("imports") or {},
                "animation_files": native_source.get("animation_files") or [],
                "font_files": fonts.get("font_hashes") or host_metadata.get("font_hashes") or {},
            },
            "runtime": {
                "browser_status": browser.get("status"),
                "motion": motion,
                "motion_preferences": browser.get("motion_preferences") or [],
                "scroll_states": browser.get("scroll_states") or [],
                "interaction_states": browser.get("interaction_states") or [],
                "font_checks": browser.get("font_checks") or [],
                "low_resolution_images": browser.get("low_resolution_images") or [],
                "external_requests": browser.get("external_requests") or [],
            },
        }
        return review_evidence, source_images

    @staticmethod
    def _screenshot_key(item: Mapping[str, Any]) -> tuple[str, str]:
        viewport = item.get("viewport") or {}
        name = str(viewport.get("name") or "").strip()
        dimensions = f"{viewport.get('width', '')}x{viewport.get('height', '')}"
        if name and dimensions != "x":
            name = f"{name}:{dimensions}"
        elif not name:
            name = dimensions
        return str(item.get("route") or ""), name

    def _parent_visual_comparison(
        self,
        run: Mapping[str, Any],
        quality_report: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Require refinement evidence to cover the same visual matrix as v1."""
        if run.get("operation_kind") != "visual_refinement":
            return None, []
        parent_run_id = str(run.get("parent_run_id") or "").strip()
        parent = self.memory.get_design_run(parent_run_id) if parent_run_id else None
        if not parent:
            return (
                {"status": "failed", "reason": "parent_run_missing", "parent_run_id": parent_run_id},
                [{
                    "gate": "visual_regression",
                    "severity": "blocker",
                    "code": "parent_visual_source_missing",
                    "message": "Visual refinement has no retained parent run for evidence comparison.",
                }],
            )
        parent_quality = parent.get("quality_report_json") or {}
        if parent_quality.get("state") != "passed":
            return (
                {
                    "status": "failed",
                    "reason": "parent_quality_not_passed",
                    "parent_run_id": parent_run_id,
                    "parent_quality_state": parent_quality.get("state"),
                },
                [{
                    "gate": "visual_regression",
                    "severity": "blocker",
                    "code": "parent_quality_not_passed",
                    "message": "Visual refinement requires a parent with passing deterministic quality evidence.",
                    "parent_run_id": parent_run_id,
                }],
            )
        parent_sha = str(parent.get("candidate_sha") or parent_quality.get("candidate_sha") or "")
        base_sha = str(run.get("base_sha") or "")
        source_sha = str(run.get("source_candidate_sha") or "")
        if not parent_sha or base_sha != parent_sha or (source_sha and source_sha != parent_sha):
            return (
                {
                    "status": "failed",
                    "reason": "parent_candidate_mismatch",
                    "parent_run_id": parent_run_id,
                    "parent_candidate_sha": parent_sha,
                    "base_sha": base_sha,
                    "source_candidate_sha": source_sha,
                },
                [{
                    "gate": "visual_regression",
                    "severity": "blocker",
                    "code": "parent_candidate_mismatch",
                    "message": "Visual refinement is not based on the retained parent candidate.",
                    "parent_candidate_sha": parent_sha,
                    "base_sha": base_sha,
                    "source_candidate_sha": source_sha,
                }],
            )

        parent_screenshots = self._screenshot_evidence(parent_quality)
        current_screenshots = self._screenshot_evidence(quality_report)
        comparison: dict[str, Any] = {
            "status": "skipped",
            "reason": "parent_has_no_screenshot_evidence",
            "parent_run_id": parent_run_id,
            "parent_candidate_sha": parent_sha,
            "parent_count": len(parent_screenshots),
            "candidate_count": len(current_screenshots),
        }
        if not parent_screenshots:
            return comparison, []

        parent_by_key = {self._screenshot_key(item): item for item in parent_screenshots}
        current_by_key = {self._screenshot_key(item): item for item in current_screenshots}
        parent_keys = set(parent_by_key)
        current_keys = set(current_by_key)
        missing = sorted(parent_keys - current_keys)
        extra = sorted(current_keys - parent_keys)
        changed = sorted(
            key for key in parent_keys & current_keys
            if parent_by_key[key].get("screenshot_hash") != current_by_key[key].get("screenshot_hash")
        )
        comparison.update({
            "status": "incomplete" if missing else "passed",
            "missing": [list(key) for key in missing],
            "extra": [list(key) for key in extra],
            "changed": [list(key) for key in changed],
        })
        if not missing:
            return comparison, []
        return comparison, [{
            "gate": "visual_regression",
            "severity": "incomplete",
            "code": "parent_screenshot_coverage",
            "message": "Visual refinement evidence does not cover every parent route and viewport.",
            "parent_run_id": parent_run_id,
            "missing": [list(key) for key in missing],
        }]

    def visual_review_run(
        self,
        run_id: str,
        *,
        reviewer: Callable[..., VisualCritiqueReport] | None = None,
        env: Mapping[str, str] | None = None,
        source_media: Any = None,
    ) -> VisualCritiqueReport:
        """Run one read-only Qwen review against retained browser evidence."""
        run = self.get_run(run_id)
        if run["status"] in {
            DesignRunStatus.INCOMPLETE.value,
            DesignRunStatus.READY_FOR_REVIEW.value,
        }:
            report_data = run.get("quality_report_json") or {}
            if report_data.get("state") != "passed":
                raise DesignServiceError("visual review retry requires passing deterministic quality gates")
            message = (
                "Starting the explicit read-only visual review."
                if run["status"] == DesignRunStatus.READY_FOR_REVIEW.value
                else "Retrying the incomplete read-only visual review explicitly."
            )
            self._advance(run_id, DesignRunStatus.VALIDATING, message)
            run = self.get_run(run_id)
        if run["status"] != DesignRunStatus.VALIDATING.value:
            raise DesignServiceError("design run is not waiting for visual review")
        report_data = run.get("quality_report_json") or {}
        if report_data.get("state") != "passed":
            raise DesignServiceError("visual review requires passing deterministic quality gates")
        candidate_sha = str(run.get("candidate_sha") or "")
        if not candidate_sha:
            raise DesignServiceError("visual review requires an immutable candidate")
        screenshots = self._screenshot_evidence(report_data)
        planning = run.get("planning_json") or {}
        brief = planning.get("brief") if isinstance(planning, Mapping) else {}
        if not isinstance(brief, Mapping):
            brief = {"intake": run.get("intake_json") or {}}
        default_reviewer = reviewer is None
        review_evidence, source_images = self._visual_review_evidence(
            run,
            report_data,
            brief,
            screenshots,
            source_media=source_media,
        )
        if default_reviewer:
            from ..hands.design_visual_review import review_design_screenshots

            reviewer = review_design_screenshots
        try:
            reviewer_kwargs = {
                "run_id": run_id,
                "candidate_sha": candidate_sha,
                "brief": brief,
                "screenshots": screenshots,
                "env": dict(env) if env is not None else None,
            }
            if default_reviewer:
                reviewer_kwargs["memory"] = self.memory
                reviewer_kwargs["review_evidence"] = review_evidence
                reviewer_kwargs["source_images"] = source_images
            critique = reviewer(self.config, **reviewer_kwargs)
            if not isinstance(critique, VisualCritiqueReport):
                raise DesignServiceError("visual reviewer returned an invalid critique")
            if critique.candidate_sha != candidate_sha:
                raise DesignServiceError("visual critique candidate SHA does not match the candidate")
            critique_data = critique.to_dict()
            combined = {**report_data, "visual_critique": critique_data}
            self.memory.update_design_run(
                run_id,
                quality_report_json=combined,
                quality_report_hash=canonical_hash(combined),
                visual_critique_hash=canonical_hash(critique_data),
            )
            if critique.state == "passed":
                next_status = DesignRunStatus.READY_FOR_REVIEW
            elif critique.state == "inconclusive":
                next_status = DesignRunStatus.INCOMPLETE
            else:
                next_status = DesignRunStatus.NEEDS_REPAIR
            self._advance(run_id, next_status, f"Visual review ended in {critique.state}.")
            self.memory.add_design_run_event(run_id, "visual_review", "Read-only visual critique recorded.", {
                "candidate_sha": candidate_sha,
                "model_id": critique.model_id,
                "state": critique.state,
                "screenshot_count": len(screenshots),
            })
            return critique
        except Exception as exc:  # noqa: BLE001 - preserve the candidate when review infrastructure fails
            current = self.memory.get_design_run(run_id)
            if current and current["status"] == DesignRunStatus.VALIDATING.value:
                self.memory.transition_design_run(run_id, DesignRunStatus.INCOMPLETE.value, error=str(exc))
                self.memory.add_design_run_event(run_id, "visual_review_error", "Visual review was incomplete.", {
                    "error": str(exc)[:500],
                    "candidate_sha": candidate_sha,
                })
            if isinstance(exc, DesignServiceError):
                raise
            raise DesignServiceError(str(exc)) from exc

    def create_visual_refinement_run(
        self,
        parent_run_id: str,
        critique: VisualCritiqueReport,
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Create the one active refinement operation from an immutable v1.

        A failed or cancelled child may be replaced explicitly; a live child
        still blocks duplicates for the same parent candidate.
        """
        if not isinstance(critique, VisualCritiqueReport):
            raise DesignServiceError("visual refinement requires a typed critique")
        parent = self.get_run(parent_run_id)
        if parent.get("operation_kind") == "visual_refinement":
            raise DesignServiceError("a visual refinement run cannot create another refinement")
        if parent["status"] not in {
            DesignRunStatus.NEEDS_REPAIR.value,
            DesignRunStatus.READY_FOR_REVIEW.value,
            DesignRunStatus.VALIDATING.value,
        }:
            raise DesignServiceError("parent design run is not available for visual refinement")
        parent_quality = parent.get("quality_report_json") or {}
        if parent_quality.get("state") != "passed":
            raise DesignServiceError("parent design run must pass deterministic quality before visual refinement")
        if critique.run_id != parent_run_id or critique.candidate_sha != parent.get("candidate_sha"):
            raise DesignServiceError("visual critique is not bound to the parent candidate")
        if critique.state != "repair":
            raise DesignServiceError("visual refinement requires actionable critique findings")
        existing = [
            item for item in self.memory.list_design_run_children(parent_run_id, limit=500)
            if item.get("operation_kind") == "visual_refinement"
        ]
        def retryable_child(item: Mapping[str, Any]) -> bool:
            status = item.get("status")
            if status in {DesignRunStatus.FAILED.value, DesignRunStatus.CANCELLED.value}:
                return True
            if status != DesignRunStatus.NEEDS_REPAIR.value:
                return False
            report = item.get("quality_report_json") or {}
            # A child that never reached visual review may be retried after a
            # host validation failure; a child with a critique is a real
            # design outcome and remains the active single refinement.
            return not isinstance(report, Mapping) or not report.get("visual_critique")
        active_existing = [
            item for item in existing
            if not retryable_child(item)
        ]
        if active_existing:
            raise DesignServiceError("a visual refinement child already exists for this candidate")
        parent_sha = str(parent.get("candidate_sha") or "")
        if not parent_sha:
            raise DesignServiceError("parent design run has no candidate SHA")
        child_id = run_id or f"design-{uuid.uuid4().hex}"
        planning = parent.get("planning_json") or {}
        raw_request = planning.get("build_request") if isinstance(planning, Mapping) else None
        if not isinstance(raw_request, Mapping):
            if parent.get("operation_kind") != "initial_build" or not isinstance(planning, Mapping):
                raise DesignServiceError("parent design run has no persisted build request")
            try:
                intake = SiteIntake.from_dict(parent["intake_json"])
                brief = DesignBrief.from_dict(planning["brief"])
                snapshot = parent.get("context_snapshot")
                context_snapshot = DesignContextSnapshot.from_dict(snapshot) if isinstance(snapshot, Mapping) else None
                # Persisted compiler-era directions remain readable as audit
                # evidence, but they never participate in request
                # reconstruction. Refinements use the same native request
                # contract regardless of the parent's historical planning
                # shape.
                raw_request = native_homepage_request(
                    intake,
                    brief,
                    run_id=child_id,
                    base_sha=parent.get("base_sha") or "",
                    context_snapshot=context_snapshot,
                ).to_dict()
            except (KeyError, ContractError, TypeError, ValueError) as exc:
                raise DesignServiceError(f"parent design run has no reconstructable build request: {exc}") from exc
        request_data = dict(raw_request)
        request_data["run_id"] = child_id
        request_data["mode"] = "visual_refinement"
        request_data["base_sha"] = parent_sha
        content = dict(request_data.get("content") or {})
        content["visual_critique"] = critique.to_dict()
        content["visual_refinement"] = {
            "parent_run_id": parent_run_id,
            "parent_candidate_sha": parent_sha,
            "critique": critique.to_dict(),
        }
        request_data["content"] = content
        snapshot = None
        if request_data.get("context_snapshot"):
            snapshot_data = dict(request_data["context_snapshot"])
            snapshot_data["base_sha"] = parent_sha
            snapshot = DesignContextSnapshot.from_dict(snapshot_data)
            request_data["context_snapshot"] = snapshot.to_dict()
            request_data["context_snapshot_hash"] = snapshot.content_hash
        request = PageBuildRequest.from_dict(request_data)
        child = self.create_run(
            SiteIntake.from_dict(parent["intake_json"]),
            mode=parent["mode"],
            base_sha=parent_sha,
            candidate_ref=f"{parent.get('candidate_ref', 'refs/ada-design').rsplit('/', 1)[0]}/{child_id}",
            publishable=bool(parent["publishable"]),
            run_id=child_id,
            parent_run_id=parent_run_id,
            operation_kind="visual_refinement",
            source_candidate_sha=parent_sha,
            owner_request=parent.get("owner_request") or "Refine the retained design candidate.",
            conversation_id=parent.get("conversation_id"),
            source_message_id=parent.get("source_message_id"),
            chat_job_id=parent.get("chat_job_id"),
            intake_session_id=parent.get("intake_session_id"),
            intake_revision_id=parent.get("intake_revision_id"),
        )
        if parent["mode"] == "local_experiment":
            experiment = next(
                (event for event in reversed(parent.get("events") or ()) if event.get("stage") == "experiment"),
                None,
            )
            if experiment:
                self.memory.add_design_run_event(child_id, "experiment", "Reusing the isolated experiment clone for refinement.", experiment.get("detail") or {})
        if snapshot is not None:
            self.memory.update_design_run(child_id, context_snapshot=snapshot)
        self._advance(child_id, DesignRunStatus.ASSESSING_INTAKE, "Visual refinement child created from the retained candidate.")
        self._advance(child_id, DesignRunStatus.PLANNING, "Visual refinement request is ready to build.")
        planning_data = dict(planning) if isinstance(planning, Mapping) else {}
        planning_data.update({
            "build_request": request.to_dict(),
            "visual_refinement": critique.to_dict(),
        })
        # Persist the parent's frozen build profile before resolving the child
        # target. This lets local Astro refinements inherit the initial
        # candidate's allowlist instead of falling back to the generic site
        # patterns while the child is still in planning.
        self.memory.update_design_run(child_id, planning_json=planning_data)
        target = self.build_target_for_run(child_id)
        planning_data["build_target"] = target.to_dict()
        self.memory.update_design_run(child_id, planning_json=planning_data)
        self.memory.add_design_run_event(child_id, "refinement_planned", "One visual refinement operation was planned from the immutable parent.", {
            "parent_run_id": parent_run_id,
            "parent_candidate_sha": parent_sha,
            "candidate_ref": child["candidate_ref"],
        })
        if existing:
            self.memory.add_design_run_event(child_id, "refinement_retry", "Retrying a previously failed visual refinement child.", {
                "parent_run_id": parent_run_id,
                "previous_run_ids": [str(item.get("run_id") or "") for item in existing],
            })
        return {"run": self.get_run(child_id), "request": request.to_dict(), "target": target.to_dict()}

    def create_sighted_refinement_run(
        self,
        parent_run_id: str,
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Create the always-on sighted self-review pass for a valid initial build.

        The design builder is vision-capable, so every passing initial candidate
        gets exactly one follow-up refinement that reads its own rendered
        screenshots and self-critiques against the frozen brief and the shared
        design skills. No separate critic model is invoked automatically.
        """
        parent = self.get_run(parent_run_id)
        if parent.get("operation_kind") == "visual_refinement":
            return {"run": None, "request": None, "target": None, "reason": "already_refined"}
        if parent["status"] != DesignRunStatus.VALIDATING.value:
            return {"run": None, "request": None, "target": None, "reason": "not_awaiting_self_review"}
        report_data = parent.get("quality_report_json") or {}
        if report_data.get("state") != "passed":
            return {"run": None, "request": None, "target": None, "reason": "deterministic_gates_not_passed"}
        parent_sha = str(parent.get("candidate_sha") or "")
        if not parent_sha:
            return {"run": None, "request": None, "target": None, "reason": "no_candidate"}
        existing = [
            item for item in self.memory.list_design_run_children(parent_run_id, limit=500)
            if item.get("operation_kind") == "visual_refinement"
        ]
        if existing:
            return {"run": self.get_run(existing[0]["run_id"]), "request": None, "target": None, "reason": "existing"}
        screenshots = self._screenshot_evidence(report_data)
        critique = VisualCritiqueReport.from_dict({
            "run_id": parent_run_id,
            "candidate_sha": parent_sha,
            "model_id": "sighted-self-review",
            "state": "repair",
            "findings": [{
                "severity": "info",
                "category": "self_review",
                "message": (
                    "Sighted self-review: compare the rendered candidate screenshots "
                    "against the frozen creative brief and the shared design skills, then "
                    "repair the highest-impact visual, composition, motion, typography, and "
                    "responsive issues without changing the established direction."
                ),
            }],
            "repair_plan": [{
                "finding": "Hosted visual self-review",
                "change": (
                    "Open and visually read every attached evidence screenshot, self-critique "
                    "the candidate, then implement focused repairs for the most impactful "
                    "issues. Preserve the established visual system, content, routes, and "
                    "accessibility; do not redesign the site from scratch."
                ),
            }],
            "screenshot_evidence": screenshots,
        })
        created = self.create_visual_refinement_run(parent_run_id, critique, run_id=run_id)
        return created

    def validate_run(
        self,
        run_id: str,
        repo: str | Path,
        *,
        policy: QualityPolicy | None = None,
        browser: BrowserQualityAdapter | None = None,
        build_env: Mapping[str, str] | None = None,
    ):
        """Run host-owned quality gates and only then make a candidate reviewable."""
        run = self.memory.get_design_run(run_id)
        if run is None:
            raise DesignRunNotFound(f"no such design run: {run_id}")
        if run["status"] == DesignRunStatus.CANDIDATE_READY.value:
            self._advance(run_id, DesignRunStatus.VALIDATING, "Candidate retained; starting host quality validation.")
            run = self.memory.get_design_run(run_id)
        if run["status"] != DesignRunStatus.VALIDATING.value:
            raise DesignServiceError("design run is not waiting for validation")
        if not run.get("base_sha") or not run.get("candidate_sha"):
            raise DesignServiceError("design run has no immutable build identities")
        try:
            effective_policy = policy or self.quality_policy_for_run(run_id)
            build_runner = None
            if (
                run.get("mode") == "local_experiment"
                and self.build_profile_for_run(run_id) == ASTRO_REACT_PROFILE.name
            ):
                npm_cache = Path(str(self.config.get("data_dir") or ".")).expanduser().resolve() / "npm-cache"

                def build_runner(workspace: Path):
                    return build_site(
                        workspace,
                        ASTRO_REACT_PROFILE,
                        npm_cache=npm_cache,
                        env=build_env,
                        timeout_seconds=effective_policy.build_timeout_seconds,
                    ).to_dict()

            report = run_quality_gates(
                repo,
                base_sha=run["base_sha"],
                candidate_sha=run["candidate_sha"],
                run_id=run_id,
                policy=effective_policy,
                browser=browser,
                build_runner=build_runner,
                build_env=build_env,
            )
            report_data = report.to_dict()
            parent_comparison, parent_findings = self._parent_visual_comparison(run, report_data)
            if parent_comparison is not None:
                evidence = dict(report_data.get("evidence") or {})
                evidence["parent_visual_comparison"] = parent_comparison
                report_data["evidence"] = evidence
                report_data["findings"] = [*list(report_data.get("findings") or ()), *parent_findings]
                gates = dict(report_data.get("gates") or {})
                gates["parent_visual_comparison"] = parent_comparison["status"]
                report_data["gates"] = gates
                if parent_comparison["status"] == "failed":
                    report_data["state"] = "failed"
                elif parent_comparison["status"] == "incomplete" and report_data.get("state") == "passed":
                    report_data["state"] = "incomplete"
            validated_report = QualityReport.from_dict(report_data)
            quality_hash = canonical_hash(report_data)
            build_artifact_id = self._record_design_artifact(
                kind=ArtifactKind.DESIGN_BUILD,
                run_id=run_id,
                title="Host design build evidence",
                summary="Immutable candidate build and deterministic quality evidence.",
                provider_id="host",
                content_hash=quality_hash,
                preview_data={
                    "candidate_sha": run["candidate_sha"],
                    "quality_report": report_data,
                },
            )
            screenshot_evidence = self._screenshot_evidence(report_data)
            screenshot_artifact_id = None
            if screenshot_evidence:
                screenshot_artifact_id = self._record_design_artifact(
                    kind=ArtifactKind.DESIGN_SCREENSHOTS,
                    run_id=run_id,
                    title="Design screenshot evidence",
                    summary="Host-generated browser screenshots for the retained candidate.",
                    provider_id="host:playwright",
                    content_hash=canonical_hash(screenshot_evidence),
                    preview_data={"candidate_sha": run["candidate_sha"], "screenshots": screenshot_evidence},
                )
            self.memory.update_design_run(
                run_id,
                quality_report_json=report_data,
                quality_report_hash=quality_hash,
                build_artifact_id=build_artifact_id,
                screenshot_artifact_id=screenshot_artifact_id,
            )
            if validated_report.state == "passed":
                operation_kind = str(run.get("operation_kind") or "initial_build").strip()
                wants_self_review = (
                    effective_policy.visual_critic
                    and operation_kind == "initial_build"
                )
                if wants_self_review:
                    self.memory.add_design_run_event(
                        run_id,
                        "visual_review_pending",
                        "Deterministic quality passed; the sighted visual self-review is queued.",
                    )
                else:
                    self._advance(run_id, DesignRunStatus.READY_FOR_REVIEW, "All blocking quality gates passed.")
            else:
                failure_status = (
                    DesignRunStatus.INCOMPLETE
                    if validated_report.state == "incomplete"
                    else DesignRunStatus.NEEDS_REPAIR
                )
                self.memory.transition_design_run(
                    run_id,
                    failure_status.value,
                    error=f"quality gates ended in {validated_report.state}",
                )
                self.memory.add_design_run_event(run_id, "quality_failed", "The candidate is not ready for review.", {
                    "state": validated_report.state,
                    "finding_count": len(validated_report.findings),
                    "candidate_sha": run["candidate_sha"],
                })
            return validated_report
        except Exception as exc:  # noqa: BLE001 - leave a durable post-candidate diagnostic
            current = self.memory.get_design_run(run_id)
            if current and current["status"] not in {
                DesignRunStatus.FAILED.value,
                DesignRunStatus.CANCELLED.value,
                DesignRunStatus.NEEDS_REPAIR.value,
                DesignRunStatus.INCOMPLETE.value,
            }:
                target_status = DesignRunStatus.INCOMPLETE if current.get("candidate_sha") else DesignRunStatus.FAILED
                self.memory.transition_design_run(run_id, target_status.value, error=str(exc))
                self.memory.add_design_run_event(run_id, "quality_error", "Quality validation failed.", {"error": str(exc)[:500]})
            if isinstance(exc, DesignServiceError):
                raise
            raise DesignServiceError(str(exc)) from exc


__all__ = ["DesignRunNotFound", "DesignService", "DesignServiceError"]
