"""Read-only owner projection of existing tenant growth work. Never provisions."""
from __future__ import annotations

import datetime
from typing import Any

from ..core.memory import Memory


def growth_snapshot(memory: Memory, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = context.get("seo_provisioning_state") or memory.kv_get("seo_provisioning_state", {}) or {}
    scheduler = context.get("scheduler")
    jobs = {name: spec for name, spec, _fn in getattr(scheduler, "jobs", [])}
    activities = []
    for name in ("article", "seo_insight", "weekly_report", "seo_site_report_cycle", "article_research_cycle", "social_post"):
        stamp = memory.kv_get(f"next_run:{name}")
        next_run = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).isoformat() if isinstance(stamp, (int, float)) else None
        activities.append({"id": name, "enabled": name in jobs, "schedule": jobs.get(name), "nextRun": next_run})
    drafts = memory.list_drafts(limit=100)
    def pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: row.get(key) for key in keys}
    ga4 = memory.latest_snapshot("ga4")
    gsc = memory.latest_snapshot("gsc")
    ga_property = state.get("ga4_property_id") or (config.get("ga") or {}).get("property_id")
    gsc_property = state.get("gsc_property") or (config.get("seo") or {}).get("site_url")
    # A configured provider is not proof of fresh data or successful verification.
    sources = [
        {"id": "ga4", "status": "collecting" if ga_property else "not_configured", "property": ga_property, "updatedAt": (ga4 or {}).get("ts")},
        {"id": "gsc", "status": "verification_required" if state.get("gsc_pending") else "collecting" if gsc_property else "not_configured", "property": gsc_property, "updatedAt": (gsc or {}).get("ts")},
        {"id": "dataforseo", "status": "configured" if context.get("crawlseo_service") else "not_configured", "updatedAt": state.get("provisioned_at")},
    ]
    for source, snapshot in ((sources[0], ga4), (sources[1], gsc)):
        if snapshot is not None and source["status"] == "collecting":
            source["status"] = "has_data"
    ideas = memory.list_article_ideas(limit=40)
    keyword_metrics = [
        pick(metric, ("keyword", "search_volume", "volume", "competition", "difficulty", "cpc"))
        for idea in ideas for metric in (idea.get("research_result_json") or [])
        if isinstance(metric, dict)
    ][:100]
    reports = []
    for row in memory.list_seo_site_reports(limit=6):
        artifact = memory.get_artifact(row["artifact_id"]) if row.get("artifact_id") else None
        body = artifact.preview_data.get("body") if artifact else row.get("summary")
        reports.append({**pick(row, ("id", "period", "status", "created_ts", "updated_ts")), "body_md": body})
    return {
        "sources": sources,
        "activities": activities,
        "latestInsight": memory.latest_seo_insight(),
        "insights": memory.list_seo_insights(limit=12),
        "keywords": [{"keyword": row.get("seed"), **pick(row, ("id", "language", "market", "research_count", "last_researched_ts"))} for row in memory.list_seo_seeds(limit=40)],
        "keywordMetrics": keyword_metrics,
        "articles": [pick(row, ("id", "title", "status", "created_ts", "updated_ts", "body")) for row in drafts if row.get("kind") == "article"][:12],
        "weeklyReports": [pick(row, ("id", "title", "status", "created_ts", "body")) for row in drafts if row.get("kind") == "report"][:8],
        "monthlyReports": reports,
        "articleIdeas": [pick(row, ("id", "status", "focus_keyword", "language", "market", "idea_json", "draft_id", "created_ts")) for row in ideas[:12]],
        "approvalRequired": True,
    }
