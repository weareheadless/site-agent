"""Read-only owner projection of existing tenant growth work. Never provisions."""
from __future__ import annotations

import datetime
from typing import Any

from ..core.contracts import ArtifactKind
from ..core.memory import Memory


def growth_snapshot(memory: Memory, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = context.get("seo_provisioning_state") or memory.kv_get("seo_provisioning_state", {}) or {}
    scheduler = context.get("scheduler")
    jobs = {name: spec for name, spec, _fn in getattr(scheduler, "jobs", [])}
    activities = []
    for name in ("growth_reconciler", "article", "seo_insight", "weekly_report", "seo_site_report_cycle", "article_research_cycle", "social_post"):
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
    evidence_artifact = next(iter(memory.list_artifacts(kind=ArtifactKind.GROWTH_EVIDENCE.value, limit=1)), None)
    evidence_manifest = (
        evidence_artifact.preview_data.get("manifest")
        if evidence_artifact and isinstance(evidence_artifact.preview_data, dict)
        else None
    )
    # A configured provider is not proof of fresh data or successful verification.
    sources = [
        {"id": "ga4", "status": "collecting" if ga_property else "not_configured", "state": "ready" if ga4 else "missing", "property": ga_property, "updatedAt": (ga4 or {}).get("ts"), "dataState": "available" if ga4 else "missing"},
        {"id": "gsc", "status": "verification_required" if state.get("gsc_pending") else "collecting" if gsc_property else "not_configured", "state": "unauthorised" if state.get("gsc_pending") else "ready" if gsc else "missing", "property": gsc_property, "updatedAt": (gsc or {}).get("ts"), "dataState": "available" if gsc else "missing"},
        {"id": "dataforseo", "status": "configured" if context.get("crawlseo_service") else "not_configured", "state": "ready" if memory.list_seo_seeds(limit=1) else "missing", "updatedAt": state.get("provisioned_at"), "dataState": "available" if memory.list_seo_seeds(limit=1) else "missing"},
    ]
    if isinstance(evidence_manifest, dict) and isinstance(evidence_manifest.get("sources"), list):
        sources = [dict(item) for item in evidence_manifest["sources"] if isinstance(item, dict)]
    for source, snapshot in ((sources[0], ga4), (sources[1], gsc)):
        if snapshot is not None and source["status"] == "collecting":
            source["status"] = "has_data"
    goal = memory.latest_growth_goal()
    latest_run = memory.latest_growth_run()
    owner_actions = []
    for action in memory.list_owner_actions(states=("open", "started", "waiting"), limit=3):
        row = action.to_record()
        owner_actions.append({key: row.get(key) for key in ("id", "title", "summary", "action_label", "priority", "state", "source_ref", "artifact_id", "approval_id", "draft_id")})
    if latest_run and latest_run.get("status") == "running":
        work_state = "running"
        work_summary_key = "backgroundRunning"
    elif latest_run and latest_run.get("status") == "failed":
        work_state = "blocked"
        work_summary_key = "backgroundBlocked"
    else:
        work_state = "idle"
        work_summary_key = "backgroundIdle"
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
    articles = []
    for row in drafts:
        if row.get("kind") != "article":
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        articles.append({
            **pick(row, ("id", "title", "status", "created_ts", "updated_ts", "body")),
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
        "goal": goal,
        "work": {
            "state": work_state,
            "summaryKey": work_summary_key,
            "latestRun": latest_run,
            "nextRun": next((item["nextRun"] for item in activities if item["id"] == "growth_reconciler"), None),
        },
        "reviewQueue": owner_actions,
        "results": {
            "state": "available" if ga4 or gsc else "too_early",
            "message": "Ada will compare results after a verified change has been live for a complete observation window.",
        },
        "latestInsight": memory.latest_seo_insight(),
        "insights": memory.list_seo_insights(limit=12),
        "keywords": [{"keyword": row.get("seed"), **pick(row, ("id", "language", "market", "research_count", "last_researched_ts"))} for row in memory.list_seo_seeds(limit=40)],
        "keywordMetrics": keyword_metrics,
        "articles": articles[:12],
        "weeklyReports": [pick(row, ("id", "title", "status", "created_ts", "body")) for row in drafts if row.get("kind") == "report"][:8],
        "monthlyReports": reports,
        "articleIdeas": [pick(row, ("id", "status", "focus_keyword", "language", "market", "idea_json", "draft_id", "created_ts")) for row in ideas[:12]],
        "approvalRequired": True,
    }
