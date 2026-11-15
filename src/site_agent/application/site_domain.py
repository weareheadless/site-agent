"""A tenant's registered domain, attached and verified through Cloudflare.

One operation turns a domain the platform already controls in Cloudflare into
the tenant's public address:

1. both the apex and ``www`` become custom domains of the tenant's Worker, so a
   visitor never lands on a redirect Worker or a third-party host;
2. the tenant record records the registered domain and canonical origin, and
   every projection (SEO property, mailbox identity, deploy material) follows;
3. the public origin is probed, and a rebuild is requested so the site's
   compiled identity matches the address it is now served from.

Nothing here is tenant-specific. A conflicting custom domain or DNS record is a
reported conflict, never silently replaced unless the caller asks for it.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..credentials import (
    cloudflare_api_token,
    cloudflare_dns_api_token,
    cloudflare_env_names,
    credential_environment,
    github_api_token,
)
from ..hands.cloudflare_dns import CloudflareDNSError, CloudflareDNSClient
from ..hands.cloudflare_domains import CloudflareDomainsClient, CloudflareDomainsError

USER_AGENT = "site-agent/0.1 (+https://helloada.app)"
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PLACEHOLDER_CONTENT = {"100::", "192.0.2.1"}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class DomainConflict:
    """One reason a hostname cannot be attached without an explicit decision."""

    kind: str
    hostname: str
    detail: str
    service: str = ""
    records: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "hostname": self.hostname,
            "detail": self.detail,
            "service": self.service,
            "records": [
                {
                    "type": item.get("type"),
                    "name": item.get("name"),
                    "content": item.get("content"),
                    "proxied": bool(item.get("proxied")),
                }
                for item in self.records
            ],
        }


class SiteDomainError(RuntimeError):
    """A tenant domain could not be attached or read."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        conflict: DomainConflict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.conflict = conflict


def registered_domain(value: str) -> str:
    """Return the registrable hostname a tenant is registered under.

    ``https://www.example.com/``, ``www.example.com`` and ``example.com`` all
    describe the tenant ``example.com``. The leading ``www`` is a serving
    convention, not part of the registration.
    """
    raw = str(value or "").strip().lower()
    if "://" in raw:
        raw = str(urllib.parse.urlsplit(raw).hostname or "")
    host = raw.strip().strip("/").rstrip(".")
    if host.startswith("www."):
        host = host[len("www."):]
    labels = [part for part in host.split(".") if part]
    if len(labels) < 2 or not all(_HOST_LABEL.fullmatch(part) for part in labels):
        raise SiteDomainError("enter a domain such as example.com", status_code=422)
    return host


def canonical_host(domain: str, canonical: str = "www") -> str:
    host = registered_domain(domain)
    choice = str(canonical or "www").strip().lower()
    if choice not in {"apex", "www"}:
        raise SiteDomainError("canonical host must be apex or www", status_code=422)
    return host if choice == "apex" else f"www.{host}"


