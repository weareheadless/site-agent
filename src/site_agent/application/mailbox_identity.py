"""Deterministic default email identity for registered HelloAda tenants."""

from __future__ import annotations

PLATFORM_EMAIL_DOMAIN = "helloada.app"


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
