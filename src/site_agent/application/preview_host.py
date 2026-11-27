"""Where a compiled candidate is served.

A compiled preview is a complete Next application, and a complete application
owns an origin. Serving it under a path on the workspace's origin forced the app
to reproduce Next's URL semantics — basePath root, RSC and prefetch headers,
redirects, asset prefixes, 404s — and every mismatch was another broken preview.
The one that kept escaping was the simplest: a plain ``<a href="/about">`` or
``fetch('/api/assistant')`` resolves against the origin, not against the mount,
so a candidate that worked live 404'd in review.

A preview therefore has its own origin: ``p-<tenant>-<job>-<signature>.<base>``.
Nothing is mounted, so a candidate's links are its origin's links, and this
service only forwards bytes. The label names the tenant and the job, so a
request never depends on which browser call happened earlier in this process's
lifetime, and the service that answers it can restart without stranding an
address it already handed out. The signature is an HMAC over the same identity,
so the address is the capability: it needs no cookie (a cross-origin frame
carries none), it cannot be forged for another tenant or job, rotating the key
retires every address at once, and each expires with its own job.

The address is a single DNS label under the platform's preview base, because the
zone's certificate is a one-level wildcard: ``*.helloada.app`` covers
``p-….helloada.app`` and nothing deeper. That is a certificate fact, so the
shape of an address is decided here, once, for every tenant.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Any

PREVIEW_SIGNING_KEY_ENV = "HELLOADA_PREVIEW_SIGNING_KEY"
# The zone a preview origin lives in. Every preview is one label under it.
PREVIEW_BASE_ENV = "HELLOADA_PREVIEW_BASE"
# The older name for the same setting, still honoured on hosts that were
# configured before the address stopped being a path on a shared host.
PREVIEW_HOST_ENV = "HELLOADA_PREVIEW_HOST"
PREVIEW_DNS_HOST_ENV = "HELLOADA_PREVIEW_DNS_HOST"

_PREFIX = "p"
_SIGNATURE_LENGTH = 10
_DIGEST_LENGTH = 8
# A job id is whatever the workspace minted, and it appears in a DNS label, so
# it is a DNS-safe token rather than one fixed format. Real ids are UUIDs; the
# parser below reads the label by its fixed ends, so a dash in the id is fine.
_JOB = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{%d}$" % _SIGNATURE_LENGTH)
_DIGEST = re.compile(r"^[0-9a-f]{%d}$" % _DIGEST_LENGTH)
# The same identity rule the tenant registry applies: a preview label is never a
# caller-controlled string.
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,120}$")
# A preview base is an origin, not an authority: no port, path or userinfo, and
# every label is a DNS label. The address is published, so a value that is not a
# bare hostname must be refused rather than published.
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


def preview_base(env: Mapping[str, str]) -> str:
    """The zone every preview origin is one label under."""
    host = str(env.get(PREVIEW_BASE_ENV) or env.get(PREVIEW_HOST_ENV) or "").strip().strip("/").lower()
    if not host or "/" in host or " " in host:
        raise PreviewHostError(f"{PREVIEW_BASE_ENV} is not configured")
    if not _HOST.fullmatch(host):
        raise PreviewHostError("preview base is not a safe hostname")
    return host


def tenant_id(value: Any) -> str:
    """Normalize a tenant identity to the form the registry and signature use."""
    normalized = str(value or "").strip().lower()
    if not _TENANT.fullmatch(normalized):
        raise PreviewHostError("preview tenant is not a safe address")
    return normalized


def tenant_digest(tenant: str) -> str:
    """The short, stable prefix that names a tenant inside a preview label.

    A tenant id and a job id do not both fit in one DNS label, so the tenant is
    carried as a digest. The signature is still computed over the full id, so a
    digest that two tenants happened to share could not be swapped.
    """
    return hashlib.sha256(tenant_id(tenant).encode()).hexdigest()[:_DIGEST_LENGTH]


def _job(job: Any) -> str:
    job_id = str(job or "").strip().lower()
    if not _JOB.fullmatch(job_id):
        raise PreviewHostError("preview identity is invalid")
    return job_id


def signature(key: str, tenant: str, job: str) -> str:
    message = f"{tenant_id(tenant)}|{_job(job)}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:_SIGNATURE_LENGTH]


def label_for(key: str, tenant: str, job: str) -> str:
    """The one DNS label that names this exact preview."""
    return f"{_PREFIX}-{tenant_digest(tenant)}-{_job(job)}-{signature(key, tenant, job)}"


def host_for(env: Mapping[str, str], tenant: str, job: str) -> str:
    return f"{label_for(signing_key(env), tenant, job)}.{preview_base(env)}"


def origin(env: Mapping[str, str], tenant: str, job: str) -> str:
    return f"https://{host_for(env, tenant, job)}"


def url_for(env: Mapping[str, str], tenant: str, job: str, path: str = "") -> str:
    clean = str(path or "").lstrip("/")
    return origin(env, tenant, job) + (f"/{clean}" if clean else "/")


def parse_host(env: Mapping[str, str], host: str) -> tuple[str, str] | None:
    """Split a preview origin into its tenant digest and job.

    Returns ``None`` for any host that is not a preview origin under this base,
    so the workspace app keeps serving its own hostnames untouched. Nothing is
    trusted from the host here: the digest and job are what the request claims,
    and the signature is checked against them separately.
    """
    raw = str(host or "").strip().strip("/").lower()
    if not raw:
        return None
    try:
        base = preview_base(env)
    except PreviewHostError:
        return None
    if not raw.endswith("." + base):
        return None
    label = raw[: -(len(base) + 1)]
    if not label or "." in label or len(label) > 63:
        return None
    # p-<digest 8>-<job>-<sig 10>. The job may itself contain dashes, so the
    # label is read from both fixed ends rather than split on every dash.
    if not label.startswith(f"{_PREFIX}-"):
        return None
    rest = label[len(_PREFIX) + 1:]
    if len(rest) < _DIGEST_LENGTH + 2 + _SIGNATURE_LENGTH:
        return None
    digest = rest[:_DIGEST_LENGTH]
    supplied = rest[-_SIGNATURE_LENGTH:]
    job = rest[_DIGEST_LENGTH + 1: -(_SIGNATURE_LENGTH + 1)]
    if not _DIGEST.fullmatch(digest) or not _JOB.fullmatch(job) or not _SIGNATURE.fullmatch(supplied):
        return None
    return digest, job


def verify(key: str, tenant: str, job: str, supplied: str) -> bool:
    """Accept only a signature this service minted for this exact tenant and job."""
    try:
        expected = signature(key, tenant, job)
    except PreviewHostError:
        return False
    if not _SIGNATURE.fullmatch(str(supplied or "").strip()):
        return False
    return hmac.compare_digest(expected.encode(), str(supplied).strip().encode())


def signature_from_host(host: str) -> str:
    parts = str(host or "").strip().strip("/").lower().split(".")
    label = parts[0] if parts else ""
    return label.rsplit("-", 1)[-1] if "-" in label else ""


def ensure_preview_base_dns(env: Mapping[str, str], *, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Give the preview zone its wildcard record if the platform has not yet.

    Every preview is one label under one base, so the whole capability needs a
    single proxied wildcard record. It follows the host that already serves the
    API, so a fresh installation gets working preview origins on first start and
    no preview ever waits for its own DNS record.
    """
    from ..credentials import credential_profile
    from ..hands.cloudflare_dns import CloudflareDNSError, CloudflareDNSClient

    base = preview_base(env)
    anchor = str(env.get(PREVIEW_DNS_HOST_ENV) or "").strip().strip("/").lower()
    if not anchor:
        raise PreviewHostError(f"{PREVIEW_DNS_HOST_ENV} is not configured")
    profile = credential_profile(config, "cloudflare_dns")
    variable = str(profile.get("api_token_env") or "CLOUDFLARE_DNS_API_TOKEN")
    token = str(env.get(variable) or "")
    if not token:
        raise PreviewHostError(f"{variable} is not set")
    client = CloudflareDNSClient(token)
    name = f"*.{base}"
    try:
        zone = client.zone_id_for_hostname(base)
        anchor_records = [
            item for item in client.records(zone, name=anchor)
            if str(item.get("type") or "") in {"A", "AAAA", "CNAME"}
        ]
        if not anchor_records:
            raise PreviewHostError(f"{anchor} has no address to follow")
        target = str(anchor_records[0].get("content") or "").strip()
        record_type = str(anchor_records[0].get("type") or "A")
        client.ensure_public_host(zone, name, target=target)
        created = [
            item for item in client.records(zone, name=name)
            if str(item.get("type") or "") in {"A", "AAAA", "CNAME"}
        ]
    except CloudflareDNSError as exc:
        raise PreviewHostError(str(exc)[:300]) from exc
    if not created:
        raise PreviewHostError(f"{name} did not resolve to a record after provisioning")
    record = created[0]
    if not bool(record.get("proxied", True)):
        raise PreviewHostError(f"{name} exists but is not proxied")
    return {
        "host": name,
        "recordId": str(record.get("id") or ""),
        "type": str(record.get("type") or record_type),
        "target": str(record.get("content") or target),
        "proxied": True,
    }


__all__ = [
    "PreviewHostError",
    "PREVIEW_BASE_ENV",
    "PREVIEW_HOST_ENV",
    "ensure_preview_base_dns",
    "host_for",
    "label_for",
    "origin",
    "parse_host",
    "preview_base",
    "signature",
    "signature_from_host",
    "signing_key",
    "tenant_digest",
    "tenant_id",
    "url_for",
    "verify",
]
