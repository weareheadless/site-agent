"""One resolution of a tenant's public identity.

The tenant record owns the name, the registered domain, the public origin and
the Worker name. Every surface that needs an address (the owner handoff, the
workspace preview, the settings page, the deploy material) reads this resolver
instead of a copy that was written once at bootstrap time.

A derived URL is never stored as authority. When a Worker is renamed or a
domain is attached, only the record changes and every projection follows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .site_origin import SiteOriginError, normalize_site_origin


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _origin(value: object) -> str:
    """Return a canonical HTTPS origin, or an empty string when absent."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return normalize_site_origin(raw)
    except SiteOriginError:
        return ""


def _hostname(origin: str) -> str:
    return str(urlsplit(origin).hostname or "").lower().rstrip(".")


@dataclass(frozen=True)
class SiteIdentity:
    """The addresses a tenant is reachable at, resolved from its record."""

    tenant_id: str
    display_name: str
    worker_name: str
    worker_url: str
    public_url: str
    admin_url: str
    payload_url: str
    registered_domain: str
    canonical_host: str

    def to_dict(self) -> dict[str, str]:
        return {
            "tenantId": self.tenant_id,
            "displayName": self.display_name,
            "workerName": self.worker_name,
            "workerUrl": self.worker_url,
            "publicUrl": self.public_url,
            "adminUrl": self.admin_url,
            "payloadUrl": self.payload_url,
            "registeredDomain": self.registered_domain,
            "canonicalHost": self.canonical_host,
        }


def site_identity(tenant_id: str, config: Mapping[str, object] | None) -> SiteIdentity:
    """Resolve the current identity of one tenant from its registered record."""
    site = _mapping(_mapping(config).get("site"))
    deployment = _mapping(site.get("source_deployment"))
    payload = _mapping(site.get("payload"))

    public_url = _origin(site.get("public_url")) or _origin(site.get("url"))
    worker_url = _origin(site.get("preview_url")) or _origin(payload.get("url")) or public_url
    canonical_host = _hostname(public_url)
    registered = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if not registered:
        registered = canonical_host
    admin_url = f"{public_url.rstrip('/')}/admin" if public_url else ""
    return SiteIdentity(
        tenant_id=str(tenant_id or "").strip().lower(),
        display_name=str(_mapping(config).get("display_name") or "").strip(),
        worker_name=str(deployment.get("worker_name") or "").strip(),
        worker_url=worker_url,
        public_url=public_url,
        admin_url=admin_url,
        payload_url=_origin(payload.get("url")) or worker_url,
        registered_domain=registered,
        canonical_host=canonical_host,
    )


__all__ = ["SiteIdentity", "site_identity"]
