"""The durable, provider-neutral first stage of Ada's growth workflow."""

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
        if state in {"reviewed", "rejected", "snoozed", "superseded"}:
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
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return manifest, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _persist_evidence_artifact(
    memory: Memory,
    *,
    run: Mapping[str, Any],
    goal: Mapping[str, Any],
    policy: GrowthPolicy,
    sources: list[dict[str, Any]],
) -> tuple[int, str, dict[str, Any]]:
    captured_at = utc_now()
    manifest, content_hash = _evidence_manifest(
        run=run,
        goal=goal,
        policy=policy,
        sources=sources,
        captured_at=captured_at,
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
                {"id": "external_collection", "status": "scheduled", "reason": "paid collection is dispatched by the bounded provider jobs"},
                {"id": "assessment", "status": "complete", "reason": "source states and freshness were evaluated without substituting missing data"},
                {"id": "preparation", "status": "complete", "reason": "owner candidates remain in their durable strategy records until provider evidence and Payload validation exist"},
                {"id": "validation", "status": "complete", "reason": "this reconciliation validated the evidence manifest; content/code candidates have their own gates"},
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
        for phase in ("assessing", "preparing", "validating"):
            run = memory.update_growth_run(run["run_id"], phase=phase, status="running", detail=detail)
        return memory.update_growth_run(run["run_id"], phase="complete", status="complete", detail=detail, completed=True)
    except Exception as exc:  # noqa: BLE001 - persist the exact blocked boundary
        return memory.update_growth_run(
            run["run_id"],
            phase="collecting",
            status="failed",
            detail={"error": str(exc)[:500]},
            completed=True,
        )


__all__ = ["ensure_default_goal", "run_growth_reconciler"]
