"""seo.py — Google Search Console sense (read-only), plus an MCP stub.

GSC queries are the highest-value SEO signal and free: what people actually
searched when your site appeared. Uses the same service-account pattern as
ga.py but with the webmasters.readonly scope. An MCP-based source can plug
in later behind source: "mcp" without touching callers.
"""

from __future__ import annotations

import datetime
import os
import json
import urllib.parse
import urllib.request
from typing import Any

API = "https://searchconsole.googleapis.com/webmasters/v3"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


class SeoError(RuntimeError):
    pass


def _settings(config: dict[str, Any]) -> tuple[str, str]:
    seo = config.get("seo") or {}
    ga = config.get("ga") or {}
    from .ga import DEFAULT_KEY_PATH

    key_path = str(seo.get("key_path") or ga.get("key_path") or os.environ.get("GA4_SERVICE_ACCOUNT") or DEFAULT_KEY_PATH)
    site_url = str(seo.get("site_url") or "")
    return key_path, site_url


def _token(key_path: str) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:
        raise SeoError("google-auth not installed; run pip install 'site-agent[ga]'") from exc
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token


def _run(config: dict[str, Any], body: dict[str, Any], timeout: int = 25) -> dict[str, Any]:
    source = str((config.get("seo") or {}).get("source", "gsc"))
    if source == "mcp":
        raise SeoError("seo.source=mcp arrives later; use 'gsc' for now")
    key_path, site_url = _settings(config)
    if not key_path or not site_url:
        raise SeoError("gsc not configured: set seo.site_url and seo.key_path (or reuse ga.key_path)")
    encoded = urllib.parse.quote(site_url, safe="")
    req = urllib.request.Request(
        f"{API}/sites/{encoded}/searchAnalytics/query",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_token(key_path)}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def top_queries(config: dict[str, Any], days: int = 28, limit: int = 10) -> list[dict[str, Any]]:
    today = datetime.date.today()
    body = {
        "startDate": (today - datetime.timedelta(days=days - 1)).isoformat(),
        "endDate": today.isoformat(),
        "dimensions": ["query"],
        "rowLimit": limit,
    }
    result = _run(config, body)
    keys_headers = [d["name"] for d in result.get("dimensionHeaders", [])]
    out = []
    for row in result.get("rows", []):
        entry = {
            "clicks": round(row["clicks"], 2),
            "impressions": row["impressions"],
            "ctr": round(row["ctr"], 4),
            "position": round(row["position"], 1),
        }
        if keys_headers:
            entry["query"] = row["keys"][0]
        out.append(entry)
    return out


def summary(config: dict[str, Any], days: int = 28) -> dict[str, Any]:
    return {"period_days": days, "top_queries": top_queries(config, days=days)}
