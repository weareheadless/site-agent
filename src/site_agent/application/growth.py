"""Read-only owner projection of existing tenant growth work. Never provisions."""
from __future__ import annotations

import datetime
from typing import Any

from ..core.contracts import ArtifactKind
from ..core.growth_contracts import GrowthPolicy
from ..core.memory import Memory
from .growth_workflow import _freshness_hours, _source_state
from .growth_tasks import growth_tasks
from .growth_service_model import service_model
from .growth_delivery import journal_reference

GROWTH_CONTRACT_VERSION = "owner-decisions-v1"
OWNER_QUEUE_CONTRACT_VERSION = "owner-queue-progression-v1"


def _has_live_lease(run: dict[str, Any] | None) -> bool:
    if not isinstance(run, dict):
        return False
    value = run.get("lease_until")
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc) > datetime.datetime.now(datetime.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return False


def owner_queue(tasks: list[dict[str, Any]], runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Project canonical Growth tasks into a small owner-facing agenda."""
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "optional": 3}
    decisions = [row for row in tasks if row.get("focus") == "needs_you"]
    decisions.sort(key=lambda row: str(row.get("updatedAt") or ""), reverse=True)
    decisions.sort(key=lambda row: priority_order.get(str(row.get("priority") or "normal"), 2))
    active = [row for row in tasks if row.get("focus") == "preparing"]
    active.sort(key=lambda row: str(row.get("updatedAt") or ""), reverse=True)
    active.sort(key=lambda row: row.get("kind") == "schedule")
    scheduled = [row for row in tasks if row.get("focus") == "planned" and row.get("nextRun")]
    scheduled.sort(key=lambda row: str(row.get("nextRun") or ""))
    attention = [row for row in tasks if row.get("focus") == "paused" and row.get("executionIssue")]
    attention.sort(key=lambda row: str(row.get("updatedAt") or ""), reverse=True)
    successful_states = {"completed", "measuring", "reviewed", "published", "analysis_completed", "live"}
    recent = [
        row for row in tasks
        if row.get("focus") == "completed"
        and row.get("state") in successful_states
        and not row.get("executionIssue")
        and row.get("kind") not in {"article_research", "schedule", "measurement"}
        and (row.get("kind") != "article" or row.get("state") == "published")
    ]
    recent.sort(key=lambda row: str(row.get("updatedAt") or ""), reverse=True)
    analysis_runs = [
        row for row in (runs or [])
        if row.get("trigger") in {"initial", "weekly", "owner_review"}
    ]
    analysis_runs.sort(key=lambda row: str(row.get("updated_ts") or ""), reverse=True)
    latest_assessment = analysis_runs[0] if analysis_runs else None
    assessment_detail = latest_assessment.get("detail") if isinstance(latest_assessment, dict) and isinstance(latest_assessment.get("detail"), dict) else {}
    assessment = assessment_detail.get("assessment") if isinstance(assessment_detail.get("assessment"), dict) else {}
    deferred = assessment.get("unpreparedOpportunities")
    # Historical assessments may contain the former pseudo-routes (`article`
    # and `code`). They were never prepared or owner-actionable. A titled
    # untyped finding is still real deferred work and remains visible.
    deferred_count = sum(
        1 for row in deferred
        if isinstance(row, dict)
        and row.get("kind") not in {"article", "code"}
        and (
            row.get("kind") in {"payload_content", "owner_information"}
            or row.get("kind") is None and bool(str(row.get("title") or "").strip())
        )
    ) if isinstance(deferred, list) else 0
    deferred_finding = next((
        row for row in deferred or []
        if isinstance(row, dict)
        and row.get("kind") not in {"article", "code"}
        and str(row.get("title") or "").strip()
    ), None)
    next_assessment = next((
        row for row in scheduled
        if row.get("id") == "schedule:growth_weekly"
    ), None)
    assessment_status = str(latest_assessment.get("status") or "") if latest_assessment else ""
    active_non_schedule = next((row for row in active if row.get("kind") != "schedule"), None)
    if decisions:
        progression_state = "ready_for_review"
    elif attention:
        progression_state = "service_issue"
    elif active_non_schedule:
        progression_state = "preparing"
    elif assessment_status == "pending" or assessment_status == "running" and _has_live_lease(latest_assessment):
        progression_state = "assessing"
    elif assessment_status in {"running", "failed", "blocked", "uncertain"}:
        progression_state = "service_issue"
    elif assessment_status == "complete" and deferred_count:
        progression_state = "deferred_findings"
    elif scheduled:
        progression_state = "scheduled"
    elif assessment_status == "complete":
        progression_state = "assessed"
    else:
        progression_state = "not_started"
    primary_task = None
    if decisions:
        primary_task = decisions[0]
    elif attention:
        primary_task = attention[0]
    elif active_non_schedule:
        primary_task = active_non_schedule
    elif scheduled and progression_state not in {"deferred_findings", "assessed"}:
        primary_task = scheduled[0]
    return {
        "featuredDecisionId": decisions[0].get("id") if decisions else None,
        "additionalDecisionIds": [row.get("id") for row in decisions[1:4]],
        "decisionCount": len(decisions),
        "activeTaskId": active[0].get("id") if active else None,
        "nextScheduledId": scheduled[0].get("id") if scheduled else None,
        "recentResultId": recent[0].get("id") if recent else None,
        "recentResultIds": [row.get("id") for row in recent[:5]],
        "attentionTaskId": attention[0].get("id") if attention else None,
        "progression": {
            "state": progression_state,
            "primaryTaskId": primary_task.get("id") if primary_task else None,
            "serviceIssueTaskId": attention[0].get("id") if attention else None,
            "latestAssessmentAt": (latest_assessment or {}).get("updated_ts"),
            "latestAssessmentStatus": assessment_status or None,
            "latestAssessmentSummary": str(assessment.get("summary") or "")[:240] or None,
            "deferredFindingCount": deferred_count,
            "deferredFindingTitle": str((deferred_finding or {}).get("title") or "")[:180] or None,
            "deferredFindingSummary": str((deferred_finding or {}).get("preparationNote") or "")[:400] or None,
            "deferredReassessWhen": str((deferred_finding or {}).get("reassessWhen") or "")[:300] or None,
            "nextAssessmentAt": (next_assessment or {}).get("nextRun"),
        },
    }




def growth_snapshot(memory: Memory, config: dict[str, Any], context: dict[str, Any], *, include_article_content: bool = False) -> dict[str, Any]:
    state = context.get("seo_provisioning_state") or memory.kv_get("seo_provisioning_state", {}) or {}
    scheduler = context.get("scheduler")
    # Scheduler specs contain a datetime.time; expose its ISO value at the
    # application boundary, not the scheduler's internal Python object.
    jobs = {
        name: {key: value.isoformat() if isinstance(value, datetime.time) else value
               for key, value in spec.items()}
        for name, spec, _fn in getattr(scheduler, "jobs", [])
    }
    runs = memory.list_growth_runs(limit=None)
    activities = []
    for name in ("growth_initial", "growth_daily", "growth_weekly", "growth_monthly", "seo_outcomes"):
        if name == "growth_initial" and any(row.get("trigger") == "initial" and row.get("status") == "complete" for row in runs):
            continue
        stamp = memory.kv_get(f"next_run:{name}")
        next_run = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).isoformat() if name in jobs and isinstance(stamp, (int, float)) else None
        activities.append({"id": name, "enabled": name in jobs, "schedule": jobs.get(name), "nextRun": next_run})
    drafts = memory.list_drafts(limit=None)
    def pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: row.get(key) for key in keys}
    evidence_artifact = next(iter(memory.list_artifacts(kind=ArtifactKind.GROWTH_EVIDENCE.value, limit=1)), None)
    evidence_manifest = (
        evidence_artifact.preview_data.get("manifest")
        if evidence_artifact and isinstance(evidence_artifact.preview_data, dict)
        else None
    )
    sources = _source_state(memory, config, context)
    goal = memory.latest_growth_goal()
    initiatives = memory.list_strategy_initiatives(limit=None)
    ideas = memory.list_article_ideas(limit=40)
    keyword_metrics = [
        pick(metric, ("keyword", "search_volume", "volume", "competition", "difficulty", "cpc"))
        for idea in ideas for metric in (idea.get("research_result_json") or [])
        if isinstance(metric, dict)
    ][:100]
    articles = []
    for row in drafts:
        if row.get("kind") != "article":
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if isinstance(meta.get("operator_archive"), dict):
            continue  # retained in draft history, excluded from active Growth projection
        articles.append({
            **pick(row, ("id", "title", "status", "created_ts", "updated_ts")),
            "payloadSync": meta.get("payload_sync"),
        })
    evidence_projection = {
        "artifactId": evidence_artifact.artifact_id if evidence_artifact else None,
        "contentHash": evidence_artifact.content_hash if evidence_artifact else None,
        "capturedAt": evidence_manifest.get("capturedAt") if isinstance(evidence_manifest, dict) else None,
        "sources": sources,
        "limits": evidence_manifest.get("limits", []) if isinstance(evidence_manifest, dict) else [
            "No persisted evidence manifest exists yet.",
        ],
    }
    tasks = growth_tasks(memory, initiatives, drafts, activities, memory.list_strategy_outcomes(limit=100), runs, ideas, include_article_content=include_article_content)
    pending_stamp = memory.kv_get("next_run:growth_pending")
    reconciliation = {"enabled": "growth_pending" in jobs, "nextRun":
        datetime.datetime.fromtimestamp(pending_stamp, datetime.timezone.utc).isoformat()
        if "growth_pending" in jobs and isinstance(pending_stamp, (int, float)) else None}
    model = service_model(
        tasks=tasks, initiatives=initiatives, runs=runs, sources=sources, activities=activities,
        website_present=(config.get("site") or {}).get("website_present") is True,
        reconciliation=reconciliation, inventory_freshness_hours=_freshness_hours(config, "inventory"),
        max_active_candidates=GrowthPolicy.from_config(config).max_active_candidates,
    )
    journal_context = {"memory": memory, "config": config, "tenant_id": context.get("tenant_id")}
    initiative_by_id = {f"initiative:{row['id']}": row for row in initiatives}
    for item in [*model["work"], *model["recentResults"]]:
        initiative = initiative_by_id.get(item["id"])
        if initiative is not None:
            item["engineering"] = journal_reference(journal_context, initiative)
    model["deliveryDiagnostics"] = memory.kv_get("growth_delivery_diagnostics", [])
    return {
        "growthContractVersion": GROWTH_CONTRACT_VERSION,
        "ownerQueueContractVersion": OWNER_QUEUE_CONTRACT_VERSION,
        "sources": sources,
        "ownerTimezone": GrowthPolicy.from_config(config).timezone,
        "evidence": evidence_projection,
        "latestEvidence": evidence_projection,
        "activities": activities,
        "tasks": tasks,
        "ownerQueue": owner_queue(tasks, runs),
        "serviceModel": model,
        "goal": goal,
        "latestInsight": memory.latest_seo_insight(),
        "keywords": [{"keyword": row.get("seed"), **pick(row, ("id", "language", "market", "research_count", "last_researched_ts"))} for row in memory.list_seo_seeds(limit=40)],
        "keywordMetrics": keyword_metrics,
        "articles": articles[:12],
        "articleIdeas": [pick(row, ("id", "status", "focus_keyword", "language", "market", "idea_json", "draft_id", "created_ts")) for row in ideas[:12]],
        "approvalRequired": GrowthPolicy.from_config(config).approval_required,
    }


def growth_chat_context(memory: Memory, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Bounded, read-only model view of the same state the owner sees in Growth.

    No credential/config dump and no provider call. A missing research result
    must not erase a configured capability; source timestamps remain explicit.
    """
    snapshot = growth_snapshot(memory, config, context)
    def pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: row.get(key) for key in keys}
    return {
        "sources": snapshot["sources"],
        "serviceModel": {
            "contractVersion": snapshot["serviceModel"]["contractVersion"],
            "websitePresent": snapshot["serviceModel"]["websitePresent"],
            "decisionCount": len(snapshot["serviceModel"]["decisionIds"]),
            "decisionIds": snapshot["serviceModel"]["decisionIds"],
            "unassignedWorkCount": len(snapshot["serviceModel"]["unassignedWorkIds"]),
            "areas": [{key: row.get(key) for key in (
                "id", "state", "summary", "lastAssessedAt", "nextAssessment", "limitations",
                "workIds", "decisionIds", "blockedWorkIds", "deferredWorkIds", "evidenceState",
            )} for row in snapshot["serviceModel"]["areas"]],
            "recentResults": [pick(row, ("id", "state", "publishedRevision", "impactState", "nextMeasurement"))
                              for row in snapshot["serviceModel"]["recentResults"]],
            "preparation": snapshot["serviceModel"]["preparation"],
        },
        "goal": pick(snapshot["goal"], ("revision", "goal_key", "objective", "metrics")) if snapshot["goal"] else None,
        "activities": [pick(row, ("id", "enabled", "schedule", "nextRun")) for row in snapshot["activities"]],
        "tasks": [pick(row, ("id", "kind", "title", "summary", "focus", "state", "nextRun", "executionIssue", "canApprove")) for row in snapshot["tasks"][:30]],
        "keywords": snapshot["keywords"][:10],
        "keywordMetrics": snapshot["keywordMetrics"][:10],
        "approvalRequired": snapshot["approvalRequired"],
        "readOnly": True,
    }


def growth_metrics(memory: Memory) -> dict[str, Any]:
    """Persisted analytics/search evidence, bounded before JSON serialization."""
    measures = ("totalUsers", "activeUsers", "newUsers", "sessions", "engagedSessions",
                "screenPageViews", "engagementRate", "averageSessionDuration", "keyEvents",
                "clicks", "impressions", "ctr", "position", "users", "views")
    dimensions = ("path", "page", "query", "source", "medium", "channel", "country", "device")
    def fields(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: value[:300] if isinstance(value, str) else value
                for key in keys if key in row
                for value in (row[key],) if value is None or isinstance(value, (str, int, float, bool))}
    result: dict[str, Any] = {"observedAt": {}}
    for source, label in (("ga4", "traffic"), ("gsc", "search")):
        snapshot = memory.latest_snapshot(source)
        result["observedAt"][source] = snapshot.get("ts") if snapshot else None
        if snapshot is None:
            result[label] = None
            continue
        data = snapshot["data"]
        summary: dict[str, Any] = fields(data, ("period_days", "period", "start_date", "end_date"))
        for key in ("current", "previous", "current_week", "previous_week", "delta_pct", "totals"):
            if isinstance(data.get(key), dict):
                summary[key] = fields(data[key], measures)
        for key in ("top_pages", "top_queries", "sources", "organic_queries"):
            if isinstance(data.get(key), list):
                summary[key] = [fields(row, measures + dimensions) for row in data[key][:10] if isinstance(row, dict)]
        result[label] = summary
    result["weekly_llm_cost_usd"] = round(memory.llm_spend(since_hours=24 * 7)["cost_usd"], 2)
    return result
