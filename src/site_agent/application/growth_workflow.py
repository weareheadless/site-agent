"""One durable growth coordinator: collection, Ada assessment and real candidates."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..config import crawlseo_research_authority_selected
from ..core.contracts import Artifact, ArtifactKind, ContractError, utc_now
from ..core.growth_contracts import GrowthGoalRevision, GrowthPolicy
from ..core.memory import Memory
from ..core.research_authority import producer_frozen, require_connector_dispatch_enabled
from .actions import owner_action_summary

_OWNER_REVIEW_ASSESSMENT_CONTRACT = "owner-summary-v3"


def ensure_default_goal(memory: Memory) -> dict[str, Any]:
    """Create the new-site goal once, at a provisioning/scheduler boundary."""

    existing = memory.latest_growth_goal()
    if existing is not None:
        return existing
    return memory.create_growth_goal(GrowthGoalRevision.default().to_dict())


def _run_key(policy: GrowthPolicy, goal_revision: int, now: datetime.datetime) -> str:
    local_date = now.astimezone(ZoneInfo(policy.timezone)).date().isoformat()
    return f"growth-reconcile:{policy.origin_revision}:goal-{int(goal_revision)}:{local_date}"


def _invalidate_incompatible_candidates(memory: Memory, goal: Mapping[str, Any], policy: GrowthPolicy) -> None:
    """Expire work bound to a previous goal or site origin before new work starts."""

    for initiative in memory.list_strategy_initiatives(limit=500):
        state = str(initiative.get("state") or "")
        if state in {"reviewed", "rejected", "snoozed", "superseded", "deferred"}:
            continue
        bound_goal = initiative.get("goal_revision")
        bound_origin = str(initiative.get("origin_revision") or "").strip()
        if bound_goal is None and not bound_origin:
            continue
        if (bound_goal is not None and int(bound_goal) != int(goal["revision"])) or (
            bound_origin and bound_origin != policy.origin_revision
        ):
            memory.transition_strategy_initiative(
                int(initiative["id"]),
                "superseded",
                last_error="This candidate was bound to a previous goal or site origin and must be prepared again.",
            )


def _freshness_hours(config: Mapping[str, Any], source_id: str) -> int:
    growth = config.get("growth") if isinstance(config.get("growth"), Mapping) else {}
    freshness = growth.get("freshness_hours", 168)
    if isinstance(freshness, Mapping):
        freshness = freshness.get(source_id, 168)
    try:
        value = int(freshness)
    except (TypeError, ValueError) as exc:
        raise ValueError("growth.freshness_hours must be an integer or source map") from exc
    if not 1 <= value <= 8760:
        raise ValueError("growth.freshness_hours must be between 1 and 8760")
    return value


def _parsed_timestamp(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.replace(tzinfo=datetime.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(datetime.timezone.utc)


def _defer_duplicate_owner_information(memory: Any, initiative: Mapping[str, Any] | None, related_id: int) -> None:
    """Close a duplicate in-preparation owner question with an explicit dependency."""
    if initiative is None:
        return
    current = memory.update_strategy_initiative(int(initiative["id"]))
    if current.get("state") not in {"preparing", "blocked"}:
        return
    previous_validation = current.get("validation") if isinstance(current.get("validation"), Mapping) else {}
    reason = "Ada already has an unanswered business question. This finding is deferred until the owner replies, so it is not left as a duplicate task in preparation."
    memory.transition_strategy_initiative(
        int(current["id"]), "deferred",
        expected_state=str(current["state"]),
        validation={
            **dict(previous_validation),
            "status": "deferred",
            "reason": reason,
            "relatedInitiativeId": int(related_id),
            "reassessWhen": "After the owner answers Ada’s current business question.",
        },
    )


def _ready_source_refs(sources: list[Mapping[str, Any]]) -> set[str]:
    """Return exact IDs and refs belonging to ready source records only."""
    return {
        str(ref)
        for source in sources
        if source.get("state") == "ready"
        for ref in (source.get("id"), source.get("sourceRef"))
        if ref
    }


def _recoverable_saved_assessment_failure(memory: Memory, run: Mapping[str, Any]) -> bool:
    """Resume only exact saved-assessment failures whose shared boundary is fixed.

    Replaying these preparing-phase runs uses their persisted evidence and
    assessment. It must not recollect sources, dispatch paid research, or
    repeat the model assessment. Partially written initiatives are eligible
    only when they have no owner decision, draft, artifact, or approval yet.
    """
    if (
        run.get("status") != "failed"
        or run.get("phase") != "preparing"
        or run.get("trigger") not in {"initial", "weekly", "owner_review"}
    ):
        return False
    detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
    assessment = detail.get("assessment")
    material = detail.get("material")
    failure = str(detail.get("error") or "")
    recoverable_failures = {
        "Ada referenced evidence that is not in this run",
        "summary exceeds 500 characters",
        "invalid strategy initiative transition deferred -> blocked",
    }
    if (
        failure not in recoverable_failures
        or not isinstance(assessment, Mapping)
        or not isinstance(assessment.get("opportunities"), list)
        or not isinstance(material, Mapping)
        or not isinstance(material.get("inventory"), list)
        or detail.get("candidateIds")
        or detail.get("queuedInitiativeIds")
    ):
        return False
    initiatives = [
        row for row in memory.list_strategy_initiatives(limit=None)
        if str(row.get("growth_run_id") or "") == str(run.get("run_id") or "")
    ]
    if failure == "Ada referenced evidence that is not in this run":
        return not initiatives
    if not initiatives:
        return False
    if failure == "invalid strategy initiative transition deferred -> blocked" and not any(
        row.get("state") == "deferred" for row in initiatives
    ):
        return False
    side_effect_fields = (
        "owner_action_id", "artifact_id", "approval_id", "draft_id", "receipt_id",
        "candidate_hash", "review_package_hash", "published_revision",
    )
    for row in initiatives:
        if any(row.get(key) is not None for key in side_effect_fields):
            return False
        if row.get("state") not in {"preparing", "blocked"}:
            if failure != "invalid strategy initiative transition deferred -> blocked" or row.get("state") != "deferred":
                return False
        validation = row.get("validation") if isinstance(row.get("validation"), Mapping) else {}
        if any(validation.get(key) for key in ("candidateHash", "reviewPackageHash")):
            return False
    return True


def _reconcile_orphan_owner_questions(memory: Memory) -> None:
    """Retain effect-free duplicates left behind by a completed assessment.

    Never reclaim in-flight work or a linked action/candidate. The existing
    owner question remains the only decision, with its normal answer-resumption
    path; the duplicate records its dependency instead of consuming capacity.
    """
    initiatives = memory.list_strategy_initiatives(limit=None)
    pending = [
        row for row in initiatives
        if row.get("kind") == "owner_information"
        and row.get("state") == "waiting_for_owner"
        and row.get("owner_action_id") is not None
        and (action := memory.get_owner_action(int(row["owner_action_id"]))) is not None
        and action.source_ref == f"growth-initiative:{row['id']}"
        and action.state.value not in {"completed", "dismissed", "stale"}
    ]
    for row in initiatives:
        if row.get("kind") != "owner_information" or row.get("state") != "preparing":
            continue
        if any(row.get(key) is not None for key in (
            "owner_action_id", "artifact_id", "approval_id", "draft_id", "receipt_id",
            "candidate_hash", "review_package_hash", "published_revision",
        )):
            continue
        validation = row.get("validation") if isinstance(row.get("validation"), Mapping) else {}
        if any(validation.get(key) for key in (
            "ownerResponse", "preparation", "candidateHash", "reviewPackageHash",
        )):
            continue
        run = memory.get_growth_run(str(row.get("growth_run_id") or ""))
        if run is None or run.get("status") != "complete":
            continue
        related = next((question for question in pending
            if question.get("goal_revision") == row.get("goal_revision")
            and question.get("origin_revision") == row.get("origin_revision")), None)
        if related is not None:
            _defer_duplicate_owner_information(memory, row, int(related["id"]))


def _record_preparation_failure(
    memory: Memory,
    initiative_id: int,
    opportunity: Mapping[str, Any],
    reason: str,
    *,
    candidate_ids: list[int],
    blocks: list[dict[str, Any]],
    unprepared_opportunities: list[dict[str, Any]],
) -> None:
    """Record a preparation failure without overwriting a concurrent decision.

    Initiative state may advance while a provider or Payload request is in
    flight. Read the durable state and use its expected value for the update;
    if another executor wins the race, classify that newer state rather than
    trying to force it back to ``blocked``.
    """
    for _attempt in range(2):
        current = memory.update_strategy_initiative(int(initiative_id))
        if current is None:
            raise ContractError("strategy initiative disappeared during preparation")
        state = str(current.get("state") or "")
        if state == "deferred":
            validation = current.get("validation") if isinstance(current.get("validation"), Mapping) else {}
            retained = {
                **dict(opportunity),
                "disposition": "deferred",
                "errorCode": str(validation.get("errorCode") or "preparation_deferred"),
                "preparationNote": str(
                    validation.get("reason")
                    or current.get("last_error")
                    or "This finding was deferred while its preparation state changed. It remains saved for reassessment."
                ),
            }
            if validation.get("reassessWhen"):
                retained["reassessWhen"] = str(validation["reassessWhen"])
            unprepared_opportunities.append(retained)
            return
        if state == "ready_for_review":
            candidate_ids.append(int(current["id"]))
            return
        if state not in {"preparing", "validating", "blocked", "uncertain"}:
            # A concurrent owner action, publication, or terminal decision is
            # authoritative. It must not be converted into a technical block.
            return
        try:
            memory.transition_strategy_initiative(
                int(initiative_id),
                "blocked",
                expected_state=state,
                last_error=reason,
            )
        except ContractError:
            latest = memory.update_strategy_initiative(int(initiative_id))
            if latest is None:
                raise
            if str(latest.get("state") or "") == state:
                raise
            continue
        blocks.append({"initiativeId": int(initiative_id), "reason": reason})
        return
    # A second concurrent state change is unusual but must not be silently
    # represented as a completed block. Let the run-level failure boundary
    # persist the exact diagnostic for a later safe replay.
    raise ContractError("strategy initiative changed repeatedly while recording its preparation failure")


_PAYLOAD_GROWTH_CONTRACT_ROUTE_404 = 'Payload gateway returned 404: Route not found "/api/workspace/growth/contract"'
_GROWTH_SCHEMA_MISMATCH = "Ada's changes do not match the canonical editable schema"


def _recoverable_payload_contract_failure(memory: Memory, run: Mapping[str, Any]) -> bool:
    """Match only a saved content candidate blocked by the now-required contract route."""
    if (
        run.get("status") != "blocked"
        or run.get("phase") != "preparing"
        or run.get("trigger") not in {"initial", "weekly", "owner_review"}
    ):
        return False
    detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
    assessment = detail.get("assessment")
    material = detail.get("material")
    blocks = detail.get("blocks")
    if (
        not isinstance(assessment, Mapping)
        or not isinstance(assessment.get("opportunities"), list)
        or not isinstance(material, Mapping)
        or not isinstance(material.get("inventory"), list)
        or detail.get("candidateIds")
        or not isinstance(blocks, list)
    ):
        return False
    blocked_ids = {
        str(block.get("initiativeId"))
        for block in blocks
        if isinstance(block, Mapping)
        and str(block.get("reason") or "") == _PAYLOAD_GROWTH_CONTRACT_ROUTE_404
        and block.get("initiativeId") is not None
    }
    if not blocked_ids:
        return False
    opportunities = assessment["opportunities"]
    for row in memory.list_strategy_initiatives(limit=None):
        if (
            str(row.get("id")) not in blocked_ids
            or str(row.get("growth_run_id") or "") != str(run.get("run_id") or "")
            or row.get("kind") != "payload_content"
            or row.get("state") != "blocked"
            or any(row.get(key) for key in (
                "owner_action_id", "artifact_id", "approval_id", "draft_id",
                "receipt_id", "review_package_hash",
            ))
        ):
            continue
        expected = row.get("expected") if isinstance(row.get("expected"), Mapping) else {}
        opportunity = expected.get("opportunity") if isinstance(expected.get("opportunity"), Mapping) else {}
        if any(
            item.get("kind") == "payload_content"
            and item.get("title") == row.get("title")
            and item.get("title") == opportunity.get("title")
            for item in opportunities
            if isinstance(item, Mapping)
        ):
            return True
    return False


_EMPTY_GROWTH_JSON_COMPLETION = "model returned an empty completion (finish_reason=length, message_fields=content,reasoning,reasoning_details,refusal,role)"


def _recoverable_growth_json_failure(memory: Memory, run: Mapping[str, Any]) -> bool:
    """Allow one exact, side-effect-free retry after structured output was truncated."""
    if (
        run.get("status") != "blocked"
        or run.get("phase") != "preparing"
        or run.get("trigger") not in {"initial", "weekly", "owner_review"}
    ):
        return False
    detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
    events = detail.get("recoveryEvents")
    if not isinstance(events, list):
        return False
    codes = {
        str(event.get("code"))
        for event in events
        if isinstance(event, Mapping)
    }
    if (
        "payload_growth_contract_route_restored" not in codes
        or "growth_json_no_reasoning_retry" in codes
        or not isinstance(detail.get("assessment"), Mapping)
        or not isinstance(detail.get("assessment", {}).get("opportunities"), list)
        or not isinstance(detail.get("material"), Mapping)
        or not isinstance(detail.get("material", {}).get("inventory"), list)
        or detail.get("candidateIds")
    ):
        return False
    blocks = detail.get("blocks")
    if not isinstance(blocks, list):
        return False
    blocked_ids = {
        str(block.get("initiativeId"))
        for block in blocks
        if isinstance(block, Mapping)
        and str(block.get("reason") or "") == _EMPTY_GROWTH_JSON_COMPLETION
        and block.get("initiativeId") is not None
    }
    if not blocked_ids:
        return False
    opportunities = detail["assessment"]["opportunities"]
    for row in memory.list_strategy_initiatives(limit=None):
        if (
            str(row.get("id")) not in blocked_ids
            or str(row.get("growth_run_id") or "") != str(run.get("run_id") or "")
            or row.get("kind") != "payload_content"
            or row.get("state") != "blocked"
            or any(row.get(key) is not None for key in (
                "owner_action_id", "artifact_id", "approval_id", "draft_id",
                "receipt_id", "review_package_hash",
            ))
        ):
            continue
        expected = row.get("expected") if isinstance(row.get("expected"), Mapping) else {}
        opportunity = expected.get("opportunity") if isinstance(expected.get("opportunity"), Mapping) else {}
        if any(
            isinstance(item, Mapping)
            and item.get("kind") == "payload_content"
            and item.get("title") == row.get("title") == opportunity.get("title")
            for item in opportunities
        ):
            return True
    return False


def _recoverable_growth_schema_failure(memory: Memory, run: Mapping[str, Any]) -> bool:
    """Replay one historical schema-only failure when saved inputs have no effects."""
    if (
        run.get("status") != "blocked"
        or run.get("phase") != "preparing"
        or run.get("trigger") not in {"initial", "weekly", "owner_review"}
    ):
        return False
    detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
    events = detail.get("recoveryEvents")
    used = {
        str(event.get("code"))
        for event in events or []
        if isinstance(event, Mapping)
    }
    assessment, material, blocks = detail.get("assessment"), detail.get("material"), detail.get("blocks")
    if (
        "growth_schema_candidate_retry" in used
        or not isinstance(assessment, Mapping)
        or not isinstance(assessment.get("opportunities"), list)
        or not isinstance(material, Mapping)
        or not isinstance(material.get("inventory"), list)
        or detail.get("candidateIds")
        or not isinstance(blocks, list)
    ):
        return False
    blocked_ids = {
        str(block.get("initiativeId"))
        for block in blocks
        if isinstance(block, Mapping)
        and str(block.get("reason") or "") == _GROWTH_SCHEMA_MISMATCH
        and block.get("initiativeId") is not None
    }
    if not blocked_ids:
        return False
    for row in memory.list_strategy_initiatives(limit=None):
        if (
            str(row.get("id")) not in blocked_ids
            or str(row.get("growth_run_id") or "") != str(run.get("run_id") or "")
            or row.get("kind") != "payload_content"
            or row.get("state") != "blocked"
            or any(row.get(key) for key in (
                "owner_action_id", "artifact_id", "approval_id", "draft_id", "receipt_id",
                "review_package_hash", "candidate_hash",
            ))
            or (row.get("validation") or {}).get("preparation")
        ):
            continue
        expected = row.get("expected") if isinstance(row.get("expected"), Mapping) else {}
        opportunity = expected.get("opportunity") if isinstance(expected.get("opportunity"), Mapping) else {}
        if any(
            isinstance(item, Mapping)
            and item.get("kind") == "payload_content"
            and item.get("title") == row.get("title") == opportunity.get("title")
            for item in assessment["opportunities"]
        ):
            return True
    return False


_GROWTH_RESTART_RECOVERY = "growth_worker_restart_recovery"


def _safe_interrupted_growth_preparation(memory: Memory, run: Mapping[str, Any]) -> bool:
    """Check whether an interrupted preparation can resume without duplicating effects."""
    if (
        run.get("status") != "running"
        or run.get("phase") != "preparing"
        or run.get("trigger") not in {"initial", "weekly", "owner_review"}
    ):
        return False
    detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
    if (
        not isinstance(detail.get("material"), Mapping)
        or not isinstance(detail.get("material", {}).get("inventory"), list)
        or not isinstance(detail.get("assessment"), Mapping)
        or not isinstance(detail.get("assessment", {}).get("opportunities"), list)
        or detail.get("candidateIds") != []
    ):
        return False

    initiatives = [
        row for row in memory.list_strategy_initiatives(limit=None)
        if str(row.get("growth_run_id") or "") == str(run.get("run_id") or "")
    ]
    if not initiatives:
        return False
    for row in initiatives:
        # A pending owner question is durable and deduplicated by initiative;
        # replaying this preparation will preserve it without creating another.
        if (
            row.get("kind") == "owner_information"
            and row.get("state") == "waiting_for_owner"
            and row.get("owner_action_id") is not None
            and not any(row.get(key) is not None for key in (
                "artifact_id", "approval_id", "draft_id", "receipt_id", "review_package_hash",
            ))
        ):
            continue
        if (
            row.get("state") not in {"preparing", "blocked"}
            or row.get("validation")
            or any(row.get(key) is not None for key in (
                "owner_action_id", "artifact_id", "approval_id", "draft_id",
                "receipt_id", "review_package_hash", "candidate_hash",
            ))
        ):
            return False
    return True


def _growth_restart_recovery_used(run: Mapping[str, Any]) -> bool:
    detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
    events = detail.get("recoveryEvents")
    return isinstance(events, list) and any(
        isinstance(event, Mapping) and event.get("code") == _GROWTH_RESTART_RECOVERY
        for event in events
    )


def _block_interrupted_growth_run(memory: Memory, run: Mapping[str, Any], *, reason: str) -> None:
    """Persist a visible stop for a run that cannot be replayed safely."""
    run_id = str(run.get("run_id") or "")
    previous_owner = str(run.get("lease_owner") or "")
    if not run_id:
        return
    owner = f"growth-recovery:{uuid.uuid4().hex}"
    claimed = memory.claim_growth_run(
        run_id,
        lease_owner=owner,
        lease_seconds=300,
        reclaim_lease_owner=previous_owner or None,
    )
    if claimed is None:
        return
    detail = dict(claimed.get("detail") or {})
    detail["error"] = reason
    events = detail.get("recoveryEvents")
    events = list(events) if isinstance(events, list) else []
    events.append({
        "code": "growth_interrupted_run_stopped",
        "resumedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
    })
    detail["recoveryEvents"] = events[-5:]
    memory.update_growth_run(
        run_id,
        phase=str(claimed.get("phase") or "preparing"),
        status="blocked",
        detail=detail,
        lease_owner=None,
        lease_until=None,
        next_due_ts=None,
        expected_lease=owner,
    )


def has_recoverable_growth_replay(memory: Memory) -> bool:
    """Whether activation should immediately resume a known safe saved run."""
    from .growth_candidates import has_recoverable_payload_revision

    if has_recoverable_payload_revision(memory):
        return True
    return any(
        _recoverable_saved_assessment_failure(memory, run)
        or _recoverable_payload_contract_failure(memory, run)
        or _recoverable_growth_json_failure(memory, run)
        or _recoverable_growth_schema_failure(memory, run)
        for run in memory.list_growth_runs(limit=None)
    )


def _snapshot_source(
    *,
    source_id: str,
    provider: str,
    capability: str,
    configured: bool,
    identity: str | None,
    snapshot: Mapping[str, Any] | None,
    now: datetime.datetime,
    max_age_hours: int,
    blocked_state: str | None = None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    observed_at = (snapshot or {}).get("ts")
    parsed = _parsed_timestamp(observed_at)
    if blocked_state:
        state = blocked_state
        reason = blocked_reason or "The source is not ready for this workflow."
    elif not configured:
        state = "missing"
        reason = "The source property is not configured."
    elif snapshot is None:
        state = "missing"
        reason = "The property is configured, but no persisted observation exists yet."
    elif parsed is None:
        state = "uncertain"
        reason = "The persisted observation has no trustworthy capture time."
    elif now - parsed > datetime.timedelta(hours=max_age_hours):
        state = "stale"
        reason = f"The latest observation is older than {max_age_hours} hours."
    else:
        state = "ready"
        reason = "A recent persisted observation is available."
    return {
        "id": source_id,
        "provider": provider,
        "capability": capability,
        "configured": configured,
        "identity": identity,
        "state": state,
        "reason": reason,
        "observedAt": observed_at,
        "freshnessHours": max_age_hours,
        "sourceRef": f"metrics_snapshot:{snapshot.get('id')}" if snapshot and snapshot.get("id") else None,
        "data": "available" if snapshot is not None else "missing",
    }


def _source_state(memory: Memory, config: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Summarise persisted source state without initiating collection.

    ``state`` is deliberately separate from the legacy display ``status``:
    configured is not connected, and zero is never used for missing evidence.
    """

    state = context.get("seo_provisioning_state") if isinstance(context.get("seo_provisioning_state"), Mapping) else None
    state = dict(state or memory.kv_get("seo_provisioning_state", {}) or {})
    ga4 = memory.latest_snapshot("ga4")
    gsc = memory.latest_snapshot("gsc")
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    ga = config.get("ga") if isinstance(config.get("ga"), Mapping) else {}
    ga_property = str(state.get("ga4_property_id") or ga.get("property_id") or "").strip() or None
    gsc_property = str(state.get("gsc_property") or seo.get("site_url") or "").strip() or None
    now = datetime.datetime.now(datetime.timezone.utc)
    ga4_source = _snapshot_source(
        source_id="ga4",
        provider="google_analytics",
        capability="analytics.read",
        configured=bool(ga_property),
        identity=ga_property,
        snapshot=ga4,
        now=now,
        max_age_hours=_freshness_hours(config, "ga4"),
    )
    ga4_source.update({
        "property": ga_property,
        "status": "has_data" if ga4_source["state"] in {"ready", "stale", "uncertain"} else "not_configured" if not ga_property else "collecting",
        "updatedAt": ga4_source["observedAt"],
    })
    gsc_source = _snapshot_source(
        source_id="gsc",
        provider="google_search_console",
        capability="search_console.read",
        configured=bool(gsc_property),
        identity=gsc_property,
        snapshot=gsc,
        now=now,
        max_age_hours=_freshness_hours(config, "gsc"),
        blocked_state="unauthorised" if state.get("gsc_pending") else None,
        blocked_reason="Google Search Console verification is still required for this origin." if state.get("gsc_pending") else None,
    )
    gsc_source.update({
        "property": gsc_property,
        "verification": "required" if state.get("gsc_pending") else "verified" if state.get("gsc_verified") else "unknown",
        "status": "verification_required" if state.get("gsc_pending") else "has_data" if gsc_source["state"] in {"ready", "stale", "uncertain"} else "not_configured" if not gsc_property else "collecting",
        "updatedAt": gsc_source["observedAt"],
    })
    seeds = memory.list_seo_seeds(limit=1000)
    researched = [seed for seed in seeds if seed.get("last_researched_ts") or int(seed.get("research_count") or 0) > 0]
    last_researched = max((str(seed.get("last_researched_ts") or "") for seed in researched), default="") or None
    research_snapshot = {"ts": last_researched, "id": None} if last_researched else None
    dataforseo_configured = context.get("crawlseo_service") is not None
    if not dataforseo_configured:
        dataforseo_state, dataforseo_reason = "missing", "The CrawlSEO/DataForSEO service is not configured for this tenant."
    elif not seeds:
        dataforseo_state, dataforseo_reason = "missing", "No approved keyword seeds are recorded yet."
    elif not researched:
        dataforseo_state, dataforseo_reason = "pending", "Keyword seeds exist; the first bounded research result is not persisted yet."
    else:
        dataforseo_state, dataforseo_reason = _snapshot_source(
            source_id="dataforseo",
            provider="crawlseo",
            capability="seo.research.read",
            configured=True,
            identity=None,
            snapshot=research_snapshot,
            now=now,
            max_age_hours=_freshness_hours(config, "dataforseo"),
        )["state"], "A persisted bounded research result is available."
    dataforseo_source = {
        "id": "dataforseo",
        "provider": "crawlseo",
        "capability": "seo.research.read",
        "configured": dataforseo_configured,
        "identity": None,
        "state": dataforseo_state,
        "reason": dataforseo_reason,
        "observedAt": last_researched,
        "freshnessHours": _freshness_hours(config, "dataforseo"),
        "sourceRef": f"seo_seed_registry:{len(researched)}" if researched else None,
        "data": "available" if researched else "missing",
        "status": "configured" if dataforseo_configured else "not_configured",
        "updatedAt": last_researched or state.get("provisioned_at"),
        "seedCount": len(seeds),
        "researchedSeedCount": len(researched),
    }
    return [ga4_source, gsc_source, dataforseo_source]


