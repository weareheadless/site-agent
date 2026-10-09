"""Cloudflare Email Service API used by the tenant provisioning workflow.

This adapter contains no tenant policy. The application layer decides which
legacy records are explicitly authorized for cutover and which Worker owns a
mailbox. Every write uses Cloudflare's zone-scoped Email Sending and Email
Routing APIs; website DNS records are never touched here.
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


class CloudflareEmailError(RuntimeError):
    """A safe Cloudflare Email Service failure."""


def _errors(payload: Mapping[str, Any]) -> str:
    values = payload.get("errors")
    if isinstance(values, list) and values:
        messages = [str(item.get("message") or "") for item in values if isinstance(item, Mapping)]
        if messages:
            return "; ".join(messages)[:500]
    return "Cloudflare Email Service API rejected the request"


class CloudflareEmailClient:
    """Small, bounded API adapter for per-zone Email Sending and Routing."""

    def __init__(self, email_api_token: str, dns_api_token: str, *, timeout_seconds: float = 30.0) -> None:
        email_token = str(email_api_token or "").strip()
        dns_token = str(dns_api_token or "").strip()
        if not email_token:
            raise CloudflareEmailError("Cloudflare Email Service API token is missing")
        if not dns_token:
            raise CloudflareEmailError("Cloudflare DNS API token is missing")
        self._email_token = email_token
        self._dns_token = dns_token
        self._timeout = float(timeout_seconds)

    @staticmethod
    def _uses_dns_token(path: str) -> bool:
        return "/email/" not in path

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        token = self._dns_token if self._uses_dns_token(path) else self._email_token
        data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            CF_API + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read(64 * 1024).decode("utf-8", "replace"))
            except (ValueError, UnicodeError):
                payload = {}
            detail = _errors(payload) if isinstance(payload, Mapping) else "Cloudflare API error"
            raise CloudflareEmailError(f"Cloudflare Email API returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudflareEmailError(f"Cloudflare Email API request failed: {type(exc).__name__}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise CloudflareEmailError("Cloudflare Email API returned invalid JSON") from exc
        if not isinstance(payload, dict) or not payload.get("success"):
            raise CloudflareEmailError(_errors(payload if isinstance(payload, Mapping) else {}))
        return payload

    def zone(self, name: str) -> dict[str, Any]:
        clean = str(name or "").strip().lower().rstrip(".")
        if not clean or "/" in clean:
            raise CloudflareEmailError("A registered Cloudflare hostname is required")
        result = self.request("GET", f"/zones?name={urllib.parse.quote(clean)}&per_page=100").get("result") or []
        matches = [item for item in result if isinstance(item, Mapping) and str(item.get("name", "")).lower() == clean]
        if len(matches) > 1:
            raise CloudflareEmailError(f"Cloudflare zone is ambiguous: {clean}")
        if not matches:
            # A site's registered hostname can be www.example.com while its
            # Cloudflare zone is example.com. Resolve only from zones visible
            # to this token and choose the most-specific active parent zone.
            zones: list[dict[str, Any]] = []
            page = 1
            while page <= 100:
                payload = self.request("GET", f"/zones?per_page=100&page={page}")
                zones.extend(dict(item) for item in (payload.get("result") or []) if isinstance(item, Mapping))
                info = payload.get("result_info") or {}
                if not isinstance(info, Mapping) or page >= int(info.get("total_pages") or 1):
                    break
                page += 1
            else:
                raise CloudflareEmailError("Cloudflare zone lookup exceeded the safe pagination limit")
            parents = [
                item for item in zones
                if str(item.get("name") or "").lower().rstrip(".") == clean
                or clean.endswith("." + str(item.get("name") or "").lower().rstrip("."))
            ]
            if not parents:
                raise CloudflareEmailError(f"No Cloudflare zone owns the registered hostname: {clean}")
            most_specific = max(len(str(item.get("name") or "")) for item in parents)
            matches = [item for item in parents if len(str(item.get("name") or "")) == most_specific]
        if len(matches) != 1:
            raise CloudflareEmailError(f"Cloudflare zone is ambiguous: {clean}")
        zone = dict(matches[0])
        if zone.get("status") != "active" or not zone.get("id"):
            raise CloudflareEmailError(f"Cloudflare zone is not active for registered hostname: {clean}")
        return zone

    def dns_records(self, zone_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while page <= 100:
            payload = self.request("GET", f"/zones/{urllib.parse.quote(zone_id, safe='')}/dns_records?per_page=100&page={page}")
            records.extend(dict(item) for item in (payload.get("result") or []) if isinstance(item, Mapping))
            info = payload.get("result_info") or {}
            if not isinstance(info, Mapping) or page >= int(info.get("total_pages") or 1):
                return records
            page += 1
        raise CloudflareEmailError("Cloudflare DNS record listing exceeded the safe pagination limit")

    def routing_settings(self, zone_id: str) -> dict[str, Any]:
        return dict(self.request("GET", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing").get("result") or {})

    def routing_dns(self, zone_id: str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing/dns")
        result = payload.get("result") or []
        if not isinstance(result, list):
            raise CloudflareEmailError("Cloudflare Email Routing DNS response was not a record list")
        return [dict(item) for item in result if isinstance(item, Mapping)]

    def routing_rules(self, zone_id: str) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        page = 1
        while page <= 100:
            payload = self.request(
                "GET",
                f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing/rules?per_page=100&page={page}",
            )
            rules.extend(dict(item) for item in (payload.get("result") or []) if isinstance(item, Mapping))
            info = payload.get("result_info") or {}
            if not isinstance(info, Mapping) or page >= int(info.get("total_pages") or 1):
                return rules
            page += 1
        raise CloudflareEmailError("Cloudflare Email Routing rule listing exceeded the safe pagination limit")

    def catch_all(self, zone_id: str) -> dict[str, Any]:
        return dict(self.request("GET", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing/rules/catch_all").get("result") or {})

    def sending_domains(self, zone_id: str) -> list[dict[str, Any]]:
        domains: list[dict[str, Any]] = []
        page = 1
        while page <= 100:
            payload = self.request(
                "GET",
                f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/sending/subdomains?per_page=100&page={page}",
            )
            domains.extend(dict(item) for item in (payload.get("result") or []) if isinstance(item, Mapping))
            info = payload.get("result_info") or {}
            if not isinstance(info, Mapping) or page >= int(info.get("total_pages") or 1):
                return domains
            page += 1
        raise CloudflareEmailError("Cloudflare Email Sending domain listing exceeded the safe pagination limit")

    def sending_dns(self, zone_id: str, identifier: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        path = (
            f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/sending/subdomains/"
            f"{urllib.parse.quote(identifier, safe='')}/dns"
        )
        while page <= 100:
            payload = self.request("GET", f"{path}?per_page=100&page={page}")
            result = payload.get("result") or []
            if not isinstance(result, list):
                raise CloudflareEmailError("Cloudflare Email Sending DNS response was not a record list")
            records.extend(dict(item) for item in result if isinstance(item, Mapping))
            info = payload.get("result_info") or {}
            if not isinstance(info, Mapping) or page >= int(info.get("total_pages") or 1):
                return records
            page += 1
        raise CloudflareEmailError("Cloudflare Email Sending DNS listing exceeded the safe pagination limit")

    def ensure_sending_domain(self, zone_id: str, domain: str, existing: list[dict[str, Any]]) -> dict[str, Any]:
        found = [item for item in existing if str(item.get("name") or "").lower() == domain.lower()]
        if found:
            item = found[0]
            if item.get("enabled") is True and item.get("tag"):
                return item
        return dict(self.request("POST", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/sending/subdomains", {"name": domain}).get("result") or {})

    def enable_routing(self, zone_id: str) -> dict[str, Any]:
        # The API enables zone-apex routing when the POST body is omitted.
        # A `name` is only valid for a subdomain; sending the apex returns 422.
        return dict(self.request("POST", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing/dns").get("result") or {})

    def create_routing_rule(self, zone_id: str, *, address: str, worker: str, priority: int = 0) -> dict[str, Any]:
        body = {
            "name": f"HelloAda {address}",
            "enabled": True,
            "priority": priority,
            "source": "api",
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "worker", "value": [worker]}],
        }
        return dict(self.request("POST", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing/rules", body).get("result") or {})

    def update_routing_rule(self, zone_id: str, rule_id: str, rule: Mapping[str, Any], *, address: str, worker: str) -> dict[str, Any]:
        body = {
            "name": str(rule.get("name") or f"HelloAda {address}"),
            "enabled": True,
            "priority": int(rule.get("priority") or 0),
            "source": "api",
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "worker", "value": [worker]}],
        }
        return dict(self.request("PUT", f"/zones/{urllib.parse.quote(zone_id, safe='')}/email/routing/rules/{urllib.parse.quote(rule_id, safe='')}", body).get("result") or {})

    def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        self.request("DELETE", f"/zones/{urllib.parse.quote(zone_id, safe='')}/dns_records/{urllib.parse.quote(record_id, safe='')}")

    def upsert_dns_txt(self, zone_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        name = str(record.get("name") or "")
        existing = [item for item in self.dns_records(zone_id) if item.get("type") == "TXT" and item.get("name") == name]
        body = {key: record[key] for key in ("type", "name", "content", "ttl", "comment") if key in record}
        if len(existing) == 1:
            return dict(self.request("PUT", f"/zones/{urllib.parse.quote(zone_id, safe='')}/dns_records/{urllib.parse.quote(str(existing[0]['id']), safe='')}", body).get("result") or {})
        return dict(self.request("POST", f"/zones/{urllib.parse.quote(zone_id, safe='')}/dns_records", body).get("result") or {})


__all__ = ["CloudflareEmailClient", "CloudflareEmailError"]
