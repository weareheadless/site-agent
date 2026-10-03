"""Read-only owner projection of existing tenant growth work. Never provisions."""
from __future__ import annotations

import datetime
from typing import Any

from ..core.contracts import ArtifactKind
from ..core.growth_contracts import GrowthPolicy
from ..core.memory import Memory
from .growth_workflow import _source_state
from .growth_tasks import growth_tasks


def growth_snapshot(memory: Memory, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = context.get("seo_provisioning_state") or memory.kv_get("seo_provisioning_state", {}) or {}
    scheduler = context.get("scheduler")
    jobs = {name: spec for name, spec, _fn in getattr(scheduler, "jobs", [])}
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
    return {
        "sources": sources,
        "evidence": evidence_projection,
        "latestEvidence": evidence_projection,
        "activities": activities,
        "tasks": growth_tasks(memory, initiatives, drafts, activities, memory.list_strategy_outcomes(limit=100), runs, memory.list_article_ideas(limit=40)),
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
