"""One durable growth coordinator: collection, Ada assessment and real candidates."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..core.contracts import Artifact, ArtifactKind, utc_now
from ..core.growth_contracts import GrowthGoalRevision, GrowthPolicy
from ..core.memory import Memory


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


def _owner_action_summary(value: Any) -> str:
    """Project long evidence scope into the bounded owner-action summary field."""
    summary = " ".join(str(value or "").split())
    if len(summary) <= 500:
        return summary
    prefix = summary[:497].rsplit(" ", 1)[0].rstrip(" .,;:") or summary[:497]
    return prefix + "…"


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
    if (
        failure not in {"Ada referenced evidence that is not in this run", "summary exceeds 500 characters"}
        or not isinstance(assessment, Mapping)
        or not isinstance(assessment.get("opportunities"), list)
        or not isinstance(material, Mapping)
        or not isinstance(material.get("inventory"), list)
        or detail.get("candidateIds")
    ):
        return False
    initiatives = [
        row for row in memory.list_strategy_initiatives(limit=None)
        if str(row.get("growth_run_id") or "") == str(run.get("run_id") or "")
    ]
    if failure == "Ada referenced evidence that is not in this run":
        return not initiatives
    return bool(initiatives) and all(
        row.get("state") in {"preparing", "blocked"}
        and not any(row.get(key) is not None for key in ("owner_action_id", "artifact_id", "approval_id", "draft_id"))
        for row in initiatives
    )


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
        manifest["material"] = dict(material)
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
    else:
        period = trigger
    return f"growth-v2:{policy.origin_revision}:goal-{goal_revision}:{trigger}:{period}"


def queue_growth_check(context: Mapping[str, Any], *, trigger: str = "owner_review") -> dict[str, Any]:
    memory, config = context["memory"], context["config"]
    policy, goal = GrowthPolicy.from_config(config), ensure_default_goal(memory)
    now = datetime.datetime.now(datetime.timezone.utc)
    # Coalesce an explicit owner review for this day/goal/origin. GET never queues.
    key = _cycle_key(policy, int(goal["revision"]), trigger + ":" + now.date().isoformat(), now)
    return memory.create_growth_run(run_id=f"growth-{uuid.uuid4().hex}", run_key=key, trigger=trigger,
        goal_revision=int(goal["revision"]), timezone=policy.timezone, phase="collecting", status="pending",
        policy=policy.to_dict(), origin_revision=policy.origin_revision, phase_version=2)


def _inventory(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    from .growth_candidates import document_content

    payload = context.get("payload_gateway")
    if payload is None:
        raise RuntimeError("The canonical Payload content gateway is unavailable")
    authoring_contract = payload.require_authoring_contract()
    enabled_collections = set((authoring_contract.get("enabled") or {}).get("collections") or [])
    inventory = []
    # Taxonomy is part of the shared schema, but categories are not public pages.
    for collection in ("pages", "posts", "products"):
        if collection not in enabled_collections:
            continue
        fields = payload.authoring_fields("collection", collection, authoring_contract=authoring_contract)
        for document in payload.list(collection, draft=False, limit=100):
            if not document.get("id"):
                raise ValueError("A canonical document has no identity")
            inventory.append({"collection": collection, "document": {"id": str(document["id"]),
                "sourceId": document.get("sourceId"), "slug": document.get("slug"),
                **document_content(document, fields)},
                "sourceRef": f"payload:{collection}:{document['id']}", "route": document.get("route")})
    if not inventory:
        raise RuntimeError("The website has no canonical editable documents")
    if len(json.dumps(inventory, ensure_ascii=False).encode()) > 120_000:
        raise ValueError("Canonical content exceeds the bounded assessment size; select a smaller declared scope")
    return inventory


def _collect_cycle_evidence(context: Mapping[str, Any], trigger: str, run_id: str) -> dict[str, Any]:
    from .growth import growth_metrics
    from .growth_evidence import growth_evidence

    memory, config = context["memory"], context["config"]
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
    if service is not None:
        for section in ("health", "research", "competition"):
            try:
                value = growth_evidence(service, section)
                datasets[section] = value
                if value.get("errors"):
                    errors[section] = "; ".join(str(item) for item in value["errors"].values())[:500]
            except Exception as exc:
                errors[section] = str(exc)[:500]
    return {"sources": sources, "inventory": inventory, "metrics": growth_metrics(memory), "datasets": datasets,
            "ownerResponses": owner_responses, "collectionErrors": errors}


def _run_monthly_research(context: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """Advance the one paid monthly research request through its existing lane.

    ``brain.seo`` owns the provider brief, reservation, idempotency key, result
    reconciliation and report/initiative lineage. The Growth run owns the
    schedule and exposes provider state to the unified owner task list. This
    wrapper never creates a second research request or infers success from a
    saved snapshot.
    """
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
    from .growth_candidates import prepare_payload_candidate

    memory, config = context["memory"], context["config"]
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
            artifact_id, evidence_hash, _ = _persist_evidence_artifact(memory, run=run, goal=goal, policy=policy, sources=detail["material"]["sources"], material=detail["material"])
            detail.update(evidenceArtifactId=artifact_id, evidenceHash=evidence_hash, policy=policy.to_dict())
            run = advance(phase="assessing", detail=detail, next_due_ts=None)
        material = detail["material"]
        if material.get("ownerResponses"):
            from .growth_owner_response import consume_owner_responses
            consume_owner_responses(memory, str(run["run_id"]), material["ownerResponses"])
        if trigger == "daily":
            return advance(phase="complete", status="complete", detail=detail, completed=True)
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
            run = advance(phase="preparing", detail=detail)
        cycle = memory.growth_strategy_cycle(run["run_id"], detail["evidenceArtifactId"])
        existing = memory.list_strategy_initiatives(cycle["id"])
        by_title = {row["title"]: row for row in existing}
        valid_refs = (
            {row["sourceRef"] for row in material["inventory"]}
            | {str(row["id"]) for row in material["sources"] if row.get("id")}
            | {row.get("sourceRef") for row in material["sources"] if row.get("sourceRef")}
        )
        ready_sources = {row["id"] for row in material["sources"] if row["state"] == "ready"}
        candidate_ids, blocks, unprepared_opportunities = [], [], []
        all_initiatives = memory.list_strategy_initiatives(limit=500)
        active = [row for row in all_initiatives if row["state"] in {"preparing", "validating", "ready_for_review", "publishing", "verifying_live"} and row.get("growth_run_id") != run["run_id"]]
        active_targets = {
            (str(opportunity.get("collection") or ""), str(opportunity.get("documentId") or "")): row
            for row in active
            if row.get("kind") == "payload_content"
            for opportunity in [((row.get("expected") or {}).get("opportunity") or {})]
            if opportunity.get("collection") and opportunity.get("documentId")
        }
        pending_owner_question = any(
            row.get("kind") == "owner_information"
            and row.get("state") == "waiting_for_owner"
            and (action := memory.get_owner_action(int(row["owner_action_id"]))) is not None
            and action.state.value not in {"completed", "dismissed", "stale"}
            for row in all_initiatives
            if row.get("owner_action_id") is not None
        )
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
            if opportunity["kind"] not in {"payload_content", "owner_information"}:
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
            if opportunity["kind"] == "owner_information" and pending_owner_question:
                unprepared_opportunities.append({
                    **opportunity,
                    "disposition": "deferred",
                    "preparationNote": "Ada already has an unanswered business question. This finding is retained and will be reconsidered after your reply, rather than asking you the same kind of question twice.",
                    "reassessWhen": "After you answer Ada's current business question.",
                })
                continue
            initiative = by_title.get(opportunity["title"])
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
            if initiative is None:
                initiative_id = memory.create_strategy_initiative(cycle["id"], kind=opportunity["kind"], title=opportunity["title"],
                    summary=opportunity["scope"], hypothesis=str(opportunity.get("hypothesis") or ""), rationale=opportunity["why"], evidence=opportunity["evidence"],
                    expected={"opportunity": opportunity}, state="preparing", growth_run_id=run["run_id"], goal_revision=int(goal["revision"]), origin_revision=policy.origin_revision)
                initiative = memory.update_strategy_initiative(initiative_id)
            if initiative["state"] == "ready_for_review":
                candidate_ids.append(initiative["id"])
                continue
            missing = set(opportunity["requiredSources"]) - ready_sources
            if missing:
                reason = "Required evidence is not ready: " + ", ".join(sorted(missing))
            elif len(active) + len(candidate_ids) >= policy.max_active_candidates:
                reason = "Existing improvements are awaiting review; no additional candidate was prepared."
            elif opportunity["kind"] == "owner_information":
                from .actions import OwnerActionService
                from ..core.contracts import ActionPriority, ActionRequirement, OwnerAction
                action = OwnerActionService(memory).create(OwnerAction(
                    capability_id="growth.owner_information", provider_id="site-agent", title=opportunity["title"],
                    summary=_owner_action_summary(opportunity["scope"]), action_label="Answer Ada", priority=ActionPriority.NORMAL,
                    requirement=ActionRequirement.OWNER_INFORMATION, source_ref=f"growth-initiative:{initiative['id']}",
                    dedupe_key=f"growth-initiative:{initiative['id']}"))
                memory.update_strategy_initiative(initiative["id"], owner_action_id=action.id)
                if initiative["state"] == "blocked":
                    memory.transition_strategy_initiative(initiative["id"], "preparing")
                memory.transition_strategy_initiative(initiative["id"], "waiting_for_owner")
                pending_owner_question = True
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
            memory.transition_strategy_initiative(initiative["id"], "blocked", last_error=reason)
            blocks.append({"initiativeId": initiative["id"], "reason": reason})
        detail.update(candidateIds=candidate_ids, blocks=blocks)
        if unprepared_opportunities:
            detail["assessment"]["unpreparedOpportunities"] = unprepared_opportunities
        else:
            detail["assessment"].pop("unpreparedOpportunities", None)
        memory.update_strategy_cycle(cycle["id"], summary=detail["assessment"]["summary"], status="blocked" if blocks else "completed")
        retry_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)).isoformat(timespec="seconds") if blocks else None
        return advance(phase="preparing" if blocks else "complete", status="blocked" if blocks else "complete", detail=detail, completed=not blocks,
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
    reconcile_historical_noop_initiatives(memory)
    due_by_id = {
        str(run.get("run_id")): run
        for run in memory.due_growth_runs(limit=20)
        if run.get("run_id")
    }
    runs = memory.list_growth_runs(limit=None)
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
    if not interrupted_run_ids and (
        due or not (recoverable_assessments or recoverable_contracts or recoverable_growth_json or recoverable_growth_schema)
    ):
        _reconcile_article_research(context)


__all__ = ["ensure_default_goal", "has_recoverable_historical_noop", "queue_growth_check", "reconcile_historical_noop_initiatives", "run_growth_cycle", "run_growth_reconciler", "run_pending_growth"]
