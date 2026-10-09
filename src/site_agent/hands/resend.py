"""Restricted Resend API used by shared tenant email provisioning."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

API = "https://api.resend.com"


class ResendError(RuntimeError):
    """A Resend API or DNS preflight error safe for provisioning diagnostics."""


class ResendCredentialError(ResendError):
    """The configured credential cannot perform management operations."""


class ResendVerificationPending(ResendError):
    """Resend accepted domain verification but has not completed it yet."""


def _domain_name(name: object, domain: str) -> str:
    value = str(name or "").strip().lower().rstrip(".")
    if value in {"", "@"}:
        return domain
    return value if value == domain or value.endswith("." + domain) else f"{value}.{domain}"


def _dns_content(record_type: str, content: object) -> str:
    value = str(content or "").strip().strip('"')
    if record_type in {"MX", "CNAME"}:
        return value.lower().rstrip(".")
    return value


def _dns_key(record: Mapping[str, Any], domain: str) -> tuple[str, str, str, int]:
    record_type = str(record.get("type") or "").upper()
    return (
        record_type,
        _domain_name(record.get("name"), domain),
        _dns_content(record_type, record.get("content", record.get("value"))),
        int(record.get("priority") or 0),
    )


class ResendProvisioner:
    """Provision a verified sender domain and a send-only tenant key."""

    def __init__(self, api_key: str, cloudflare_email_client: Any, *, timeout_seconds: float = 25.0) -> None:
        self._api_key = str(api_key or "").strip()
        self._cloudflare = cloudflare_email_client
        self._timeout = float(timeout_seconds)
        if not self._api_key:
            raise ResendError("The protected Resend management API key is not configured")

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            API + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "site-agent/0.1 (+https://helloada.app)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_payload = json.loads(exc.read(64 * 1024).decode("utf-8", "replace"))
            except (ValueError, UnicodeError):
                error_payload = {}
            if exc.code in {401, 403}:
                raise ResendCredentialError(
                    f"Resend rejected the management credential (HTTP {exc.code}); a Full access API key is required"
                ) from exc
            message = str(error_payload.get("message") or error_payload.get("name") or "Resend rejected the request")[:300]
            raise ResendError(f"Resend API returned HTTP {exc.code}: {message}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
            raise ResendError(f"Resend API request failed: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise ResendError("Resend API returned an invalid response")
        return payload

    def _domains(self) -> list[dict[str, Any]]:
        domains: list[dict[str, Any]] = []
        after = ""
        for _ in range(100):
            query = "?limit=100" + ("&after=" + urllib.parse.quote(after, safe="") if after else "")
            payload = self._request("GET", "/domains" + query)
            batch = payload.get("data")
            if not isinstance(batch, list):
                raise ResendError("Resend domain list did not contain a data array")
            domains.extend(dict(item) for item in batch if isinstance(item, Mapping))
            if payload.get("has_more") is not True:
                return domains
            if not batch or not isinstance(batch[-1], Mapping) or not batch[-1].get("id"):
                raise ResendError("Resend domain pagination returned no continuation identity")
            after = str(batch[-1]["id"])
        raise ResendError("Resend domain lookup exceeded the safe pagination limit")

    def validate_management_access(self) -> None:
        """Prove this key can read managed domains without changing provider state."""
        payload = self._request("GET", "/domains?limit=1")
        if not isinstance(payload.get("data"), list):
            raise ResendError("Resend domain preflight did not return a data array")

    def _get_domain(self, domain_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/domains/{urllib.parse.quote(domain_id, safe='')}")
        result = payload.get("data", payload)
        if not isinstance(result, Mapping) or not result.get("id"):
            raise ResendError("Resend domain response is incomplete")
        return dict(result)

    def _create_domain(self, domain: str) -> dict[str, Any]:
        payload = self._request("POST", "/domains", {
            "name": domain,
            "open_tracking": False,
            "click_tracking": False,
        })
        result = payload.get("data", payload)
        if not isinstance(result, Mapping) or not result.get("id"):
            raise ResendError("Resend did not return an identity for the new sender domain")
        return dict(result)

    def _dns_plan(self, domain: str, provider_records: object, existing_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(provider_records, list) or not provider_records:
            raise ResendError("Resend did not declare sender authentication DNS records")
        desired: list[dict[str, Any]] = []
        for item in provider_records:
            if not isinstance(item, Mapping):
                raise ResendError("Resend returned an invalid sender DNS record")
            record_type = str(item.get("type") or "").upper()
            name = _domain_name(item.get("name"), domain)
            content = str(item.get("value") or "").strip()
            if record_type not in {"TXT", "MX", "CNAME"} or not content or not name.endswith("." + domain) and name != domain:
                raise ResendError("Resend returned an unsupported or out-of-zone DNS record")
            record = {"type": record_type, "name": name, "content": content}
            if record_type == "MX":
                record["priority"] = int(item.get("priority") or 10)
            desired.append(record)

        current = [_dns_key(item, domain) for item in existing_records]
        planned: list[dict[str, Any]] = []
        for record in desired:
            key = _dns_key(record, domain)
            same_name = [entry for entry in current if entry[1] == key[1]]
            exact = [entry for entry in same_name if entry == key]
            if len(exact) > 1:
                raise ResendError(f"Duplicate Resend DNS record already exists at {key[1]}")
            if exact:
                continue
            if any(entry[0] == "CNAME" or key[0] == "CNAME" for entry in same_name):
                raise ResendError(f"A conflicting CNAME already exists at {key[1]}; no DNS record was changed")
            if any(entry[0] == key[0] for entry in same_name):
                raise ResendError(f"A conflicting {key[0]} record already exists at {key[1]}; no DNS record was changed")
            planned.append(record)
            current.append(key)
        return planned

    def ensure_domain(self, domain: str) -> dict[str, Any]:
        normalized = str(domain or "").strip().lower().rstrip(".")
        if not normalized or "/" in normalized:
            raise ResendError("The registered sender domain is invalid")
        matches = [item for item in self._domains() if str(item.get("name") or "").lower().rstrip(".") == normalized]
        if len(matches) > 1:
            raise ResendError("Resend reports duplicate sender domains for this tenant")
        if matches:
            identity = str(matches[0].get("id") or "")
            if not identity:
                raise ResendError("The registered Resend sender domain has no provider identity")
            provider_domain = self._get_domain(identity)
        else:
            # Avoid reserving a Resend domain when its well-known DNS names are
            # already occupied by another service.
            zone = self._cloudflare.zone(normalized)
            zone_id = str(zone.get("id") or "")
            current = self._cloudflare.dns_records(zone_id)
            blocked_names = {
                f"resend._domainkey.{normalized}", f"send.{normalized}", f"links.{normalized}",
            }
            if any(str(item.get("name") or "").lower().rstrip(".") in blocked_names for item in current):
                raise ResendError("A Resend authentication hostname already has DNS records; no provider domain was created")
            try:
                provider_domain = self._create_domain(normalized)
            except ResendError:
                # Concurrent tenant setup may have created the shared sender
                # domain, or the create response may have been lost. Reconcile
                # only if the exact domain now exists once in this account.
                matches = [
                    item for item in self._domains()
                    if str(item.get("name") or "").lower().rstrip(".") == normalized
                ]
                if len(matches) != 1 or not matches[0].get("id"):
                    raise
                provider_domain = self._get_domain(str(matches[0]["id"]))

        identity = str(provider_domain.get("id") or "")
        records = provider_domain.get("records")
        if not identity or not isinstance(records, list):
            provider_domain = self._get_domain(identity)
            records = provider_domain.get("records")
        if not isinstance(records, list) or not records:
            raise ResendError("Resend did not return DNS records for the sender domain")

        zone = self._cloudflare.zone(normalized)
        zone_id = str(zone.get("id") or "")
        zone_name = str(zone.get("name") or "").lower().rstrip(".")
        if not zone_name or (normalized != zone_name and not normalized.endswith("." + zone_name)):
            raise ResendError("The Resend sender domain is not covered by its registered Cloudflare zone")
        existing = self._cloudflare.dns_records(zone_id)
        plan = self._dns_plan(normalized, records, existing)
        # Preflight the complete record set before the first DNS mutation.
        for record in plan:
            try:
                self._cloudflare.create_dns_record(zone_id, record)
            except Exception:
                # A different provisioning call may have committed the exact
                # same record after preflight. Accept only one exact observed
                # record; conflicts and ambiguous absence remain hard errors.
                desired_key = _dns_key(record, normalized)
                observed = [
                    _dns_key(item, normalized)
                    for item in self._cloudflare.dns_records(zone_id)
                    if _dns_key(item, normalized) == desired_key
                ]
                if len(observed) != 1:
                    raise

        provider_domain = self._get_domain(identity)
        status = str(provider_domain.get("status") or "")
        if status != "verified" and status != "pending":
            self._request("POST", f"/domains/{urllib.parse.quote(identity, safe='')}/verify")
            provider_domain = self._get_domain(identity)
            status = str(provider_domain.get("status") or "")
        if status != "verified":
            if status not in {"pending", "not_started"}:
                raise ResendError(f"Resend reports sender-domain verification status {status or 'unknown'}")
            raise ResendVerificationPending("Resend is still verifying the sender domain; provisioning will check again automatically")
        return {"id": identity, "domain": normalized, "status": status, "dnsRecordsCreated": len(plan)}

    def api_keys(self) -> list[dict[str, Any]]:
        keys: list[dict[str, Any]] = []
        after = ""
        for _ in range(100):
            query = "?limit=100" + ("&after=" + urllib.parse.quote(after, safe="") if after else "")
            payload = self._request("GET", "/api-keys" + query)
            batch = payload.get("data")
            if not isinstance(batch, list):
                raise ResendError("Resend API key list did not contain a data array")
            keys.extend(dict(item) for item in batch if isinstance(item, Mapping))
            if payload.get("has_more") is not True:
                return keys
            if not batch or not isinstance(batch[-1], Mapping) or not batch[-1].get("id"):
                raise ResendError("Resend API key pagination returned no continuation identity")
            after = str(batch[-1]["id"])
        raise ResendError("Resend API key lookup exceeded the safe pagination limit")

    def api_keys_named(self, name: str) -> list[dict[str, Any]]:
        return [item for item in self.api_keys() if str(item.get("name") or "") == name]

    def delete_api_key(self, identity: str) -> None:
        key_identity = str(identity or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", key_identity):
            raise ResendError("A valid Resend API key identity is required for deletion")
        if not any(str(item.get("id") or "") == key_identity for item in self.api_keys()):
            return
        payload = self._request("DELETE", f"/api-keys/{urllib.parse.quote(key_identity, safe='')}")
        result = payload.get("data", payload)
        if not isinstance(result, Mapping) or result.get("deleted") is not True:
            if any(str(item.get("id") or "") == key_identity for item in self.api_keys()):
                raise ResendError("Resend did not confirm deletion of a tenant API key")

    def create_sending_key(self, name: str, domain_id: str) -> tuple[str, str]:
        label = str(name or "HelloAda tenant").strip()[:50] or "HelloAda tenant"
        domain_identity = str(domain_id or "").strip()
        if not domain_identity:
            raise ResendError("The verified Resend domain identity is unavailable for a restricted sender key")
        payload = self._request("POST", "/api-keys", {
            "name": label,
            "permission": "sending_access",
            "domain_id": domain_identity,
        })
        result = payload.get("data", payload)
        if not isinstance(result, Mapping):
            raise ResendError("Resend did not return the tenant sending credential")
        token = str(result.get("token") or "").strip()
        identity = str(result.get("id") or "").strip()
        if not token or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identity):
            raise ResendError("Resend returned an incomplete tenant sending credential")
        return identity, token


__all__ = ["ResendCredentialError", "ResendError", "ResendProvisioner", "ResendVerificationPending"]
