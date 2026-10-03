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
    inventory = []
    for collection in payload.contract.collections:
        for document in payload.list(collection, draft=False, limit=100):
            if not document.get("id"):
                raise ValueError("A canonical document has no identity")
            inventory.append({"collection": collection, "document": {"id": str(document["id"]),
                "sourceId": document.get("sourceId"), "slug": document.get("slug"),
                **document_content(document, payload.contract.collection_fields[collection])},
                "sourceRef": f"payload:{collection}:{document['id']}", "route": document.get("route")})
    if not inventory:
        raise RuntimeError("The website has no canonical editable documents")
    if len(json.dumps(inventory, ensure_ascii=False).encode()) > 120_000:
        raise ValueError("Canonical content exceeds the bounded assessment size; select a smaller declared scope")
    return inventory


def _collect_cycle_evidence(context: Mapping[str, Any], trigger: str) -> dict[str, Any]:
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
    return {"sources": sources, "inventory": inventory, "metrics": growth_metrics(memory), "datasets": datasets, "collectionErrors": errors}


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


def run_growth_cycle(context: dict[str, Any], *, trigger: str = "weekly", run_id: str | None = None) -> dict[str, Any]:
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
    due = _parsed_timestamp(run.get("next_due_ts"))
    if due is not None and due > now:
        return run
    claimed = memory.claim_growth_run(run["run_id"], lease_owner=f"growth:{uuid.uuid4().hex}", lease_seconds=3600)
    if claimed is None:
        return memory.get_growth_run(run["run_id"]) or run
    run = claimed
    lease_owner = run["lease_owner"]
    def advance(**fields):
        return memory.update_growth_run(run["run_id"], expected_lease=lease_owner, **fields)
    detail = dict(run.get("detail") or {})
    try:
        if "material" not in detail:
            detail["material"] = _collect_cycle_evidence(context, trigger)
            artifact_id, evidence_hash, _ = _persist_evidence_artifact(memory, run=run, goal=goal, policy=policy, sources=detail["material"]["sources"], material=detail["material"])
            detail.update(evidenceArtifactId=artifact_id, evidenceHash=evidence_hash, policy=policy.to_dict())
            run = advance(phase="assessing", detail=detail, next_due_ts=None)
        material = detail["material"]
        if trigger == "daily":
            return advance(phase="complete", status="complete", detail=detail, completed=True)
        if trigger == "weekly" and "articleResearch" not in detail:
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
        valid_refs = {row["sourceRef"] for row in material["inventory"]} | {row.get("sourceRef") for row in material["sources"] if row.get("sourceRef")}
        ready_sources = {row["id"] for row in material["sources"] if row["state"] == "ready"}
        candidate_ids, blocks = [], []
        active = [row for row in memory.list_strategy_initiatives(limit=500) if row["state"] in {"preparing", "validating", "ready_for_review", "publishing", "verifying_live"} and row.get("growth_run_id") != run["run_id"]]
        for opportunity in detail["assessment"]["opportunities"]:
            if set(opportunity["evidence"]) - valid_refs:
                raise ValueError("Ada referenced evidence that is not in this run")
            initiative = by_title.get(opportunity["title"])
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
                    summary=opportunity["scope"], action_label="Answer Ada", priority=ActionPriority.NORMAL,
                    requirement=ActionRequirement.OWNER_INFORMATION, source_ref=f"growth-initiative:{initiative['id']}",
                    dedupe_key=f"growth-initiative:{initiative['id']}"))
                memory.update_strategy_initiative(initiative["id"], owner_action_id=action.id)
                if initiative["state"] == "blocked":
                    memory.transition_strategy_initiative(initiative["id"], "preparing")
                memory.transition_strategy_initiative(initiative["id"], "waiting_for_owner")
                continue
            elif opportunity["kind"] == "payload_content":
                try:
                    if initiative["state"] == "blocked":
                        initiative = memory.transition_strategy_initiative(initiative["id"], "preparing")
                    candidate = prepare_payload_candidate(context, initiative, opportunity, material["inventory"], detail)
                    candidate_ids.append(candidate["id"])
                    continue
                except Exception as exc:
                    reason = str(exc)[:500]
            else:
                reason = f"The {opportunity['kind']} preparation boundary is not connected; no candidate was invented."
            memory.transition_strategy_initiative(initiative["id"], "blocked", last_error=reason)
            blocks.append({"initiativeId": initiative["id"], "reason": reason})
        detail.update(candidateIds=candidate_ids, blocks=blocks)
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


def run_pending_growth(context: dict[str, Any]) -> None:
    for run in context["memory"].due_growth_runs(limit=20):
        run_growth_cycle(context, trigger=run["trigger"], run_id=run["run_id"])
    _reconcile_article_research(context)


__all__ = ["ensure_default_goal", "queue_growth_check", "run_growth_cycle", "run_growth_reconciler", "run_pending_growth"]