def _evidence_manifest(
    *,
    run: Mapping[str, Any],
    goal: Mapping[str, Any],
    policy: GrowthPolicy,
    sources: list[dict[str, Any]],
    captured_at: str,
    material: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    manifest = {
        "schemaVersion": 1,
        "runId": run["run_id"],
        "runKey": run["run_key"],
        "capturedAt": captured_at,
        "timezone": policy.timezone,
        "goalRevision": int(goal["revision"]),
        "goalKey": goal["goal_key"],
        "sources": sources,
        "limits": [
            "This manifest records persisted observations only; it does not claim a complete console export.",
            "Missing, stale, unauthorised and pending sources remain distinct from observed zero values.",
        ],
    }
    if material is not None:
        canonical_material = json.dumps(dict(material), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        manifest["materialHash"] = hashlib.sha256(canonical_material.encode("utf-8")).hexdigest()
        manifest["materialRef"] = f"growth-run:{run['run_id']}:material"
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return manifest, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _persist_evidence_artifact(
    memory: Memory,
    *,
    run: Mapping[str, Any],
    goal: Mapping[str, Any],
    policy: GrowthPolicy,
    sources: list[dict[str, Any]],
    material: Mapping[str, Any] | None = None,
) -> tuple[int, str, dict[str, Any]]:
    captured_at = utc_now()
    manifest, content_hash = _evidence_manifest(
        run=run,
        goal=goal,
        policy=policy,
        sources=sources,
        captured_at=captured_at,
        material=material,
    )
    for existing in memory.list_artifacts(kind=ArtifactKind.GROWTH_EVIDENCE.value, limit=100):
        existing_manifest = existing.preview_data.get("manifest") if isinstance(existing.preview_data, Mapping) else None
        if isinstance(existing_manifest, Mapping) and existing_manifest.get("runId") == run["run_id"]:
            if existing.artifact_id is None:
                raise ValueError("growth evidence artifact has no id")
            expected_manifest = {**manifest, "capturedAt": existing_manifest.get("capturedAt")}
            if dict(existing_manifest) != expected_manifest:
                raise ValueError("growth evidence artifact for this run is bound to different evidence")
            return existing.artifact_id, existing.content_hash, existing_manifest
    artifact = memory.create_artifact(
        Artifact(
            kind=ArtifactKind.GROWTH_EVIDENCE,
            title=f"Ada growth evidence · {captured_at[:10]}",
            summary="Persisted source states and freshness used by Ada's growth workflow.",
            renderer="growth_evidence",
            capability_id="growth.evidence.read",
            provider_id="site-agent",
            content_hash=content_hash,
            preview_data={"manifest": manifest},
        )
    )
    if artifact.artifact_id is None:
        raise ValueError("growth evidence artifact was not assigned an id")
    return artifact.artifact_id, content_hash, manifest


def run_growth_reconciler(context: dict[str, Any]) -> dict[str, Any]:
    """Reconcile the durable owner-facing state for one tenant-local day.

    This stage intentionally does not perform paid research, call providers, or
    publish anything. It records exactly what is already known and leaves real
    collection/preparation to later phases of the shared pipeline.
    """

    memory: Memory = context["memory"]
    if producer_frozen(memory):
        raise RuntimeError("Local research and recommendation producers are frozen for CrawlSEO migration")
    config = context.get("config") if isinstance(context.get("config"), Mapping) else {}
    policy = GrowthPolicy.from_config(config)
    goal = ensure_default_goal(memory)
    now = datetime.datetime.now(datetime.timezone.utc)
    from .growth_owner_response import queue_saved_owner_responses
    queue_saved_owner_responses(context)
    _invalidate_incompatible_candidates(memory, goal, policy)
    key = _run_key(policy, int(goal["revision"]), now)
    existing = memory.get_growth_run_by_key(key)
    if existing and existing.get("status") == "complete":
        detail = existing.get("detail") if isinstance(existing.get("detail"), Mapping) else {}
        if detail.get("evidenceArtifactId"):
            return existing
        # Backfill the immutable manifest for runs created before the evidence
        # contract existed. This is local persistence only and does not rerun
        # paid research or change the public site.
        sources = _source_state(memory, config, context)
        artifact_id, content_hash, _manifest = _persist_evidence_artifact(
            memory,
            run=existing,
            goal=goal,
            policy=policy,
            sources=sources,
        )
        return memory.update_growth_run(
            existing["run_id"],
            detail={**detail, "sources": sources, "evidenceArtifactId": artifact_id, "evidenceHash": content_hash},
        )
    run = existing or memory.create_growth_run(
        run_id=f"growth-{uuid.uuid4().hex}",
        run_key=key,
        trigger="scheduled_reconciliation",
        goal_revision=int(goal["revision"]),
        timezone=policy.timezone,
        phase="collecting",
        status="pending",
        detail={"steps": [{"id": "goal", "status": "complete"}]},
        policy=policy.to_dict(),
        origin_revision=policy.origin_revision,
        phase_version=1,
    )
    claimed = memory.claim_growth_run(
        run["run_id"],
        lease_owner=f"site-agent:{os.getpid()}",
    )
    if claimed is None:
        return memory.get_growth_run(run["run_id"]) or run
    run = claimed
    try:
        sources = _source_state(memory, config, context)
        evidence_artifact_id, evidence_hash, _manifest = _persist_evidence_artifact(
            memory,
            run=run,
            goal=goal,
            policy=policy,
            sources=sources,
        )
        detail = {
            "steps": [
                {"id": "goal", "status": "complete", "revision": int(goal["revision"])},
                {
                    "id": "persisted_evidence",
                    "status": "complete",
                    "sourceCount": len(sources),
                    "artifactId": evidence_artifact_id,
                    "contentHash": evidence_hash,
                },
            ],
            "sources": sources,
            "evidenceArtifactId": evidence_artifact_id,
            "evidenceHash": evidence_hash,
            "sourceRefs": [item.get("sourceRef") for item in sources if item.get("sourceRef")],
            "policy": policy.to_dict(),
            "originRevision": policy.origin_revision,
            "goalRevision": int(goal["revision"]),
            "note": "Reconciled saved evidence; paid research and publication remain separate, approval-bound operations.",
        }
        run = memory.update_growth_run(
            run["run_id"],
            source_refs=detail["sourceRefs"],
            policy=policy.to_dict(),
            origin_revision=policy.origin_revision,
        )
        return memory.update_growth_run(run["run_id"], phase="evidence_reconciled", status="complete", detail=detail, completed=True)
    except Exception as exc:  # noqa: BLE001 - persist the exact blocked boundary
        return memory.update_growth_run(
            run["run_id"],
            phase="collecting",
            status="failed",
            detail={"error": str(exc)[:500]},
            completed=True,
        )


def _cycle_key(policy: GrowthPolicy, goal_revision: int, trigger: str, now: datetime.datetime) -> str:
    local = now.astimezone(ZoneInfo(policy.timezone))
    if trigger == "initial":
        period = "first-live-review"
    elif trigger == "weekly":
        iso = local.date().isocalendar()
        period = f"{iso.year}-W{iso.week:02d}"
    elif trigger == "monthly":
        period = local.strftime("%Y-%m")
    elif trigger == "daily":
        period = local.date().isoformat()
    elif trigger == "owner_review":
        period = f"owner_review:{local.date().isoformat()}"
    else:
        period = trigger
    key = f"growth-v2:{policy.origin_revision}:goal-{goal_revision}:{trigger}:{period}"
    if trigger == "owner_review":
        key += f":assessment-{_OWNER_REVIEW_ASSESSMENT_CONTRACT}"
    return key


def queue_growth_check(context: Mapping[str, Any], *, trigger: str = "owner_review") -> dict[str, Any]:
    memory, config = context["memory"], context["config"]
    if trigger != "crawlseo_action" and producer_frozen(memory):
        raise RuntimeError("Local research and recommendation producers are frozen for CrawlSEO migration")
    if _crawlseo_authoritative(config):
        # The manual owner refresh must enter the same CrawlSEO sync path as
        # scheduled reconciliation. A local owner_review run is filtered out
        # after cutover and would otherwise remain stranded forever.
        trigger = "crawlseo_action"
    policy, goal = GrowthPolicy.from_config(config), ensure_default_goal(memory)
    now = datetime.datetime.now(datetime.timezone.utc)
    # Coalesce an explicit owner review for this day/goal/origin and the
    # assessment contract. A contract upgrade gets one new durable run while
    # leaving the previous run and its candidates untouched. GET never queues.
    key_trigger = trigger if trigger == "owner_review" else trigger + ":" + now.date().isoformat()
    key = _cycle_key(policy, int(goal["revision"]), key_trigger, now)
    run = memory.create_growth_run(run_id=f"growth-{uuid.uuid4().hex}", run_key=key, trigger=trigger,
        goal_revision=int(goal["revision"]), timezone=policy.timezone, phase="collecting", status="pending",
        policy=policy.to_dict(), origin_revision=policy.origin_revision, phase_version=2)
    # An explicit request may bring forward an already scheduled retry. Keep
    # its phase, saved evidence, candidates and effect receipts untouched; the
    # same leased scheduler and destination guards still own execution.
    scheduled_retry = run["status"] in {"blocked", "failed"} and bool(run.get("next_due_ts"))
    if scheduled_retry:
        run = memory.update_growth_run(run["run_id"], next_due_ts=now.isoformat(timespec="seconds"))
    if run["status"] == "pending" or scheduled_retry:
        from .growth_candidates import wake_growth_pending

        wake_growth_pending(memory)
    return run


def _inventory(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    from .growth_candidates import content_hash, document_content

    payload = context.get("payload_gateway")
    if payload is None:
        raise RuntimeError("The canonical Payload content gateway is unavailable")
    authoring_contract = payload.require_authoring_contract()
    enabled_collections = set((authoring_contract.get("enabled") or {}).get("collections") or [])
    inventory = []
    content_samples = []
    # Taxonomy is part of the shared schema, but categories are not public pages.
    for collection in ("pages", "posts", "products"):
        if collection not in enabled_collections:
            continue
        fields = payload.authoring_fields("collection", collection, authoring_contract=authoring_contract)
        for document in payload.list(collection, draft=False, limit=100):
            if not document.get("id"):
                raise ValueError("A canonical document has no identity")
            canonical = document_content(document, fields)
            sample = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
            metadata = {key: document.get(key) for key in (
                "sourceId", "slug", "title", "metaTitle", "metaDescription",
            ) if key in document}
            partial_fields = []
            if isinstance(document.get("seo"), Mapping):
                metadata["seo"] = {key: document["seo"][key] for key in ("title", "description")
                    if isinstance(document["seo"].get(key), str)}
                if set(document["seo"]) - set(metadata["seo"]):
                    partial_fields.append("seo")
            inventory.append({"collection": collection, "document": {**metadata, "id": str(document["id"])},
                "sourceRef": f"payload:{collection}:{document['id']}", "route": document.get("route"),
                "assessmentScope": {"completeDocument": False, "documentHash": content_hash(canonical),
                    "omittedFields": sorted(set(fields) - set(metadata)),
                    "partialFields": partial_fields,
                    "totalCharacters": len(sample), "previewCharacters": 0}, "contentPreview": ""})
            content_samples.append(sample)
    if not inventory:
        raise RuntimeError("The website has no canonical editable documents")
    metadata_bytes = len(json.dumps(inventory, ensure_ascii=False).encode())
    if metadata_bytes > 116_000:
        raise ValueError("Canonical route metadata exceeds the declared assessment scope")
    # Account conservatively for UTF-8 and JSON string escaping. Every route
    # remains represented; excerpts are explicitly not full-document evidence.
    preview_limit = min(1600, (116_000 - metadata_bytes) // len(inventory) // 8)
    for entry, sample in zip(inventory, content_samples):
        entry["contentPreview"] = sample[:preview_limit]
        entry["assessmentScope"]["previewCharacters"] = len(entry["contentPreview"])
    if len(json.dumps(inventory, ensure_ascii=False).encode()) > 120_000:
        raise ValueError("Assessment inventory exceeded its declared byte budget")
    return inventory


def _collect_cycle_evidence(context: Mapping[str, Any], trigger: str, run_id: str) -> dict[str, Any]:
    from .growth import growth_metrics
    from .growth_evidence import growth_evidence
    from ..brain.growth import ASSESSMENT_CONTRACT_VERSION

    memory, config = context["memory"], context["config"]
    if _crawlseo_authoritative(config) and context.get("crawlseo_service") is not None:
        return _sync_crawlseo_actions(context)
    if _crawlseo_authoritative(config):
        raise RuntimeError("CrawlSEO is the configured research authority, but its connector is unavailable")
    if producer_frozen(memory):
        raise RuntimeError("Local research and recommendation producers are frozen for CrawlSEO migration")
    errors: dict[str, str] = {}
    if trigger in {"daily", "initial"}:
        from ..core.jobs import _ga_snapshot, _seo_snapshot
        for source, operation in (("ga4", _ga_snapshot), ("gsc", _seo_snapshot)):
            try:
                operation(dict(context))
            except Exception as exc:
                errors[source] = str(exc)[:500]
    inventory = _inventory(context)
    sources = _source_state(memory, config, context)
    from .growth_owner_response import owner_response_evidence
    owner_responses, owner_response_sources = owner_response_evidence(memory, run_id)
    sources.extend(owner_response_sources)
    for source in sources:
        if source["id"] in errors:
            source.update(state="failed", reason=errors[source["id"]])
    sources.append({"id": "inventory", "state": "ready", "sourceRef": "canonical_payload_inventory", "observedAt": utc_now()})
    datasets: dict[str, Any] = {}
    service = context.get("crawlseo_service")
    for section in ("health", "research", "competition"):
        if service is None:
            value = {"errors": {}, "collectionState": "missing"}
        else:
            try:
                value = growth_evidence(service, section)
            except Exception as exc:
                value = {"errors": {"collection": str(exc)[:500]}}
                errors[section] = str(exc)[:500]
        source = _crawlseo_dataset_source(section, value, config)
        value = {**value, **{key: source[key] for key in ("sourceRef", "state", "observedAt", "freshnessHours", "reason")}}
        datasets[section] = value
        sources.append(source)
        if value.get("errors"):
            errors[section] = "; ".join(str(item) for item in value["errors"].values())[:500]
    return {"assessmentContractVersion": ASSESSMENT_CONTRACT_VERSION,
            "sources": sources, "inventory": inventory, "metrics": growth_metrics(memory), "datasets": datasets,
            "ownerResponses": owner_responses, "collectionErrors": errors}


def _crawlseo_authoritative(config: Mapping[str, Any]) -> bool:
    if not crawlseo_research_authority_selected(config):
        return False
    provider = config.get("providers") if isinstance(config.get("providers"), Mapping) else {}
    crawlseo = provider.get("crawlseo") if isinstance(provider.get("crawlseo"), Mapping) else {}
    if not crawlseo.get("enabled") or not crawlseo.get("connector_url"):
        raise RuntimeError("CrawlSEO research authority is selected but its connector is not fully configured")
    return True


def _crawlseo_evidence_freshness_valid(age_days: Any, limit_days: Any) -> bool:
    if (isinstance(age_days, bool) or not isinstance(age_days, (int, float))
            or isinstance(limit_days, bool) or not isinstance(limit_days, (int, float))):
        return False
    return -(5 / 1440) <= age_days <= limit_days


def _technical_crawl_evidence_sources(
    action: Mapping[str, Any], *, site_id: str, context_snapshot: Mapping[str, Any], target_url: str,
    source_path: str, required_capabilities: list[Any], now: datetime.datetime,
) -> list[dict[str, Any]]:
    """Validate versioned crawl provenance separately from ResearchSource evidence."""
    technical = action.get("technicalEvidence")
    if not isinstance(technical, Mapping):
        raise ValueError("The Action has no typed technical crawl provenance")
    if action.get("technicalEvidenceComplete") is not True or action.get("invalidTechnicalEvidenceReferences") is not False:
        raise ValueError("The Action technical crawl references are incomplete or invalid")
    if action.get("technicalEvidenceStale") is not False:
        raise ValueError("The Action technical crawl observation is stale")
    if action.get("unavailableTechnicalEvidenceIds") not in ([], None):
        raise ValueError("The Action is missing one or more persisted crawl records")
    if (technical.get("schemaVersion") != "1.0" or technical.get("sourceKind") != "crawl"
            or technical.get("siteId") != site_id or technical.get("recencyLimitDays") != 7):
        raise ValueError("The Action technical evidence contract version or identity is unsupported")
    if set(technical) != {"schemaVersion", "sourceKind", "siteId", "canonicalContextRevision", "canonicalOrigin",
            "crawlId", "completedAt", "recencyLimitDays", "sourceFingerprint", "issueRefs", "pageRefs"}:
        raise ValueError("The Action technical evidence contract has unsupported fields")
    if technical.get("canonicalContextRevision") != context_snapshot.get("revision"):
        raise ValueError("Canonical connector context changed since the technical evidence was bound")
    canonical_origin = str(technical.get("canonicalOrigin") or "")
    snapshot_origin = str(context_snapshot.get("canonicalOrigin") or "")
    def origin(value: str, *, bare: bool = False) -> tuple[str, str] | None:
        parsed = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(value)
        if (parsed.scheme.lower() != "https" or not parsed.netloc or parsed.username or parsed.password
                or (bare and parsed.path not in {"", "/"}) or parsed.query or parsed.fragment):
            return None
        return parsed.scheme.lower(), parsed.netloc.lower()
    if not origin(canonical_origin, bare=True) or origin(canonical_origin, bare=True) != origin(snapshot_origin, bare=True):
        raise ValueError("Technical evidence does not match the current canonical site origin")
    crawl_id = technical.get("crawlId")
    completed_at = technical.get("completedAt")
    if not isinstance(crawl_id, str) or not crawl_id or not isinstance(completed_at, str):
        raise ValueError("Technical evidence is missing its exact completed crawl identity")
    try:
        observed = datetime.datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("Technical evidence completion time must include a timezone")
        observed = observed.astimezone(datetime.timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Technical evidence has an invalid crawl completion time") from exc
    age = now.astimezone(datetime.timezone.utc) - observed
    if age < datetime.timedelta(0) or age > datetime.timedelta(days=7):
        raise ValueError("Technical crawl evidence is outside its explicit 7-day recency limit")

    issue_refs = technical.get("issueRefs")
    page_refs = technical.get("pageRefs")
    if not isinstance(issue_refs, list) or not issue_refs or len(issue_refs) > 500 or not isinstance(page_refs, list) or len(page_refs) > 500:
        raise ValueError("Technical evidence must contain bounded persisted issue and page references")
    issue_ids: list[str] = []
    issue_types: set[str] = set()
    issue_urls: set[str] = set()
    sources: list[dict[str, Any]] = []
    allowed_types = {"MISSING_TITLE", "MISSING_DESCRIPTION", "DUPLICATE_TITLE", "DUPLICATE_DESCRIPTION",
        "MISSING_ROBOTS", "MISSING_SITEMAP"}
    for ref in issue_refs:
        if not isinstance(ref, Mapping):
            raise ValueError("Technical evidence contains a malformed issue reference")
        if set(ref) != {"id", "url", "type", "severity", "message"}:
            raise ValueError("Technical issue reference has unsupported fields")
        identity, url, issue_type, severity, message = (ref.get(key) for key in ("id", "url", "type", "severity", "message"))
        if (not isinstance(identity, str) or not identity or not isinstance(url, str) or not isinstance(issue_type, str)
                or issue_type not in allowed_types or severity not in {"CRITICAL", "WARNING", "INFO"}
                or not isinstance(message, str) or origin(url) != origin(canonical_origin)):
            raise ValueError("Technical issue reference is malformed or outside the canonical site")
        issue_ids.append(identity)
        issue_types.add(issue_type)
        issue_urls.add(url)
        sources.append({"id": f"crawl_issue:{crawl_id}:{identity}", "sourceKind": "crawl_issue", "sourceRef": url,
            "url": url, "title": f"{issue_type}: {message[:240]}", "observedAt": completed_at,
            "crawlId": crawl_id, "issueType": issue_type, "severity": severity})
    if len(set(issue_ids)) != len(issue_ids):
        raise ValueError("Technical evidence contains duplicate issue references")
    if source_path:
        basename = "robots.txt" if source_path.endswith("robots.txt") else "sitemap.xml" if source_path.endswith("sitemap.xml") else ""
        expected_type = "MISSING_ROBOTS" if basename == "robots.txt" else "MISSING_SITEMAP"
        expected_capability = "site_metadata.robots" if basename == "robots.txt" else "site_metadata.sitemap"
        if (not basename or expected_type not in issue_types or expected_capability not in required_capabilities
                or __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(target_url).path != f"/{basename}"):
            raise ValueError("Technical crawl evidence does not authorize this exact robots/sitemap target")
    elif ("content.prepare" not in required_capabilities or target_url not in issue_urls
            or not any(ref.get("url") == target_url and ref.get("type") in {"MISSING_TITLE", "DUPLICATE_TITLE",
                "MISSING_DESCRIPTION", "DUPLICATE_DESCRIPTION"} for ref in issue_refs)):
        raise ValueError("Technical crawl evidence does not cite an exact supported Payload metadata target")
    page_ids: list[str] = []
    for ref in page_refs:
        if not isinstance(ref, Mapping):
            raise ValueError("Technical evidence contains a malformed audit page reference")
        if set(ref) != {"id", "url", "statusCode", "title", "description", "canonical", "h1Count", "wordCount",
                "contentScore", "hasSchema", "indexable"}:
            raise ValueError("Technical audit page reference has unsupported fields")
        identity, url = ref.get("id"), ref.get("url")
        if (not isinstance(identity, str) or not identity or not isinstance(url, str) or origin(url) != origin(canonical_origin)
                or isinstance(ref.get("statusCode"), bool) or not isinstance(ref.get("statusCode"), int)
                or isinstance(ref.get("h1Count"), bool) or not isinstance(ref.get("h1Count"), int) or ref["h1Count"] < 0
                or isinstance(ref.get("wordCount"), bool) or not isinstance(ref.get("wordCount"), int) or ref["wordCount"] < 0
                or isinstance(ref.get("contentScore"), bool) or not isinstance(ref.get("contentScore"), int)
                or not 0 <= ref["contentScore"] <= 100 or not isinstance(ref.get("hasSchema"), bool)
                or not isinstance(ref.get("indexable"), bool)
                or any(ref.get(key) is not None and not isinstance(ref.get(key), str)
                    for key in ("title", "description", "canonical"))):
            raise ValueError("Technical audit page reference is malformed or outside the canonical site")
        page_ids.append(identity)
        sources.append({"id": f"crawl_page:{crawl_id}:{identity}", "sourceKind": "crawl_page", "sourceRef": url,
            "url": url, "title": f"Crawl page observation · HTTP {ref.get('statusCode')}",
            "observedAt": completed_at, "crawlId": crawl_id})
    if len(set(page_ids)) != len(page_ids):
        raise ValueError("Technical evidence contains duplicate audit page references")
    fingerprint = hashlib.sha256(json.dumps({"siteId": site_id, "crawlId": crawl_id,
        "issueIds": sorted(issue_ids)}, sort_keys=False, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if technical.get("sourceFingerprint") != fingerprint:
        raise ValueError("Technical evidence source fingerprint does not match its exact issue references")
    return sources


def _execute_crawlseo_preparation(
    context: Mapping[str, Any], remote: Mapping[str, Any], binding: Mapping[str, Any],
    *, site_id: str, generation: int,
) -> dict[str, Any]:
    """Prepare one accepted CrawlSEO Action through Ada's existing candidate path."""
    from .growth_candidates import prepare_payload_candidate, queue_source_candidate

    service = context["crawlseo_service"]
    memory = context["memory"]
    action_id = str(remote.get("id") or "")
    revision = int(remote.get("revision") or 0)
    preparation_request_id = str(remote.get("preparationRequestId") or "").strip()
    detail = dict(binding.get("detail") or {})
    try:
        if not preparation_request_id or len(preparation_request_id) > 240:
            raise ValueError("The accepted CrawlSEO preparation attempt is missing its request identity")
        detail["preparationRequestId"] = preparation_request_id
        target = remote.get("target") if isinstance(remote.get("target"), Mapping) else {}
        target_url = str(target.get("canonicalUrl") or "").strip()
        parsed_target = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(target_url)
        identity = target.get("connectorIdentity") if isinstance(target.get("connectorIdentity"), Mapping) else {}
        required = remote.get("requiredCapabilities") if isinstance(remote.get("requiredCapabilities"), list) else []
        snapshot_result = service.connector_context(site_id)
        snapshot = snapshot_result.get("snapshot") if isinstance(snapshot_result, Mapping) else None
        if not isinstance(snapshot, Mapping):
            raise ValueError("Current canonical connector context is required before preparing this Action")
        source_path = str(identity.get("path") or "") if identity.get("kind") == "source_file" else ""
        if source_path:
            from ..frontend_ownership import is_crawl_metadata_path
            expected_name = "robots.txt" if source_path.endswith("robots.ts") or source_path.endswith("robots.txt/route.ts") or source_path.endswith("/robots.txt") else "sitemap.xml"
            expected_route = "/" + expected_name
            expected_capability = "site_metadata.robots" if expected_name == "robots.txt" else "site_metadata.sitemap"
            if (not is_crawl_metadata_path(source_path) or expected_capability not in required
                    or parsed_target.path != expected_route or parsed_target.query or parsed_target.fragment):
                raise ValueError("This Action does not match an exact supported robots/sitemap source capability")
        elif "content.prepare" not in required:
            raise ValueError("This Action does not declare a HelloAda preparation capability")
        inventory = _inventory(context)
        selected = next((row for row in inventory if not source_path and row.get("route") and
            str(row.get("route")).rstrip("/") == (parsed_target.path.rstrip("/") or "/") and
            parsed_target.scheme in {"http", "https"}), None)
        if (not target_url or parsed_target.username or parsed_target.password or parsed_target.query or parsed_target.fragment
                or (not source_path and selected is None)):
            raise ValueError("The Action target is no longer an exact current canonical Payload route")
        snapshot_origin = str(snapshot.get("canonicalOrigin") or "") if isinstance(snapshot, Mapping) else ""
        parsed_origin = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(snapshot_origin)
        if (not snapshot_origin or parsed_target.scheme.lower() != parsed_origin.scheme.lower()
                or parsed_target.netloc.lower() != parsed_origin.netloc.lower()):
            raise ValueError("The Action target is outside the current canonical site origin")
        if source_path:
            capabilities = snapshot.get("capabilities") if isinstance(snapshot, Mapping) and isinstance(snapshot.get("capabilities"), Mapping) else {}
            source_files = capabilities.get("sourceFiles") if isinstance(capabilities.get("sourceFiles"), list) else []
            if source_path not in source_files:
                raise ValueError("HelloAda did not declare this exact crawl metadata source file")
        else:
            current_hash = str(selected.get("assessmentScope", {}).get("documentHash") or "")
            snapshot_inventory = snapshot.get("websiteInventory") if isinstance(snapshot, Mapping) else None
            snap_row = next((row for row in snapshot_inventory or [] if isinstance(row, Mapping)
                and str(row.get("collection") or "") == str(selected.get("collection") or "")
                and str(row.get("id") or "") == str(selected.get("document", {}).get("id") or "")), None)
            if not snap_row or snap_row.get("documentHash") != current_hash:
                raise ValueError("The current Payload document changed since CrawlSEO's inventory snapshot; reassessment is required")
        technical_mode = isinstance(remote.get("technicalEvidence"), Mapping)
        if technical_mode:
            sources = _technical_crawl_evidence_sources(remote, site_id=site_id, context_snapshot=snapshot,
                target_url=target_url, source_path=source_path, required_capabilities=required,
                now=datetime.datetime.now(datetime.timezone.utc))
        else:
            sources = remote.get("evidence") if isinstance(remote.get("evidence"), list) else []
            if not sources:
                raise ValueError("The Action has no linked evidence sources")
            for source in sources:
                if not isinstance(source, Mapping):
                    raise ValueError("The Action contains malformed evidence")
                if not _crawlseo_evidence_freshness_valid(source.get("freshnessDays"), source.get("recencyLimitDays")):
                    raise ValueError("The Action evidence is stale or has no verifiable freshness limit")
        source_binding = {"siteId": site_id, "actionId": action_id, "actionRevision": revision,
            "generation": generation, "candidateRef": f"{'source' if source_path else 'payload'}-growth:{action_id}:{revision}:{generation}",
            "reviewUrl": str(context.get("config", {}).get("site", {}).get("payload", {}).get("url") or "").rstrip("/") + "/admin",
            "targetUrl": target_url}
        opportunity = {
            "kind": "code" if source_path else "payload_content", "title": str(remote.get("problem") or remote.get("recommendation") or "CrawlSEO improvement")[:300],
            "why": str(remote.get("problem") or "CrawlSEO identified an evidence-backed website opportunity")[:2000],
            "hypothesis": str(remote.get("expectedOutcome") or "")[:2000],
            "scope": str(remote.get("recommendation") or "")[:2000],
            "evidence": [str(source.get("id")) for source in sources if source.get("id")],
            "requiredSources": [str(source.get("id")) for source in sources if source.get("id")],
            "collection": selected["collection"] if selected else None,
            "documentId": str(selected["document"]["id"]) if selected else None,
            "metric": "technical.crawl_issue_count" if technical_mode else "gsc.clicks", "whyAction": action_id,
            **({"allowedPaths": [source_path]} if source_path else {}),
            "crawlseoBinding": source_binding,
        }
        if not opportunity["scope"].strip() or not opportunity["evidence"]:
            raise ValueError("The Action lacks a bounded recommendation or stable evidence identities")
        policy = GrowthPolicy.from_config(context.get("config") or {})
        goal = ensure_default_goal(memory)
        run_key = f"crawlseo-action:{site_id}:{action_id}:revision-{revision}"
        run = memory.get_growth_run_by_key(run_key)
        if run is None:
            run = memory.create_growth_run(
                run_id=f"growth-{hashlib.sha256(run_key.encode()).hexdigest()[:32]}", run_key=run_key,
                trigger="crawlseo_action", goal_revision=int(goal["revision"]), timezone=policy.timezone,
                phase="preparing", status="pending", policy=policy.to_dict(),
                origin_revision=policy.origin_revision, phase_version=2,
                source_refs=[str(source.get("id")) for source in sources if source.get("id")],
            )
        material = {"authority": "crawlseo", "action": dict(remote), "inventory": inventory, "sources": sources}
        manifest = {"schemaVersion": 1, "runId": run["run_id"], "runKey": run_key,
            "goalRevision": int(goal["revision"]), "originRevision": policy.origin_revision,
            "sources": [{"id": source.get("id"), "sourceRef": source.get("sourceRef") or source.get("url"), "state": "ready",
                "observedAt": source.get("observedAt"), "retrievedAt": source.get("retrievedAt"),
                **({"sourceKind": source.get("sourceKind"), "crawlId": source.get("crawlId"),
                   "issueType": source.get("issueType"), "severity": source.get("severity")} if source.get("sourceKind") else {})}
                for source in sources],
            "materialHash": "sha256:" + hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()}
        manifest_hash = "sha256:" + hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        artifact = next((row for row in memory.list_artifacts(kind=ArtifactKind.GROWTH_EVIDENCE.value, limit=500)
            if row.content_hash == manifest_hash), None)
        if artifact is None:
            artifact = memory.create_artifact(Artifact(
                kind=ArtifactKind.GROWTH_EVIDENCE, title=f"CrawlSEO Action evidence · {action_id[:60]}",
                summary="Immutable evidence snapshot used for this accepted CrawlSEO Action.", renderer="growth_evidence",
                capability_id="growth.evidence.read", provider_id="crawlseo", content_hash=manifest_hash,
                preview_data={"manifest": manifest, "action": dict(remote)},
            ))
        cycle = memory.growth_strategy_cycle(run["run_id"], int(artifact.artifact_id or 0))
        initiative_id = int(detail.get("initiativeId") or 0)
        initiative = memory.update_strategy_initiative(initiative_id) if initiative_id else None
        if initiative is None:
            initiative = next((row for row in memory.list_strategy_initiatives(limit=500)
                if row.get("growth_run_id") == run["run_id"]
                and (row.get("expected") or {}).get("crawlseoActionId") == action_id
                and (row.get("expected") or {}).get("crawlseoRevision") == revision), None)
            if initiative is not None:
                initiative_id = int(initiative["id"])
        if initiative is None:
            initiative_id = memory.create_strategy_initiative(
                int(cycle["id"]), kind="code" if source_path else "payload_content", title=opportunity["title"],
                summary=opportunity["scope"], hypothesis=opportunity["hypothesis"], rationale=opportunity["why"],
                evidence=opportunity["evidence"], expected={"opportunity": opportunity, "crawlseoActionId": action_id,
                    "crawlseoRevision": revision, "crawlseoGeneration": generation},
                priority="normal", state="preparing", growth_run_id=run["run_id"],
                goal_revision=int(goal["revision"]), origin_revision=policy.origin_revision,
            )
            detail["initiativeId"] = initiative_id
            memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                expected_state="preparing", state="preparing", detail=detail, release_lease=False)
            initiative = memory.update_strategy_initiative(initiative_id)
        if source_path:
            validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
            preparation = validation.get("preparation") if isinstance(validation.get("preparation"), Mapping) else {}
            if preparation.get("jobId"):
                job = memory.get_chat_job(int(preparation["jobId"]))
                if initiative.get("state") == "blocked" or (job and job.get("status") in {"failed", "cancelled"}):
                    job_result = job.get("result") if isinstance(job, Mapping) and isinstance(job.get("result"), Mapping) else {}
                    error = str(job.get("error") or job_result.get("error") or initiative.get("last_error")
                        or "The exact source candidate could not be prepared")[:500] if job else str(initiative.get("last_error") or "The exact source candidate could not be prepared")[:500]
                    report = {"status": "preparation_blocked", "preparationRequestId": preparation_request_id,
                        "detail": {"error": error, "sourcePath": source_path}}
                    detail.update({"initiativeId": initiative_id, "candidateRef": source_binding["candidateRef"],
                        "reviewUrl": source_binding["reviewUrl"], "sourcePath": source_path, "report": report})
                    memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                        expected_state="preparing", state="preparation_blocked_unreported", detail=detail)
                    pending = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
                    if pending:
                        _reconcile_crawlseo_execution_report(context, pending)
                    return {"status": "blocked", "error": error}
                detail.update({"initiativeId": initiative_id, "candidateRef": source_binding["candidateRef"],
                    "reviewUrl": source_binding["reviewUrl"], "sourcePath": source_path, "sourceJobId": preparation["jobId"]})
                memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                    expected_state="preparing", state="preparing", detail=detail)
                return {"status": "preparing", "sourceJobId": preparation["jobId"]}
            job_id = queue_source_candidate(context, initiative, opportunity, {"evidenceHash": manifest_hash})
            validation = memory.update_strategy_initiative(initiative_id)
            detail.update({"initiativeId": initiative_id, "candidateRef": source_binding["candidateRef"],
                "reviewUrl": source_binding["reviewUrl"], "sourcePath": source_path,
                "sourceJobId": (validation.get("validation") or {}).get("preparation", {}).get("jobId") if isinstance(validation, Mapping) else job_id})
            memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                expected_state="preparing", state="preparing", detail=detail)
            return {"status": "preparing", "sourceJobId": job_id}
        candidate = prepare_payload_candidate(context, initiative, opportunity, inventory, {
            "evidenceHash": manifest_hash, "policy": {"policy_version": policy.policy_version},
            "action": dict(remote), "sources": sources,
            "businessFacts": (context.get("customer_context_service").task_view("strategy")
                if context.get("customer_context_service") is not None else {}),
        })
        review_origin = str(context.get("config", {}).get("site", {}).get("payload", {}).get("url") or "").rstrip("/")
        if not review_origin:
            raise ValueError("The authenticated HelloAda owner workspace URL is not configured")
        review_url = review_origin + "/admin"
        candidate_ref = str(opportunity["crawlseoBinding"]["candidateRef"])
        current_action = service.connector_action(action_id)
        current_envelope = current_action.get("action") if isinstance(current_action.get("action"), Mapping) else current_action
        if (not isinstance(current_envelope, Mapping) or current_envelope.get("revision") != revision
                or str(current_envelope.get("preparationStatus") or "").lower() != "queued"
                or current_envelope.get("preparationRequestId") != preparation_request_id):
            raise ValueError("The CrawlSEO preparation request was cancelled or changed while Ada was preparing the candidate")
        current_binding = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
        if (current_binding is None or int(current_binding.get("generation") or 0) != generation
                or str((current_binding.get("detail") or {}).get("preparationRequestId") or "") != preparation_request_id):
            return {"status": "stale_attempt", "error": "A newer CrawlSEO preparation attempt owns this Action revision"}
        ready_report = {"status": "preparation_ready", "preparationRequestId": preparation_request_id, "candidateRef": candidate_ref,
            "reviewUrl": review_url,
            "detail": {"initiativeId": initiative_id, "draftId": candidate.get("draft_id"),
                "candidateHash": candidate.get("candidate_hash"), "reviewPackageHash": candidate.get("review_package_hash")}}
        detail.update({"initiativeId": initiative_id, "candidateRef": candidate_ref,
            "reviewUrl": review_url, "reviewPackageHash": candidate.get("review_package_hash"),
            "candidateHash": candidate.get("candidate_hash"), "draftId": candidate.get("draft_id"),
            "preparationStatus": "ready", "report": ready_report})
        memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
            expected_state="preparing", state="preparation_unreported", detail=detail)
        pending = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
        reported = bool(pending and _reconcile_crawlseo_execution_report(context, pending))
        return {"status": "ready" if reported else "ready_unreported", "candidateRef": candidate_ref, "reviewUrl": review_url}
    except Exception as exc:
        message = str(exc)[:500] or "CrawlSEO Action preparation failed"
        current = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
        if (current is not None
                and str((current.get("detail") or {}).get("preparationRequestId") or "") not in {"", preparation_request_id}):
            return {"status": "stale_attempt", "error": "A newer CrawlSEO preparation attempt owns this Action revision"}
        try:
            fresh_action = service.connector_action(action_id)
            fresh_envelope = fresh_action.get("action") if isinstance(fresh_action.get("action"), Mapping) else fresh_action
        except Exception:
            fresh_envelope = {}
        if isinstance(fresh_envelope, Mapping) and str(fresh_envelope.get("preparationStatus") or "").lower() == "cancelled":
            if current is not None and current.get("state") in {"claimed", "preparing", "blocked", "preparation_unreported", "preparation_blocked_unreported"}:
                try:
                    current = memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                        expected_state=str(current["state"]), state="cancelled",
                        detail={**dict(current.get("detail") or {}), "error": "Owner cancelled preparation; any saved candidate remains private and cannot be published."})
                except Exception:
                    pass
            initiative = next((row for row in memory.list_strategy_initiatives(limit=500)
                if (row.get("expected") or {}).get("crawlseoActionId") == action_id
                and (row.get("expected") or {}).get("crawlseoRevision") == revision), None)
            if initiative is not None and initiative.get("state") in {"preparing", "validating", "ready_for_review"}:
                try:
                    target = "rejected" if initiative.get("state") == "ready_for_review" else "blocked"
                    memory.transition_strategy_initiative(int(initiative["id"]), target,
                        expected_state=str(initiative["state"]), last_error="Owner cancelled preparation; the private candidate is retained without publication authority.")
                except Exception:
                    pass
            return {"status": "cancelled", "error": message}
        if (isinstance(fresh_envelope, Mapping)
                and fresh_envelope.get("preparationRequestId") != preparation_request_id):
            return {"status": "stale_attempt", "error": "A newer CrawlSEO preparation attempt owns this Action revision"}
        if current is not None and current.get("state") in {"claimed", "preparing"}:
            try:
                existing_detail = dict(current.get("detail") or {})
                if existing_detail.get("preparationRequestId") not in {None, preparation_request_id}:
                    return {"status": "stale_attempt", "error": "A newer CrawlSEO preparation attempt owns this Action revision"}
                report = {"status": "preparation_blocked", "preparationRequestId": preparation_request_id,
                    "detail": {"error": message}}
                memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                    expected_state=str(current["state"]), state="preparation_blocked_unreported",
                    detail={**existing_detail, "preparationRequestId": preparation_request_id,
                        "error": message, "report": report})
                pending = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
                if pending:
                    _reconcile_crawlseo_execution_report(context, pending)
            except Exception:
                pass
        return {"status": "blocked", "error": message}


