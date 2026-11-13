"""Where a compiled candidate is served.

A compiled preview is a complete Next application. Serving it under a path that
belongs to the workspace app meant the app had to reproduce Next's URL
semantics — basePath root, RSC and prefetch headers, redirects, asset prefixes,
404s — and share a namespace the CMS also answered on. Every mismatch was
another broken preview.

A preview now has its own origin, ``preview.<platform host>``, and the path
``/p/<tenant>/<job>/<expiry>/<signature>``. One service owns that URL and the
process behind it and only forwards bytes, so nothing interprets the candidate's
links.

The address is self-describing: it names the tenant and the job, so a request
never depends on which browser call happened earlier in this process's lifetime,
and the service that answers it can restart without stranding an address it
already handed out. The signature is an HMAC over the same three values, so the
address is the capability: it needs no cookie (a cross-origin frame carries
none), it cannot be forged for another tenant or job, rotating the key retires
every address at once, and each one expires on its own.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

PREVIEW_PREFIX = "/p"
PREVIEW_SIGNING_KEY_ENV = "HELLOADA_PREVIEW_SIGNING_KEY"
PREVIEW_HOST_ENV = "HELLOADA_PREVIEW_HOST"
PREVIEW_DNS_HOST_ENV = "HELLOADA_PREVIEW_DNS_HOST"
PREVIEW_TTL_SECONDS = 7 * 24 * 60 * 60

_JOB = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{16}$")
# The same identity rule the tenant registry applies: a preview path segment is
# never a caller-controlled string.
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,120}$")
# A preview host is an origin, not an authority: no port, path or userinfo, and
# every label is a DNS label. The address is signed and published, so a value
# that is not a bare hostname must be refused rather than published.
_HOST = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


class PreviewHostError(RuntimeError):
    """A missing or invalid preview host configuration."""


def signing_key(env: Mapping[str, str]) -> str:
    key = str(env.get(PREVIEW_SIGNING_KEY_ENV) or "").strip()
    if len(key) < 32:
        raise PreviewHostError(f"{PREVIEW_SIGNING_KEY_ENV} must be a 32+ character secret")
    return key


def preview_host(env: Mapping[str, str]) -> str:
    host = str(env.get(PREVIEW_HOST_ENV) or "").strip().strip("/").lower()
    if not host or "/" in host or " " in host:
        raise PreviewHostError(f"{PREVIEW_HOST_ENV} is not configured")
    return host


def host_for(env: Mapping[str, str], config: Mapping[str, Any] | None = None) -> str:
    """The origin one site's previews are served at.

    A preview belongs to the site it compiles, so its address belongs to that
    site's domain: ``preview.<site domain>``. The platform host stays the
    fallback for a tenant that has not been given its own address, and a tenant
    config is the only place the choice lives, so the URL a build reports and
    the URL the workspace frames can never disagree.
    """
    preview = config.get("preview") if isinstance(config, Mapping) else None
    configured = str((preview or {}).get("host") or "").strip().strip("/").lower() if isinstance(preview, Mapping) else ""
    host = configured or preview_host(env)
    if not _HOST.fullmatch(host):
        raise PreviewHostError("preview host is not a safe hostname")
    return host


def origin(env: Mapping[str, str], config: Mapping[str, Any] | None = None) -> str:
    return f"https://{host_for(env, config)}"


def expiry_for(created_at: Any, *, now: float | None = None) -> int:
    """A stable expiry: one address per job, valid for as long as it can exist."""
    moment = _timestamp(created_at, now=now)
    return int(moment) + PREVIEW_TTL_SECONDS


def _timestamp(created_at: Any, *, now: float | None = None) -> float:
    raw = str(created_at or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
    return float(now if now is not None else time.time())


def signature(key: str, tenant: str, job: str, expires: int) -> str:
    message = f"{tenant}|{job}|{int(expires)}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:16]


def tenant_id(value: Any) -> str:
    """Normalize a tenant identity to the form the registry and signature use."""
    normalized = str(value or "").strip().lower()
    if not _TENANT.fullmatch(normalized):
        raise PreviewHostError("preview tenant is not a safe address")
    return normalized


def path_for(key: str, tenant: str, job: str, expires: int) -> str:
    owner = tenant_id(tenant)
    job_id = str(job or "").strip()
    if not _JOB.fullmatch(job_id):
        raise PreviewHostError("preview identity is invalid")
    return f"{PREVIEW_PREFIX}/{owner}/{job_id}/{int(expires)}/{signature(key, owner, job_id, expires)}"


def url_for(env: Mapping[str, str], tenant: str, job: str, expires: int,
            *, config: Mapping[str, Any] | None = None) -> str:
    return f"{origin(env, config)}{path_for(signing_key(env), tenant, job, expires)}"


def verify(key: str, tenant: str, job: str, expires: str, supplied: str, *, now: float | None = None) -> bool:
    """Accept only an unexpired address this service signed for this tenant."""
    job_id = str(job or "").strip()
    if not _JOB.fullmatch(job_id):
        return False
    if not _SIGNATURE.fullmatch(str(supplied or "").strip()):
        return False
    try:
        moment = int(str(expires).strip())
    except (TypeError, ValueError):
        return False
    if moment <= float(now if now is not None else time.time()):
        return False
    try:
        owner = tenant_id(tenant)
    except PreviewHostError:
        return False
    expected = signature(key, owner, job_id, moment)
    return hmac.compare_digest(expected.encode(), str(supplied).strip().encode())


def ensure_preview_host_dns(env: Mapping[str, str], *, config: Mapping[str, Any] | None = None,
                            host: str | None = None) -> dict[str, Any]:
    """Create a preview host's public record if the platform has not yet.

    The address follows the host that already serves the API, so a preview
    hostname needs no hand-made Cloudflare record and a fresh installation gets
    one the first time the API starts. ``host`` lets a site bring its own
    ``preview.<site domain>`` address instead of the platform-wide one.
    """
    from ..credentials import credential_profile
    from ..hands.cloudflare_dns import CloudflareDNSError, CloudflareDNSClient

    host = str(host or "").strip().strip("/").lower() or host_for(env, config)
    if not _HOST.fullmatch(host):
        raise PreviewHostError("preview host is not a safe hostname")
    anchor = str(env.get(PREVIEW_DNS_HOST_ENV) or "").strip().strip("/").lower()
    if not anchor:
        raise PreviewHostError(f"{PREVIEW_DNS_HOST_ENV} is not configured")
    profile = credential_profile(config, "cloudflare_dns")
    variable = str(profile.get("api_token_env") or "CLOUDFLARE_DNS_API_TOKEN")
    token = str(env.get(variable) or "")
    if not token:
        raise PreviewHostError(f"{variable} is not set")
    client = CloudflareDNSClient(token)
    try:
        zone = client.zone_id_for_hostname(host)
        anchor_records = [
            item for item in client.records(zone, name=anchor)
            if str(item.get("type") or "") in {"A", "AAAA", "CNAME"}
        ]
        if not anchor_records:
            raise PreviewHostError(f"{anchor} has no address to follow")
        target = str(anchor_records[0].get("content") or "").strip()
        record_type = str(anchor_records[0].get("type") or "A")
        client.ensure_public_host(zone, host, target=target)
        created = [
            item for item in client.records(zone, name=host)
            if str(item.get("type") or "") in {"A", "AAAA", "CNAME"}
        ]
    except CloudflareDNSError as exc:
        raise PreviewHostError(str(exc)[:300]) from exc
    if not created:
        raise PreviewHostError(f"{host} did not resolve to a record after provisioning")
    record = created[0]
    if not bool(record.get("proxied", True)):
        raise PreviewHostError(f"{host} exists but is not proxied")
    return {
        "host": host,
        "recordId": str(record.get("id") or ""),
        "type": str(record.get("type") or record_type),
        "target": str(record.get("content") or target),
        "proxied": True,
    }


__all__ = [
    "PREVIEW_PREFIX",
    "PreviewHostError",
    "ensure_preview_host_dns",
    "expiry_for",
    "host_for",
    "origin",
    "path_for",
    "preview_host",
    "signature",
    "signing_key",
    "tenant_id",
    "url_for",
    "verify",
]
