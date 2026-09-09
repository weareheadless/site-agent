"""Finite specialist orchestration for typed design planning.

The coordinator owns phase order and persistence. OpenCode specialists only
return phase artifacts; they cannot dispatch another phase or decide whether a
new creative round is needed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping, Protocol, Sequence, Type
from pathlib import Path

from ..core.contracts import ContractError
from ..core.design_contracts import (
    BuildTarget,
    BrandSourceMap,
    CopyDeck,
    CreativeConcept,
    DesignPhase,
    DesignPhaseArtifact,
    DesignPlanBundle,
    ExperiencePlanBundle,
    BrandSourceReport,
    TransferReview,
    CreativeRealizationReview,
    CriticReport,
    ImplementationReport,
    MotionReport,
    PageBuildRequest,
    RepairBrief,
    RepairReport,
    canonical_hash,
    canonical_json,
)
from ..hands.opencode_provider import (
    OpenCodeSpecialistAdapter,
    SpecialistInvocation,
    SpecialistProviderError,
    decode_structured_output,
    structured_output_prompt,
)


class DesignOrchestrationError(RuntimeError):
    """A finite specialist workflow could not complete a phase."""


class SpecialistInvoker(Protocol):
    def invoke(self, request: SpecialistInvocation, progress=None):
        ...


@dataclass(frozen=True)
class DesignPlanResult:
    copy_deck: CopyDeck
    concepts: tuple[CreativeConcept, ...]
    plan: DesignPlanBundle
    creative_director_session_id: str
    experience_plan: ExperiencePlanBundle | None = None

    @property
    def locked_plan(self) -> DesignPlanBundle:
        """Return the durable phase envelope used by realization and repair."""
        return self.plan


@dataclass(frozen=True)
class DesignReviewResult:
    creative_review: CreativeRealizationReview
    experience_review: CriticReport
    technical_review: CriticReport

    @property
    def needs_repair(self) -> bool:
        reports = (self.creative_review, self.experience_review, self.technical_review)
        for report in reports:
            payload = report.payload
            if payload.get("needs_repair") is True or payload.get("state") in {"repair", "failed"}:
                return True
        return False


class SpecialistDesignCoordinator:
    """Run the finite copy/concept/selection portion of a design workflow."""

    CONCEPT_VARIANTS = ("a", "b", "c")

    def __init__(
        self,
        context: Mapping[str, Any],
        *,
        invoker: SpecialistInvoker | None = None,
        scratch_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.context = dict(context)
        self.memory = self.context.get("memory")
        if self.memory is None:
            raise DesignOrchestrationError("specialist orchestration requires durable memory")
        self.config = dict(self.context.get("config") or {})
        self.invoker = invoker or OpenCodeSpecialistAdapter()
        self.scratch_factory = scratch_factory or TemporaryDirectory

    @staticmethod
    def _brief(request: PageBuildRequest) -> dict[str, Any]:
        snapshot = request.context_snapshot
        site_facts = snapshot.site_facts if snapshot is not None else {}
        result = {
            "owner_request": str((request.content or {}).get("creative_prompt") or request.purpose),
            "purpose": request.purpose,
            "acceptance_criteria": list(request.acceptance_criteria),
            "required_files": list(request.required_files),
            "media_paths": list(request.supplied_media_paths),
            "business": dict(site_facts.get("business") or {}),
            "audience": dict(site_facts.get("audience") or {}),
            "conversion": dict(site_facts.get("conversion") or {}),
            "brand": dict(site_facts.get("brand") or {}),
            "constraints": dict(site_facts.get("constraints") or {}),
            "unknowns": list(snapshot.unknowns if snapshot is not None else ()),
            "capabilities": list(snapshot.capabilities if snapshot is not None else ()),
        }
        if snapshot is not None:
            result["asset_inventory"] = [dict(item) for item in snapshot.asset_inventory]
            result["asset_visual_evidence"] = [item.to_dict() for item in snapshot.asset_visual_evidence]
            result["asset_visual_evidence_errors"] = list(
                snapshot.extra.get("asset_visual_evidence_errors") or ()
                if isinstance(snapshot.extra, Mapping)
                else ()
            )
        return result

    def _experience_plan_required(self, request: PageBuildRequest) -> bool:
        engine = self.config.get("design_engine") or {}
        return request.context_snapshot is not None or bool(engine.get("require_experience_plan"))

    @staticmethod
    def _brand_source_map(report: BrandSourceReport) -> BrandSourceMap:
        payload = report.payload
        raw = payload.get("brand_source_map") if isinstance(payload, Mapping) else None
        if not isinstance(raw, Mapping):
            raise DesignOrchestrationError("brand-source phase did not return a brand_source_map")
        try:
            return BrandSourceMap.from_dict(raw)
        except ContractError as exc:
            raise DesignOrchestrationError(str(exc)) from exc

    @staticmethod
    def _strict_experience_plan(
        plan: DesignPlanBundle,
        request: PageBuildRequest,
        target: BuildTarget,
        copy_deck: CopyDeck,
        *,
        asset_evidence: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[DesignPlanBundle, ExperiencePlanBundle]:
        """Validate and normalize the creative director's locked bundle."""
        raw = dict(plan.payload)
        # The copy deck remains a separate durable phase artifact. Include its
        # canonical envelope in the locked plan so realization receives the
        # final visible-copy decisions without weakening the phase contract.
        raw.setdefault("copy_deck", copy_deck.to_dict())
        try:
            bundle = ExperiencePlanBundle.from_dict(raw)
        except ContractError as exc:
            raise DesignOrchestrationError(str(exc)) from exc
        if bundle.run_id != request.run_id or bundle.base_sha != target.base_sha:
            raise DesignOrchestrationError("experience plan identity does not match the design run")
        if bundle.context_snapshot_hash != request.context_snapshot_hash:
            raise DesignOrchestrationError("experience plan context hash does not match the design run")
        if bundle.copy_deck_hash != copy_deck.content_hash:
            raise DesignOrchestrationError("experience plan copy_deck_hash does not match the final copy deck")
        if copy_deck.content_hash not in bundle.input_artifact_hashes:
            raise DesignOrchestrationError("experience plan input hashes omit the final copy deck")
        allowed = {str(item.get("asset_id")): str(item.get("asset_sha256")) for item in asset_evidence if isinstance(item, Mapping)}
        for item in bundle.asset_evidence:
            if request.context_snapshot is not None and (item.asset_id not in allowed or allowed[item.asset_id] != item.asset_sha256):
                raise DesignOrchestrationError(f"experience plan uses asset evidence outside the frozen snapshot: {item.asset_id}")
        normalized_raw = {**plan.to_dict(), "payload": bundle.to_dict()}
        try:
            normalized_plan = DesignPlanBundle.from_dict(normalized_raw)
        except ContractError as exc:
            raise DesignOrchestrationError(str(exc)) from exc
        return normalized_plan, bundle

    @staticmethod
    def _transfer_passed(review: TransferReview, plan_hash: str) -> None:
        payload = review.payload
        state = str(payload.get("state") or "").strip().lower()
        if state != "passed":
            raise DesignOrchestrationError("experience plan failed the counterfactual transfer test")
        reported_hash = str(payload.get("plan_hash") or "").strip().lower()
        if reported_hash and reported_hash != plan_hash:
            raise DesignOrchestrationError("transfer review plan hash does not match the locked experience plan")

    @staticmethod
    def _input_hashes(request: PageBuildRequest, *artifacts: DesignPhaseArtifact) -> tuple[str, ...]:
        hashes = [canonical_hash(request.to_dict())]
        if request.context_snapshot_hash:
            hashes.append(request.context_snapshot_hash)
        hashes.extend(artifact.content_hash for artifact in artifacts)
        return tuple(dict.fromkeys(hashes))

    def _invoke_phase(
        self,
        *,
        request: PageBuildRequest,
        target: BuildTarget,
        role: str,
        phase: str,
        variant_key: str,
        contract: Type[DesignPhaseArtifact],
        instruction: str,
        input_hashes: tuple[str, ...],
        progress=None,
        session_id: str | None = None,
        image_files: Sequence[str] = (),
        workspace: str | Path | None = None,
    ) -> tuple[DesignPhaseArtifact, str]:
        claimed = self.memory.claim_design_phase(
            request.run_id,
            phase,
            variant_key=variant_key,
            base_sha=target.base_sha,
            context_snapshot_hash=request.context_snapshot_hash,
            input_hashes=input_hashes,
            provider_id=str((self.config.get("design_engine") or {}).get("provider") or "openrouter"),
            model=str((self.config.get("design_engine") or {}).get("model") or ""),
            session_id=session_id or "",
        )
        if claimed["status"] == "completed":
            artifact = contract.from_dict(claimed["payload"])
            return artifact, str(claimed.get("session_id") or "")
        if claimed["status"] == "running" and not claimed.get("claimed"):
            raise DesignOrchestrationError(
                f"design phase is already running: {phase}/{variant_key}"
            )
        attempt = int(claimed["attempt"])
        envelope_prompt = structured_output_prompt(
            instruction
            + "\nPHASE INPUTS:\n"
            + canonical_json(self._brief(request))
            + f"\nThe host expects attempt {attempt} and variant {variant_key or 'primary'}. "
            "Preserve all verified unknowns and do not invent destinations or claims.",
            contract.__name__,
        )
        try:
            workspace_context = (
                nullcontext(Path(workspace).expanduser().resolve())
                if workspace is not None
                else self.scratch_factory()
            )
            with workspace_context as scratch:
                invocation = SpecialistInvocation(
                    role=role,
                    workspace=scratch,
                    prompt=envelope_prompt,
                    config=self.config,
                    session_id=session_id,
                    timeout_seconds=int((self.config.get("design_engine") or {}).get("specialist_timeout_seconds", 300)),
                    api_key_env=str((self.config.get("design_engine") or {}).get("api_key_env") or "") or None,
                    api_key=self.context.get("api_key"),
                    env=self.context.get("env"),
                    image_files=tuple(str(item) for item in image_files),
                    memory=self.memory,
                )
                result = self.invoker.invoke(invocation, progress=progress)
            raw = result.provider_dict() if hasattr(result, "provider_dict") else result
            payload = decode_structured_output(raw)
            artifact = contract.from_dict(payload)
            if artifact.run_id != request.run_id or artifact.base_sha != target.base_sha:
                raise DesignOrchestrationError("specialist artifact identity does not match the design run")
            if artifact.context_snapshot_hash != request.context_snapshot_hash:
                raise DesignOrchestrationError("specialist artifact context hash does not match the design run")
            if artifact.phase != phase or artifact.variant_key != variant_key or artifact.attempt != attempt:
                raise DesignOrchestrationError("specialist artifact phase identity does not match its claim")
            completed = self.memory.complete_design_phase(
                claimed["id"],
                artifact.to_dict(),
                output_hash=artifact.content_hash,
                prompt_tokens=int((getattr(result, "usage", {}) or {}).get("prompt_tokens", 0)),
                completion_tokens=int((getattr(result, "usage", {}) or {}).get("completion_tokens", 0)),
                reported_cost_usd=getattr(result, "cost", None),
                session_id=str(getattr(result, "session_id", "") or ""),
            )
            return contract.from_dict(completed["payload"]), str(getattr(result, "session_id", "") or "")
        except Exception as exc:  # noqa: BLE001 - failure is persisted before surfacing
            self.memory.fail_design_phase(
                claimed["id"],
                error_code="specialist_error",
                error_detail=str(exc),
            )
            if isinstance(exc, (DesignOrchestrationError, SpecialistProviderError, ContractError)):
                raise
            raise DesignOrchestrationError(str(exc)) from exc

    def record_implementation_phase(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        plan: DesignPlanBundle,
        provider_result: Mapping[str, Any],
    ) -> ImplementationReport:
        """Persist host evidence for the implementation turn before motion begins."""
        input_hashes = self._input_hashes(request, plan)
        claimed = self.memory.claim_design_phase(
            request.run_id,
            DesignPhase.IMPLEMENTATION.value,
            variant_key="primary",
            base_sha=target.base_sha,
            context_snapshot_hash=request.context_snapshot_hash,
            input_hashes=input_hashes,
            provider_id="host",
            model="",
        )
        if claimed["status"] == "completed":
            return ImplementationReport.from_dict(claimed["payload"])
        if claimed["status"] == "running" and not claimed.get("claimed"):
            raise DesignOrchestrationError("design phase is already running: implementation/primary")
        artifact = ImplementationReport.from_dict({
            "schema_version": 1,
            "run_id": request.run_id,
            "phase": DesignPhase.IMPLEMENTATION.value,
            "variant_key": "primary",
            "attempt": int(claimed["attempt"]),
            "status": "completed",
            "base_sha": target.base_sha,
            "context_snapshot_hash": request.context_snapshot_hash,
            "input_hashes": list(input_hashes),
            "producer": "host",
            "payload": dict(provider_result),
        })
        completed = self.memory.complete_design_phase(
            claimed["id"],
            artifact.to_dict(),
            output_hash=artifact.content_hash,
            session_id=str(provider_result.get("session_id") or ""),
        )
        return ImplementationReport.from_dict(completed["payload"])

    def run_motion_phase(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        plan: DesignPlanBundle,
        workspace: str | Path,
        progress=None,
        image_files: Sequence[str] = (),
    ) -> MotionReport:
        """Give the motion specialist one write turn in the existing worktree."""
        instruction = (
            "Act as the motion designer for the already implemented locked plan. Inspect the current source and apply "
            "only purposeful motion named or implied by the selected direction. Keep the resting state complete, "
            "respect prefers-reduced-motion, avoid layout-thrashing effects, and do not redesign the page. "
            "After editing, run one bounded local check and return the motion report.\nLOCKED PLAN:\n"
            + canonical_json(plan.to_dict())
        )
        artifact, _ = self._invoke_phase(
            request=request,
            target=target,
            role="motion-designer",
            phase=DesignPhase.MOTION.value,
            variant_key="primary",
            contract=MotionReport,
            instruction=instruction,
            input_hashes=self._input_hashes(request, plan),
            progress=progress,
            workspace=workspace,
            image_files=image_files,
        )
        return artifact  # type: ignore[return-value]

    def review_candidate(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        plan: DesignPlanBundle,
        candidate_sha: str = "",
        creative_director_session_id: str | None = None,
        screenshots: Sequence[Mapping[str, Any]] = (),
        quality_evidence: Mapping[str, Any] | None = None,
        progress=None,
    ) -> DesignReviewResult:
        """Run one creative-director review and two independent read-only critics."""
        evidence = {
            "candidate_sha": str(candidate_sha or ""),
            "screenshots": [dict(item) for item in screenshots][:24],
            "quality": dict(quality_evidence or {}),
        }
        evidence_hash = canonical_hash(evidence)
        image_files = tuple(
            str(item.get("screenshot_path"))
            for item in screenshots
            if str(item.get("screenshot_path") or "").strip()
            and Path(str(item.get("screenshot_path"))).expanduser().is_file()
        )
        review_inputs = (*self._input_hashes(request, plan), evidence_hash)
        creative_instruction = (
            "Act as the creative director continuing the selection session. Review the rendered candidate evidence "
            "against the locked plan. Do not invent a new direction. Identify only concrete realization deviations, "
            "and set needs_repair true only when a focused repair would materially improve the locked direction. "
            "Return the final creative realization review.\nLOCKED PLAN:\n"
            + canonical_json(plan.to_dict())
            + "\nRENDERED EVIDENCE:\n"
            + canonical_json(evidence)[:80_000]
        )
        creative_review, _ = self._invoke_phase(
            request=request,
            target=target,
            role="creative-director",
            phase=DesignPhase.CREATIVE_REALIZATION_REVIEW.value,
            variant_key="primary",
            contract=CreativeRealizationReview,
            instruction=creative_instruction,
            input_hashes=review_inputs,
            progress=progress,
            session_id=creative_director_session_id or self._creative_director_session(request.run_id),
            image_files=image_files,
        )

        critic_instructions = {
            "experience": (
                "Act as an independent experience critic. Review only the supplied rendered evidence and locked plan. "
                "Check comprehension, hierarchy, audience fit, conversion clarity, accessibility, responsive resting "
                "states, and whether the experience feels specific rather than generic. Do not edit files or propose a "
                "new direction. Return concrete findings and needs_repair.\n"
            ),
            "technical": (
                "Act as an independent technical critic. Review only the supplied rendered evidence, quality evidence, "
                "and locked plan. Check implementation-risk signals, motion safety, responsive behavior, accessibility, "
                "and host-policy drift. Do not edit files or propose a new direction. Return concrete findings and "
                "needs_repair.\n"
            ),
        }
        critic_results: dict[str, CriticReport] = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="design-critic") as pool:
            futures = {
                pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role=f"{kind}-critic",
                    phase=(
                        DesignPhase.EXPERIENCE_REVIEW.value
                        if kind == "experience"
                        else DesignPhase.TECHNICAL_REVIEW.value
                    ),
                    variant_key=kind,
                    contract=CriticReport,
                    instruction=instruction + "LOCKED PLAN:\n" + canonical_json(plan.to_dict())
                    + "\nRENDERED EVIDENCE:\n" + canonical_json(evidence)[:80_000],
                    input_hashes=review_inputs,
                    progress=progress,
                    image_files=image_files,
                ): kind
                for kind, instruction in critic_instructions.items()
            }
            for future in as_completed(futures):
                kind = futures[future]
                artifact, _ = future.result()
                critic_results[kind] = artifact  # type: ignore[assignment]
        return DesignReviewResult(
            creative_review=creative_review,  # type: ignore[arg-type]
            experience_review=critic_results["experience"],
            technical_review=critic_results["technical"],
        )

    def create_repair_brief(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        plan: DesignPlanBundle,
        review: DesignReviewResult,
    ) -> RepairBrief | None:
        """Freeze one bounded repair scope from the review panel."""
        if not review.needs_repair:
            return None
        payload = {
            "needs_repair": True,
            "locked_plan_hash": plan.content_hash,
            "scope": "Apply only the highest-impact concrete findings; do not change the chosen direction.",
            "findings": [
                {"review": "creative_director", **self._bounded_review_payload(review.creative_review.payload)},
                {"review": "experience", **self._bounded_review_payload(review.experience_review.payload)},
                {"review": "technical", **self._bounded_review_payload(review.technical_review.payload)},
            ],
            "max_repair_turns": 1,
        }
        input_hashes = self._input_hashes(request, plan) + (
            canonical_hash(payload),
        )
        claimed = self.memory.claim_design_phase(
            request.run_id,
            DesignPhase.REPAIR_BRIEF.value,
            variant_key="primary",
            base_sha=target.base_sha,
            context_snapshot_hash=request.context_snapshot_hash,
            input_hashes=input_hashes,
            provider_id="host",
            model="",
        )
        if claimed["status"] == "completed":
            return RepairBrief.from_dict(claimed["payload"])
        if claimed["status"] == "running" and not claimed.get("claimed"):
            raise DesignOrchestrationError("design phase is already running: repair_brief/primary")
        artifact = RepairBrief.from_dict({
            "schema_version": 1,
            "run_id": request.run_id,
            "phase": DesignPhase.REPAIR_BRIEF.value,
            "variant_key": "primary",
            "attempt": int(claimed["attempt"]),
            "status": "completed",
            "base_sha": target.base_sha,
            "context_snapshot_hash": request.context_snapshot_hash,
            "input_hashes": list(input_hashes),
            "producer": "host",
            "payload": payload,
        })
        completed = self.memory.complete_design_phase(
            claimed["id"],
            artifact.to_dict(),
            output_hash=artifact.content_hash,
        )
        return RepairBrief.from_dict(completed["payload"])

    def final_signoff(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        plan: DesignPlanBundle,
        review: DesignReviewResult,
        creative_director_session_id: str | None = None,
        progress=None,
    ) -> CreativeRealizationReview:
        """Use the selecting creative director session for one final sign-off."""
        instruction = (
            "Act as the creative director for the final sign-off. Confirm that the retained candidate implements the "
            "locked direction and that the review panel found no unresolved material repair. Do not introduce a new "
            "direction. Return a final sign-off with state passed only when the evidence is sufficient.\nLOCKED PLAN:\n"
            + canonical_json(plan.to_dict())
            + "\nREVIEW PANEL:\n"
            + canonical_json({
                "creative": review.creative_review.payload,
                "experience": review.experience_review.payload,
                "technical": review.technical_review.payload,
            })[:80_000]
        )
        artifact, _ = self._invoke_phase(
            request=request,
            target=target,
            role="creative-director",
            phase=DesignPhase.CREATIVE_FINAL_SIGNOFF.value,
            variant_key="primary",
            contract=CreativeRealizationReview,
            instruction=instruction,
            input_hashes=self._input_hashes(request, plan),
            progress=progress,
            session_id=creative_director_session_id or self._creative_director_session(request.run_id),
        )
        return artifact  # type: ignore[return-value]

    @staticmethod
    def _bounded_review_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        for key in ("findings", "repair_plan", "strengths"):
            value = result.get(key)
            if isinstance(value, list):
                result[key] = value[:24]
        return result

    def record_repair_phase(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        *,
        repair_brief: Mapping[str, Any],
        provider_result: Mapping[str, Any],
    ) -> RepairReport:
        """Persist the one repair implementer turn on a refinement candidate."""
        input_hashes = (
            canonical_hash(request.to_dict()),
            canonical_hash(dict(repair_brief)),
        )
        claimed = self.memory.claim_design_phase(
            request.run_id,
            DesignPhase.REPAIR.value,
            variant_key="primary",
            base_sha=target.base_sha,
            context_snapshot_hash=request.context_snapshot_hash,
            input_hashes=input_hashes,
            provider_id="host",
            model="",
        )
        if claimed["status"] == "completed":
            return RepairReport.from_dict(claimed["payload"])
        if claimed["status"] == "running" and not claimed.get("claimed"):
            raise DesignOrchestrationError("design phase is already running: repair/primary")
        artifact = RepairReport.from_dict({
            "schema_version": 1,
            "run_id": request.run_id,
            "phase": DesignPhase.REPAIR.value,
            "variant_key": "primary",
            "attempt": int(claimed["attempt"]),
            "status": "completed",
            "base_sha": target.base_sha,
            "context_snapshot_hash": request.context_snapshot_hash,
            "input_hashes": list(input_hashes),
            "producer": "host",
            "payload": {
                "repair_brief_hash": canonical_hash(dict(repair_brief)),
                **dict(provider_result),
            },
        })
        completed = self.memory.complete_design_phase(
            claimed["id"],
            artifact.to_dict(),
            output_hash=artifact.content_hash,
            session_id=str(provider_result.get("session_id") or ""),
        )
        return RepairReport.from_dict(completed["payload"])

    def _creative_director_session(self, run_id: str) -> str:
        records = self.memory.list_design_phase_artifacts(
            run_id,
            phase=DesignPhase.CREATIVE_SELECTION.value,
            status="completed",
        )
        if not records:
            raise DesignOrchestrationError("creative selection is required before realization review")
        return str(records[-1].get("session_id") or "")

    def create_plan(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress=None,
        *,
        image_files: Sequence[str] = (),
    ) -> DesignPlanResult:
        """Create the finite creative plan, using the strict bundle when frozen context exists."""
        if not self._experience_plan_required(request):
            return self._create_legacy_plan(request, target, progress, image_files=image_files)
        if request.context_snapshot is None:
            raise DesignOrchestrationError("strict experience planning requires a frozen context snapshot")
        if not request.run_id:
            raise DesignOrchestrationError("design request has no stable run identity")

        input_hashes = self._input_hashes(request)
        copy_instruction = (
            "Act as the copywriter. Produce the final visible copy hierarchy for the required page. "
            "Use verified facts only, preserve unresolved contact details, and make the primary action honest."
        )
        brand_instruction = (
            "Act as the brand-source analyst. Read the frozen owner context and approved asset visual evidence. "
            "Return a payload with exactly one brand_source_map object describing only evidence-backed visual grammar. "
            "Do not choose a page template, invent brand claims, or implement source. Preserve signals that are not safe "
            "to infer and reference the supplied evidence IDs."
        )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="design-foundation") as pool:
            futures = {
                "copy": pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="copywriter",
                    phase=DesignPhase.COPY.value,
                    variant_key="primary",
                    contract=CopyDeck,
                    instruction=copy_instruction,
                    input_hashes=input_hashes,
                    progress=progress,
                    image_files=image_files,
                ),
                "brand": pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="brand-source-analyst",
                    phase=DesignPhase.BRAND_SOURCE.value,
                    variant_key="primary",
                    contract=BrandSourceReport,
                    instruction=brand_instruction,
                    input_hashes=input_hashes,
                    progress=progress,
                    image_files=image_files,
                ),
            }
            results: dict[str, tuple[DesignPhaseArtifact, str]] = {}
            for future in as_completed(futures.values()):
                key = next(name for name, item in futures.items() if item is future)
                results[key] = future.result()

        copy_deck = results["copy"][0]
        brand_report = results["brand"][0]
        brand_map = self._brand_source_map(brand_report)  # type: ignore[arg-type]
        concept_inputs = self._input_hashes(request, copy_deck, brand_report)
        concept_instruction = (
            "Act as an independent visual concept designer. Develop one distinctive concept for this specific audience "
            "and supplied media. The concept must include exact asset assignments, logo integration, a behavioral thesis, "
            "one signature behavior, responsive and reduced-motion translations, feasibility risks, evidence references, "
            "and a transfer-test prediction. Do not implement source or copy a template.\nBRAND SOURCE MAP:\n"
            + canonical_json(brand_map.to_dict())
        )
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="design-concept") as pool:
            futures = {
                variant: pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="concept-designer",
                    phase=DesignPhase.CONCEPT.value,
                    variant_key=variant,
                    contract=CreativeConcept,
                    instruction=concept_instruction,
                    input_hashes=concept_inputs,
                    progress=progress,
                    image_files=image_files,
                )
                for variant in self.CONCEPT_VARIANTS
            }
            concept_results: dict[str, tuple[DesignPhaseArtifact, str]] = {}
            for future in as_completed(futures.values()):
                variant = next(name for name, item in futures.items() if item is future)
                concept_results[variant] = future.result()
        concepts = tuple(concept_results[variant][0] for variant in self.CONCEPT_VARIANTS)
        selection_inputs = self._input_hashes(request, copy_deck, brand_report, *concepts)
        asset_evidence = [item.to_dict() for item in request.context_snapshot.asset_visual_evidence]
        selection_prompt = (
            "Act as the creative director. Compare the three independent concepts, select the strongest direction or "
            "synthesize only named strengths, and emit one strict ExperiencePlanBundle as the payload of the phase "
            "envelope. The bundle must freeze the asset composition plan and brand behavior system before repository "
            "mutation. Every selected asset must use an ID and hash from the frozen evidence. The behavior must be "
            "specific to the supplied business, audience, copy, or media, pass the counterfactual transfer test, and "
            "include complete no-JavaScript, reduced-motion, mobile, keyboard, resting-state, and observable acceptance "
            "conditions. Do not implement source or invent a template. Use these exact hashes: run_id="
            + request.run_id
            + ", base_sha=" + target.base_sha
            + ", context_snapshot_hash=" + request.context_snapshot_hash
            + ", copy_deck_hash=" + copy_deck.content_hash
            + ". The payload must set input_artifact_hashes to include the copy deck hash and transfer_test.state to passed.\n"
            "COPY DECK:\n" + canonical_json(copy_deck.to_dict())
            + "\nBRAND SOURCE MAP:\n" + canonical_json(brand_map.to_dict())
            + "\nFROZEN ASSET EVIDENCE:\n" + canonical_json(asset_evidence)
            + "\nCONCEPTS:\n" + canonical_json([concept.to_dict() for concept in concepts])
        )
        plan, director_session = self._invoke_phase(
            request=request,
            target=target,
            role="creative-director",
            phase=DesignPhase.CREATIVE_SELECTION.value,
            variant_key="primary",
            contract=DesignPlanBundle,
            instruction=selection_prompt,
            input_hashes=selection_inputs,
            progress=progress,
            image_files=image_files,
        )
        normalized_plan, experience_plan = self._strict_experience_plan(
            plan,
            request,
            target,
            copy_deck,  # type: ignore[arg-type]
            asset_evidence=asset_evidence,
        )
        if experience_plan.brand_source_map.content_hash != brand_map.content_hash:
            raise DesignOrchestrationError("experience plan brand_source_map does not match the frozen brand-source phase")

        transfer_instruction = (
            "Act as the adversarial transfer critic. Review only the locked ExperiencePlanBundle and its evidence. "
            "Run the unrelated-business counterfactual: reject generic or unsupported metaphors, but do not replace the "
            "selected direction. Return a payload with state passed or rejected, plan_hash, evidence_specific_elements, "
            "transferable_elements, unsupported_metaphors, and required_corrections.\nLOCKED EXPERIENCE PLAN:\n"
            + canonical_json(experience_plan.to_dict())
            + "\nPLAN HASH: " + experience_plan.content_hash
        )
        transfer, _ = self._invoke_phase(
            request=request,
            target=target,
            role="transfer-critic",
            phase=DesignPhase.TRANSFER_REVIEW.value,
            variant_key="primary",
            contract=TransferReview,
            instruction=transfer_instruction,
            input_hashes=self._input_hashes(request, normalized_plan),
            progress=progress,
            image_files=image_files,
        )
        self._transfer_passed(transfer, experience_plan.content_hash)  # type: ignore[arg-type]
        return DesignPlanResult(
            copy_deck=copy_deck,  # type: ignore[arg-type]
            concepts=tuple(concepts),  # type: ignore[arg-type]
            plan=normalized_plan,
            creative_director_session_id=director_session,
            experience_plan=experience_plan,
        )

    def _create_legacy_plan(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress=None,
        *,
        image_files: Sequence[str] = (),
    ) -> DesignPlanResult:
        """Create exactly one copy deck, three concepts, and one selection."""
        if not request.run_id:
            raise DesignOrchestrationError("design request has no stable run identity")
        input_hashes = self._input_hashes(request)
        copy_instruction = (
            "Act as the copywriter. Produce the final visible copy hierarchy for the required page. "
            "Use verified facts only, preserve unresolved contact details, and make the primary action honest."
        )
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="design-specialist") as pool:
            futures = {
                "copy": pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="copywriter",
                    phase=DesignPhase.COPY.value,
                    variant_key="primary",
                    contract=CopyDeck,
                    instruction=copy_instruction,
                    input_hashes=input_hashes,
                    progress=progress,
                    image_files=image_files,
                )
            }
            for variant in self.CONCEPT_VARIANTS:
                futures[f"concept-{variant}"] = pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="concept-designer",
                    phase=DesignPhase.CONCEPT.value,
                    variant_key=variant,
                    contract=CreativeConcept,
                    instruction=(
                        "Act as an independent visual concept designer. Develop one distinctive concept "
                        "for this specific audience and supplied media. Do not implement source or copy a template."
                    ),
                    input_hashes=input_hashes,
                    progress=progress,
                    image_files=image_files,
                )
            results: dict[str, tuple[DesignPhaseArtifact, str]] = {}
            for future in as_completed(futures.values()):
                key = next(name for name, item in futures.items() if item is future)
                results[key] = future.result()
        copy_deck, copy_session = results["copy"]
        concepts = tuple(results[f"concept-{variant}"][0] for variant in self.CONCEPT_VARIANTS)
        selection_inputs = self._input_hashes(request, copy_deck, *concepts)
        selection_prompt = (
            "Act as the creative director. Compare the three independent concepts, select the strongest direction "
            "or synthesize only named strengths, and lock a concrete implementation bundle. Protect the chosen concept "
            "from generic-template drift. The same session will later review the rendered realization.\n"
            "COPY DECK:\n" + canonical_json(copy_deck.to_dict())
            + "\nCONCEPTS:\n" + canonical_json([concept.to_dict() for concept in concepts])
        )
        plan, director_session = self._invoke_phase(
            request=request,
            target=target,
            role="creative-director",
            phase=DesignPhase.CREATIVE_SELECTION.value,
            variant_key="primary",
            contract=DesignPlanBundle,
            instruction=selection_prompt,
            input_hashes=selection_inputs,
            progress=progress,
            image_files=image_files,
        )
        return DesignPlanResult(
            copy_deck=copy_deck,  # type: ignore[arg-type]
            concepts=tuple(concepts),  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            creative_director_session_id=director_session or copy_session,
        )