def _reconcile_crawlseo_execution_report(context: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    """Replay a locally durable owner/publication status until CrawlSEO receipts it."""
    service = context.get("crawlseo_service")
    if service is None:
        return False
    state = str(row.get("state") or "")
    if state not in {"preparation_unreported", "preparation_blocked_unreported", "decision_unreported", "publication_unreported"}:
        return False
    detail = dict(row.get("detail") or {})
    try:
        report = dict(detail.get("report") or {})
        service.connector_record_execution(str(row["action_id"]), report)
        final_state = ("ready" if state == "preparation_unreported" else "blocked" if state == "preparation_blocked_unreported"
            else "owner_decision" if state == "decision_unreported" else "published")
        context["memory"].update_crawlseo_execution_binding(
            str(row["site_id"]), str(row["action_id"]), int(row["action_revision"]), int(row["generation"]),
            expected_state=state, state=final_state, detail=detail,
        )
        return True
    except Exception:
        return False


def _record_crawlseo_source_candidate_ready(
    context: Mapping[str, Any], initiative: Mapping[str, Any], package: Mapping[str, Any], draft: Mapping[str, Any],
) -> bool:
    """Return Ada's exact, preview-verified source candidate to CrawlSEO."""
    memory = context["memory"]
    service = context.get("crawlseo_service")
    connector = package.get("crawlseoBinding") if isinstance(package.get("crawlseoBinding"), Mapping) else {}
    site_id, action_id = str(connector.get("siteId") or ""), str(connector.get("actionId") or "")
    revision, generation = connector.get("actionRevision"), connector.get("generation")
    if (service is None or not site_id or not action_id or isinstance(revision, bool) or not isinstance(revision, int)
            or isinstance(generation, bool) or not isinstance(generation, int)):
        return False
    binding = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
    if binding is None or int(binding.get("generation") or 0) != generation:
        return False
    detail = dict(binding.get("detail") or {})
    candidate_ref = str(connector.get("candidateRef") or detail.get("candidateRef") or "")
    review_url = str(connector.get("reviewUrl") or detail.get("reviewUrl") or "")
    preparation_request_id = str(detail.get("preparationRequestId") or "")
    if not candidate_ref or not review_url or not preparation_request_id or not package.get("source", {}).get("candidateSha"):
        return False
    report = {"status": "preparation_ready", "preparationRequestId": preparation_request_id,
        "candidateRef": candidate_ref, "reviewUrl": review_url,
        "detail": {"initiativeId": int(initiative["id"]), "draftId": int(draft["id"]),
            "candidateSha": str(package["source"]["candidateSha"]),
            "reviewPackageHash": str(initiative.get("review_package_hash") or ""),
            "changedPaths": list(package["source"].get("changedPaths") or [])}}
    state = str(binding.get("state") or "")
    try:
        if state == "preparation_unreported":
            if dict(detail.get("report") or {}) != report:
                return False
        elif state == "preparing":
            detail.update({"candidateRef": candidate_ref, "reviewUrl": review_url, "report": report,
                "initiativeId": int(initiative["id"]), "draftId": int(draft["id"])})
            binding = memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                expected_state="preparing", state="preparation_unreported", detail=detail)
        elif state == "ready":
            return True
        else:
            return False
        pending = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
        return bool(pending and _reconcile_crawlseo_execution_report(context, pending))
    except Exception:
        return False


