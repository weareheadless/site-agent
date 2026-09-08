"""Application service for assembling and serving accepted customer context."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.contracts import ContractError, utc_now
from ..core.customer_context_contracts import (
    AcceptanceManifest,
    CustomerAssetBinding,
    CustomerContextSnapshot,
    ResearchEvidenceManifest,
)
from ..core.design_contracts import SiteIntake, canonical_hash
from ..core.memory import Memory


class CustomerContextService:
    """Keep the complete accepted context available behind one service boundary."""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory

    def snapshot_for_run(
        self,
        incubation_id: str,
        run: Mapping[str, Any],
        *,
        website_source: Mapping[str, Any] | None = None,
    ) -> tuple[CustomerContextSnapshot, AcceptanceManifest]:
        if not isinstance(run, Mapping):
            raise ContractError("design run must be an object")
        run_id = str(run.get("run_id") or "").strip()
        candidate_sha = str(run.get("candidate_sha") or "").strip().lower()
        session_id = str(run.get("intake_session_id") or "").strip()
        if not run_id or not candidate_sha or not session_id:
            raise ContractError("accepted design run is missing its immutable lineage")

        intake_value = run.get("intake_json")
        if not isinstance(intake_value, Mapping):
            raise ContractError("accepted design run is missing its intake")
        intake = SiteIntake.from_dict(intake_value)
        intake_hash = str(run.get("intake_hash") or intake.content_hash).strip().lower()
        if len(intake_hash) != 64:
            raise ContractError("accepted design run intake hash is invalid")

        revisions = self.memory.list_design_intake_revisions(session_id, limit=500)
        revision_id = run.get("intake_revision_id")
        selected_revision = None
        if isinstance(revision_id, int) and revision_id > 0:
            selected_revision = next((item for item in revisions if int(item.get("id") or 0) == revision_id), None)
        if selected_revision is None:
            selected_revision = next(
                (
                    item for item in reversed(revisions)
                    if str(item.get("site_intake_hash") or "") == intake_hash
                    or str(item.get("draft_hash") or "") == intake_hash
                ),
                None,
            )
        if selected_revision is None:
            raise ContractError("accepted design run does not reference a stored intake revision")
        intake_revision = int(selected_revision.get("revision") or 0)
        if intake_revision < 1:
            raise ContractError("accepted intake revision is invalid")
        intake_revision_id = int(selected_revision["id"]) if selected_revision.get("id") else None

        genesis_record = self.memory.get_customer_genesis_revision()
        if genesis_record is None:
            raise ContractError("accepted incubation has no customer genesis")
        genesis = genesis_record["genesis"]
        genesis_hash = genesis.content_hash
        run_hash = design_run_content_hash(run)
        context_id = "ctx_" + canonical_hash({
            "incubation_id": str(incubation_id),
            "run_id": run_id,
            "intake_hash": intake_hash,
            "genesis_hash": genesis_hash,
        })[:32]

        # The session's current asset table is mutable: changing a confirmed
        # intake starts a new collecting revision. Accepted context must use the
        # exact revision bound to this design run, never whatever is current when
        # provisioning is attempted later.
        frozen_draft = selected_revision.get("draft")
        frozen_assets = frozen_draft.get("assets") if isinstance(frozen_draft, Mapping) else None
        if not isinstance(frozen_assets, list):
            frozen_assets = intake_value.get("assets") if isinstance(intake_value.get("assets"), list) else []

        assets: list[CustomerAssetBinding] = []
        for item in frozen_assets:
            if not isinstance(item, Mapping):
                raise ContractError("accepted intake asset binding is invalid")
            raw_asset_id = item.get("asset_id") or item.get("id")
            try:
                asset_id = int(raw_asset_id)
            except (TypeError, ValueError) as exc:
                raise ContractError("accepted intake asset binding has an invalid asset id") from exc
            media_asset = self.memory.get_media_asset(asset_id)
            if media_asset is None:
                raise ContractError(f"accepted intake asset {asset_id} is unavailable")
            analysis = media_asset.analysis if isinstance(media_asset.analysis, Mapping) else {}
            assets.append(CustomerAssetBinding.from_dict({
                "asset_id": asset_id,
                "position": item.get("position", 0),
                "usage": item.get("usage") or "undecided",
                "content_hash": item.get("content_hash") or media_asset.original_sha256,
                "role": item.get("role") or item.get("usage") or "",
                "required": bool(item.get("required")),
                "reference_aspects": item.get("reference_aspects") or [],
                "analysis_hash": item.get("analysis_hash") or (canonical_hash(analysis) if analysis else ""),
                "source_id": str(asset_id),
                "owner_note": item.get("owner_note") or "",
                "metadata": {
                    "original_name": media_asset.original_name,
                    "content_type": media_asset.content_type,
                    "original_size": media_asset.original_size,
                    "analysis_version": media_asset.analysis_version,
                    "analysis_status": media_asset.analysis_status.value,
                    "analysis": copy.deepcopy(analysis),
                },
            }))

        sources = self.memory.list_research_sources(limit=500)
        findings = [item.to_dict() for item in self.memory.list_research_findings(limit=1_000)]
        requests = [dict(item) for item in self.memory.list_research_requests(limit=500)]
        insights = [dict(item) for item in self.memory.list_incubation_insights(limit=500)]
        deductions = [dict(item) for item in self.memory.list_incubation_deductions(limit=500)]
        approved_knowledge = [
            dict(item)
            for item in self.memory.list_business_knowledge(status="approved", limit=500)
        ]
        design = {
            "run": copy.deepcopy(dict(run)),
            "run_hash": run_hash,
            "candidate_sha": candidate_sha,
            "candidate_ref": str(run.get("candidate_ref") or ""),
            "base_sha": str(run.get("base_sha") or ""),
            "operation_kind": str(run.get("operation_kind") or ""),
            "design_manifest": copy.deepcopy(run.get("design_manifest_json") or {}),
            "planning": copy.deepcopy(run.get("planning_json") or {}),
            "quality_report": copy.deepcopy(run.get("quality_report_json") or {}),
            "context_snapshot": copy.deepcopy(run.get("context_snapshot") or {}),
        }
        research = {
            "sources": sources,
            "findings": findings,
            "requests": requests,
            "insights": insights,
            "deductions": deductions,
            "genesis_identity": copy.deepcopy(genesis.research_identity),
        }
        open_questions = [{"value": item} for item in intake.unknowns]
        open_questions.extend(
            {"value": item}
            for item in (genesis.creative_identity.get("open_questions") or [])
            if item not in intake.unknowns
        )
        source_states = []
        included_sources = []
        excluded_source_ids = []
        for source in sources:
            source_hash = str(source.get("source_hash") or "").strip().lower() or canonical_hash(source)
            state = {
                "source_id": str(source.get("source_id") or ""),
                "source_hash": source_hash,
                "trust_state": str(source.get("trust_state") or ""),
                "ongoing_subscription": str(source.get("ongoing_subscription") or ""),
                "language": str(source.get("language") or ""),
                "excluded": bool(source.get("excluded")),
            }
            source_states.append(state)
            if state["excluded"] or state["trust_state"] == "excluded":
                excluded_source_ids.append(state["source_id"])
            else:
                included_sources.append(state)
        contradictions = [
            {"finding_id": item.get("finding_id"), "contradicts": item.get("contradicts") or []}
            for item in findings
            if item.get("contradicts")
        ]
        research_manifest = ResearchEvidenceManifest.from_dict({
            "schema_version": 1,
            "included_sources": included_sources,
            "source_states": source_states,
            "findings": [
                {"finding_id": item.get("finding_id"), "finding_hash": item.get("finding_hash") or canonical_hash(item)}
                for item in findings
            ],
            "insights": [
                {"insight_id": item.get("insight_id"), "insight_hash": item.get("insight_hash") or canonical_hash(item)}
                for item in insights
            ],
            "deductions": [
                {"deduction_id": item.get("deduction_id"), "deduction_hash": item.get("deduction_hash") or canonical_hash(item)}
                for item in deductions
            ],
            "excluded_source_ids": excluded_source_ids,
            "contradictions": contradictions,
            "unresolved_claims": open_questions,
            "source_languages": sorted({state["language"] for state in source_states if state["language"]}),
            "target_language": str(intake.site.get("language") or ""),
        })
        research_manifest_hash = research_manifest.computed_hash
        context = CustomerContextSnapshot.from_dict({
            "schema_version": 1,
            "context_id": context_id,
            "revision": 1,
            "created_at": utc_now(),
            "source_kind": "accepted_design_run",
            "source_incubation_id": str(incubation_id),
            "source_intake_session_id": session_id,
            "source_intake_revision": intake_revision,
            "source_intake_revision_id": intake_revision_id,
            "source_intake_hash": intake_hash,
            "source_genesis_revision": int(genesis.revision),
            "source_genesis_hash": genesis_hash,
            "source_design_run_id": run_id,
            "source_design_run_hash": run_hash,
            "business": intake.business,
            "audience": intake.audience,
            "conversion": intake.conversion,
            "brand": intake.brand,
            "site": intake.site,
            "relationship": genesis.relationship,
            "constraints": intake.constraints,
            "research": research,
            "research_manifest": research_manifest.to_dict(),
            "creative_identity": genesis.creative_identity,
            "design": design,
            "assets": [item.to_dict() for item in assets],
            "knowledge": approved_knowledge,
            "open_questions": open_questions,
            "contradictions": contradictions,
            "provenance": {
                "intake": copy.deepcopy(intake.provenance),
                "genesis_evidence": [item.to_dict() for item in genesis.evidence],
                "run_hash": run_hash,
                "accepted_at": utc_now(),
            },
        })
        self.memory.save_customer_context(context, accepted=True)
        manifest_id = "accept_" + canonical_hash({
            "incubation_id": str(incubation_id),
            "run_id": run_id,
            "candidate_sha": candidate_sha,
            "context_hash": context.computed_hash,
        })[:32]
        manifest = AcceptanceManifest.from_dict({
            "schema_version": 1,
            "manifest_id": manifest_id,
            "incubation_id": str(incubation_id),
            "accepted_candidate_sha": candidate_sha,
            "accepted_run_id": run_id,
            "accepted_run_hash": run_hash,
            "intake_session_id": session_id,
            "intake_revision": intake_revision,
            "intake_revision_id": intake_revision_id,
            "intake_hash": intake_hash,
            "genesis_revision": int(genesis.revision),
            "genesis_hash": genesis_hash,
            "context_id": context.context_id,
            "context_revision": context.revision,
            "context_hash": context.computed_hash,
            "website_source": {
                "candidate_sha": candidate_sha,
                "candidate_ref": str(run.get("candidate_ref") or ""),
                "base_sha": str(run.get("base_sha") or ""),
                **copy.deepcopy(dict(website_source or {})),
            },
            "created_at": utc_now(),
            "accepted_by": "owner",
            "base_sha": str(run.get("base_sha") or ""),
            "research_manifest_hash": research_manifest_hash,
            "required_assets": [item.to_dict() for item in assets if item.required],
            "approved_knowledge": [
                {"id": item.get("id"), "asset_id": item.get("asset_id"), "content_hash": canonical_hash(item)}
                for item in approved_knowledge
            ],
            "design_manifest_hash": str(run.get("design_manifest_hash") or ""),
            "quality_report_hash": str(run.get("quality_report_hash") or ""),
            "planning_hash": str(run.get("planning_hash") or ""),
            "design_skill_set_hash": str(((run.get("context_snapshot") or {}).get("design_skill_set") or {}).get("content_hash") or ""),
            "website_build_profile": {"operation_kind": str(run.get("operation_kind") or "")},
            "repository_identity": {"candidate_ref": str(run.get("candidate_ref") or "")},
        })
        self.memory.save_acceptance_manifest(manifest)
        return context, manifest

    def current(self) -> CustomerContextSnapshot | None:
        rows = self.memory.list_customer_contexts(limit=1, accepted_only=True)
        if not rows:
            return None
        item = rows[0]
        return item.get("context") if isinstance(item, Mapping) else None

    def accepted(self) -> CustomerContextSnapshot | None:
        return self.current()

    def get(self, context_id: str, revision: int | None = None) -> CustomerContextSnapshot | None:
        record = self.memory.get_customer_context(context_id, revision)
        return record.get("context") if record else None

    def task_view(self, task: str = "full", *, limits: "ContextLimits | None" = None) -> dict[str, Any]:
        """Return a task-shaped view without making a new source of truth."""
        context = self.current()
        if context is None:
            return {}
        full = context.to_dict()
        purpose = str(task or "full").strip().lower()
        limits = limits or ContextLimits()
        if purpose == "identity":
            keys = ("business", "audience", "conversion", "brand", "site", "relationship", "constraints")
        elif purpose == "design":
            keys = ("business", "audience", "conversion", "brand", "site", "constraints", "assets", "creative_identity", "design", "research", "research_manifest")
        elif purpose == "editorial":
            keys = ("business", "audience", "brand", "conversion", "constraints", "knowledge", "research", "research_manifest")
        elif purpose == "research":
            keys = ("business", "audience", "research", "research_manifest", "knowledge", "contradictions", "open_questions")
        elif purpose == "strategy":
            keys = ("business", "audience", "conversion", "site", "constraints", "research", "knowledge")
        elif purpose in {"relationship", "owner_relationship"}:
            keys = ("relationship", "open_questions", "provenance")
        else:
            keys = tuple(full)
        result = {key: copy.deepcopy(full[key]) for key in keys}
        for key in ("assets", "knowledge", "open_questions", "contradictions"):
            if isinstance(result.get(key), list):
                result[key] = result[key][:limits.max_items]
        result["context"] = {
            "context_id": context.context_id,
            "revision": context.revision,
            "content_hash": context.computed_hash,
            "source_record_hashes": {
                "intake": context.source_intake_hash,
                "genesis": context.source_genesis_hash,
                "design_run": context.source_design_run_hash,
            },
            "truncation": {"max_items": limits.max_items},
        }
        return result

    def view(self, purpose: str = "full") -> dict[str, Any]:
        return self.task_view(purpose)


@dataclass(frozen=True)
class ContextLimits:
    max_items: int = 100


def design_run_content_hash(run: Mapping[str, Any]) -> str:
    """Hash immutable design evidence, excluding the later context binding."""
    payload = {
        key: copy.deepcopy(value)
        for key, value in dict(run).items()
        if key not in {
            "customer_context_id", "customer_context_hash", "customer_context_revision",
            "updated_ts", "events",
        }
    }
    return canonical_hash(payload)
