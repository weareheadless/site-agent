"""Cloudflare DNS records used for platform-managed domain verification.

The shared host credential profile only points at a token; this adapter owns
the small, fixed DNS surface Ada needs: publishing the Google site-verification
TXT record, ensuring the host resolves, and cleaning those records up again.
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


class CloudflareDNSError(RuntimeError):
    """A safe, customer-readable Cloudflare DNS failure."""


def _error_message(payload: Mapping[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, Mapping):
            return str(first.get("message") or "Cloudflare API error")[:300]
    return "Cloudflare API error"


class CloudflareDNSClient:
    """A bounded DNS-record client for the platform credential profile."""

    def __init__(self, api_token: str, *, timeout_seconds: float = 25.0) -> None:
        token = str(api_token or "").strip()
        if not token:
            raise CloudflareDNSError("Cloudflare DNS token is missing")
        self._token = token
        self._timeout = float(timeout_seconds)

    def _request(self, path: str, *, method: str = "GET", body: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode() or "{}")
            except (ValueError, UnicodeError):
                payload = {}
            raise CloudflareDNSError(_error_message(payload)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudflareDNSError(f"Cloudflare DNS request failed: {type(exc).__name__}") from exc

    def zone_id(self, zone_name: str) -> str:
        name = str(zone_name or "").strip().rstrip(".")
        if not name:
            raise CloudflareDNSError("zone name is required")
        payload = self._request(f"/zones?name={urllib.parse.quote(name)}&per_page=1")
        results = payload.get("result") or []
        if not payload.get("success") or not results:
            raise CloudflareDNSError(f"zone not found: {name}")
        return str(results[0].get("id") or "")

    def zone_id_for_hostname(self, hostname: str) -> str:
        """Resolve the authoritative Cloudflare zone for a hostname.

        Looking up ``example.com`` by taking everything after the first dot
        breaks apexes such as ``example.com`` (it produces ``com``) and nested
        delegated zones. Try the most specific candidate first and let
        Cloudflare identify the zone we actually control.
        """
        value = str(hostname or "").strip().lower().rstrip(".")
        labels = [part for part in value.split(".") if part]
        if len(labels) < 2:
            return self.zone_id(value)
        for index in range(0, len(labels) - 1):
            candidate = ".".join(labels[index:])
            try:
                return self.zone_id(candidate)
            except CloudflareDNSError:
                continue
        raise CloudflareDNSError(f"zone not found: {value}")

    def records(self, zone_id: str, *, record_type: str = "", name: str = "") -> list[dict[str, Any]]:
        query = [f"per_page=100"]
        if record_type:
            query.append(f"type={urllib.parse.quote(record_type)}")
        if name:
            query.append(f"name={urllib.parse.quote(name)}")
        payload = self._request(f"/zones/{zone_id}/dns_records?{'&'.join(query)}")
        if not payload.get("success"):
            raise CloudflareDNSError(_error_message(payload))
        return [dict(item) for item in (payload.get("result") or []) if isinstance(item, Mapping)]

    def upsert_txt(self, zone_id: str, name: str, content: str, *, ttl: int = 120) -> str:
        """Create or refresh one TXT record; returns the record id."""
        existing = self.records(zone_id, record_type="TXT", name=name)
        match = next((item for item in existing if str(item.get("content") or "").strip() == content.strip()), None)
        if match is None and existing:
            # A stale verification token from a previous attempt at the same
            # name is replaced rather than stacked.
            match = existing[0]
        body = {"type": "TXT", "name": name, "content": content, "ttl": ttl}
        if match:
            payload = self._request(f"/zones/{zone_id}/dns_records/{match['id']}", method="PUT", body=body)
        else:
            payload = self._request(f"/zones/{zone_id}/dns_records", method="POST", body=body)
        if not payload.get("success"):
            raise CloudflareDNSError(_error_message(payload))
        return str((payload.get("result") or {}).get("id") or "")

    def ensure_public_host(self, zone_id: str, name: str, *, target: str = "192.0.2.1") -> str:
        """Make a hostname resolve publicly with a proxied placeholder record.

        Verification and crawlers only need the name to resolve to a public
        address; the site itself is served by the platform Worker. Existing
        records are left untouched.
        """
        existing = [item for item in self.records(zone_id, name=name) if str(item.get("type") or "") in {"A", "AAAA", "CNAME"}]
        if existing:
            return str(existing[0].get("id") or "")
        payload = self._request(
            f"/zones/{zone_id}/dns_records",
            method="POST",
            body={"type": "A", "name": name, "content": target, "proxied": True, "ttl": 1},
        )
        if not payload.get("success"):
            raise CloudflareDNSError(_error_message(payload))
        return str((payload.get("result") or {}).get("id") or "")

    def delete_record(self, zone_id: str, record_id: str) -> bool:
        payload = self._request(f"/zones/{zone_id}/dns_records/{record_id}", method="DELETE")
        return bool(payload.get("success"))


__all__ = ["CloudflareDNSClient", "CloudflareDNSError"]