def record_crawlseo_source_publication(
    context: Mapping[str, Any], package: Mapping[str, Any], deployment: Mapping[str, Any],
    promotion: Mapping[str, Any] | None = None,
) -> bool:
    """Report only a deployed, exact source candidate with a verified release receipt."""
    connector = package.get("crawlseoBinding") if isinstance(package.get("crawlseoBinding"), Mapping) else {}
    source = package.get("source") if isinstance(package.get("source"), Mapping) else {}
    release = deployment.get("release_receipt") if isinstance(deployment.get("release_receipt"), Mapping) else {}
    commit = str(deployment.get("verified_commit") or "").lower()
    release_id = str(deployment.get("release_id") or "")
    verified_at = str(release.get("connectionVerifiedAt") or "")
    target_url = str(connector.get("targetUrl") or "")
    candidate_sha = str(source.get("candidateSha") or "").lower()
    promotion_refs = promotion.get("refs") if isinstance(promotion, Mapping) else None
    promotion_refs = promotion_refs if isinstance(promotion_refs, Mapping) else {}
    promotion_candidate = str(promotion_refs.get("candidateSha") or "").lower()
    promotion_source = str(promotion_refs.get("sourceSha") or "").lower()
    promotion_tree = str(promotion_refs.get("treeSha") or "").lower()
    if (deployment.get("status") != "deployed" or deployment.get("live") is not True
            or not release_id or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or str(deployment.get("commit") or "").lower() != commit
            or not str(release.get("uploadedVersion") or "")
            or not re.fullmatch(r"[a-f0-9]{40}", candidate_sha)
            or promotion_candidate != candidate_sha or promotion_source != commit
            or not re.fullmatch(r"[a-f0-9]{40}", promotion_tree)
            or not verified_at or not target_url):
        return False
    try:
        verified_datetime = datetime.datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
        if verified_datetime.tzinfo is None:
            return False
        verified_at = verified_datetime.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
        return False
    memory = context["memory"]
    site_id, action_id = str(connector.get("siteId") or ""), str(connector.get("actionId") or "")
    revision, generation = connector.get("actionRevision"), connector.get("generation")
    if (not site_id or not action_id or isinstance(revision, bool) or not isinstance(revision, int)
            or isinstance(generation, bool) or not isinstance(generation, int)):
        return False
    binding = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
    if binding is None or int(binding.get("generation") or 0) != generation:
        return False
    detail = dict(binding.get("detail") or {})
    candidate_ref = str(connector.get("candidateRef") or detail.get("candidateRef") or "")
    review_package_hash = str(detail.get("reviewPackageHash") or "")
    if not candidate_ref or not re.fullmatch(r"[a-f0-9]{64}", review_package_hash):
        return False
    receipt = {"candidateRef": candidate_ref, "receiptId": release_id,
        "targetUrl": target_url, "publishedAt": verified_at, "contentHash": candidate_sha}
    report = {"status": "publication_verified", "candidateRef": candidate_ref,
        "publicationReceipt": receipt,
        "detail": {"releaseId": release_id, "verifiedCommit": commit,
            "reviewPackageHash": review_package_hash}}
    state = str(binding.get("state") or "")
    try:
        if state == "publication_unreported":
            if dict(detail.get("report") or {}) != report:
                return False
        elif state == "owner_decision":
            detail["report"] = report
            binding = memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                expected_state=state, state="publication_unreported", detail=detail)
        elif state == "published":
            return True
        else:
            return False
        pending = memory.get_crawlseo_execution_binding(site_id, action_id, revision)
        return bool(pending and _reconcile_crawlseo_execution_report(context, pending))
    except Exception:
        return False


