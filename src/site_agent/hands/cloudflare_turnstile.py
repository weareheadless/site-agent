"""Tenant-scoped Cloudflare Turnstile widget provisioning."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from site_agent.hands.cloudflare_resources import CloudflareResourceError, CloudflareResourceProvisioner


@dataclass(frozen=True)
class TurnstileWidgetReceipt:
    name: str
    sitekey: str
    secret: str = field(repr=False)
    domains: tuple[str, ...] = ()
    created: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "sitekey": self.sitekey, "domains": list(self.domains), "created": self.created}


class CloudflareTurnstileProvisioner(CloudflareResourceProvisioner):
    """Create one durable widget per tenant and reconcile its exact hostname set."""

    def ensure_widget(
        self,
        tenant: str,
        domains: Sequence[str],
        *,
        sitekey: str | None = None,
        secret: str | None = None,
    ) -> TurnstileWidgetReceipt:
        tenant = str(tenant or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", tenant):
            raise CloudflareResourceError("Turnstile tenant identity is invalid")
        name = f"helloada-{tenant}-forms"
        normalized = self._domains(domains)
        has_sitekey = bool(str(sitekey or "").strip())
        has_secret = bool(str(secret or "").strip())
        if has_sitekey != has_secret:
            raise CloudflareResourceError("registered Turnstile sitekey and secret must be stored together")

        created = False
        if has_sitekey:
            widget = self._get_widget(str(sitekey).strip())
            if widget.get("name") != name or widget.get("sitekey") != sitekey:
                raise CloudflareResourceError("registered Turnstile widget identity differs from this tenant")
            live_secret = str(widget.get("secret") or "").strip()
            if live_secret and live_secret != secret:
                raise CloudflareResourceError("registered Turnstile secret differs from Cloudflare")
            resolved_secret = str(secret)
        else:
            matches = self._find_named(name)
            if len(matches) > 1:
                raise CloudflareResourceError("multiple Cloudflare Turnstile widgets match one tenant identity")
            if matches:
                widget = self._get_widget(str(matches[0].get("sitekey") or ""))
                if widget.get("name") != name:
                    raise CloudflareResourceError("Cloudflare Turnstile lookup returned a different widget")
                resolved_secret = str(widget.get("secret") or "").strip()
                if not resolved_secret:
                    widget = self._request_widget(
                        "POST",
                        f"/accounts/{self.account_id}/challenges/widgets/{urllib.parse.quote(str(widget.get('sitekey') or ''), safe='')}/rotate_secret",
                        {"invalidate_immediately": False},
                    )
                    resolved_secret = str(widget.get("secret") or "").strip()
                sitekey = str(widget.get("sitekey") or "").strip()
            else:
                widget = self._request_widget(
                    "POST",
                    f"/accounts/{self.account_id}/challenges/widgets",
                    {"name": name, "domains": list(normalized), "mode": "managed", "region": "world"},
                )
                sitekey = str(widget.get("sitekey") or "").strip()
                resolved_secret = str(widget.get("secret") or "").strip()
                created = True
            if not sitekey or not resolved_secret:
                raise CloudflareResourceError("Cloudflare did not return the tenant's Turnstile key pair")

        current_domains = self._domains(widget.get("domains") or [])
        if current_domains != normalized:
            widget = self._request_widget(
                "PUT",
                f"/accounts/{self.account_id}/challenges/widgets/{urllib.parse.quote(str(sitekey), safe='')}",
                {"name": name, "domains": list(normalized), "mode": str(widget.get("mode") or "managed")},
            )
            if widget.get("sitekey") != sitekey or widget.get("name") != name:
                raise CloudflareResourceError("Cloudflare updated a different tenant Turnstile widget")
            if self._domains(widget.get("domains") or []) != normalized:
                raise CloudflareResourceError("Cloudflare did not apply the exact Turnstile hostname set")
        return TurnstileWidgetReceipt(name, str(sitekey), resolved_secret, normalized, created)

    def _domains(self, values: Sequence[str]) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise CloudflareResourceError("Turnstile hostnames must be a list")
        domains = set()
        for raw in values:
            domain = str(raw or "").strip().lower().rstrip(".")
            if not re.fullmatch(
                r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
                domain,
            ):
                raise CloudflareResourceError("Turnstile hostname is invalid")
            domains.add(domain)
        normalized = tuple(sorted(domains))
        if not normalized or len(normalized) > 10:
            raise CloudflareResourceError("Turnstile requires one to ten exact production hostnames")
        return normalized

    def _request_widget(self, method: str, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        status, body = self._request(method, path, payload=payload)
        result = body.get("result")
        if status not in {200, 201} or body.get("success") is not True or not isinstance(result, dict):
            raise CloudflareResourceError(self._error(body))
        return result

    def _get_widget(self, sitekey: str) -> dict[str, Any]:
        if not sitekey or len(sitekey) > 32:
            raise CloudflareResourceError("registered Turnstile sitekey is invalid")
        path = f"/accounts/{self.account_id}/challenges/widgets/{urllib.parse.quote(sitekey, safe='')}"
        status, body = self._request("GET", path)
        result = body.get("result")
        if status != 200 or body.get("success") is not True or not isinstance(result, dict):
            raise CloudflareResourceError(self._error(body))
        return result

    def _find_named(self, name: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        per_page = 100
        page = 1
        while True:
            query = urllib.parse.urlencode({"filter": f"name:{name}", "page": page, "per_page": per_page})
            status, body = self._request(
                "GET",
                f"/accounts/{self.account_id}/challenges/widgets?{query}",
            )
            rows = body.get("result")
            if status != 200 or body.get("success") is not True or not isinstance(rows, list):
                raise CloudflareResourceError(self._error(body))
            matches.extend(row for row in rows if isinstance(row, dict) and row.get("name") == name)
            info = body.get("result_info") if isinstance(body.get("result_info"), dict) else {}
            total_count = int(info.get("total_count") or len(rows))
            if page * per_page >= total_count:
                return matches
            page += 1
