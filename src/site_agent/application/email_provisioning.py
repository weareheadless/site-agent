"""Tenant-scoped Cloudflare Email provisioning with an explicit cutover policy."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ..hands.cloudflare_email import CloudflareEmailClient, CloudflareEmailError

_EMAIL = re.compile(r"^[^\s@<>]{1,64}@[a-z0-9.-]+\.[a-z]{2,63}$", re.IGNORECASE)


class EmailProvisioningError(RuntimeError):
    """Safe, operator-readable email provisioning failure."""


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        nested = value.get("records")
        if isinstance(nested, list):
            return [dict(item) for item in nested if isinstance(item, Mapping)]
    return []


def _record_key(record: Mapping[str, Any], domain: str) -> tuple[str, str, str, int]:
    name = str(record.get("name") or "").strip().lower().rstrip(".")
    if name in ("", "@"):
        name = domain
    elif name != domain and not name.endswith("." + domain):
        name = f"{name}.{domain}"
    record_type = str(record.get("type") or "").strip().upper()
    content = str(record.get("content") or "").strip().rstrip(".")
    if record_type != "TXT":
        content = content.lower()
    return (
        record_type,
        name,
        content,
        int(record.get("priority") or 0),
    )


def _require_declared_dns(
    declared: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    domain: str,
    service: str,
) -> None:
    if not declared:
        raise EmailProvisioningError(f"Cloudflare did not return the DNS requirements for {service}")
    expected = Counter(_record_key(item, domain) for item in declared)
    observed = Counter(_record_key(item, domain) for item in actual)
    if expected - observed:
        raise EmailProvisioningError(f"{service} DNS records declared by Cloudflare are not all present in the registered zone")


def _verify_sending_dns(
    declared: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    domain: str,
) -> None:
    # DMARC is a domain-owner policy rather than a Cloudflare-specific sender
    # key. Keep the existing policy (for example p=none and its reporting
    # mailbox) while still requiring one syntactically valid DMARC record.
    declared_dmarc = [
        item for item in declared
        if _record_key(item, domain)[:2] == ("TXT", f"_dmarc.{domain}")
        and str(item.get("content") or "").strip().lower().startswith("v=dmarc1")
    ]
    strict_records = [
        item for item in declared
        if not (
            _record_key(item, domain)[:2] == ("TXT", f"_dmarc.{domain}")
            and str(item.get("content") or "").strip().lower().startswith("v=dmarc1")
        )
    ]
    _require_declared_dns(strict_records, actual, domain, "Cloudflare Email Sending")
    if declared_dmarc:
        actual_dmarc = [
            item for item in actual
            if _record_key(item, domain)[:2] == ("TXT", f"_dmarc.{domain}")
            and str(item.get("content") or "").strip().lower().startswith("v=dmarc1")
        ]
        if len(actual_dmarc) != 1:
            raise EmailProvisioningError("Cloudflare Email Sending requires exactly one valid owner-managed DMARC record")


def _email_address(value: str, domain: str) -> str:
    address = str(value or "").strip().lower()
    if not _EMAIL.fullmatch(address) or address.rsplit("@", 1)[1] != domain:
        raise EmailProvisioningError("The configured mailbox must be a valid address on the registered domain")
    return address


def _mailbox_rule(rules: list[dict[str, Any]], address: str) -> dict[str, Any] | None:
    matches = []
    for rule in rules:
        matchers = rule.get("matchers") if isinstance(rule.get("matchers"), list) else []
        if any(
            isinstance(matcher, Mapping)
            and matcher.get("type") == "literal"
            and matcher.get("field") == "to"
            and str(matcher.get("value") or "").lower() == address
            for matcher in matchers
        ):
            matches.append(rule)
    if len(matches) > 1:
        raise EmailProvisioningError("More than one Email Routing rule matches the registered mailbox")
    return matches[0] if matches else None


class EmailProvisioningService:
    """Converge one tenant's sender domain and exact Worker mailbox route."""

    def __init__(self, client: CloudflareEmailClient) -> None:
        self.client = client

    def plan(self, tenant_id: str, policy: Mapping[str, Any]) -> dict[str, Any]:
        domain = str(policy.get("domain") or "").strip().lower().rstrip(".")
        worker = str(policy.get("worker") or "").strip()
        address = _email_address(str(policy.get("address") or ""), domain)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", tenant_id):
            raise EmailProvisioningError("Tenant identity is invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", worker):
            raise EmailProvisioningError("Registered Cloudflare Worker identity is invalid")

        zone = self.client.zone(domain)
        zone_name = str(zone.get("name") or "").lower().rstrip(".")
        if domain != zone_name and not domain.endswith("." + zone_name):
            raise EmailProvisioningError("The registered email domain is not owned by the resolved Cloudflare zone")
        zone_id = str(zone["id"])
        dns = self.client.dns_records(zone_id)
        routing = self.client.routing_settings(zone_id)
        routing_dns = _records(self.client.routing_dns(zone_id)) if routing.get("enabled") else []
        # Read exact-recipient rules even before routing is marked enabled:
        # the DNS onboarding flag and rule inventory are separate resources,
        # and a pre-existing personal forward must never be silently replaced.
        rules = self.client.routing_rules(zone_id)
        catch_all = self.client.catch_all(zone_id) if routing.get("enabled") else {}
        sending = self.client.sending_domains(zone_id)
        sending_matches = [item for item in sending if str(item.get("name") or "").lower() == domain]
        if len(sending_matches) > 1:
            raise EmailProvisioningError("Cloudflare reports duplicate Email Sending domains for this zone")
        sending_dns = []
        if sending_matches and sending_matches[0].get("enabled") is True:
            sending_tag = str(sending_matches[0].get("tag") or "")
            if not sending_tag:
                raise EmailProvisioningError("Enabled Cloudflare Email Sending domain has no provider identifier")
            sending_dns = _records(self.client.sending_dns(zone_id, sending_tag))
            _verify_sending_dns(sending_dns, dns, domain)

        apex_mx = [item for item in dns if _record_key(item, domain)[:2] == ("MX", domain)]
        apex_spf = [
            item for item in dns
            if _record_key(item, domain)[:2] == ("TXT", domain)
            and str(item.get("content") or "").strip().lower().startswith("v=spf1")
        ]
        legacy_mx = sorted(str(item).lower().rstrip(".") for item in policy.get("approvedLegacyMx", []))
        actual_mx = sorted(str(item.get("content") or "").lower().rstrip(".") for item in apex_mx)
        legacy_spf = str(policy.get("approvedLegacySpf") or "").strip().lower()
        dmarc = [
            item for item in dns
            if _record_key(item, domain)[:2] == ("TXT", f"_dmarc.{domain}")
        ]
        if len(dmarc) > 1:
            raise EmailProvisioningError("Multiple DMARC records exist; no email configuration was changed")

        if routing.get("enabled"):
            expected_routing_records = sorted(_record_key(item, domain) for item in routing_dns)
            actual_dns_records = sorted(_record_key(item, domain) for item in dns)
            if not expected_routing_records or any(item not in actual_dns_records for item in expected_routing_records):
                raise EmailProvisioningError("Enabled Email Routing DNS differs from Cloudflare's complete declared record set")
            expected_mx = sorted(
                (key[2], key[3]) for item in routing_dns
                if (key := _record_key(item, domain))[0:2] == ("MX", domain)
            )
            actual_mx_pairs = sorted(
                (key[2], key[3]) for item in apex_mx
                if (key := _record_key(item, domain))[0:2] == ("MX", domain)
            )
            if not expected_mx or actual_mx_pairs != expected_mx:
                raise EmailProvisioningError("Enabled Email Routing MX records differ from Cloudflare's declared set")
            if len(apex_spf) != 1:
                raise EmailProvisioningError("Enabled Email Routing requires exactly one apex SPF record")
            expected_spf = {
                _record_key(item, domain)[2].lower() for item in routing_dns
                if _record_key(item, domain)[0:2] == ("TXT", domain)
                and str(item.get("content") or "").strip().lower().startswith("v=spf1")
            }
            if len(expected_spf) != 1 or _record_key(apex_spf[0], domain)[2].lower() not in expected_spf:
                raise EmailProvisioningError("Enabled Email Routing SPF differs from Cloudflare's declared set")
        else:
            if apex_mx:
                if not bool(policy.get("allowLegacyMailgunCutover")):
                    raise EmailProvisioningError("Apex MX records exist; legacy email cutover is not authorized for this tenant")
                if actual_mx != legacy_mx:
                    raise EmailProvisioningError("Apex MX records differ from the exact approved legacy set; no DNS was changed")
                if not legacy_spf:
                    raise EmailProvisioningError("Legacy MX cutover policy must identify its exact SPF record")
            if len(apex_spf) > 1:
                raise EmailProvisioningError("Multiple apex SPF records exist; no DNS was changed")
            if apex_spf:
                is_approved_legacy = str(apex_spf[0].get("content") or "").strip().lower() == legacy_spf
                if not is_approved_legacy:
                    raise EmailProvisioningError("Apex SPF is not the exact approved legacy record; no DNS was changed")
                if not bool(policy.get("allowLegacyMailgunCutover")):
                    raise EmailProvisioningError("Legacy SPF cutover is not authorized for this tenant")

        existing_rule = _mailbox_rule(rules, address)
        if existing_rule:
            if str(existing_rule.get("source") or "api") != "api":
                raise EmailProvisioningError("The mailbox rule is managed by Wrangler and cannot be changed by this provisioner")
            actions = existing_rule.get("actions") if isinstance(existing_rule.get("actions"), list) else []
            worker_targets = [
                str(action["value"][0]) for action in actions
                if isinstance(action, Mapping) and action.get("type") == "worker"
                and isinstance(action.get("value"), list) and action["value"]
            ]
            forward_targets = [
                str(action["value"][0]) for action in actions
                if isinstance(action, Mapping) and action.get("type") == "forward"
                and isinstance(action.get("value"), list) and action["value"]
            ]
            if worker_targets and worker_targets != [worker]:
                raise EmailProvisioningError("The mailbox is already routed to a different Worker")
            if forward_targets and not bool(policy.get("allowForwardingCutover")):
                raise EmailProvisioningError("The mailbox has an existing forward rule without explicit cutover authorization")
            if not worker_targets and not forward_targets:
                raise EmailProvisioningError("The mailbox has an unrecognized routing action; no rule was changed")

        snapshot = {
            "tenant": tenant_id,
            "domain": domain,
            "address": address,
            "worker": worker,
            "zoneId": zone_id,
            "accountId": str(zone.get("account", {}).get("id") or "") if isinstance(zone.get("account"), Mapping) else "",
            "mailRoutingWasEnabled": bool(routing.get("enabled")),
            "dns": dns,
            "routingDns": routing_dns,
            "existingMailboxRule": existing_rule,
            "existingCatchAll": catch_all,
            "existingSendingDomain": sending_matches[0] if sending_matches else None,
            "sendingDns": sending_dns,
        }
        operations: list[str] = []
        if not sending_matches or sending_matches[0].get("enabled") is not True:
            operations.append("enable Cloudflare Email Sending for the registered domain")
        if not routing.get("enabled"):
            operations.append("enable Cloudflare Email Routing and configure its managed DNS records")
        if not routing.get("enabled") and (apex_mx or apex_spf):
            operations.append("replace only the exact, explicitly approved legacy Mailgun MX/SPF records")
        if not existing_rule or existing_rule.get("enabled") is not True or not any(
            isinstance(action, Mapping) and action.get("type") == "worker" and action.get("value") == [worker]
            for action in (existing_rule.get("actions") or [])
        ):
            operations.append(f"route {address} to the registered Worker")
        return {
            "schema": 1,
            "state": "ready_to_apply",
            "tenant": tenant_id,
            "domain": domain,
            "address": address,
            "worker": worker,
            "snapshotSha256": _canonical_hash(snapshot),
            "snapshot": snapshot,
            "operations": operations,
            "plannedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def provision(self, plan: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a fresh plan. Retries converge; uncertain state is never hidden."""
        current = self.plan(str(plan.get("tenant") or ""), policy)
        if current.get("snapshotSha256") != plan.get("snapshotSha256"):
            raise EmailProvisioningError("Cloudflare email/DNS state changed after planning; re-run preflight before applying")
        snapshot = current["snapshot"]
        zone_id = str(snapshot["zoneId"])
        domain = str(current["domain"])
        address = str(current["address"])
        worker = str(current["worker"])
        records = list(snapshot["dns"])
        old_dmarc = [
            item for item in records
            if str(item.get("type") or "").upper() == "TXT"
            and str(item.get("name") or "").lower().rstrip(".") == f"_dmarc.{domain}"
        ]
        if len(old_dmarc) > 1:
            raise EmailProvisioningError("Multiple DMARC records exist; no email provisioning was applied")

        # Cloudflare accepts a domain under the exact active zone and returns a
        # stable sending-domain ID. It owns the authenticated sender records.
        sending = self.client.ensure_sending_domain(zone_id, domain, self.client.sending_domains(zone_id))
        sending_id = str(sending.get("tag") or "")
        if not sending_id or sending.get("enabled") is not True:
            raise EmailProvisioningError("Cloudflare did not enable Email Sending for the registered domain")
        send_dns = self.client.sending_dns(zone_id, sending_id)
        # Cloudflare owns these locked cf-bounce MX/SPF/DKIM records. Its
        # API returns the expected records, so verify them against the exact
        # zone state instead of assuming the POST completed DNS setup.
        _verify_sending_dns(send_dns, self.client.dns_records(zone_id), domain)

        routing = self.client.routing_settings(zone_id)
        if not routing.get("enabled"):
            fresh_records = self.client.dns_records(zone_id)
            apex_mx = [item for item in fresh_records if _record_key(item, domain)[:2] == ("MX", domain)]
            approved_mx = sorted(str(item).lower().rstrip(".") for item in policy.get("approvedLegacyMx", []))
            original_mx = [item for item in records if _record_key(item, domain)[:2] == ("MX", domain)]
            if sorted(_record_key(item, domain) for item in apex_mx) != sorted(_record_key(item, domain) for item in original_mx):
                raise EmailProvisioningError("Apex MX records changed after preflight; no mail cutover was applied")
            if apex_mx and sorted(str(item.get("content") or "").lower().rstrip(".") for item in apex_mx) != approved_mx:
                raise EmailProvisioningError("Apex MX changed after preflight; no mail cutover was applied")
            apex_spf = [
                item for item in fresh_records
                if _record_key(item, domain)[:2] == ("TXT", domain)
                and str(item.get("content") or "").strip().lower().startswith("v=spf1")
            ]
            original_spf = [
                item for item in records
                if _record_key(item, domain)[:2] == ("TXT", domain)
                and str(item.get("content") or "").strip().lower().startswith("v=spf1")
            ]
            if sorted(_record_key(item, domain) for item in apex_spf) != sorted(_record_key(item, domain) for item in original_spf):
                raise EmailProvisioningError("Apex SPF records changed after preflight; no mail cutover was applied")
            approved_spf = str(policy.get("approvedLegacySpf") or "").strip().lower()
            if len(apex_spf) > 1 or (apex_spf and str(apex_spf[0].get("content") or "").strip().lower() != approved_spf):
                raise EmailProvisioningError("Apex SPF changed after preflight; no mail cutover was applied")
            if (apex_mx or apex_spf) and not bool(policy.get("allowLegacyMailgunCutover")):
                raise EmailProvisioningError("Legacy Mailgun records are present without an explicit cutover authorization")

            deleted_mx: list[dict[str, Any]] = []
            deleted_spf: list[dict[str, Any]] = []
            try:
                for item in apex_mx:
                    self.client.delete_dns_record(zone_id, str(item["id"]))
                    deleted_mx.append(item)
                for item in apex_spf:
                    self.client.delete_dns_record(zone_id, str(item["id"]))
                    deleted_spf.append(item)
                self.client.enable_routing(zone_id, domain)
            except Exception as exc:
                restore_errors = []
                for item in deleted_mx:
                    try:
                        self.client.request("POST", f"/zones/{urllib.parse.quote(zone_id, safe='')}/dns_records", {
                            key: item[key] for key in ("type", "name", "content", "ttl", "priority", "proxied", "comment") if key in item
                        })
                    except Exception:
                        restore_errors.append("MX")
                for item in deleted_spf:
                    try:
                        self.client.upsert_dns_txt(zone_id, item)
                    except Exception:
                        restore_errors.append("SPF")
                if restore_errors:
                    raise EmailProvisioningError(
                        "Cloudflare Email Routing activation failed and exact legacy DNS restoration also failed; inspect the protected provisioning receipt"
                    ) from exc
                if isinstance(exc, CloudflareEmailError):
                    raise EmailProvisioningError(str(exc)) from exc
                raise

        # Preserve any existing DMARC policy/reporting record if onboarding
        # adds a default or changes the value.
        if old_dmarc:
            after = self.client.dns_records(zone_id)
            current_dmarc = [
                item for item in after
                if str(item.get("type") or "").upper() == "TXT"
                and str(item.get("name") or "").lower().rstrip(".") == f"_dmarc.{domain}"
            ]
            if len(current_dmarc) > 1:
                raise EmailProvisioningError("Cloudflare created duplicate DMARC records; stop and inspect the protected receipt")
            if not current_dmarc or str(current_dmarc[0].get("content") or "") != str(old_dmarc[0].get("content") or ""):
                self.client.upsert_dns_txt(zone_id, old_dmarc[0])

        settings = self.client.routing_settings(zone_id)
        if settings.get("enabled") is not True or (settings.get("status") not in (None, "ready")):
            raise EmailProvisioningError("Cloudflare Email Routing did not reach its ready state")
        rules = self.client.routing_rules(zone_id)
        route_match = _mailbox_rule(rules, address)
        if route_match:
            actions = route_match.get("actions") if isinstance(route_match.get("actions"), list) else []
            already_routed = route_match.get("enabled") is True and any(
                isinstance(action, Mapping) and action.get("type") == "worker" and action.get("value") == [worker]
                for action in actions
            )
            route = route_match if already_routed else self.client.update_routing_rule(
                zone_id, str(route_match.get("id") or ""), route_match, address=address, worker=worker,
            )
        else:
            route = self.client.create_routing_rule(zone_id, address=address, worker=worker)
        if not route.get("id") or route.get("enabled") is not True:
            raise EmailProvisioningError("Cloudflare did not confirm the mailbox-to-Worker rule")
        verified_route = _mailbox_rule(self.client.routing_rules(zone_id), address)
        verified_actions = verified_route.get("actions") if isinstance(verified_route, Mapping) else []
        if (
            not verified_route
            or verified_route.get("enabled") is not True
            or not any(
                isinstance(action, Mapping)
                and action.get("type") == "worker"
                and action.get("value") == [worker]
                for action in verified_actions
            )
        ):
            raise EmailProvisioningError("Cloudflare did not read back the exact enabled mailbox-to-Worker route")

        after_dns = self.client.dns_records(zone_id)
        declared_routing_dns = _records(self.client.routing_dns(zone_id))
        expected_routing_records = sorted(_record_key(item, domain) for item in declared_routing_dns)
        actual_routing_records = sorted(_record_key(item, domain) for item in after_dns)
        if not expected_routing_records or any(item not in actual_routing_records for item in expected_routing_records):
            raise EmailProvisioningError("Cloudflare Email Routing DNS verification did not match every provider-declared record")
        expected_mx = sorted(
            (_record_key(item, domain)[2], _record_key(item, domain)[3]) for item in declared_routing_dns
            if _record_key(item, domain)[:2] == ("MX", domain)
        )
        actual_mx = sorted(
            (_record_key(item, domain)[2], _record_key(item, domain)[3]) for item in after_dns
            if _record_key(item, domain)[:2] == ("MX", domain)
        )
        if not expected_mx or actual_mx != expected_mx:
            raise EmailProvisioningError("Cloudflare Email Routing MX verification did not match the provider-declared records")
        expected_spf = {
            _record_key(item, domain)[2].lower() for item in declared_routing_dns
            if _record_key(item, domain)[:2] == ("TXT", domain)
            and str(item.get("content") or "").strip().lower().startswith("v=spf1")
        }
        actual_spf = [
            item for item in after_dns
            if _record_key(item, domain)[:2] == ("TXT", domain)
            and str(item.get("content") or "").strip().lower().startswith("v=spf1")
        ]
        if len(actual_spf) != 1 or len(expected_spf) != 1 or _record_key(actual_spf[0], domain)[2].lower() not in expected_spf:
            raise EmailProvisioningError("Cloudflare Email Routing SPF verification did not match the provider-declared record")

        return {
            "schema": 1,
            "state": "cloudflare_ready",
            "tenant": current["tenant"],
            "domain": domain,
            "address": address,
            "worker": worker,
            "zoneId": zone_id,
            "sendingDomainId": sending_id,
            "sendingEnabled": True,
            "sendingDns": send_dns,
            "routingRuleId": str(route["id"]),
            "routingEnabled": True,
            "routingStatus": str(settings.get("status") or "ready"),
            "previousStateSha256": current["snapshotSha256"],
            "previousDmarcSha256": _canonical_hash(old_dmarc) if old_dmarc else "",
            "previousMx": [{"content": item.get("content"), "priority": item.get("priority")} for item in records if _record_key(item, domain)[:2] == ("MX", domain)],
            "previousSpfSha256": _canonical_hash([item.get("content") for item in records if _record_key(item, domain)[:2] == ("TXT", domain) and str(item.get("content") or "").lower().startswith("v=spf1")]),
            "forwardRuleWasPresent": bool(snapshot.get("existingMailboxRule")),
            "catchAllWasEnabled": bool(snapshot.get("existingCatchAll", {}).get("enabled")) if isinstance(snapshot.get("existingCatchAll"), Mapping) else False,
            "completedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


__all__ = ["EmailProvisioningError", "EmailProvisioningService"]
