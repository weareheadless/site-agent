"""Client for CrawlSEO's internal, idempotent project-provisioning endpoint.

Ada calls this once per tenant. The endpoint returns a project-scoped service
credential (``cseo_...``) the first time only, so the caller must persist it
immediately; a repeat call with the same idempotency key returns no token.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any


USER_AGENT = "site-agent/0.1 (+https://helloada.app)"


class CrawlSEOProvisioningError(RuntimeError):
    """A safe, customer-readable provisioning failure."""


class CrawlSEOProvisioningClient:
    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 90.0) -> None:
        url = str(base_url or "").strip()
        secret = str(token or "").strip()
        if not url:
            raise CrawlSEOProvisioningError("CrawlSEO provisioning URL is missing")
        if not secret:
            raise CrawlSEOProvisioningError("CrawlSEO provisioning token is missing")
        self._url = url
        self._token = secret
        self._timeout = float(timeout_seconds)

    def provision(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = json.dumps(dict(payload), default=str).encode()
        request = urllib.request.Request(
            self._url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode() or "{}")
                message = str(detail.get("error") or "provisioning failed")
            except (ValueError, UnicodeError):
                message = "provisioning failed"
            raise CrawlSEOProvisioningError(f"{message} (HTTP {exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CrawlSEOProvisioningError(f"CrawlSEO request failed: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise CrawlSEOProvisioningError("CrawlSEO returned an unexpected response")
        if not body.get("project_id"):
            raise CrawlSEOProvisioningError(str(body.get("error") or "CrawlSEO did not return a project"))
        return body


__all__ = ["CrawlSEOProvisioningClient", "CrawlSEOProvisioningError"]
