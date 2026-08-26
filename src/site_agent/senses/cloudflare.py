"""cloudflare.py — Cloudflare Pages deployment lookups (read-only)."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

CF_API = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    pass


def _request(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.load(resp)
    if not body.get("success"):
        raise CloudflareError(f"cloudflare api error: {body.get('errors')}")
    return body


def latest_preview_url(account_id: str, project: str, branch: str, token: str) -> str | None:
    """Most recent preview deployment for a branch, by alias URL."""
    url = (
        f"{CF_API}/accounts/{account_id}/pages/projects/{project}"
        f"/deployments?env=preview&per_page=10"
    )
    body = _request(url, token)
    for dep in body.get("result", []):
        trigger_branch = ((dep.get("deployment_trigger") or {}).get("metadata") or {}).get("branch")
        if trigger_branch == branch and dep.get("url"):
            return dep["url"]
    return None