class SiteDomainService:
    """Cloudflare side of one tenant's registered domain."""

    def __init__(self, config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> None:
        self.config = config
        self.env = dict(env or {})
        self._dns: CloudflareDNSClient | None = None
        self._domains: CloudflareDomainsClient | None = None

    # -- credentials -----------------------------------------------------

    def _dns_client(self) -> CloudflareDNSClient:
        if self._dns is not None:
            return self._dns
        token = cloudflare_dns_api_token(self.config, self.env)
        if not token:
            raise SiteDomainError("the Cloudflare DNS credential is unavailable", status_code=503)
        self._dns = CloudflareDNSClient(token)
        return self._dns

    def _domains_client(self) -> CloudflareDomainsClient:
        if self._domains is not None:
            return self._domains
        resolved = credential_environment(self.config, self.env)
        token = cloudflare_api_token(self.config, resolved)
        account_name = cloudflare_env_names(self.config)[1]
        account_id = str(resolved.get(account_name) or "").strip()
        if not token or not account_id:
            raise SiteDomainError("the Cloudflare Worker credential is unavailable", status_code=503)
        self._domains = CloudflareDomainsClient(token, account_id)
        return self._domains

    # -- reads -----------------------------------------------------------

    def zone(self, domain: str) -> dict[str, Any]:
        try:
            return self._dns_client().zone_for_hostname(domain)
        except CloudflareDNSError as exc:
            raise SiteDomainError(
                f"{domain} is not in the platform Cloudflare account; "
                "point its nameservers here first",
                status_code=409,
            ) from exc

    def status(self, identity: Any) -> dict[str, Any]:
        """The domain's Cloudflare and serving state, tolerant of outages."""
        domain = str(getattr(identity, "registered_domain", "") or "")
        result: dict[str, Any] = {
            "registeredDomain": domain,
            "publicUrl": str(getattr(identity, "public_url", "") or ""),
            "canonicalHost": str(getattr(identity, "canonical_host", "") or ""),
            "zone": None,
            "customDomains": [],
            "serving": {"ok": False, "status": None, "reason": "not checked"},
            "available": True,
            "reason": "",
        }
        if not domain:
            result["available"] = False
            result["reason"] = "no registered domain"
            return result
        try:
            zone = self.zone(domain)
            result["zone"] = {
                "id": zone.get("id"),
                "name": zone.get("name"),
                "status": zone.get("status"),
            }
        except SiteDomainError as exc:
            result["available"] = False
            result["reason"] = str(exc)
        try:
            worker = str(getattr(identity, "worker_name", "") or "")
            result["customDomains"] = [
                {
                    "hostname": row.get("hostname"),
                    "service": row.get("service"),
                    "certId": row.get("cert_id"),
                }
                for row in self._domains_client().list()
                if str(row.get("service") or "") == worker
            ]
        except (SiteDomainError, CloudflareDomainsError) as exc:
            result["available"] = False
            result["reason"] = str(exc)
        result["serving"] = self.probe(result["publicUrl"])
        return result

    @staticmethod
    def probe(url: str, *, timeout_seconds: float = 6.0) -> dict[str, Any]:
        target = str(url or "").strip()
        if not target:
            return {"ok": False, "status": None, "reason": "no public origin"}
        request = urllib.request.Request(
            target,
            method="GET",
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return {
                    "ok": 200 <= int(response.status) < 300,
                    "status": int(response.status),
                    "finalUrl": str(response.geturl() or target),
                }
        except urllib.error.HTTPError as exc:
            return {
                "ok": False,
                "status": int(exc.code),
                "finalUrl": str(exc.geturl() or target),
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status": None, "reason": type(exc).__name__}

    # -- attach ----------------------------------------------------------

    def attach(
        self,
        *,
        domain: str,
        worker_name: str,
        canonical: str = "www",
        replace_dns: bool = False,
        takeover: bool = False,
    ) -> dict[str, Any]:
        registered = registered_domain(domain)
        host = canonical_host(registered, canonical)
        worker = str(worker_name or "").strip()
        if not worker:
            raise SiteDomainError("this website has no registered Worker", status_code=409)
        zone = self.zone(registered)
        zone_id = str(zone.get("id") or "")
        if not zone_id:
            raise SiteDomainError("the Cloudflare zone has no identity", status_code=409)

        # Decide everything before changing anything: a conflict on the second
        # hostname must not leave the first one already moved off another
        # Worker's service.
        plan: list[dict[str, Any]] = []
        for hostname in dict.fromkeys((registered, f"www.{registered}")):
            existing = self._domains_client().for_hostname(hostname)
            service = str((existing or {}).get("service") or "")
            if existing is not None and service == worker:
                plan.append({"hostname": hostname, "state": "kept", "existing": existing})
                continue
            if existing is not None and not takeover:
                raise SiteDomainError(
                    f"{hostname} is already attached to {service or 'another service'}",
                    conflict=DomainConflict(
                        kind="custom_domain",
                        hostname=hostname,
                        detail="another Worker owns this hostname",
                        service=service,
                    ),
                )
            conflicts = self._dns_conflicts(zone_id, hostname)
            if conflicts and not replace_dns:
                raise SiteDomainError(
                    f"{hostname} already has DNS records that would block the Worker",
                    conflict=DomainConflict(
                        kind="dns_record",
                        hostname=hostname,
                        detail="existing DNS records point somewhere else",
                        records=tuple(conflicts),
                    ),
                )
            plan.append({
                "hostname": hostname,
                "state": "attach",
                "existing": existing,
                "records": conflicts,
            })

        attached: list[str] = []
        kept: list[str] = []
        for step in plan:
            hostname = str(step["hostname"])
            if step["state"] == "kept":
                kept.append(hostname)
                continue
            existing = step.get("existing")
            if isinstance(existing, Mapping):
                self._domains_client().detach(str(existing.get("id") or ""))
            for record in step.get("records") or []:
                self._dns_client().delete_record(zone_id, str(record.get("id") or ""))
            self._domains_client().attach(zone_id=zone_id, hostname=hostname, service=worker)
            attached.append(hostname)
        return {
            "registeredDomain": registered,
            "canonicalHost": host,
            "publicUrl": f"https://{host}/",
            "zone": {"id": zone_id, "name": zone.get("name"), "status": zone.get("status")},
            "hosts": [registered, f"www.{registered}"],
            "attached": attached,
            "kept": kept,
        }

    def _dns_conflicts(self, zone_id: str, hostname: str) -> list[dict[str, Any]]:
        rows = self._dns_client().records(zone_id, name=hostname)
        conflicts = []
        for row in rows:
            if str(row.get("type") or "") not in {"A", "AAAA", "CNAME"}:
                continue
            content = str(row.get("content") or "").strip()
            if bool(row.get("proxied")) and content in _PLACEHOLDER_CONTENT:
                continue
            conflicts.append(row)
        return conflicts


def request_site_rebuild(config: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    """Ask the tenant repository to deploy its current main again.

    A custom domain changes the address the site is compiled for, so the next
    release must build with the new public origin. The run is dispatched for the
    commit that is already main; the deploy material carries the new address.
    """
    site = _mapping(_mapping(config).get("site"))
    repository = str(site.get("repository") or "").strip().strip("/")
    if not repository:
        return {"state": "skipped", "reason": "no repository"}
    token = github_api_token(config, credential_environment(config, env))
    if not token:
        return {"state": "skipped", "reason": "no GitHub credential"}
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/git/ref/heads/main",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            head = json.loads(response.read().decode() or "{}")
        sha = str(_mapping(head.get("object")).get("sha") or "")
        if not sha:
            return {"state": "failed", "reason": "main has no commit"}
        dispatch = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/dispatches",
            data=json.dumps(
                {"event_type": "helloada-release", "client_payload": {"sha": sha}}
            ).encode(),
            method="POST",
            headers={**headers, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(dispatch, timeout=20) as response:
            if int(response.status) not in {201, 204}:
                return {"state": "failed", "reason": f"dispatch refused ({response.status})"}
    except urllib.error.HTTPError as exc:
        return {"state": "failed", "reason": f"GitHub refused the rebuild ({exc.code})"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"state": "failed", "reason": type(exc).__name__}
    return {"state": "queued", "sha": sha}


__all__ = [
    "DomainConflict",
    "SiteDomainError",
    "SiteDomainService",
    "canonical_host",
    "registered_domain",
    "request_site_rebuild",
]
