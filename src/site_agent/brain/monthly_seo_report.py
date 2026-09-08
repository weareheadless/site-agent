"""Monthly website SEO report loop.

This loop reads only bounded first-party evidence from CrawlSEO and Ada's local
article-research ledger. It never starts paid research and never creates an
article brief.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..core.contracts import Artifact, ArtifactKind
from ..core.llm import extract_json


REPORT_SCHEMA_VERSION = 1


def _report_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return dict(((config.get("seo") or {}).get("site_report") or {}))


def previous_period(config: Mapping[str, Any], now: datetime.datetime | None = None) -> str:
    settings = _report_config(config)
    timezone = ZoneInfo(str(settings.get("timezone") or "UTC"))
    local_now = now.astimezone(timezone) if now is not None else datetime.datetime.now(timezone)
    first = local_now.date().replace(day=1)
    return (first - datetime.timedelta(days=1)).strftime("%Y-%m")


def _period_window(period: str, timezone_name: str) -> tuple[str, str]:
    try:
        year, month = (int(value) for value in period.split("-", 1))
        timezone = ZoneInfo(timezone_name)
        start = datetime.datetime(year, month, 1, tzinfo=timezone)
        next_month = start.replace(day=28) + datetime.timedelta(days=4)
        end = next_month.replace(day=1)
    except (TypeError, ValueError, KeyError):
        raise ValueError("period must use a valid YYYY-MM value")
    return start.astimezone(datetime.timezone.utc).isoformat(), end.astimezone(datetime.timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _article_history(memory: Any, period: str, timezone_name: str) -> dict[str, Any]:
    since, until = _period_window(period, timezone_name)
    ideas = memory.list_article_ideas(limit=200)
    drafts = {row["id"]: row for row in memory.list_drafts(limit=300)}
    publishes = {row.get("draft_id"): row for row in memory.list_publishes(limit=300) if row.get("draft_id")}
    selected: list[dict[str, Any]] = []
    actual_cost = 0
    for idea in ideas:
        created = str(idea.get("created_ts") or "")
        researched = str(idea.get("researched_ts") or "")
        if not ((since <= created < until) or (since <= researched < until)):
            continue
        note = idea.get("research_note_json") if isinstance(idea.get("research_note_json"), Mapping) else {}
        idea_data = idea.get("idea_json") if isinstance(idea.get("idea_json"), Mapping) else {}
        draft_id = idea.get("draft_id")
        draft = drafts.get(draft_id) if draft_id else None
        publication = publishes.get(draft_id) if draft_id else None
        cost = idea.get("research_cost_micros")
        if isinstance(cost, (int, float)):
            actual_cost += int(cost)
        selected.append({
            "idea_id": idea["id"],
            "working_title": str(idea_data.get("working_title") or "")[:300],
            "audience_need": str(idea_data.get("audience_need") or "")[:500],
            "research_seed": str(idea_data.get("research_seed") or "")[:120],
            "research_decision": str(note.get("decision") or "")[:80],
            "key_learning": str(note.get("reasoning") or "")[:800],
            "research_run_id": idea.get("research_run_id"),
            "provider_task_id": idea.get("provider_task_id"),
            "researched_at": idea.get("researched_ts"),
            "research_cost_micros": cost,
            "draft_id": draft_id,
            "draft_status": draft.get("status") if draft else None,
            "published_at": publication.get("ts") if publication else None,
        })
    selected = selected[:20]
    return {
        "attempted_count": sum(1 for item in selected if item.get("research_run_id")),
        "completed_count": sum(1 for item in selected if item.get("researched_at")),
        "actual_cost_micros": actual_cost,
        "items": selected,
    }


def _prompt(persona: str, period: str, evidence: Mapping[str, Any], article_research: Mapping[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nYou are writing a monthly website SEO report for the owner. Use only the supplied evidence. "
        "Do not invent numbers, URLs, trends, causes, or recommendations. This is a website performance "
        "report, not an article brief: do not propose an article or turn keyword volume into editorial authority. "
        "Do not mention backlinks. Keep the report plain-language and actionable."
    )
    user = (
        f"Report month: {period}\n\n"
        "First-party website evidence (GSC, GA4, technical crawl):\n"
        + json.dumps(evidence, ensure_ascii=False, default=str)[:30_000]
        + "\n\nPaid article research completed during this month, as dated editorial context only:\n"
        + json.dumps(article_research, ensure_ascii=False, default=str)[:12_000]
        + "\n\nReturn markdown only with exactly these sections:\n"
        "# Website SEO report: <month>\n"
        "## What changed\n"
        "## Data quality and freshness\n"
        "## Technical and content findings\n"
        "## Article research context\n"
        "## Prioritized next steps\n"
        "Use no more than three numbered next steps. The article research section may summarize what was learned and its cost, "
        "but must not create an article brief."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _report_text(raw: str, period: str) -> str:
    parsed = extract_json(raw)
    if isinstance(parsed, Mapping):
        raw = str(parsed.get("report") or parsed.get("body") or "")
    text = raw.strip()
    if not text:
        raise RuntimeError("monthly SEO report returned no body")
    if not text.startswith("#"):
        text = f"# Website SEO report: {period}\n\n{text}"
    return text[:30_000]


def _source_error(evidence: Mapping[str, Any]) -> str | None:
    states = evidence.get("source_states")
    if not isinstance(states, Mapping):
        return None
    unavailable = [
        name for name, state in states.items()
        if isinstance(state, Mapping) and state.get("status") == "unavailable"
    ]
    return "SOURCE_UNAVAILABLE_" + "_".join(unavailable).upper() if unavailable else None


def _ready_evidence(response: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return response if str(response.get("status") or "").lower() == "ready" else None


def run(context: dict[str, Any]) -> None:
    config = context["config"]
    memory = context["memory"]
    settings = _report_config(config)
    if not (config.get("seo") or {}).get("enabled") or not settings.get("enabled", False):
        return
    service = context.get("crawlseo_service")
    if service is None:
        memory.record_action("seo_site_report", "skipped: CrawlSEO provider is unavailable")
        return

    period = previous_period(config)
    row = memory.get_seo_site_report_for_period(period)
    if row is None:
        row = memory.create_seo_site_report(period)
    if row.get("status") == "completed":
        return

    stored = row.get("evidence_json") if isinstance(row.get("evidence_json"), Mapping) else {}
    stored_site = stored.get("site") if isinstance(stored.get("site"), Mapping) else stored
    evidence: Mapping[str, Any] | None = _ready_evidence(stored_site)
    try:
        if evidence is None:
            retry_source_preparation = row.get("status") == "failed" and str(row.get("error") or "").startswith("SOURCE_UNAVAILABLE_")
            if row.get("status") == "waiting" and not retry_source_preparation:
                response = service.monthly_site_evidence(period)
            else:
                response = service.prepare_monthly_site_evidence(
                    period,
                    f"site-report:{period}:v1",
                    max(1, min(int(settings.get("max_crawl_pages", 200)), 2000)),
                )
            source_error = _source_error(response)
            if source_error:
                memory.update_seo_site_report(row["id"], status="failed", evidence_json=response, error=source_error)
                memory.record_action("seo_site_report", f"{period}: {source_error}")
                return
            evidence = _ready_evidence(response)
            if evidence is None:
                memory.update_seo_site_report(row["id"], status="waiting", evidence_json=response, error=None)
                memory.record_action("seo_site_report", f"{period}: waiting for first-party sources")
                return

        article_research = _article_history(memory, period, str(settings.get("timezone") or "UTC"))
        combined = {"site": evidence, "article_research": article_research}
        evidence_hash = _hash(combined)
        memory.update_seo_site_report(
            row["id"], evidence_hash=evidence_hash, evidence_json=combined, status="preparing", error=None
        )
        llm = context.get("llm")
        if llm is None:
            raise RuntimeError("llm client missing; cannot write monthly SEO report")
        body = _report_text(llm.chat(_prompt(context.get("persona_prompt") or "", period, evidence, article_research), temperature=0.4), period)
        artifact = memory.create_artifact(
            Artifact(
                kind=ArtifactKind.SEO_REPORT,
                title=f"Website SEO report {period}",
                summary="Monthly website performance and technical SEO report.",
                renderer="seo_report",
                capability_id="seo.report.read",
                provider_id="site-agent",
                content_hash="sha256:" + hashlib.sha256(body.encode()).hexdigest(),
                preview_data={"body": body, "period": period, "evidence_hash": evidence_hash},
            )
        )
        summary = next((line.strip("# ") for line in body.splitlines() if line.strip() and not line.startswith("#")), body[:500])
        memory.update_seo_site_report(
            row["id"],
            status="completed",
            evidence_hash=evidence_hash,
            evidence_json=combined,
            summary=summary[:500],
            artifact_id=artifact.artifact_id,
            completed_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            error=None,
        )
        memory.record_action("seo_site_report", f"{period}: report #{row['id']}, artifact #{artifact.artifact_id}")
    except Exception as exc:  # noqa: BLE001 - source evidence remains saved for a retry
        memory.update_seo_site_report(row["id"], status="failed", error=str(exc)[:500])
        memory.record_action("seo_site_report", f"{period}: report retryable failure: {str(exc)[:300]}")


__all__ = ["previous_period", "run"]