def record_crawlseo_owner_decision(context: Mapping[str, Any], approval_id: int, approved: bool) -> bool:
    """Persist and report the exact local candidate decision to its CrawlSEO Action."""
    if not _crawlseo_authoritative(context.get("config") or {}):
        return False
    memory = context["memory"]
    initiative = next((row for row in memory.list_strategy_initiatives(limit=None)
        if int(row.get("approval_id") or 0) == int(approval_id)), None)
    if initiative is None:
        return False
    expected = initiative.get("expected") if isinstance(initiative.get("expected"), Mapping) else {}
    action_id = str(expected.get("crawlseoActionId") or "")
    revision, generation = expected.get("crawlseoRevision"), expected.get("crawlseoGeneration")
    if (not action_id or isinstance(revision, bool) or not isinstance(revision, int)
            or isinstance(generation, bool) or not isinstance(generation, int)):
        return False
    binding = memory.get_crawlseo_execution_binding(str(context.get("connector_site_id") or
        context.get("site_id") or ""), action_id, revision)
    if binding is None or int(binding.get("generation") or 0) != generation:
        return False
    detail = dict(binding.get("detail") or {})
    candidate_ref = str(detail.get("candidateRef") or "")
    review_url = str(detail.get("reviewUrl") or "")
    if not candidate_ref or not review_url:
        return False
    if str(binding.get("state") or "") == "preparation_unreported":
        if not _reconcile_crawlseo_execution_report(context, binding):
            return False
        binding = memory.get_crawlseo_execution_binding(str(binding["site_id"]), action_id, revision)
        if binding is None:
            return False
        detail = dict(binding.get("detail") or {})
    report = {"status": "owner_decision", "candidateRef": candidate_ref,
        "reviewUrl": review_url, "ownerDecision": "approved" if approved else "declined",
        "detail": {"approvalId": int(approval_id), "initiativeId": int(initiative["id"]),
            "reviewPackageHash": str(initiative.get("review_package_hash") or "")}}
    try:
        state = str(binding.get("state") or "")
        if state == "decision_unreported":
            prior = dict(detail.get("report") or {})
            if prior != report:
                return False
        else:
            if state != "ready":
                return False
            detail["report"] = report
            binding = memory.update_crawlseo_execution_binding(str(binding["site_id"]), action_id, revision,
                generation, expected_state=state, state="decision_unreported", detail=detail)
        return _reconcile_crawlseo_execution_report(context, binding)
    except Exception:
        return False


def _persist_unbound_crawlseo_events(memory: Any, service: Any, events: Any) -> list[str]:
    """Record no-Action events locally before acknowledging them upstream."""
    if not isinstance(events, list):
        return []
    acknowledged: list[str] = []
    for event in events:
        if not isinstance(event, Mapping) or event.get("actionId"):
            continue
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        if str(event.get("type") or "") == "context.updated":
            disposition, reason = "reconciled", ""
        else:
            disposition, reason = "unsupported", "Event type has no local execution effect"
        # Store identity and a payload hash only. Remote event text is untrusted
        # and must not become a local instruction or diagnostic string.
        memory.record_crawlseo_connector_event(dict(event), disposition=disposition, reason=reason)
        acknowledged.append(event_id)
    if acknowledged:
        site_id = str(next((event.get("siteId") for event in events if isinstance(event, Mapping) and event.get("siteId")), "")) or None
        service.connector_ack_events(acknowledged[:100], site_id=site_id)
    return acknowledged


def _persist_action_crawlseo_events(memory: Any, service: Any, events: Any, action_id: str) -> list[str]:
    """Persist reconciled Action event identities before upstream acknowledgement."""
    if not isinstance(events, list):
        return []
    matching = [event for event in events if isinstance(event, Mapping)
        and str(event.get("actionId") or "") == action_id and str(event.get("id") or "")]
    for event in matching:
        memory.record_crawlseo_connector_event(
            dict(event), disposition="reconciled",
            reason="Action projection and execution state reconciled",
        )
    acknowledged = [str(event["id"]) for event in matching]
    site_id = str(matching[0].get("siteId") or "") or None
    for offset in range(0, len(acknowledged), 100):
        service.connector_ack_events(acknowledged[offset:offset + 100], site_id=site_id)
    return acknowledged


