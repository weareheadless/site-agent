"""Registered mail-management settings for one tenant.

The platform never infers who owns a domain's mail from its DNS records. An
empty apex MX can mean a domain that never had mail, a record deleted by
mistake, or a provider migration in progress. Those cases need different
answers, and DNS cannot tell them apart.

The registered settings are the only authority. A tenant whose mail is managed
elsewhere records that fact, and the platform then never writes mail DNS,
routing rules, a mailbox or a sender key for that tenant - whatever the
records look like at the time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .mailbox_identity import OWNER_DOMAIN_SOURCE, PLATFORM_EMAIL_DOMAIN

MANAGED_MODE = "managed"
EXTERNAL_MODE = "external"
MODES = (MANAGED_MODE, EXTERNAL_MODE)

ALERT_INBOUND = "inbound"
ALERT_EXTERNAL = "external"
ALERT_KINDS = (ALERT_INBOUND, ALERT_EXTERNAL)

MAX_PROVIDER_LENGTH = 80
MAX_TEMPLATE_LENGTH = 500
MAX_RECIPIENT_LENGTH = 254

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_LOCAL_PART = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

DEFAULT_ALERT_SUBJECT = {
    ALERT_INBOUND: "New mail for {site}",
    ALERT_EXTERNAL: "Mail for {site} is handled outside HelloAda",
}

DEFAULT_ALERT_BODY = {
    ALERT_INBOUND: (
        "You have mail waiting for {site}. Check HelloAda to read it in your "
        "inbox: {mailbox}."
    ),
    ALERT_EXTERNAL: (
        "Mail addressed to {domain} is handled by {provider}, not by HelloAda. "
        "Enquiries from your website still arrive in your HelloAda inbox: {mailbox}."
    ),
}


class EmailManagementError(ValueError):
    """The registered mail-management settings are invalid."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def email_settings(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return the registered ``messages.email`` block of one tenant."""
    messages = _mapping(_mapping(config).get("messages"))
    return _mapping(messages.get("email"))


def email_management_mode(config: Mapping[str, Any] | None) -> str:
    """Return who owns the tenant's mail: ``managed`` or ``external``."""
    management = _mapping(email_settings(config).get("management"))
    mode = str(management.get("mode") or "").strip().lower()
    return mode if mode in MODES else MANAGED_MODE


def email_is_externally_managed(config: Mapping[str, Any] | None) -> bool:
    """Return true when the tenant's mail is managed outside HelloAda."""
    return email_management_mode(config) == EXTERNAL_MODE


def email_management_provider(config: Mapping[str, Any] | None) -> str:
    """Return the registered label of the external mail provider."""
    management = _mapping(email_settings(config).get("management"))
    return str(management.get("provider") or "").strip()


