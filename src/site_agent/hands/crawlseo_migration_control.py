"""Bounded host-authenticated reads of authoritative migration receipts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..credentials import credential_environment, credential_profile


class CrawlSEOMigrationControlError(ValueError):
    """Migration evidence could not be verified with the configured host."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CrawlSEOMigrationControlError("migration control endpoint redirects are not permitted")


class CrawlSEOMigrationControlClient:
    def __init__(self, provisioning_url: str, token: str):
        suffix = "/api/internal/projects/provision"
        parsed = urlsplit(provisioning_url)
        try:
            port = parsed.port
        except ValueError:
            raise CrawlSEOMigrationControlError("configured provisioning URL is invalid") from None
        mount = parsed.path.removesuffix(suffix)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or not parsed.path.endswith(suffix) or parsed.netloc.endswith(":")
                or port is not None and not 1 <= port <= 65535
                or mount and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", mount)):
            raise CrawlSEOMigrationControlError("configured provisioning URL is invalid")
        if not token:
            raise CrawlSEOMigrationControlError("host provisioning credential is unavailable")
        self._base = f"https://{parsed.netloc}{mount}/api/internal"
        self._token = token

    @classmethod
    def from_config(cls, config: Mapping[str, Any], env: Mapping[str, str]):
        profile = credential_profile(config, "crawlseo")
        resolved = credential_environment(config, env)
        return cls(str(profile.get("provisioning_url") or ""),
                   str(resolved.get(str(profile.get("provisioning_token_env") or "")) or ""))

    def budget_import_receipt(self, receipt_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", receipt_id):
            raise CrawlSEOMigrationControlError("import receipt identity is invalid")
        request = Request(self._base + "/budget-imports?" + urlencode({"receiptId": receipt_id}), headers={
            "Authorization": "Bearer " + self._token, "Accept": "application/json",
            "Cache-Control": "no-store", "User-Agent": "HelloAda/migration-control",
        })
        try:
            with build_opener(_NoRedirect()).open(request, timeout=20) as response:
                if response.status != 200:
                    raise CrawlSEOMigrationControlError("import receipt was not available")
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise CrawlSEOMigrationControlError("import receipt exceeded the response limit")
        except HTTPError as exc:
            raise CrawlSEOMigrationControlError(f"import receipt lookup returned HTTP {exc.code}") from None
        except (URLError, OSError, TimeoutError):
            raise CrawlSEOMigrationControlError("import receipt lookup is unavailable") from None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CrawlSEOMigrationControlError("import receipt response is invalid") from None
        if not isinstance(result, dict) or result.get("id") != receipt_id:
            raise CrawlSEOMigrationControlError("import receipt response has a different identity")
        return result