def _sync_crawlseo_actions(context: Mapping[str, Any]) -> dict[str, Any]:
    """Synchronize remote Actions into HelloAda's one owner task projection."""
    require_connector_dispatch_enabled(context["memory"])
    service = context.get("crawlseo_service")
    if service is None:
        raise RuntimeError("CrawlSEO is the configured research authority, but its connector is unavailable")
    state = context.get("seo_provisioning_state") if isinstance(context.get("seo_provisioning_state"), Mapping) else context["memory"].kv_get("seo_provisioning_state", {})
    crawlseo_state = state.get("crawlseo") if isinstance(state, Mapping) and isinstance(state.get("crawlseo"), Mapping) else {}
    site_id = str(context.get("connector_site_id") or context.get("site_id") or crawlseo_state.get("site_id") or "").strip()
    if not site_id:
        raise RuntimeError("CrawlSEO authority requires the provisioned connector site id")
    payload = context.get("payload_gateway")
    if payload is None:
        raise RuntimeError("CrawlSEO authority requires the canonical Payload gateway")
    inventory = _inventory(context)
    site = context["config"].get("site") if isinstance(context["config"].get("site"), Mapping) else {}
    origin = str(site.get("public_url") or site.get("custom_domain") or
                 ((context["config"].get("seo") or {}).get("site_url") if isinstance(context["config"].get("seo"), Mapping) else "") or
                 ((context["config"].get("seo") or {}).get("preview_url") if isinstance(context["config"].get("seo"), Mapping) else "") or "").strip()
    if origin and "://" not in origin:
        origin = "https://" + origin
    context_result = service.connector_context(site_id)
    customer_context = context.get("customer_context_service")
    owner_facts = customer_context.task_view("strategy") if customer_context is not None and customer_context.current() is not None else {}
    payload_origin = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(str(payload.base_url))
    source_files: list[str] = []
    source_capabilities: list[str] = []
    if str((context["config"].get("design_engine") or {}).get("build_profile") or "").strip().lower() == "next_react":
        from ..frontend_ownership import CRAWL_METADATA_PATTERNS
        from ..hands.opencode_runner import builder_available
        if builder_available(context["config"]):
            source_files = list(CRAWL_METADATA_PATTERNS)
            source_capabilities = ["site_metadata.robots", "site_metadata.sitemap"]
    context_payload = {
        "siteId": site_id,
        "canonicalOrigin": origin,
        "websiteInventory": [{"collection": row["collection"], "id": str(row["document"]["id"]),
                       "route": row.get("route"), "documentHash": row["assessmentScope"]["documentHash"]}
                      for row in inventory],
        "businessFacts": owner_facts,
        "capabilities": {"supported": ["content.prepare", *source_capabilities],
            "sourceFiles": source_files,
            "reviewOrigin": payload_origin.scheme + "://" + payload_origin.netloc,
            "reviewPath": "/admin"},
    }
    synced = service.connector_sync(snapshot=context_payload)
    generation_data = synced.get("capabilities") if isinstance(synced.get("capabilities"), Mapping) else {}
    binding_data = generation_data.get("binding") if isinstance(generation_data.get("binding"), Mapping) else {}
    generation = binding_data.get("generation")
    if binding_data.get("executionSupported") is False:
        raise RuntimeError("The active CrawlSEO execution adapter is not implemented and cannot receive owner work")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise RuntimeError("CrawlSEO connector is not bound to an active execution generation")
    actions = synced.get("actions") if isinstance(synced.get("actions"), list) else []
    from .actions import OwnerActionService, owner_action_summary
    from ..core.contracts import ActionPriority, ActionRequirement, ActionState, OwnerAction
    owner_actions = OwnerActionService(context["memory"])
    normalized = []
    for remote in actions:
        if not isinstance(remote, Mapping) or not isinstance(remote.get("id"), str):
            continue
        action_id = str(remote["id"])
        revision = remote.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            continue
        status = str(remote.get("status") or "PROPOSED").lower()
        execution = remote.get("execution") if isinstance(remote.get("execution"), Mapping) else {}
        preparation_status = str(remote.get("preparationStatus") or "none").lower()
        execution_status = str(execution.get("status") or "").lower()
        if execution.get("ownerDecision") == "declined" or preparation_status == "cancelled":
            status = "dismissed"
        elif execution.get("ownerDecision") == "approved":
            status = "completed" if execution_status in {"publication_verified", "outcome_measured"} else "started"
        elif preparation_status in {"queued", "preparing", "ready"}:
            status = "started"
        elif preparation_status == "blocked":
            status = "waiting"
        state_map = {"proposed": ActionState.OPEN, "open": ActionState.OPEN, "started": ActionState.STARTED,
                     "in_progress": ActionState.STARTED, "drafting": ActionState.STARTED,
                     "draft_ready": ActionState.WAITING, "delivery_approved": ActionState.WAITING,
                     "delivering": ActionState.STARTED, "delivered": ActionState.WAITING,
                     "verified": ActionState.COMPLETED, "waiting": ActionState.WAITING,
                     "completed": ActionState.COMPLETED, "snoozed": ActionState.SNOOZED,
                     "dismissed": ActionState.DISMISSED, "failed": ActionState.WAITING,
                     "stale": ActionState.STALE}
        requirement = str(remote.get("requirement") or "OWNER_DECISION").lower()
        req_map = {"owner_decision": ActionRequirement.OWNER_DECISION,
                   "owner_information": ActionRequirement.OWNER_INFORMATION,
                   "suggestion": ActionRequirement.SUGGESTION}
        priority = str(remote.get("priority") or "NORMAL").lower()
        priority_map = {"urgent": ActionPriority.URGENT, "normal": ActionPriority.NORMAL, "optional": ActionPriority.OPTIONAL}
        title = str(remote.get("title") or "CrawlSEO recommendation")[:500]
        summary = owner_action_summary(remote.get("summary") or remote.get("scope") or "Review the shared research recommendation.")
        local = owner_actions.create(OwnerAction(
            capability_id="growth.crawlseo_action", provider_id="crawlseo", title=title, summary=summary,
            action_label="Review recommendation", priority=priority_map.get(priority, ActionPriority.NORMAL),
            requirement=req_map.get(requirement, ActionRequirement.OWNER_DECISION),
            state=state_map.get(status, ActionState.OPEN), source_ref=f"crawlseo-action:{action_id}",
            dedupe_key=f"crawlseo-action:{action_id}", payload={"remoteActionId": action_id,
                "revision": remote.get("revision"), "executionStatus": remote.get("preparationStatus"),
                "execution": dict(execution),
                "envelope": dict(remote)},), reuse_terminal=True)
        remote_state = state_map.get(status, ActionState.OPEN)
        if local.state != remote_state and local.state not in {ActionState.COMPLETED, ActionState.DISMISSED, ActionState.STALE}:
            try:
                local = context["memory"].transition_owner_action(int(local.id), remote_state)
            except Exception:
                # A remote cancellation/failure may be newer than a terminal
                # local projection. Keep the durable connector state visible
                # without resurrecting the local owner action.
                pass
        context["memory"].update_owner_action_payload(int(local.id), {
            **local.payload, "remoteActionId": action_id, "revision": remote.get("revision"),
            "executionStatus": remote.get("preparationStatus"), "execution": dict(execution), "envelope": dict(remote),
        })
        normalized.append({**local.to_owner_dict(), "remote_action_id": action_id})
        pending_report = context["memory"].get_crawlseo_execution_binding(site_id, action_id, revision)
        if pending_report is not None:
            _reconcile_crawlseo_execution_report(context, pending_report)
        preparation = str(remote.get("preparationStatus") or "none").lower()
        if preparation in {"queued", "preparing", "blocked", "ready"}:
            state_name = "claimed" if preparation == "queued" else "blocked" if preparation == "blocked" else "preparing" if preparation == "preparing" else "ready"
            memory = context["memory"]
            binding_row, created = memory.claim_crawlseo_execution_binding(
                site_id, action_id, revision, generation,
                state=state_name,
                detail={"remoteAction": dict(remote), "ownerActionId": local.id, "preparationStatus": preparation,
                    "preparationRequestId": remote.get("preparationRequestId")},
            )
            # Bind events only after the local Action projection and execution
            # record are durable. Replayed events hit the uniqueness key.
            if preparation == "queued" and binding_row.get("state") in {"blocked", "preparation_blocked_unreported"}:
                binding_row = memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                    expected_state=str(binding_row["state"]), state="claimed",
                    detail={**dict(binding_row.get("detail") or {}), "remoteAction": dict(remote),
                        "ownerActionId": local.id, "preparationRequestId": remote.get("preparationRequestId"),
                        "retryRequestedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            if preparation == "queued" and binding_row.get("state") in {"claimed", "preparing"}:
                lease = memory.acquire_crawlseo_execution_lease(
                    site_id, action_id, revision, generation,
                    lease_owner=f"crawlseo:{os.getpid()}:{uuid.uuid4().hex}",
                )
                if lease is not None:
                    try:
                        _execute_crawlseo_preparation(context, remote, lease, site_id=site_id, generation=generation)
                        binding_row = memory.get_crawlseo_execution_binding(site_id, action_id, revision) or lease
                    except Exception as exc:
                        try:
                            memory.update_crawlseo_execution_binding(site_id, action_id, revision, generation,
                                expected_state="preparing", state="blocked", detail={**dict(lease.get("detail") or {}), "error": str(exc)[:500]})
                            service.connector_record_execution(action_id, {"status": "preparation_blocked",
                                "preparationRequestId": str(remote.get("preparationRequestId") or ""),
                                "detail": {"error": str(exc)[:500]}})
                        except Exception:
                            pass
            # Projection plus the unique binding (or explicit unsupported
            # classification) is the local durable receipt for at-least-once
            # delivery. Acknowledge only these event IDs.
        # Keep page-sized acknowledgements while persisting every receipt first.
        _persist_action_crawlseo_events(context["memory"], service, synced.get("events", []), action_id)
    _persist_unbound_crawlseo_events(context["memory"], service, synced.get("events", []))
    # CrawlSEO Actions may use Ada's existing source-candidate worker. Reconcile
    # only those explicitly bound initiatives; legacy local Growth work stays
    # excluded while the shared authority is active.
    from .growth_candidates import reconcile_source_candidates
    reconcile_source_candidates(context, crawlseo_only=True)
    return {"authority": "crawlseo", "actions": normalized, "inventory": inventory,
            "contextRevision": synced.get("contextRevision"), "collectionErrors": {}}


def _crawlseo_dataset_source(
    section: str,
    dataset: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Bind a saved CrawlSEO dataset to its source lineage and observation time.

    The dataset fetch timestamp is deliberately ignored: only a crawl completion,
    report completion, keyword observation, or SERP observation can make it current.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if section not in {"health", "research", "competition"}:
        raise ValueError("unknown CrawlSEO dataset")
    source_id = f"crawlseo_{section}"
    source_ref = f"crawlseo:{section}"
    errors = dataset.get("errors")
    has_errors = isinstance(errors, Mapping) and bool(errors)
    timestamps: list[datetime.datetime] = []
    missing_timestamp = False
    has_observation = False

    def record(value: Any, *time_fields: str) -> None:
        nonlocal has_observation, missing_timestamp
        if not isinstance(value, Mapping):
            return
        has_observation = True
        observed = next((_parsed_timestamp(value.get(key)) for key in time_fields
            if _parsed_timestamp(value.get(key)) is not None), None)
        if observed is None:
            missing_timestamp = True
        else:
            timestamps.append(observed)

    if section == "health":
        summary = dataset.get("summary")
        if isinstance(summary, Mapping) and summary.get("status") == "completed":
            record(summary, "finished_at", "finishedAt")
        elif isinstance(summary, Mapping) and summary:
            has_observation = True
            missing_timestamp = True
    elif section == "research":
        # Research history is context, not proof: it may contain failed or
        # pending reports. Only returned metric observations bind readiness.
        for field in ("keywords", "domains", "backlinks"):
            rows = dataset.get(field)
            if isinstance(rows, list):
                for row in rows:
                    record(row, "updatedAt", "updated_at", "completedAt", "completed_at")
    else:
        report_time = dataset.get("updatedAt")
        benchmarks = dataset.get("benchmarks")
        if isinstance(benchmarks, list):
            for row in benchmarks:
                record({"updatedAt": row.get("updatedAt") or report_time} if isinstance(row, Mapping) else row, "updatedAt")
        serps = dataset.get("serps")
        if isinstance(serps, list):
            for row in serps:
                record(row, "updatedAt", "checkedAt")
    # A dataset ref covers the whole returned section, so its freshness is
    # bounded by the oldest included observation, never refreshed by a newer row.
    observed_at = min(timestamps).isoformat(timespec="seconds") if timestamps else None
    freshness_key = "inventory" if section == "health" else "dataforseo"
    freshness_hours = _freshness_hours(config, freshness_key)
    clock_skew = datetime.timedelta(minutes=5)
    if timestamps and any(timestamp > now.astimezone(datetime.timezone.utc) + clock_skew for timestamp in timestamps):
        state = "uncertain"
        reason = "At least one saved dataset observation is dated in the future beyond the allowed clock skew."
    elif has_errors:
        state = "partial" if has_observation and timestamps else "failed"
        reason = "The dataset has collection errors; only its successful saved portions are retained." if state == "partial" else "The dataset collection failed."
    elif not has_observation:
        state = "missing"
        reason = "No saved observation is available for this dataset."
    elif not timestamps or missing_timestamp:
        state = "uncertain" if not timestamps else "partial"
        reason = "The saved dataset lacks a trustworthy observation time for all returned records."
    else:
        oldest = min(timestamps)
        if now.astimezone(datetime.timezone.utc) - oldest > datetime.timedelta(hours=freshness_hours):
            state = "stale"
            reason = f"At least one saved dataset observation is older than {freshness_hours} hours."
        else:
            state = "ready"
            reason = "All saved dataset observations are within the freshness window."
    return {"id": source_id, "provider": "crawlseo", "capability": f"growth.{section}.read",
        "configured": dataset.get("collectionState") != "missing", "state": state, "reason": reason, "observedAt": observed_at,
        "freshnessHours": freshness_hours, "sourceRef": source_ref}


def _run_monthly_research(context: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """Advance the one paid monthly research request through its existing lane.

    ``brain.seo`` owns the provider brief, reservation, idempotency key, result
    reconciliation and report/initiative lineage. The Growth run owns the
    schedule and exposes provider state to the unified owner task list. This
    wrapper never creates a second research request or infers success from a
    saved snapshot.
    """
    if producer_frozen(context.get("memory")):
        raise RuntimeError("Local research and recommendation producers are frozen for CrawlSEO migration")
    if _crawlseo_authoritative(context.get("config") or {}):
        raise RuntimeError("Local monthly research is disabled while CrawlSEO is the research authority")
    from ..brain import seo as brain_seo

    service = context.get("crawlseo_service")
    if service is None:
        raise RuntimeError("The monthly research provider is not configured for this site")
    config = context["config"]
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    research = seo.get("research") if isinstance(seo, Mapping) else None
    if not isinstance(research, Mapping) or not bool(research.get("enabled")):
        raise RuntimeError("Monthly research is not enabled in the tenant Growth policy")

    memory = context["memory"]
    period = brain_seo.previous_period(config)
    before = memory.get_seo_research_request(period, brain_seo.PACKAGE_VERSION)
    brain_seo.run(context)
    request = memory.get_seo_research_request(period, brain_seo.PACKAGE_VERSION)
    if request is None:
        raise RuntimeError("The monthly research request was not persisted")
    status = str(request.get("status") or "pending").lower()
    research_detail = {
        "period": period,
        "requestId": request.get("id"),
        "reportId": request.get("report_id"),
        "status": status,
        "idempotencyKey": request.get("idempotency_key"),
        "budgetReservationId": request.get("budget_reservation_id"),
        "requestedAt": request.get("requested_ts"),
        "completedAt": request.get("completed_ts"),
        "error": request.get("error") or None,
        "created": before is None,
    }
    detail["monthlyResearch"] = research_detail
    return research_detail


def _queue_article_research(context: dict[str, Any]) -> dict[str, Any]:
    """Start the optional reader-led article flow from the weekly Growth run."""
    if _crawlseo_authoritative(context.get("config") or {}):
        return {"state": "disabled", "reason": "CrawlSEO owns article research for this site."}
    from ..brain import article_research as brain_article_research

    config = context["config"]
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    settings = seo.get("article_research") if isinstance(seo, Mapping) else {}
    if not isinstance(settings, Mapping) or not bool(settings.get("enabled")):
        return {"state": "disabled", "reason": "Article research is not enabled for this site."}
    if context.get("llm") is None or context.get("crawlseo_service") is None:
        return {"state": "blocked", "reason": "Article research requires both Ada and the configured CrawlSEO provider."}
    from ..core.jobs import _with_persona

    _with_persona(context, brain_article_research.select_and_request, "article_research")
    ideas = context["memory"].list_article_ideas(limit=20)
    current = ideas[0] if ideas else None
    return {
        "state": str((current or {}).get("status") or "queued"),
        "ideaId": (current or {}).get("id"),
        "draftId": (current or {}).get("draft_id"),
        "error": (current or {}).get("error") or None,
    }


def _reconcile_article_research(context: dict[str, Any]) -> None:
    """Reconcile article provider work from the same durable pending tick."""
    if _crawlseo_authoritative(context.get("config") or {}):
        return
    config = context["config"]
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    settings = seo.get("article_research") if isinstance(seo, Mapping) else {}
    if not isinstance(settings, Mapping) or not bool(settings.get("enabled")):
        return
    if context.get("llm") is None or context.get("crawlseo_service") is None:
        return
    from ..core.jobs import _article_research_cycle

    _article_research_cycle(context)


def run_growth_cycle(
    context: dict[str, Any],
    *,
    trigger: str = "weekly",
    run_id: str | None = None,
    resume_payload_contract: bool = False,
    resume_growth_json: bool = False,
    resume_growth_schema: bool = False,
    resume_interrupted: bool = False,
    reclaim_lease_owner: str | None = None,
) -> dict[str, Any]:
    """Execute persisted phases, never count labels as proof of completed work."""
    from ..brain import growth as brain_growth
    from .growth_candidates import prepare_payload_candidate, queue_source_candidate

    memory, config = context["memory"], context["config"]
    if trigger != "crawlseo_action" and producer_frozen(memory):
        raise RuntimeError("Local research and recommendation producers are frozen for CrawlSEO migration")
    if _crawlseo_authoritative(config) and trigger != "crawlseo_action":
        raise RuntimeError("Local Growth discovery is disabled while CrawlSEO is the research authority")
    policy, goal = GrowthPolicy.from_config(config), ensure_default_goal(memory)
    _invalidate_incompatible_candidates(memory, goal, policy)
    now = datetime.datetime.now(datetime.timezone.utc)
    run = memory.get_growth_run(run_id) if run_id else memory.create_growth_run(
        run_id=f"growth-{uuid.uuid4().hex}", run_key=_cycle_key(policy, int(goal["revision"]), trigger, now), trigger=trigger,
        goal_revision=int(goal["revision"]), timezone=policy.timezone, phase="collecting", status="pending",
        policy=policy.to_dict(), origin_revision=policy.origin_revision, phase_version=2)
    if run is None:
        raise ValueError("The queued growth run does not exist")
    if run["status"] in {"complete", "cancelled"}:
        return run
    recover_saved_assessment = _recoverable_saved_assessment_failure(memory, run)
    recover_payload_contract = (
        resume_payload_contract and _recoverable_payload_contract_failure(memory, run)
    )
    recover_growth_json = (
        resume_growth_json and _recoverable_growth_json_failure(memory, run)
    )
    recover_growth_schema = (
        resume_growth_schema and _recoverable_growth_schema_failure(memory, run)
    )
    recover_interrupted = resume_interrupted and run.get("status") == "running"
    recover_saved_run = (
        recover_saved_assessment or recover_payload_contract or recover_growth_json
        or recover_growth_schema or recover_interrupted
    )
    due = _parsed_timestamp(run.get("next_due_ts"))
    if due is not None and due > now and not recover_saved_run:
        return run
    lease_owner = f"growth:{uuid.uuid4().hex}"
    claimed = memory.claim_growth_run(
        run["run_id"],
        lease_owner=lease_owner,
        lease_seconds=3600,
        reclaim_lease_owner=reclaim_lease_owner,
    )
    if claimed is None:
        return memory.get_growth_run(run["run_id"]) or run
    run = claimed
    lease_owner = run["lease_owner"]
    def advance(**fields):
        return memory.update_growth_run(run["run_id"], expected_lease=lease_owner, **fields)
    detail = dict(run.get("detail") or {})
    if recover_saved_run:
        recovery_events = detail.get("recoveryEvents")
        recovery_events = list(recovery_events) if isinstance(recovery_events, list) else []
        previous_error = detail.pop("error", "")
        if recover_growth_json:
            previous_error = _EMPTY_GROWTH_JSON_COMPLETION
            recovery_code = "growth_json_no_reasoning_retry"
        elif recover_growth_schema:
            previous_error = _GROWTH_SCHEMA_MISMATCH
            recovery_code = "growth_schema_candidate_retry"
        elif recover_payload_contract:
            previous_error = _PAYLOAD_GROWTH_CONTRACT_ROUTE_404
            recovery_code = "payload_growth_contract_route_restored"
        elif recover_interrupted:
            previous_error = "The shared API restarted while Ada was preparing an assessed recommendation."
            recovery_code = _GROWTH_RESTART_RECOVERY
        elif previous_error == "invalid strategy initiative transition deferred -> blocked":
            recovery_code = "initiative_state_transition_conflict_replayed"
        else:
            recovery_code = (
                "evidence_binding_fixed"
                if previous_error == "Ada referenced evidence that is not in this run"
                else "owner_action_summary_contract_fixed"
            )
        recovery_events.append({
            "code": recovery_code,
            "resumedAt": now.isoformat(timespec="seconds"),
            "previousError": previous_error,
        })
        detail["recoveryEvents"] = recovery_events[-5:]
        run = advance(detail=detail, next_due_ts=None)
    try:
        if "material" not in detail:
            detail["material"] = _collect_cycle_evidence(context, trigger, str(run["run_id"]))
            if detail["material"].get("assessmentContractVersion"):
                detail["assessmentContractVersion"] = detail["material"]["assessmentContractVersion"]
            # Collection can be expensive. Persist its exact result before the
            # evidence artifact boundary so a failure there resumes from here.
            run = advance(phase="collecting", detail=detail, next_due_ts=None)
        if not detail.get("evidenceArtifactId"):
            artifact_id, evidence_hash, _ = _persist_evidence_artifact(memory, run=run, goal=goal, policy=policy, sources=detail["material"]["sources"], material=detail["material"])
            detail.update(evidenceArtifactId=artifact_id, evidenceHash=evidence_hash, policy=policy.to_dict())
            run = advance(phase="assessing", detail=detail, next_due_ts=None)
        material = detail["material"]
        if material.get("ownerResponses"):
            from .growth_owner_response import consume_owner_responses
            consume_owner_responses(memory, str(run["run_id"]), material["ownerResponses"])
        if trigger == "daily":
            return advance(phase="complete", status="complete", detail=detail, completed=True)
        if material.get("authority") == "crawlseo":
            detail["remoteActions"] = material.get("actions", [])
            detail["note"] = "Recommendations and owner decisions are synchronized from CrawlSEO. HelloAda retains execution and publication controls."
            return advance(phase="complete", status="complete", detail=detail, completed=True,
                lease_owner=None, lease_until=None, next_due_ts=None)
        if trigger == "weekly" and "articleResearch" not in detail and not recover_saved_run:
            detail["articleResearch"] = _queue_article_research(context)
            run = advance(phase="assessing", detail=detail)
        if trigger == "monthly":
            research_detail = _run_monthly_research(context, detail)
            status = str(research_detail.get("status") or "pending")
            if status in {"completed", "partial"}:
                detail["note"] = "Monthly research was reconciled through the bounded provider contract; its report and owner work remain in the unified Growth list."
                return advance(phase="complete", status="complete", detail=detail, completed=True,
                    lease_owner=None, lease_until=None, next_due_ts=None)
            if status == "uncertain":
                detail["error"] = "The provider did not conclusively reconcile the paid monthly operation. No duplicate dispatch is allowed."
                return advance(status="uncertain", phase="collecting", detail=detail, lease_owner=None, lease_until=None,
                    next_due_ts=None)
            if status in {"blocked", "failed"}:
                detail["error"] = str(research_detail.get("error") or f"Monthly research is {status}.")
                retry = None if status == "blocked" else (now + datetime.timedelta(days=1)).isoformat(timespec="seconds")
                return advance(status="blocked" if status == "blocked" else "failed", phase="collecting", detail=detail,
                    lease_owner=None, lease_until=None, next_due_ts=retry)
            # Requested, budget_reserved and waiting are durable provider work,
            # not a completed report. Re-enter this same run later to poll it.
            detail["nextAction"] = "Ada will reconcile the provider report before preparing recommendations."
            return advance(status="pending", phase="collecting", detail=detail, lease_owner=None, lease_until=None,
                next_due_ts=(now + datetime.timedelta(hours=6)).isoformat(timespec="seconds"))
        if "assessment" not in detail:
            service = context.get("customer_context_service")
            business = service.task_view("research") if service is not None and service.current() is not None else {
                "audience": (config.get("persona") or {}).get("audience"),
                "research": {key: ((config.get("seo") or {}).get("research") or {}).get(key) for key in ("languages", "priority_services", "anchor_topics")}}
            detail["assessment"] = brain_growth.assess(context, {**material, "goal": goal, "business": business,
                "maxRecommendations": policy.max_recommendations, "priorWork": memory.list_strategy_initiatives(limit=100),
                "priorOutcomes": memory.list_strategy_outcomes(limit=20), "allowance": policy.research_allowance_micros})
            detail["assessmentCompletedAt"] = utc_now()
            run = advance(phase="preparing", detail=detail)
        cycle = memory.growth_strategy_cycle(run["run_id"], detail["evidenceArtifactId"])
        existing = memory.list_strategy_initiatives(cycle["id"])
        by_title = {row["title"]: row for row in existing}
        valid_refs = (
            {row["sourceRef"] for row in material["inventory"]}
            | {str(row["id"]) for row in material["sources"] if row.get("id")}
            | {row.get("sourceRef") for row in material["sources"] if row.get("sourceRef")}
        )
        ready_sources = _ready_source_refs(material["sources"])
        candidate_ids, blocks, unprepared_opportunities = [], [], []
        queued_initiative_ids: list[int] = []
        waiting_for_capacity: list[str] = []
        all_initiatives = memory.list_strategy_initiatives(limit=500)
        active = [row for row in all_initiatives if row.get("kind") != "owner_information" and row["state"] in {"preparing", "validating", "ready_for_review", "publishing", "verifying_live"} and row.get("growth_run_id") != run["run_id"]]
        active_targets = {
            (str(opportunity.get("collection") or ""), str(opportunity.get("documentId") or "")): row
            for row in active
            if row.get("kind") == "payload_content"
            for opportunity in [((row.get("expected") or {}).get("opportunity") or {})]
            if opportunity.get("collection") and opportunity.get("documentId")
        }
        pending_owner_initiative = next((
            row for row in all_initiatives
            if row.get("kind") == "owner_information"
            and row.get("state") == "waiting_for_owner"
            and row.get("owner_action_id") is not None
            and (action := memory.get_owner_action(int(row["owner_action_id"]))) is not None
            and action.state.value not in {"completed", "dismissed", "stale"}
        ), None)
        for opportunity in detail["assessment"]["opportunities"]:
            if opportunity.get("disposition") == "deferred":
                unprepared_opportunities.append(dict(opportunity))
                continue
            evidence_refs = opportunity.get("evidence")
            missing_refs = sorted({str(ref) for ref in evidence_refs if not isinstance(ref, str) or ref not in valid_refs}) if isinstance(evidence_refs, list) else ["invalid evidence list"]
            if missing_refs:
                unprepared_opportunities.append({
                    **opportunity,
                    "disposition": "deferred",
                    "errorCode": "evidence_not_bound_to_run",
                    "preparationNote": "Ada's evidence references could not be matched to this assessment, so this finding was retained but not prepared. Valid recommendations from the same assessment continue independently.",
                    "reassessWhen": "After the next successful scheduled assessment, once the required evidence is available.",
                })
                continue
            if opportunity["kind"] not in {"payload_content", "code", "owner_information"}:
                missing = set(opportunity["requiredSources"]) - ready_sources
                unprepared_opportunities.append({
                    **opportunity,
                    "disposition": "deferred",
                    "preparationNote": (
                        "This finding is retained for Ada's internal reassessment because this scheduled workflow cannot prepare its requested effect. It is not an owner task or an approval. Reassess it when the relevant shared execution route becomes available."
                        + (f" Required evidence is also not ready: {', '.join(sorted(missing))}." if missing else "")
                    ),
                    "reassessWhen": "When the shared execution route for this effect becomes available.",
                })
                continue
            target = (str(opportunity.get("collection") or ""), str(opportunity.get("documentId") or ""))
            if opportunity["kind"] == "payload_content" and target in active_targets:
                related = active_targets[target]
                unprepared_opportunities.append({
                    **opportunity,
                    "disposition": "deferred",
                    "relatedInitiativeId": related["id"],
                    "preparationNote": "Ada already has a proposal for this page in progress or awaiting your decision. This finding is retained and will be reconsidered after that decision, so the two changes cannot overwrite each other.",
                    "reassessWhen": "After the current proposal for this page is decided.",
                })
                continue
            initiative = by_title.get(opportunity["title"])
            if opportunity["kind"] == "owner_information" and pending_owner_initiative is not None:
                reason = "Ada already has an unanswered business question. This finding is deferred until the owner replies, so the system does not leave a duplicate task stuck in preparation."
                _defer_duplicate_owner_information(memory, initiative, int(pending_owner_initiative["id"]))
                unprepared_opportunities.append({
                    **opportunity,
                    "disposition": "deferred",
                    **({"relatedInitiativeId": int(pending_owner_initiative["id"])} if pending_owner_initiative else {}),
                    "preparationNote": reason,
                    "reassessWhen": "After you answer Ada’s current business question.",
                })
                continue
            if initiative is not None and initiative["state"] in {
                "deferred", "rejected", "reviewed", "superseded", "completed", "cancelled",
            }:
                if initiative["state"] == "deferred" and not any(
                    item.get("kind") == opportunity.get("kind")
                    and item.get("title") == opportunity.get("title")
                    for item in unprepared_opportunities
                ):
                    validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
                    unprepared = {
                        **opportunity,
                        "disposition": "deferred",
                        "relatedInitiativeId": initiative["id"],
                        "preparationNote": str(
                            validation.get("reason")
                            or initiative.get("last_error")
                            or "This finding was deferred earlier in the same assessment and was not retried."
                        ),
                    }
                    if validation.get("reassessWhen"):
                        unprepared["reassessWhen"] = str(validation["reassessWhen"])
                    unprepared_opportunities.append(unprepared)
                continue
            if initiative is not None and initiative["state"] == "ready_for_review":
                candidate_ids.append(initiative["id"])
                continue
            if initiative is not None and opportunity["kind"] == "code":
                preparation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
                preparation = preparation.get("preparation") if isinstance(preparation.get("preparation"), Mapping) else {}
                existing_job = memory.get_chat_job(int(preparation["jobId"])) if preparation.get("kind") == "source_code" and preparation.get("jobId") else None
                if existing_job is not None and existing_job.get("status") in {"queued", "running", "done"}:
                    queued_initiative_ids.append(int(initiative["id"]))
                    continue
            # Capacity is a dependency, not an unsuccessful external effect.
            # Keep this assessment pending on the existing hourly invocation;
            # do not manufacture a blocked/preparing initiative with no job.
            if opportunity["kind"] != "owner_information" and (
                len(active) + len(candidate_ids) + len(queued_initiative_ids)
                >= policy.max_active_candidates
            ):
                waiting_for_capacity.append(str(opportunity["title"]))
                continue
            if initiative is None:
                initiative_id = memory.create_strategy_initiative(cycle["id"], kind=opportunity["kind"], title=opportunity["title"],
                    summary=opportunity["scope"], hypothesis=str(opportunity.get("hypothesis") or ""), rationale=opportunity["why"], evidence=opportunity["evidence"],
                    expected={"opportunity": opportunity}, state="preparing", growth_run_id=run["run_id"], goal_revision=int(goal["revision"]), origin_revision=policy.origin_revision)
                initiative = memory.update_strategy_initiative(initiative_id)
            missing = set(opportunity["requiredSources"]) - ready_sources
            if missing:
                reason = "Required evidence is not ready: " + ", ".join(sorted(missing))
                reassess_when = "After a later assessment captures the required sources in a ready state."
                memory.transition_strategy_initiative(
                    int(initiative["id"]), "deferred",
                    validation={"status": "deferred", "errorCode": "required_source_not_ready",
                        "reason": reason, "reassessWhen": reassess_when},
                    last_error=reason,
                )
                unprepared_opportunities.append({**opportunity, "disposition": "deferred",
                    "errorCode": "required_source_not_ready", "preparationNote": reason,
                    "reassessWhen": reassess_when})
                continue
            elif opportunity["kind"] == "owner_information":
                from .actions import OwnerActionService
                from .growth_delivery import journal
                from ..core.contracts import ActionPriority, ActionRequirement, OwnerAction
                journal(context).issue(initiative)
                action = OwnerActionService(memory).create(OwnerAction(
                    capability_id="growth.owner_information", provider_id="site-agent", title=opportunity["title"],
                    summary=owner_action_summary(opportunity["scope"]), action_label="Answer Ada", priority=ActionPriority.NORMAL,
                    requirement=ActionRequirement.OWNER_INFORMATION, source_ref=f"growth-initiative:{initiative['id']}",
                    dedupe_key=f"growth-initiative:{initiative['id']}"))
                memory.update_strategy_initiative(initiative["id"], owner_action_id=action.id)
                if initiative["state"] == "blocked":
                    memory.transition_strategy_initiative(initiative["id"], "preparing")
                memory.transition_strategy_initiative(initiative["id"], "waiting_for_owner")
                pending_owner_initiative = memory.update_strategy_initiative(int(initiative["id"]))
                continue
            elif opportunity["kind"] == "payload_content":
                active_targets[target] = initiative
                try:
                    if initiative["state"] == "blocked":
                        initiative = memory.transition_strategy_initiative(initiative["id"], "preparing")
                    candidate = prepare_payload_candidate(context, initiative, opportunity, material["inventory"], detail)
                    candidate_ids.append(candidate["id"])
                    continue
                except brain_growth.UnsupportedGrowthPreparation as exc:
                    reason = exc.reason
                    memory.transition_strategy_initiative(
                        initiative["id"], "deferred",
                        validation={"status": "deferred", "reason": reason, "reassessWhen": exc.reassess_when},
                    )
                    unprepared_opportunities.append({
                        **opportunity,
                        "disposition": "deferred",
                        "errorCode": exc.code,
                        "preparationNote": reason,
                        "reassessWhen": exc.reassess_when,
                    })
                    continue
                except Exception as exc:
                    reason = str(exc)[:500]
            elif opportunity["kind"] == "code":
                active_code = next((row for row in active if row.get("kind") == "code"), None)
                if queued_initiative_ids or active_code:
                    related_id = active_code.get("id") if active_code else queued_initiative_ids[0]
                    memory.transition_strategy_initiative(
                        int(initiative["id"]), "deferred",
                        validation={
                            "status": "deferred",
                            "reason": "Ada is already preparing another website improvement. This finding will be reassessed after that decision.",
                            "relatedInitiativeId": related_id,
                            "reassessWhen": "After the current website improvement is decided.",
                        },
                    )
                    continue
                try:
                    if initiative["state"] == "blocked":
                        initiative = memory.transition_strategy_initiative(initiative["id"], "preparing")
                    job_id = queue_source_candidate(context, initiative, opportunity, detail)
                    if job_id is not None:
                        queued_initiative_ids.append(int(initiative["id"]))
                    continue
                except Exception as exc:
                    reason = str(exc)[:500]
            _record_preparation_failure(
                memory,
                int(initiative["id"]),
                opportunity,
                reason,
                candidate_ids=candidate_ids,
                blocks=blocks,
                unprepared_opportunities=unprepared_opportunities,
            )
        detail.update(candidateIds=candidate_ids, blocks=blocks)
        if queued_initiative_ids:
            detail["queuedInitiativeIds"] = queued_initiative_ids
        else:
            detail.pop("queuedInitiativeIds", None)
        if waiting_for_capacity:
            detail["waitingForCapacity"] = waiting_for_capacity
        else:
            detail.pop("waitingForCapacity", None)
        if unprepared_opportunities:
            detail["assessment"]["unpreparedOpportunities"] = unprepared_opportunities
        else:
            detail["assessment"].pop("unpreparedOpportunities", None)
        pending = bool(waiting_for_capacity)
        status = "blocked" if blocks else "pending" if pending else "complete"
        memory.update_strategy_cycle(cycle["id"], summary=detail["assessment"]["summary"], status="blocked" if blocks else "pending" if pending else "completed")
        retry_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1 if pending else 24)).isoformat(timespec="seconds") if blocks or pending else None
        return advance(phase="preparing" if blocks or pending else "complete", status=status, detail=detail, completed=not (blocks or pending),
            lease_owner=None, lease_until=None, next_due_ts=retry_at)
    except Exception as exc:
        detail["error"] = str(exc)[:700]
        retry_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=min(24, 2 ** min(int(run["attempt"]), 4)))).isoformat(timespec="seconds")
        from ..core.contracts import ContractError
        try:
            return advance(status="failed", detail=detail, lease_owner=None, lease_until=None, next_due_ts=retry_at)
        except ContractError:
            # A superseded executor must not overwrite the new owner's state.
            return memory.get_growth_run(run["run_id"])