def email_alert_settings(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the registered alert settings with their defaults applied."""
    alerts = _mapping(email_settings(config).get("alerts"))
    recipient = str(alerts.get("recipient") or "").strip()
    return {
        # An alert needs a registered recipient. Until the owner registers
        # one, no alert is sent and no notice is promised.
        "enabled": bool(alerts.get("enabled", bool(recipient))),
        "recipient": recipient,
        "subject": str(alerts.get("subject") or "").strip(),
        "body": str(alerts.get("body") or "").strip(),
        ALERT_INBOUND: bool(alerts.get(ALERT_INBOUND, True)),
        ALERT_EXTERNAL: bool(alerts.get(ALERT_EXTERNAL, True)),
    }


def email_mailbox_address(config: Mapping[str, Any] | None) -> str:
    """Return the tenant's registered HelloAda mailbox address."""
    email = email_settings(config)
    domain = str(email.get("domain") or "").strip().lower().rstrip(".")
    local_part = str(email.get("local_part") or "").strip().lower()
    if not local_part and domain == PLATFORM_EMAIL_DOMAIN:
        # The shared platform domain defaults an unset local part to the tenant
        # id, so every reader shows the address provisioning will create.
        local_part = str(_mapping(config).get("instance_name") or "").strip().lower()
    if not domain or not local_part:
        return ""
    return f"{local_part}@{domain}"


def email_settings_view(
    config: Mapping[str, Any] | None,
    provisioning_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the secret-free mail settings an owner may read and change.

    ``provisioning_state`` is the tenant's durable provider state, so the owner
    sees whether the mailbox on this domain is live, pending, or blocked on a
    host credential rather than only whether the platform may provision it.
    """
    alerts = email_alert_settings(config)
    provisioning = _mapping(email_settings(config).get("provisioning"))
    state = _mapping(provisioning_state)
    settings = email_settings(config)
    domain = str(settings.get("domain") or "").strip()
    local_part = str(settings.get("local_part") or "").strip()
    return {
        "mode": email_management_mode(config),
        "provider": email_management_provider(config),
        "mailbox": {
            "address": email_mailbox_address(config),
            "domain": domain,
            "localPart": local_part,
            "domainSource": str(settings.get("domain_source") or "").strip(),
        },
        "provisioning": {
            "auto": bool(provisioning.get("auto")),
            "state": str(state.get("state") or "").strip(),
            "address": str(state.get("address") or "").strip(),
            "error": str(state.get("error") or "").strip(),
            "lastAttemptAt": str(state.get("lastAttemptAt") or "").strip(),
        },
        "alerts": {
            "enabled": alerts["enabled"],
            "recipient": alerts["recipient"],
            "subject": alerts["subject"],
            "body": alerts["body"],
            ALERT_INBOUND: alerts[ALERT_INBOUND],
            ALERT_EXTERNAL: alerts[ALERT_EXTERNAL],
        },
    }


def _validated_text(value: Any, field: str, limit: int, *, allow_newlines: bool = False) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise EmailManagementError(f"{field} must be a string")
    text = value.strip()
    if len(text) > limit:
        raise EmailManagementError(f"{field} is longer than {limit} characters")
    if _CONTROL_CHARACTERS.search(text):
        raise EmailManagementError(f"{field} contains an unsupported character")
    if not allow_newlines and ("\n" in text or "\r" in text):
        raise EmailManagementError(f"{field} must be a single line")
    return text


def validate_email_settings_update(
    body: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one owner request and return the exact settings to persist.

    The request merges over the registered settings, so a request that only
    changes the mail mode never clears the alert configuration. The returned
    block is the complete ``messages.email`` policy: the mode, the external
    provider label, the alert configuration and whether the platform may
    provision mail for this tenant.
    """
    if not isinstance(body, Mapping):
        raise EmailManagementError("The mail settings request must be an object")
    unknown = sorted(set(body) - {"mode", "provider", "mailbox", "alerts"})
    if unknown:
        raise EmailManagementError(f"Unsupported mail settings: {', '.join(unknown)}")

    current_settings = email_settings(current)
    current_management = _mapping(current_settings.get("management"))
    current_mode = str(current_management.get("mode") or "").strip().lower()
    current_mode = current_mode if current_mode in MODES else MANAGED_MODE
    current_provider = str(current_management.get("provider") or "").strip()

    mode = str(body["mode"]).strip().lower() if "mode" in body else current_mode
    if mode not in MODES:
        raise EmailManagementError(f"mode must be one of {', '.join(MODES)}")
    provider = (
        _validated_text(body.get("provider"), "provider", MAX_PROVIDER_LENGTH)
        if "provider" in body
        else current_provider
    )

    mailbox = _validated_mailbox_update(body.get("mailbox"), current)

    alerts_body = body.get("alerts")
    if alerts_body is None:
        alerts_body = {}
    if not isinstance(alerts_body, Mapping):
        raise EmailManagementError("alerts must be an object")
    unknown_alerts = sorted(
        set(alerts_body) - {"enabled", "recipient", "subject", "body", *ALERT_KINDS}
    )
    if unknown_alerts:
        raise EmailManagementError(f"Unsupported alert settings: {', '.join(unknown_alerts)}")

    alerts = dict(email_alert_settings(current))
    if "enabled" in alerts_body:
        if not isinstance(alerts_body.get("enabled"), bool):
            raise EmailManagementError("alerts.enabled must be true or false")
        alerts["enabled"] = bool(alerts_body.get("enabled"))
    if "recipient" in alerts_body:
        alerts["recipient"] = _validated_text(
            alerts_body.get("recipient"), "alerts.recipient", MAX_RECIPIENT_LENGTH
        )
    if "subject" in alerts_body:
        alerts["subject"] = _validated_text(alerts_body.get("subject"), "alerts.subject", MAX_TEMPLATE_LENGTH)
    if "body" in alerts_body:
        alerts["body"] = _validated_text(
            alerts_body.get("body"), "alerts.body", MAX_TEMPLATE_LENGTH, allow_newlines=True
        )
    for kind in ALERT_KINDS:
        if kind not in alerts_body:
            continue
        if not isinstance(alerts_body.get(kind), bool):
            raise EmailManagementError(f"alerts.{kind} must be true or false")
        alerts[kind] = bool(alerts_body.get(kind))

    if alerts["recipient"] and not _EMAIL.match(alerts["recipient"]):
        raise EmailManagementError("alerts.recipient must be an email address")
    if alerts["enabled"] and (alerts[ALERT_INBOUND] or alerts[ALERT_EXTERNAL]) and not alerts["recipient"]:
        raise EmailManagementError("alerts.recipient is required while an alert is enabled")

    return {
        "mode": mode,
        "provider": provider,
        "mailbox": mailbox,
        "alerts": {
            "enabled": alerts["enabled"],
            "recipient": alerts["recipient"],
            "subject": alerts["subject"],
            "body": alerts["body"],
            ALERT_INBOUND: alerts[ALERT_INBOUND],
            ALERT_EXTERNAL: alerts[ALERT_EXTERNAL],
        },
        # An externally managed tenant is never provisioned by the platform,
        # whatever its DNS records look like at the time.
        "provisioning": {"auto": mode == MANAGED_MODE},
    }


def _validated_mailbox_update(
    value: Any,
    current: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    """Return the mailbox identity an owner request registers, if any.

    The domain follows the registered site origin unless the owner names one.
    The local part is the owner's choice and survives a domain change. A tenant
    on the shared platform domain needs an address unique in that domain, which
    the tenant id already is.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EmailManagementError("mailbox must be an object")
    settings = email_settings(current)
    tenant_id = str(_mapping(current).get("instance_name") or "").strip().lower()
    local_part = str(settings.get("local_part") or "").strip().lower()
    domain = str(settings.get("domain") or "").strip().lower().rstrip(".")
    source = str(settings.get("domain_source") or "").strip().lower()
    derived = _derived_domain(current)

    request = value
    unknown_mailbox = sorted(set(request) - {"localPart", "domain"})
    if unknown_mailbox:
        raise EmailManagementError(f"Unsupported mailbox settings: {', '.join(unknown_mailbox)}")

    if "localPart" in request:
        local_part = _validated_text(request.get("localPart"), "mailbox.localPart", 64).lower()
        if local_part and not _LOCAL_PART.match(local_part):
            raise EmailManagementError("mailbox.localPart must be a single address label")
    if "domain" in request:
        registered = _validated_text(request.get("domain"), "mailbox.domain", 253).lower().rstrip(".")
        if registered:
            if not _DOMAIN.match(registered):
                raise EmailManagementError("mailbox.domain must be a domain name")
            domain, source = registered, OWNER_DOMAIN_SOURCE
        else:
            # Clearing the domain returns the mailbox to the registered origin.
            domain, source = derived, ""

    if not domain:
        domain, source = derived, ""
    if source != OWNER_DOMAIN_SOURCE:
        source = "site_custom_domain" if domain != PLATFORM_EMAIL_DOMAIN else "helloada_platform"
    if domain == PLATFORM_EMAIL_DOMAIN and not local_part:
        local_part = tenant_id
    if domain == PLATFORM_EMAIL_DOMAIN and local_part == "hello" and tenant_id != "hello":
        raise EmailManagementError("choose a mailbox name that is unique on helloada.app")
    return {"localPart": local_part, "domain": domain, "domainSource": source}


def _derived_domain(current: Mapping[str, Any] | None) -> str:
    site = _mapping(_mapping(current).get("site"))
    custom = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if custom:
        return custom
    return PLATFORM_EMAIL_DOMAIN


def render_alert_template(template: str, values: Mapping[str, str]) -> str:
    """Fill the supported placeholders without evaluating anything else."""
    text = str(template or "")
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value or ""))
    return text


__all__ = [
    "ALERT_EXTERNAL",
    "ALERT_INBOUND",
    "ALERT_KINDS",
    "DEFAULT_ALERT_BODY",
    "DEFAULT_ALERT_SUBJECT",
    "EXTERNAL_MODE",
    "MANAGED_MODE",
    "MODES",
    "EmailManagementError",
    "email_alert_settings",
    "email_is_externally_managed",
    "email_mailbox_address",
    "email_management_mode",
    "email_management_provider",
    "email_settings",
    "email_settings_view",
    "render_alert_template",
    "validate_email_settings_update",
]
