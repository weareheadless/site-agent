"""Cloudflare Workers custom domains for a tenant's public hostnames.

A custom domain is the supported way to serve a tenant's own hostname from its
Worker: Cloudflare owns the DNS record, the certificate and the route. This
client only touches the Workers Domains API; it never edits DNS records, so a
mail MX or a third-party CNAME is never collateral damage.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

CF_API = "https://api.cloudflare.com/client/v4"
USER_AGENT = "site-agent/0.1 (+https://helloada.app)"


class CloudflareDomainsError(RuntimeError):
    """A Worker custom domain could not be read or changed."""


def _error_message(payload: Mapping[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, Mapping):
            return str(first.get("message") or "Cloudflare API error")[:300]
    return "Cloudflare API error"


class CloudflareDomainsClient:
    """The Workers Domains surface of one Cloudflare account."""

    def __init__(self, api_token: str, account_id: str, *, timeout_seconds: float = 30.0) -> None:
        token = str(api_token or "").strip()
        account = str(account_id or "").strip()
        if not token:
            raise CloudflareDomainsError("Cloudflare Worker API token is missing")
        if not account:
            raise CloudflareDomainsError("Cloudflare account id is missing")
        self._token = token
        self._account_id = account
        self._timeout = float(timeout_seconds)

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(dict(body)).encode() if body is not None else None
        request = urllib.request.Request(
            CF_API + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {"success": True, "result": None}
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode() or "{}")
            except (ValueError, UnicodeError):
                payload = {}
            raise CloudflareDomainsError(_error_message(payload)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudflareDomainsError(
                f"Cloudflare Worker domains request failed: {type(exc).__name__}"
            ) from exc

    @property
    def _collection(self) -> str:
        return f"/accounts/{urllib.parse.quote(self._account_id, safe='')}/workers/domains"

    def list(self) -> list[dict[str, Any]]:
        """Every custom domain attached in this account."""
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"page": page, "per_page": 100})
            payload = self._request("GET", f"{self._collection}?{query}")
            if not payload.get("success"):
                raise CloudflareDomainsError(_error_message(payload))
            batch = [dict(item) for item in (payload.get("result") or []) if isinstance(item, Mapping)]
            rows.extend(batch)
            info = payload.get("result_info")
            total_pages = info.get("total_pages") if isinstance(info, Mapping) else None
            if total_pages is not None:
                try:
                    if page >= int(total_pages):
                        return rows
                except (TypeError, ValueError) as exc:
                    raise CloudflareDomainsError("Cloudflare domain pagination is invalid") from exc
            if len(batch) < 100:
                return rows
            page += 1

    def for_hostname(self, hostname: str) -> dict[str, Any] | None:
        host = str(hostname or "").strip().lower().rstrip(".")
        for row in self.list():
            if str(row.get("hostname") or "").strip().lower().rstrip(".") == host:
                return row
        return None

    def attach(self, *, zone_id: str, hostname: str, service: str) -> dict[str, Any]:
        payload = self._request(
            "PUT",
            self._collection,
            {
                "zone_id": str(zone_id or "").strip(),
                "hostname": str(hostname or "").strip().lower().rstrip("."),
                "service": str(service or "").strip(),
                "environment": "production",
            },
        )
        result = payload.get("result")
        if not payload.get("success") or not isinstance(result, Mapping):
            raise CloudflareDomainsError(_error_message(payload))
        return dict(result)

    def detach(self, domain_id: str) -> None:
        payload = self._request(
            "DELETE",
            f"{self._collection}/{urllib.parse.quote(str(domain_id or '').strip(), safe='')}",
        )
        if not payload.get("success", True):
            raise CloudflareDomainsError(_error_message(payload))


__all__ = ["CloudflareDomainsClient", "CloudflareDomainsError"]
