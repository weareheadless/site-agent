"""cloudflare_pages — static site deployed via Cloudflare Pages.

Two modes:

  git (default, day-one path)
    The site repo is connected to a Cloudflare Pages project. Publishing is
    still a GitHub commit (inherited from GithubStatic); Cloudflare picks up
    the push and deploys automatically. status() reads the latest deployment
    from the Cloudflare API so the admin UI can show what is live.

  direct (planned for Phase 4)
    Upload a built directory straight to Pages via wrangler/API without any
    git wiring. Stubbed until the editor flow exists.

Config:
    site:
      adapter: cloudflare_pages
      repository: owner/repo        # source repo (same as github_static)
      branch: main
      content_path: content.json
      cloudflare:
        account_id: "<cf account id>"
        project_name: "<pages project>"
        mode: git                   # git | direct

Env: CLOUDFLARE_API_TOKEN (remappable via env.cloudflare_api_token).
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from ..config import resolve_secret as secret
from .base import AdapterError, register
from .github_static import GithubStatic

CF_API = "https://api.cloudflare.com/client/v4"


def _cf_request(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode())
    if not body.get("success"):
        raise AdapterError(f"cloudflare api error: {body.get('errors')}")
    return body


@register
class CloudflarePages(GithubStatic):
    name = "cloudflare_pages"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        cf = self.site.get("cloudflare") or {}
        self.account_id = str(cf.get("account_id", "")).strip()
        self.project = str(cf.get("project_name", "")).strip()
        self.mode = str(cf.get("mode", "git")).strip()

    def validate(self) -> None:
        super().validate()
        if self.mode not in ("git", "direct"):
            raise AdapterError(f"{self.name}: unknown cloudflare.mode '{self.mode}'")
        if self.mode == "git" and self.account_id and not self.project:
            raise AdapterError(f"{self.name}: site.cloudflare.account_id set but project_name missing")
        if self.mode == "direct":
            raise AdapterError(
                f"{self.name}: direct upload arrives in Phase 4; use mode 'git' "
                "(connect the repo to a Pages project and commits deploy automatically)"
            )

    def status(self) -> dict[str, Any]:
        base: dict[str, Any] = {"adapter": self.name, "mode": self.mode}
        token = secret(self.root, "cloudflare_api_token")
        if not (self.account_id and self.project and token):
            return {**base, "deployment": "unconfigured"}
        url = (
            f"{CF_API}/accounts/{self.account_id}/pages/projects/{self.project}"
            "/deployments?per_page=1"
        )
        body = _cf_request(url, token)
        result = body.get("result") or []
        if not result:
            return {**base, "deployment": "none"}
        dep = result[0]
        stage = dep.get("latest_stage") or {}
        return {
            **base,
            "deployment": {
                "id": dep.get("id"),
                "stage": stage.get("name"),
                "status": stage.get("status"),
                "modified_on": dep.get("modified_on"),
                "url": dep.get("url"),
                "environment": dep.get("environment"),
            },
        }
