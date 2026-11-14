"""Tenant-owned public site origin helpers.

An origin is a property of a tenant deployment, not of a particular customer
or hosting provider.  Keeping normalization here prevents provisioning,
analytics, and domain-change flows from growing provider-specific branches.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


class SiteOriginError(ValueError):
    """A public site origin cannot be used safely."""


_HOSTNAME = re.compile(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$", re.IGNORECASE)


def normalize_site_origin(value: str, *, field: str = "site_url") -> str:
    """Return one canonical root URL for a tenant's public site.

    GSC URL-prefix properties and runtime canonical URLs must describe the
    same origin.  Paths, query strings, fragments, credentials, and wildcard
    hostnames are therefore rejected instead of being silently reinterpreted.
    """
    raw = str(value or "").strip()
    if not raw:
        raise SiteOriginError(f"{field} is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SiteOriginError(f"{field} must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SiteOriginError(f"{field} must be a public origin without credentials, query, or fragment")
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if not hostname or "*" in hostname or not _HOSTNAME.fullmatch(hostname):
        raise SiteOriginError(f"{field} must contain a valid public hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SiteOriginError(f"{field} contains an invalid port") from exc
    netloc = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", "")) + "/"


def origin_hostname(value: str) -> str:
    """Return the normalized hostname for a previously validated origin."""
    return str(urlsplit(normalize_site_origin(value)).hostname or "").lower()


def origins_equal(left: str, right: str) -> bool:
    """Compare origins without allowing malformed values to compare equal."""
    try:
        return normalize_site_origin(left) == normalize_site_origin(right)
    except SiteOriginError:
        return False


def property_covers_domain(property_value: str, domain: str) -> bool:
    """True when a Search Console property covers ``domain`` and its hosts.

    A domain property (``sc-domain:example.com``) keeps covering a tenant when
    its canonical host changes from ``example.com`` to ``www.example.com``. A
    URL-prefix property belongs to one host and does not.
    """
    value = str(property_value or "").strip().lower().rstrip("/")
    host = str(domain or "").strip().lower().rstrip(".")
    if not value or not host:
        return False
    if value.startswith("sc-domain:"):
        base = value[len("sc-domain:"):].strip().rstrip(".")
    else:
        try:
            base = str(urlsplit(value).hostname or "").strip().lower().rstrip(".")
        except ValueError:
            return False
    return bool(base) and (host == base or host.endswith("." + base))


__all__ = [
    "SiteOriginError",
    "normalize_site_origin",
    "origin_hostname",
    "origins_equal",
    "property_covers_domain",
]
