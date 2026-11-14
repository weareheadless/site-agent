"""Deliver the registered mail alerts for one tenant.

Two alerts exist, and both are configured per tenant:

* ``inbound`` - mail arrived in the tenant's HelloAda inbox. The owner is
  told that they have mail and where to read it.
* ``external`` - the tenant's domain mail is handled somewhere else. The owner
  is told that HelloAda is not managing it, so nobody waits for mail that
  HelloAda never receives.

The alert is sent with the tenant's own restricted Resend key, as the tenant's
own mailbox address. The platform's management key never sends tenant mail.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..hands.resend import ResendError, ResendSender
from .email_management import (
    ALERT_EXTERNAL,
    ALERT_INBOUND,
    DEFAULT_ALERT_BODY,
    DEFAULT_ALERT_SUBJECT,
    email_alert_settings,
    email_is_externally_managed,
    email_mailbox_address,
    email_management_provider,
    render_alert_template,
)


class MailAlertError(RuntimeError):
    """The registered mail alert could not be delivered."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class MailAlertService:
    """Send one tenant's configured alerts through its own sending key."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        tenant_id: str,
        tenant_config_path: str | Path,
        memory: Any,
    ) -> None:
        self._config = config
        self._tenant_id = str(tenant_id or "").strip()
        self._tenant_config_path = Path(str(tenant_config_path or ""))
        self._memory = memory

    # -- settings -------------------------------------------------------

    def _alerts(self) -> dict[str, Any]:
        return email_alert_settings(self._config)

    def _trigger_enabled(self, kind: str) -> bool:
        alerts = self._alerts()
        return bool(alerts["enabled"] and alerts.get(kind))

    def _site_name(self) -> str:
        return str(self._config.get("display_name") or self._tenant_id).strip() or self._tenant_id

    def _mail_domain(self) -> str:
        site = self._config.get("site") if isinstance(self._config.get("site"), Mapping) else {}
        domain = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
        if domain:
            return domain
        return email_mailbox_address(self._config).partition("@")[2]

    # -- transport ------------------------------------------------------

    def _tenant_secret(self, name: str) -> str:
        from .tenant_environment import read_tenant_environment, tenant_environment_path, TenantEnvironmentError

        try:
            path = tenant_environment_path(self._tenant_config_path, self._tenant_id)
            return str(read_tenant_environment(path).get(name) or "").strip()
        except TenantEnvironmentError as exc:
            raise MailAlertError(str(exc)) from exc

    def _sender_address(self) -> str:
        address = self._tenant_secret("MAILFLARE_ADDRESS")
        return address or email_mailbox_address(self._config)

    # -- delivery -------------------------------------------------------

    def _deliver(self, kind: str, operation_id: str, subject: str, text: str, recipient: str) -> dict[str, Any]:
        receipt_key = f"mail_alert:{kind}:{operation_id}"
        previous = self._memory.kv_get(receipt_key, {}) if self._memory is not None else {}
        if isinstance(previous, Mapping) and previous.get("state") == "sent":
            return {**dict(previous), "state": "already_sent"}

        api_key = self._tenant_secret("RESEND_API_KEY")
        sender = self._sender_address()
        if not api_key:
            raise MailAlertError("The tenant Resend sending credential is unavailable")
        if not sender:
            raise MailAlertError("The tenant mailbox address is unavailable")
        if not recipient:
            raise MailAlertError("The registered alert recipient is unavailable")
        try:
            identity = ResendSender(api_key).send_message(
                tenant=self._tenant_id,
                operation_id=operation_id,
                sender=sender,
                recipient=recipient,
                subject=subject,
                text=text,
            )
        except ResendError as exc:
            raise MailAlertError(str(exc)) from exc
        receipt = {
            "state": "sent",
            "kind": kind,
            "tenant": self._tenant_id,
            "recipient": recipient,
            "sender": sender,
            "providerId": identity,
            "sentAt": _now(),
        }
        if self._memory is not None:
            self._memory.kv_set(receipt_key, receipt)
        return receipt

    def _render(self, kind: str, extra: Mapping[str, str]) -> tuple[str, str]:
        alerts = self._alerts()
        values = {
            "site": self._site_name(),
            "mailbox": self._sender_address(),
            "domain": self._mail_domain(),
            "provider": email_management_provider(self._config) or "another provider",
            **{key: str(value or "") for key, value in extra.items()},
        }
        subject_template = alerts["subject"] or DEFAULT_ALERT_SUBJECT[kind]
        body_template = alerts["body"] or DEFAULT_ALERT_BODY[kind]
        return (
            render_alert_template(subject_template, values),
            render_alert_template(body_template, values),
        )

    # -- alerts ---------------------------------------------------------

    def inbound_alert(self, *, message_id: str, subject: str = "", sender: str = "") -> dict[str, Any]:
        """Tell the owner that mail is waiting in the HelloAda inbox."""
        if not self._trigger_enabled(ALERT_INBOUND):
            return {"state": "disabled", "kind": ALERT_INBOUND}
        operation = str(message_id or "").strip()
        if not operation:
            raise MailAlertError("The inbound mail identity is required")
        alerts = self._alerts()
        alert_subject, alert_body = self._render(ALERT_INBOUND, {
            "subject": str(subject or "").strip(),
            "sender": str(sender or "").strip(),
        })
        return self._deliver(ALERT_INBOUND, operation, alert_subject, alert_body, alerts["recipient"])

    def external_notice(self) -> dict[str, Any]:
        """Tell the owner that their domain mail is handled outside HelloAda."""
        if not email_is_externally_managed(self._config):
            return {"state": "not_applicable", "kind": ALERT_EXTERNAL}
        if not self._trigger_enabled(ALERT_EXTERNAL):
            return {"state": "disabled", "kind": ALERT_EXTERNAL}
        alerts = self._alerts()
        alert_subject, alert_body = self._render(ALERT_EXTERNAL, {"subject": ""})
        # The notice describes the current policy, so its identity is the
        # policy revision rather than a mail that never arrives.
        operation = f"external:{email_management_provider(self._config) or 'external'}"
        return self._deliver(ALERT_EXTERNAL, operation, alert_subject, alert_body, alerts["recipient"])


__all__ = ["MailAlertError", "MailAlertService"]
