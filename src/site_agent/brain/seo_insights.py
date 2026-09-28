"""Owner-facing SEO synthesis.

Google shows numbers. This turns the tenant's own evidence — Search Console,
GA4, and Ada's keyword research — into one short judgement: what matters, what
to do next, and what to ignore. The same record is read back by the article
cycle so the owner's view and Ada's working context never diverge.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping
from typing import Any

from ..core.llm import extract_json

_MAX_OPPORTUNITIES = 5
_MAX_WATCHOUTS = 4


def _period(now: datetime.datetime | None = None) -> str:
    local = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc)
    iso = local.date().isocalendar()
    return f"seo:{iso.year}-W{iso.week:02d}"


def _top_pages(snapshot: Mapping[str, Any] | None, limit: int = 6) -> list[dict[str, Any]]:
    data = (snapshot or {}).get("data") if isinstance(snapshot, Mapping) else {}
    pages = (data or {}).get("top_pages") if isinstance(data, Mapping) else []
    rows: list[dict[str, Any]] = []
    for page in pages[:limit] if isinstance(pages, list) else []:
        if not isinstance(page, Mapping):
            continue
        rows.append({
            "path": str(page.get("path") or "")[:200],
            "views": page.get("views"),
            "clicks": page.get("clicks"),
            "impressions": page.get("impressions"),
        })
    return rows


def _top_queries(snapshot: Mapping[str, Any] | None, limit: int = 8) -> list[dict[str, Any]]:
    data = (snapshot or {}).get("data") if isinstance(snapshot, Mapping) else {}
    queries = (data or {}).get("top_queries") if isinstance(data, Mapping) else []
    rows: list[dict[str, Any]] = []
    for item in queries[:limit] if isinstance(queries, list) else []:
        if not isinstance(item, Mapping):
            continue
        rows.append({
            "query": str(item.get("query") or "")[:200],
            "clicks": item.get("clicks"),
            "impressions": item.get("impressions"),
            "position": item.get("position"),
        })
    return rows


def _metrics(analytics: Mapping[str, Any], search: Mapping[str, Any]) -> dict[str, Any]:
    current = analytics.get("current_week") if isinstance(analytics.get("current_week"), Mapping) else {}
    previous = analytics.get("previous_week") if isinstance(analytics.get("previous_week"), Mapping) else {}
    deltas = analytics.get("delta_pct") if isinstance(analytics.get("delta_pct"), Mapping) else {}
    return {
        "sessions_current": current.get("sessions"),
        "sessions_previous": previous.get("sessions"),
        "clicks_delta_pct": deltas.get("clicks"),
        "impressions_delta_pct": deltas.get("impressions"),
        "search_days": search.get("period_days"),
    }


def _evidence(context: Mapping[str, Any]) -> dict[str, Any]:
    memory = context["memory"]
    analytics_snapshot = memory.latest_snapshot("ga4")
    search_snapshot = memory.latest_snapshot("gsc")
    analytics = (analytics_snapshot or {}).get("data") if isinstance(analytics_snapshot, Mapping) else {}
    search = (search_snapshot or {}).get("data") if isinstance(search_snapshot, Mapping) else {}
    analytics = analytics if isinstance(analytics, Mapping) else {}
    search = search if isinstance(search, Mapping) else {}
    latest_draft = next((row for row in memory.list_drafts(limit=10) if row.get("kind") == "article"), None)
    return {
        "metrics": _metrics(analytics, search),
        "top_pages": _top_pages(analytics_snapshot),
        "top_queries": _top_queries(search_snapshot),
        "latest_article": str((latest_draft or {}).get("title") or "")[:200],
        "previous_insight": {
            "headline": (memory.latest_seo_insight() or {}).get("headline", ""),
            "next_action": (memory.latest_seo_insight() or {}).get("next_action", ""),
        },
    }


def _prompt(config: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[dict[str, str]]:
    audience = str(((config.get("persona") or {}).get("audience")) or "the site's audience")
    language = ""
    research = ((config.get("seo") or {}).get("research") or {})
    for item in research.get("languages") or []:
        if isinstance(item, Mapping) and item.get("primary"):
            language = str(item.get("code") or "")
            break
    system = (
        "You write a short, honest SEO briefing for the owner of a small business website. "
        "The owner is not an SEO expert and does not want a data dump. Use ONLY the supplied evidence; "
        "never invent metrics, keywords, rankings, or trends. If the evidence is too thin to support a "
        "claim, say so plainly instead of speculating. Prefer two or three concrete observations over "
        "completeness. Write in the site's language"
        + (f" ({language})" if language else "")
        + f", for this audience: {audience}. Return JSON only."
    )
    user = (
        json.dumps(dict(evidence), ensure_ascii=False, default=str)[:12_000]
        + "\n\nReturn exactly: {\"headline\":\"one sentence the owner should remember\","
        "\"summary_md\":\"2-4 short markdown paragraphs: what changed, what it means, what not to worry about\","
        "\"opportunities\":[{\"title\":\"...\",\"rationale\":\"why this, grounded in the evidence\","
        "\"action\":\"the concrete next step\"}],"
        "\"watchouts\":[\"something that looks alarming but is not, or a caveat\"],"
        "\"next_action\":\"the single most valuable thing to do next\","
        "\"focus_keyword\":\"one query worth building content around, or an empty string\"}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _validate(raw: str) -> dict[str, Any]:
    parsed = extract_json(raw)
    if not isinstance(parsed, Mapping):
        raise ValueError("SEO insight must be a JSON object")
    headline = _text(parsed.get("headline"), 300)
    summary = str(parsed.get("summary_md") or "").strip()[:8000]
    if not headline or not summary:
        raise ValueError("SEO insight needs a headline and a summary")
    opportunities: list[dict[str, str]] = []
    for item in parsed.get("opportunities") or []:
        if not isinstance(item, Mapping):
            continue
        title = _text(item.get("title"), 200)
        if not title:
            continue
        opportunities.append({
            "title": title,
            "rationale": _text(item.get("rationale"), 600),
            "action": _text(item.get("action"), 600),
        })
        if len(opportunities) >= _MAX_OPPORTUNITIES:
            break
    watchouts = [_text(item, 400) for item in (parsed.get("watchouts") or []) if _text(item, 400)][:_MAX_WATCHOUTS]
    return {
        "headline": headline,
        "summary_md": summary,
        "opportunities": opportunities,
        "watchouts": watchouts,
        "next_action": _text(parsed.get("next_action"), 1000),
        "focus_keyword": _text(parsed.get("focus_keyword"), 200),
    }


def generate(context: dict[str, Any]) -> int:
    """Produce and persist one owner-facing SEO insight."""
    memory = context["memory"]
    llm = context.get("llm")
    config = context.get("config") or {}
    if llm is None:
        raise RuntimeError("llm client missing; cannot write an SEO insight")
    evidence = _evidence(context)
    insight = _validate(llm.chat(_prompt(config, evidence), json_mode=True, temperature=0.3))
    model = str(((config.get("llm") or {}).get("model")) or "")
    insight_id = memory.save_seo_insight(
        period=_period(),
        metrics=evidence.get("metrics") or {},
        evidence=[
            {"kind": "ga4_snapshot", "present": bool(memory.latest_snapshot("ga4"))},
            {"kind": "gsc_snapshot", "present": bool(memory.latest_snapshot("gsc"))},
        ],
        model=model,
        **insight,
    )
    memory.record_action("seo_insight", f"#{insight_id}: {insight['headline'][:200]}")
    return insight_id


__all__ = ["generate"]