_HISTORICAL_NOOP_ERROR = "Ada proposed no actual change"
_HISTORICAL_NOOP_EXPLANATION = "No page change was needed. Ada created no draft, so there is nothing to approve."


def _is_recoverable_historical_noop(initiative: Mapping[str, Any]) -> bool:
    if (
        str(initiative.get("state") or "") != "blocked"
        or str(initiative.get("kind") or "") != "payload_content"
        or str(initiative.get("last_error") or "") != _HISTORICAL_NOOP_ERROR
    ):
        return False
    side_effect_fields = (
        "owner_action_id", "draft_id", "artifact_id", "approval_id", "receipt_id",
        "candidate_hash", "review_package_hash", "published_revision",
    )
    if any(initiative.get(field) for field in side_effect_fields):
        return False
    validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
    return not any(validation.get(field) for field in ("candidateHash", "reviewPackageHash"))


def has_recoverable_historical_noop(memory: Memory) -> bool:
    return any(
        _is_recoverable_historical_noop(row)
        for row in memory.list_strategy_initiatives(limit=None)
    )


def reconcile_historical_noop_initiatives(memory: Memory) -> int:
    """Move exact persisted no-op failures out of the technical-blocker queue."""
    reconciled = 0
    for initiative in memory.list_strategy_initiatives(limit=None):
        if not _is_recoverable_historical_noop(initiative):
            continue
        validation = dict(initiative.get("validation") or {})
        validation.update({
            "status": "deferred",
            "errorCode": "no_actionable_change",
            "reason": _HISTORICAL_NOOP_EXPLANATION,
            "recovery": "historical_noop_reconciliation",
        })
        memory.transition_strategy_initiative(
            int(initiative["id"]),
            "deferred",
            expected_state="blocked",
            validation=validation,
            last_error=_HISTORICAL_NOOP_EXPLANATION,
        )
        reconciled += 1
    return reconciled


