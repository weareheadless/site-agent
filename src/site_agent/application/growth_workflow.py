"""The durable, provider-neutral first stage of Ada's growth workflow."""

from __future__ import annotations

import datetime
import os
import uuid
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..core.growth_contracts import GrowthGoalRevision, GrowthPolicy
from ..core.memory import Memory


def ensure_default_goal(memory: Memory) -> dict[str, Any]:
    """Create the new-site goal once, at a provisioning/scheduler boundary."""

    existing = memory.latest_growth_goal()
    if existing is not None:
        return existing
    return memory.create_growth_goal(GrowthGoalRevision.default().to_dict())


def _run_key(policy: GrowthPolicy, now: datetime.datetime) -> str:
    local_date = now.astimezone(ZoneInfo(policy.timezone)).date().isoformat()
    return f"growth-reconcile:{local_date}"


def _source_state(memory: Memory, config: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Summarise persisted source state without initiating collection."""

    state = memory.kv_get("seo_provisioning_state", {}) or {}
    ga4 = memory.latest_snapshot("ga4")
    gsc = memory.latest_snapshot("gsc")
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    ga = config.get("ga") if isinstance(config.get("ga"), Mapping) else {}
    ga_property = state.get("ga4_property_id") or ga.get("property_id")
    gsc_property = state.get("gsc_property") or seo.get("site_url")
    return [
        {
            "id": "ga4",
            "configured": bool(ga_property),
            "property": ga_property,
            "data": "available" if ga4 else "missing",
            "updatedAt": (ga4 or {}).get("ts"),
        },
        {
            "id": "gsc",
            "configured": bool(gsc_property),
            "property": gsc_property,
            "verification": "required" if state.get("gsc_pending") else "unknown",
            "data": "available" if gsc else "missing",
            "updatedAt": (gsc or {}).get("ts"),
        },
        {
            "id": "dataforseo",
            "configured": context.get("crawlseo_service") is not None,
            "data": "available" if memory.list_seo_seeds(limit=1) else "missing",
            "updatedAt": state.get("provisioned_at"),
        },
    ]


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
    key = _run_key(policy, now)
    existing = memory.get_growth_run_by_key(key)
    if existing and existing.get("status") == "complete":
        return existing
    run = existing or memory.create_growth_run(
        run_id=f"growth-{uuid.uuid4().hex}",
        run_key=key,
        trigger="scheduled_reconciliation",
        goal_revision=int(goal["revision"]),
        timezone=policy.timezone,
        phase="collecting",
        status="pending",
        detail={"steps": [{"id": "goal", "status": "complete"}]},
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
        detail = {
            "steps": [
                {"id": "goal", "status": "complete", "revision": int(goal["revision"])},
                {"id": "persisted_evidence", "status": "complete", "sourceCount": len(sources)},
                {"id": "external_collection", "status": "not_started", "reason": "scheduled in the next pipeline phase"},
            ],
            "sources": sources,
            "note": "Reconciled saved evidence; no external research or publication was dispatched.",
        }
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
