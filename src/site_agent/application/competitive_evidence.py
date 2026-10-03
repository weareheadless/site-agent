"""Project-scoped competitive evidence from completed CrawlSEO research.

No provider dispatch occurs here. Search rivals are observed SERP neighbours,
not assumed commercial competitors, and sampled absence is not a keyword gap.
"""
from __future__ import annotations

import datetime
import math
from typing import Any
from urllib.parse import urlsplit

from .crawlseo import CrawlSEOApplicationError, CrawlSEOApplicationService


def _domain(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        url = urlsplit(value if "://" in value else f"https://{value}")
        if url.scheme not in ("http", "https") or url.username or url.password:
            return ""
        return (url.hostname or "").lower().removeprefix("www.").rstrip(".")[:253]
    except ValueError:
        return ""


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def competitive_evidence(service: CrawlSEOApplicationService) -> dict[str, Any]:
    result: dict[str, Any] = {"capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "errors": {}, "benchmarks": [], "serps": [], "rivals": [],
        "coverage": "sampled_top_10_not_domain_keyword_gap"}

    def read(name, operation):
        try:
            return operation()
        except CrawlSEOApplicationError as exc:
            result["errors"][name] = str(exc)
            return None

    project = read("project", service.project) or {}
    site = project.get("site") or {}
    own = _domain(site.get("domain"))
    result["site"] = {"domain": own or None, "url": site.get("url")}
    latest = read("report", service.latest_research_report) or {}
    report = latest.get("report") or {}
    selected = _domain((report.get("brief") or {}).get("competitor"))
    result.update(selectedCompetitor=selected or None, period=latest.get("period"),
        updatedAt=latest.get("completed_at"), market=report.get("focus_market") or {},
        reportId=latest.get("report_id"), reportStatus=latest.get("status"))
    fields = ("organicKeywords", "organicTraffic", "referringDomains", "totalBacklinks")
    domains: dict[str, dict[str, Any]] = {}
    for task in report.get("dataforseo") or []:
        if not isinstance(task, dict) or task.get("status") != "completed" or task.get("kind") not in ("domain_overview", "backlinks_overview"):
            continue
        domain = _domain((task.get("input") or {}).get("domain"))
        value = task.get("result")
        if not domain or not isinstance(value, dict):
            continue
        row = domains.setdefault(domain, {"domain": domain, "isOwn": bool(own and domain == own),
            "isSelected": bool(selected and domain == selected), **dict.fromkeys(fields)})
        for key in fields:
            if key in value:
                row[key] = _number(value[key])
    result["benchmarks"] = sorted(domains.values(), key=lambda row: (not row["isOwn"], row["domain"]))
    research = read("serps", lambda: service.list_article_keyword_research(limit=50)) or {}
    latest_serps: dict[tuple[str, str, str], dict[str, Any]] = {}
    for run in research.get("runs") or []:
        if not isinstance(run, dict) or run.get("kind") != "organic_serp" or run.get("status") != "completed":
            continue
        value = run.get("result")
        if not isinstance(value, dict) or not value.get("query"):
            continue
        query, language, country = str(value["query"])[:120], run.get("language"), run.get("country")
        key = (query.casefold(), str(language), str(country))
        updated = run.get("completed_at")
        if key in latest_serps and str(updated or "") <= str(latest_serps[key].get("updatedAt") or ""):
            continue
        organic = []
        for entry in (value.get("organic") or [])[:10]:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "")[:2000]
            domain = _domain(entry.get("domain"))
            if not url.startswith(("https://", "http://")) or not domain or _domain(url) != domain:
                continue
            rank = _number(entry.get("rank"))
            organic.append({"domain": domain, "rank": rank if rank and rank <= 100 else None,
                "url": url, "title": str(entry.get("title") or "")[:500], "isOwn": bool(own and own == domain)})
        positions = [row["rank"] for row in organic if row["isOwn"] and row["rank"] is not None]
        latest_serps[key] = {"query": query, "language": language, "country": country,
            "updatedAt": updated, "checkedAt": value.get("checkedAt"), "runId": run.get("run_id") or run.get("id"),
            "ownPosition": min(positions) if positions else None, "organic": organic}
    result["serps"] = sorted(latest_serps.values(), key=lambda row: (str(row["country"]), str(row["language"]), row["query"]))
    rivals: dict[tuple[str, str, str], dict[str, Any]] = {}
    for serp in result["serps"]:
        seen = set()
        for entry in serp["organic"]:
            if entry["isOwn"]:
                continue
            key = (entry["domain"], str(serp["language"]), str(serp["country"]))
            row = rivals.setdefault(key, {"domain": entry["domain"], "language": serp["language"], "country": serp["country"],
                "appearances": 0, "bestPosition": None, "queries": []})
            if entry["rank"] is not None:
                row["bestPosition"] = min(row["bestPosition"], entry["rank"]) if row["bestPosition"] is not None else entry["rank"]
            if key not in seen:
                row["appearances"] += 1
                row["queries"].append(serp["query"])
                seen.add(key)
    result["rivals"] = sorted(rivals.values(), key=lambda row: (-row["appearances"], row["bestPosition"] or 999, row["domain"]))
    return result