def run_pending_growth(context: dict[str, Any], *, recover_interrupted_runs: bool = False) -> None:
    memory = context["memory"]
    crawlseo_authoritative = _crawlseo_authoritative(context.get("config") or {})
    frozen = producer_frozen(memory)
    if crawlseo_authoritative:
        require_connector_dispatch_enabled(memory)
        try:
            # The hourly canonical Growth worker also drains connector events
            # and replays durable execution reports after transient failures.
            _sync_crawlseo_actions(context)
            memory.kv_set("crawlseo_connector_sync_error", {})
        except Exception as exc:  # noqa: BLE001 - leave durable connector work for the next tick
            memory.kv_set("crawlseo_connector_sync_error", {
                "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "error": str(exc)[:500],
            })
    else:
        if frozen:
            # Keep recording-only and exact-receipt reconciliation alive, but
            # do not enqueue or replay local discovery/preparation work.
            from .growth_candidates import reconcile_payload_growth_revisions
            from .growth_delivery import reconcile_delivery

            reconcile_delivery(context)
            reconcile_payload_growth_revisions(context)
            return
        from .growth_candidates import reconcile_payload_growth_revisions, reconcile_source_candidates
        from .growth_delivery import reconcile_delivery

        # Recording is independently resumable; the receipt remains execution truth.
        # The local execution journal remains active only for local research authority.
        reconcile_delivery(context)
        reconcile_payload_growth_revisions(context)
        reconcile_source_candidates(context)
        reconcile_historical_noop_initiatives(memory)
        _reconcile_orphan_owner_questions(memory)
    due_runs = memory.due_growth_runs(limit=20)
    historical_runs = memory.list_growth_runs(limit=None)
    if crawlseo_authoritative:
        # The old local discovery ledger is history after cutover. Only
        # CrawlSEO Action runs may resume; never replay a legacy assessment,
        # topic-selection or paid research phase from a saved local run.
        legacy_runs = [run for run in historical_runs if run.get("trigger") != "crawlseo_action"]
        legacy_initiatives: dict[str, list[Mapping[str, Any]]] = {}
        for initiative in memory.list_strategy_initiatives(limit=None):
            run_id = str(initiative.get("growth_run_id") or "")
            if run_id:
                legacy_initiatives.setdefault(run_id, []).append(initiative)
        for run in legacy_runs:
            if run.get("status") not in {"complete", "cancelled", "blocked"}:
                detail = run.get("detail") if isinstance(run.get("detail"), Mapping) else {}
                linked_initiatives = legacy_initiatives.get(str(run.get("run_id") or ""), [])
                exact_work_exists = bool(detail.get("candidateIds") or detail.get("queuedInitiativeIds")) or any(
                    row.get("state") in {"preparing", "validating", "ready_for_review", "publishing", "verifying_live", "published", "verified"}
                    or any(row.get(key) is not None for key in (
                        "owner_action_id", "artifact_id", "approval_id", "draft_id", "receipt_id",
                        "candidate_hash", "review_package_hash",
                    ))
                    or bool((row.get("validation") if isinstance(row.get("validation"), Mapping) else {}).get("preparation"))
                    for row in linked_initiatives
                )
                if exact_work_exists:
                    # Existing exact candidates, owner decisions and receipts
                    # remain on their guarded execution/reconciliation path.
                    continue
                detail = dict(run.get("detail") or {}) if isinstance(run.get("detail"), Mapping) else {}
                events = detail.get("recoveryEvents") if isinstance(detail.get("recoveryEvents"), list) else []
                if not any(isinstance(event, Mapping) and event.get("code") == "legacy_discovery_quarantined_at_cutover" for event in events):
                    events.append({
                        "code": "legacy_discovery_quarantined_at_cutover",
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                        "reason": "CrawlSEO owns research after cutover; this local discovery/research run is retained as history and will not be replayed.",
                    })
                    detail["recoveryEvents"] = events[-20:]
                    memory.update_growth_run(
                        str(run.get("run_id") or ""), completed=True, status="blocked", phase=str(run.get("phase") or "collecting"),
                        detail=detail, lease_owner=None, lease_until=None, next_due_ts=None,
                    )
        # Keep only current CrawlSEO Action work in this executor's recovery set.
        due_runs = [run for run in due_runs if run.get("trigger") == "crawlseo_action"]
        historical_runs = [run for run in historical_runs if run.get("trigger") == "crawlseo_action"]
    due_by_id = {
        str(run.get("run_id")): run
        for run in due_runs
        if run.get("run_id")
    }
    runs = historical_runs
    interrupted_run_ids: set[str] = set()
    reclaim_lease_owners: dict[str, str] = {}
    if recover_interrupted_runs:
        # This path is called only by the tenant scheduler while it holds the
        # exclusive scheduler.lock. A running lease therefore belongs to a
        # process that exited before its durable phase checkpoint.
        for run in runs:
            if run.get("status") != "running":
                continue
            run_id = str(run.get("run_id") or "")
            if not run_id:
                continue
            if _safe_interrupted_growth_preparation(memory, run) and not _growth_restart_recovery_used(run):
                due_by_id[run_id] = run
                interrupted_run_ids.add(run_id)
                if run.get("lease_owner"):
                    reclaim_lease_owners[run_id] = str(run["lease_owner"])
                continue
            reason = (
                "Ada's one bounded restart recovery was already interrupted before a durable candidate checkpoint. "
                "The run was stopped to avoid repeating paid work."
                if _growth_restart_recovery_used(run)
                else "This run was interrupted in a phase that cannot be replayed without risking duplicate side effects. "
                "It was stopped for investigation."
            )
            _block_interrupted_growth_run(memory, run, reason=reason)
            due_by_id.pop(run_id, None)
    due = list(due_by_id.values())
    due_ids = {str(row.get("run_id")) for row in due}
    recoverable_assessments = [
        run for run in runs
        if str(run.get("run_id")) not in due_ids and _recoverable_saved_assessment_failure(memory, run)
    ]
    recoverable_contracts = [
        run for run in runs
        if str(run.get("run_id")) not in due_ids and _recoverable_payload_contract_failure(memory, run)
    ]
    recoverable_growth_json = [
        run for run in runs
        if str(run.get("run_id")) not in due_ids and _recoverable_growth_json_failure(memory, run)
    ]
    recoverable_growth_schema = [
        run for run in runs
        if str(run.get("run_id")) not in due_ids and _recoverable_growth_schema_failure(memory, run)
    ]
    for run in [*due, *recoverable_assessments]:
        run_id = str(run["run_id"])
        run_growth_cycle(
            context,
            trigger=run["trigger"],
            run_id=run_id,
            resume_interrupted=run_id in interrupted_run_ids,
            reclaim_lease_owner=reclaim_lease_owners.get(run_id),
        )
    if recoverable_contracts:
        # Prove the canonical preparation contract is available once before
        # replaying any saved candidates. A failing gateway leaves the durable
        # blocked run untouched and lets the scheduler record the failure.
        context["payload_gateway"].require_growth_contract()
        for run in recoverable_contracts:
            run_growth_cycle(
                context,
                trigger=run["trigger"],
                run_id=run["run_id"],
                resume_payload_contract=True,
            )
    if recoverable_growth_json:
        # The previous exact candidate passed this canonical contract gate
        # before truncation; re-check it before spending one bounded retry.
        context["payload_gateway"].require_growth_contract()
        for run in recoverable_growth_json:
            run_growth_cycle(
                context,
                trigger=run["trigger"],
                run_id=run["run_id"],
                resume_growth_json=True,
            )
    if recoverable_growth_schema:
        context["payload_gateway"].require_growth_contract()
        for run in recoverable_growth_schema:
            run_growth_cycle(
                context,
                trigger=run["trigger"],
                run_id=run["run_id"],
                resume_growth_schema=True,
            )
    # Recovery must not pull forward unrelated article research (which may
    # dispatch paid provider calls) when there is saved work to resume.
    if not crawlseo_authoritative and not interrupted_run_ids and (
        due or not (recoverable_assessments or recoverable_contracts or recoverable_growth_json or recoverable_growth_schema)
    ):
        _reconcile_article_research(context)


__all__ = ["ensure_default_goal", "has_recoverable_historical_noop", "queue_growth_check", "reconcile_historical_noop_initiatives", "run_growth_cycle", "run_growth_reconciler", "run_pending_growth"]
