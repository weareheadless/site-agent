"""Deterministic default email identity for registered HelloAda tenants."""

from __future__ import annotations

PLATFORM_EMAIL_DOMAIN = "helloada.app"

# The owner registered this mailbox domain explicitly in the tenant settings.
# Every other domain source is derived from the registered site origin, so a
# domain change rewrites it and a later release provisions the new identity.
OWNER_DOMAIN_SOURCE = "owner"


def default_mailbox_identity(tenant_id: str, custom_domain: str = "") -> dict[str, str]:
    """Return the one default mailbox selected by a tenant's registered site origin."""
    domain = str(custom_domain or "").strip().lower().rstrip(".")
    if domain:
        return {"domain": domain, "local_part": "hello", "domain_source": "site_custom_domain"}
    return {
        "domain": PLATFORM_EMAIL_DOMAIN,
        "local_part": str(tenant_id).strip().lower(),
        "domain_source": "helloada_platform",
    }


def mailbox_domain_is_owner_registered(settings: object) -> bool:
    """True when the registered mailbox domain does not follow the site origin."""
    email = settings if isinstance(settings, dict) else {}
    return str(email.get("domain_source") or "").strip().lower() == OWNER_DOMAIN_SOURCE


def mailbox_identity_source(
    tenant_id: str,
    configured_domain: str,
    site_custom_domain: str = "",
) -> str:
    """Return the domain source for a mailbox domain that was just resolved.

    A domain that differs from the registered site origin's is the owner's
    choice, so a later domain change must not silently replace it.
    """
    derived = default_mailbox_identity(tenant_id, site_custom_domain)
    configured = str(configured_domain or "").strip().lower().rstrip(".")
    if configured and configured != derived["domain"]:
        return OWNER_DOMAIN_SOURCE
    return derived["domain_source"]
