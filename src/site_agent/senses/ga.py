"""ga.py — Google Analytics 4, read-only. Ported from Ada's ga.py.

Credentials come from the instance config (with the original environment
variables as fallback). google-auth is imported lazily so the base install
stays light; install with `pip install site-agent[ga]`.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.request
from typing import Any

API = "https://analyticsdata.googleapis.com/v1beta"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
DEFAULT_KEY_PATH = "/home/admin/.config/ga4-service-account.json"


def _settings(config: dict[str, Any]) -> tuple[str, str]:
    ga = config.get("ga") or {}
    key_path = str(
        ga.get("key_path")
        or os.environ.get("GA4_SERVICE_ACCOUNT")
        or DEFAULT_KEY_PATH
    )
    property_id = str(ga.get("property_id") or os.environ.get("GA4_PROPERTY_ID", ""))
    return key_path, property_id


def _token(key_path: str) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("google-auth not installed; run pip install 'site-agent[ga]'") from exc
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token


def _run(config: dict[str, Any], body: dict[str, Any], timeout: int = 25) -> dict[str, Any]:
    key_path, property_id = _settings(config)
    if not key_path or not property_id:
        raise RuntimeError("ga4 not configured: set ga.key_path and ga.property_id")
    req = urllib.request.Request(
        f"{API}/properties/{property_id}:runReport",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_token(key_path)}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _source(config: dict[str, Any]) -> str:
    return str((config.get("ga") or {}).get("source", "ga4")).lower()


def _crawlseo_summary(config: dict[str, Any], crawlseo_service: Any | None = None) -> dict[str, Any]:
    from . import crawlseo as crawlseo_sense

    return crawlseo_sense.analytics_summary(config, service=crawlseo_service)


def _totals(config: dict[str, Any], start: str, end: str) -> dict[str, int]:
    result = _run(
        config,
        {
            "dateRanges": [{"startDate": start, "endDate": end}],
            "metrics": [{"name": "activeUsers"}, {"name": "totalUsers"}, {"name": "sessions"}, {"name": "screenPageViews"}],
        },
    )
    rows = result.get("rows") or []
    metrics = rows[0].get("metricValues", []) if rows else []
    names = [m["name"] for m in (result.get("metricHeaders") or [])]
    return {name: int(metrics[i]["value"]) for i, name in enumerate(names)} if names else {}


def traffic_sources(
    config: dict[str, Any],
    days: int = 7,
    limit: int = 8,
    crawlseo_service: Any | None = None,
) -> list[dict[str, Any]]:
    if _source(config) == "crawlseo":
        return _crawlseo_summary(config, crawlseo_service)["sources"][:limit]
    end = datetime.date.today() - datetime.timedelta(days=1)
    result = _run(
        config,
        {
            "dateRanges": [{"startDate": (end - datetime.timedelta(days=days - 1)).isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": "sessions"}, {"name": "totalUsers"}],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": limit,
        },
    )
    return [
        {
            "source": r["dimensionValues"][0]["value"],
            "sessions": int(r["metricValues"][0]["value"]),
            "users": int(r["metricValues"][1]["value"]),
        }
        for r in (result.get("rows") or [])
    ]


def top_pages(
    config: dict[str, Any],
    days: int = 28,
    limit: int = 10,
    crawlseo_service: Any | None = None,
) -> list[dict[str, Any]]:
    if _source(config) == "crawlseo":
        return _crawlseo_summary(config, crawlseo_service)["top_pages"][:limit]
    result = _run(
        config,
        {
            "dateRanges": [
                {"startDate": f"{days}daysAgo", "endDate": "yesterday"},
            ],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}],
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
            "limit": limit,
        },
    )
    return [
        {"path": r["dimensionValues"][0]["value"], "views": int(r["metricValues"][0]["value"])}
        for r in (result.get("rows") or [])
    ]


def organic_queries(
    config: dict[str, Any],
    days: int = 28,
    limit: int = 10,
    crawlseo_service: Any | None = None,
) -> list[dict[str, Any]]:
    """Search queries that brought visitors — requires the GA4<->Search
    Console product link (Admin > Product links), then ~24-48h of data."""
    if _source(config) == "crawlseo":
        return _crawlseo_summary(config, crawlseo_service)["organic_queries"][:limit]
    end = datetime.date.today() - datetime.timedelta(days=1)
    result = _run(
        config,
        {
            "dateRanges": [{"startDate": (end - datetime.timedelta(days=days - 1)).isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": "googleOrganicSearchQuery"}],
            "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "screenPageViews"}],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": limit,
        },
    )
    return [
        {
            "query": r["dimensionValues"][0]["value"],
            "sessions": int(r["metricValues"][0]["value"]),
            "users": int(r["metricValues"][1]["value"]),
            "views": int(r["metricValues"][2]["value"]),
        }
        for r in (result.get("rows") or [])
    ]


def weekly_summary(config: dict[str, Any], crawlseo_service: Any | None = None) -> dict[str, Any]:
    if _source(config) == "crawlseo":
        return _crawlseo_summary(config, crawlseo_service)

    end = datetime.date.today() - datetime.timedelta(days=1)
    this_start = (end - datetime.timedelta(days=6)).isoformat()
    prev_end = (end - datetime.timedelta(days=7)).isoformat()
    prev_start = (end - datetime.timedelta(days=13)).isoformat()
    current = _totals(config, this_start, end.isoformat())
    previous = _totals(config, prev_start, prev_end)
    delta = {}
    for key, value in current.items():
        old = previous.get(key, 0)
        delta[key] = round((value - old) / old * 100, 1) if old else None

    try:
        queries = organic_queries(config, days=7)
    except Exception:  # noqa: BLE001 — no GSC link yet must not break traffic reporting
        queries = []
    return {
        "current_week": current,
        "previous_week": previous,
        "delta_pct": delta,
        "top_pages": top_pages(config, days=7),
        "sources": traffic_sources(config, days=7),
        "organic_queries": queries,
    }
