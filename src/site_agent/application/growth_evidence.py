"""Read existing project-scoped CrawlSEO evidence for the owner workspace.

These reads never launch a crawl, paid research, or a publication. Provider
failures are explicit per source; missing measurements remain null.
"""
from __future__ import annotations

import datetime
from typing import Any

from .crawlseo import CrawlSEOApplicationError, CrawlSEOApplicationService


def growth_evidence(service: CrawlSEOApplicationService, section: str) -> dict[str, Any]:
    result: dict[str, Any] = {"capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "errors": {}}

    def read(name: str, operation):
        try:
            return operation()
        except CrawlSEOApplicationError as exc:
            result["errors"][name] = str(exc)
            return None

    if section == "health":
        result["summary"] = read("summary", service.crawl_summary)
        result["issues"] = read("issues", lambda: service.crawl_issues(limit=100))
        return result
    if section != "research":
        raise ValueError("unknown growth evidence section")

    latest = read("report", service.latest_research_report)
    articles = read("articleResearch", lambda: service.list_article_keyword_research(limit=50))
    history = read("history", lambda: service.list_research_reports(limit=24))
    result["reports"] = (history or {}).get("reports", [])
    result["keywords"] = []
    result["domains"] = []
    result["backlinks"] = []
    report = (latest or {}).get("report") or {}
    market = report.get("focus_market") or {}
    result["market"] = market
    result["period"] = (latest or {}).get("period")
    result["reportId"] = (latest or {}).get("report_id")
    result["updatedAt"] = (latest or {}).get("completed_at")
    result["status"] = (latest or {}).get("status")

    def keywords(rows, *, language=None, country=None, source=None, updated=None):
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict) or not row.get("keyword"):
                continue
            result["keywords"].append({
                **{key: row.get(key) for key in ("keyword", "volume", "difficulty", "cpc", "competition", "intent", "trend")},
                "language": language, "market": country, "source": source, "updatedAt": updated,
            })

    for task in report.get("dataforseo") or []:
        if not isinstance(task, dict) or task.get("status") != "completed":
            continue
        value = task.get("result")
        inputs = task.get("input") or {}
        if task.get("kind") == "keyword_seed":
            keywords(value, language=market.get("language"), country=market.get("country"), source="monthly", updated=result["updatedAt"])
        elif task.get("kind") in ("domain_overview", "backlinks_overview") and isinstance(value, dict):
            fields = ("organicKeywords", "organicTraffic", "organicCost") if task["kind"] == "domain_overview" else ("totalBacklinks", "referringDomains", "referringIps", "dofollow", "nofollow")
            result["domains" if task["kind"] == "domain_overview" else "backlinks"].append({
                "domain": inputs.get("domain"), **{key: value.get(key) for key in fields}, "updatedAt": result["updatedAt"],
            })
    for run in (articles or {}).get("runs") or []:
        if not isinstance(run, dict) or run.get("kind") not in ("keyword_overview", "related_keywords") or run.get("status") != "completed":
            continue
        value = run.get("result")
        # Article metric runs persist an array; SERP runs persist an object and
        # must never be mistaken for keyword metrics.
        keywords(value, language=run.get("language"), country=run.get("country"), source="article", updated=run.get("completed_at"))
    # Keep the newest observation per keyword AND market: country-specific
    # demand/difficulty from different markets cannot be merged.
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in result["keywords"]:
        key = (str(row["keyword"]).casefold(), str(row["language"]), str(row["market"]))
        if key not in unique or str(row["updatedAt"] or "") > str(unique[key]["updatedAt"] or ""):
            unique[key] = row
    result["keywords"] = list(unique.values())
    return result
