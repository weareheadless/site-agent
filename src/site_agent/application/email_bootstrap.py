"""Automatic domain-email reconciliation after the tenant Worker supports it."""

from __future__ import annotations

import copy
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from ..credentials import cloudflare_dns_api_token, cloudflare_email_api_token, credential_environment
from ..hands.cloudflare_email import CloudflareEmailClient
from .email_provisioning import EmailProvisioningError, EmailProvisioningService
from .tenant_registration import tenant_token_env


class EmailWorkerReadinessError(EmailProvisioningError):
    """The exact registered Worker release is not ready for email routing."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _registered_site_origin(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> str:
    site = _mapping(config.get("site"))
    raw_origin = str(site.get("public_url") or "").strip()
    custom_domain = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if not custom_domain:
        from .worker_origin import WorkerOriginError, canonical_worker_preview_url

        try:
            canonical_origin = canonical_worker_preview_url(config, env)
        except WorkerOriginError as exc:
            raise EmailProvisioningError("The registered account-qualified Worker origin could not be confirmed.") from exc
        if raw_origin:
            try:
                parsed = urlsplit(raw_origin)
                if (
                    parsed.scheme.lower() != "https"
                    or parsed.hostname is None
                    or parsed.hostname.lower().rstrip(".") != urlsplit(canonical_origin).hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.port is not None
                    or parsed.path not in ("", "/")
                    or parsed.query
                    or parsed.fragment
                ):
                    raise EmailProvisioningError("The registered public website origin does not match the exact Cloudflare Worker.")
            except ValueError as exc:
                raise EmailProvisioningError("The registered public website origin is invalid.") from exc
        return canonical_origin
    try:
        parsed = urlsplit(raw_origin)
        port = parsed.port
    except ValueError as exc:
        raise EmailProvisioningError("The registered public website origin is invalid.") from exc
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or not custom_domain
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (hostname != custom_domain and not hostname.endswith("." + custom_domain))
    ):
        raise EmailProvisioningError("The registered public website origin must be HTTPS on the tenant's custom domain.")
    return f"https://{hostname}"


def _worker_readiness(
    config: Mapping[str, Any],
    tenant_id: str,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    site = _mapping(config.get("site"))
    deployment = _mapping(site.get("source_deployment"))
    worker = str(deployment.get("worker_name") or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
        return "", "The registered Cloudflare Worker identity is unavailable."
    try:
        origin = _registered_site_origin(config, env)
    except EmailProvisioningError as exc:
        return "", str(exc)
    request = urllib.request.Request(
        urllib.parse.urljoin(origin.rstrip("/") + "/", "api/health"),
        headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "HelloAda-Email-Provisioner/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeError):
        return "", "The tenant Worker health contract is not available yet."
    if (
        not isinstance(body, Mapping)
        or body.get("ok") is not True
        or body.get("tenant") != tenant_id
        or body.get("contentContract") != "helloada-content-v3"
        or body.get("emailProvisioningVersion") != 1
    ):
        return "", "The tenant Worker has not confirmed the canonical Messages/email release."
    return worker, ""


def _configure_payload_mailbox(
    config: Mapping[str, Any],
    *,
    tenant_id: str,
    token: str,
    domain: str,
    address: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    origin = _registered_site_origin(config, env)
    request = urllib.request.Request(
        origin + "/api/helloada/internal/messages/configure-mailbox",
        data=json.dumps({"domain": domain, "address": address}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-HelloAda-Tenant": tenant_id,
            "User-Agent": "HelloAda-Email-Provisioner/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read(8 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise EmailProvisioningError(f"The tenant Worker rejected Payload mailbox configuration (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
        raise EmailProvisioningError(f"The tenant Worker did not confirm Payload mailbox configuration ({type(exc).__name__})") from exc
    if (
        not isinstance(result, Mapping)
        or result.get("state") != "active"
        or str(result.get("domain") or "").lower() != domain
        or str(result.get("address") or "").lower() != address
    ):
        raise EmailProvisioningError("Payload did not confirm the requested mailbox as active")
    return {"state": "active", "domain": domain, "address": address}


def prepare_email_plan(
    config: Mapping[str, Any],
    *,
    tenant_id: str,
    env: Mapping[str, str] | None = None,
    policy_overrides: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """Read and validate the exact tenant/provider state without changing it."""
    messages = _mapping(config.get("messages"))
    email = _mapping(messages.get("email"))
    provisioning = _mapping(email.get("provisioning"))
    resolved_env = credential_environment(config, env)
    domain_override = str(_mapping(policy_overrides).get("emailDomain") or "").strip()
    domain = _validated_email_domain(domain_override) if domain_override else _configured_email_domain(config)
    if not domain:
        raise EmailProvisioningError("A registered email domain is required before email can be provisioned")

    local_part = _configured_local_part(email, policy_overrides)
    dns_token = cloudflare_dns_api_token(config, resolved_env)
    email_token = cloudflare_email_api_token(config, resolved_env)
    if not dns_token:
        raise EmailProvisioningError("The host Cloudflare DNS API token is not configured for Email provisioning")
    if not email_token:
        raise EmailProvisioningError("The host Cloudflare Email Service API token is not configured for Email provisioning")
    worker, readiness_error = _worker_readiness(config, tenant_id, resolved_env)
    if readiness_error:
        raise EmailWorkerReadinessError(readiness_error)
    client = CloudflareEmailClient(email_token, dns_token)
    zone = client.zone(domain)
    zone_name = str(zone.get("name") or "").strip().lower().rstrip(".")
    if not zone_name or (domain != zone_name and not domain.endswith("." + zone_name)):
        raise EmailProvisioningError("The registered email domain is not owned by an accessible Cloudflare zone")
    requested_email_domain = domain
    if domain != zone_name and (email.get("domain") or domain_override):
        raise EmailProvisioningError(
            "This provisioning workflow supports Cloudflare zone-apex email domains only; subdomain routing requires a separate supported onboarding path"
        )
    if domain != zone_name:
        domain = zone_name
    address = f"{local_part}@{domain}"
    policy: dict[str, Any] = {
        **dict(email),
        **dict(provisioning),
        **dict(policy_overrides or {}),
        "domain": domain,
        "emailDomainSetting": requested_email_domain,
        "address": address,
        "worker": worker,
    }
    plan = EmailProvisioningService(client).plan(tenant_id, policy)
    return plan, policy, resolved_env


def _validated_email_domain(value: str) -> str:
    domain = str(value or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise EmailProvisioningError("The configured email domain is invalid")
    return domain


def _configured_email_domain(config: Mapping[str, Any]) -> str:
    email = _mapping(_mapping(config.get("messages")).get("email"))
    explicit = str(email.get("domain") or "").strip().lower().rstrip(".")
    if explicit:
        return _validated_email_domain(explicit)

    site = _mapping(config.get("site"))
    domain = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if domain:
        return _validated_email_domain(domain)
    origin = str(site.get("public_url") or site.get("url") or "").strip()
    if not origin:
        return ""
    try:
        host = str(urlsplit(origin if "://" in origin else f"https://{origin}").hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise EmailProvisioningError("The registered website origin is invalid") from exc
    return host if host and not host.endswith(".workers.dev") else ""


def _configured_local_part(email: Mapping[str, Any], policy_overrides: Mapping[str, Any] | None) -> str:
    overrides = _mapping(policy_overrides)
    configured = str(overrides.get("localPart") or email.get("local_part") or "").strip().lower()
    if (overrides.get("emailDomain") or email.get("domain")) and not configured:
        raise EmailProvisioningError("A tenant-unique mailbox local part must be registered for an explicit email domain")
    return configured or "hello"


def _registered_site_domain(config: Mapping[str, Any]) -> str:
    site = _mapping(config.get("site"))
    custom_domain = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if custom_domain:
        return custom_domain
    origin = str(site.get("public_url") or site.get("url") or "").strip()
    if not origin:
        return ""
    try:
        host = urlsplit(origin if "://" in origin else f"https://{origin}").hostname
    except ValueError as exc:
        raise EmailProvisioningError("The registered website origin is invalid") from exc
    return str(host or "").lower().rstrip(".")


def auto_provision_email(
    config: Mapping[str, Any],
    *,
    tenant_id: str,
    memory: Any,
    env: Mapping[str, str] | None = None,
    policy_overrides: Mapping[str, Any] | None = None,
    expected_snapshot_sha256: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    """Provision email automatically for a ready tenant with a registered email domain.

    No provider writes happen until the canonical Messages Worker health
    marker passes and the exact DNS/routing state has been preflighted.
    """
    messages = _mapping(config.get("messages"))
    email = _mapping(messages.get("email"))
    provisioning = _mapping(email.get("provisioning"))
    resolved_env = credential_environment(config, env)
    previous = memory.kv_get("email_provisioning_state", {}) if memory is not None else {}
    state = copy.deepcopy(dict(previous)) if isinstance(previous, Mapping) else {}

    if messages.get("enabled") is False or email.get("enabled") is not True or provisioning.get("auto") is not True:
        result = {**state, "state": "disabled", "lastAttemptAt": _now()}
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env

    site = _mapping(config.get("site"))
    try:
        raw_domain = _registered_site_domain(config)
        domain_override = str(_mapping(policy_overrides).get("emailDomain") or "").strip()
        requested_email_domain = _validated_email_domain(domain_override) if domain_override else _configured_email_domain(config)
        local_part = _configured_local_part(email, policy_overrides)
    except EmailProvisioningError as exc:
        result = {
            **state,
            "state": "failed",
            "tenant": tenant_id,
            "error": str(exc)[:500],
            "lastAttemptAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env
    if not requested_email_domain:
        result = {**state, "state": "domain_required", "lastAttemptAt": _now()}
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env

    address = f"{local_part}@{requested_email_domain}"
    configured_worker = str(_mapping(site.get("source_deployment")).get("worker_name") or "").strip().lower()
    if (
        not expected_snapshot_sha256
        and state.get("state") == "active"
        and state.get("siteDomain") == raw_domain
        and state.get("emailDomainSetting") == requested_email_domain
        and str(state.get("address") or "").split("@", 1)[0] == local_part
        and state.get("worker") == configured_worker
    ):
        return state, resolved_env
    policy: dict[str, Any] = {
        **dict(email),
        **dict(provisioning),
        **dict(policy_overrides or {}),
        "domain": requested_email_domain,
        "emailDomainSetting": requested_email_domain,
        "local_part": local_part,
        "address": address,
    }
    attempt: dict[str, Any] = {}
    resolved_email_domain = requested_email_domain
    try:
        preflight, policy, resolved_env = prepare_email_plan(
            config,
            tenant_id=tenant_id,
            env=resolved_env,
            policy_overrides=policy_overrides,
        )
        if expected_snapshot_sha256 and preflight.get("snapshotSha256") != expected_snapshot_sha256:
            raise EmailProvisioningError("Cloudflare email/DNS state changed after the reviewed CLI preflight; re-run the plan")
        resolved_email_domain = str(preflight["domain"])
        requested_email_domain = str(policy.get("emailDomainSetting") or requested_email_domain)
        address = str(preflight["address"])
        worker = str(policy["worker"])
        tenant_token = str(resolved_env.get(tenant_token_env(tenant_id)) or "").strip()
        if not tenant_token:
            raise EmailProvisioningError("The tenant Worker service token is unavailable for Payload provisioning")

        attempt = {
            "state": "applying",
            "tenant": tenant_id,
            "domain": resolved_email_domain,
            "emailDomainSetting": requested_email_domain,
            "siteDomain": raw_domain,
            "address": address,
            "worker": worker,
            "preflightSha256": preflight["snapshotSha256"],
            "operations": preflight["operations"],
            "lastAttemptAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", attempt)

        dns_token = cloudflare_dns_api_token(config, resolved_env)
        email_token = cloudflare_email_api_token(config, resolved_env)
        if not dns_token or not email_token:
            raise EmailProvisioningError("The Cloudflare DNS and Email Service API tokens must both be configured")
        provider = EmailProvisioningService(CloudflareEmailClient(email_token, dns_token)).provision(preflight, policy)
        attempt.update(state="configuring_payload", cloudflareRouteId=provider["routingRuleId"])
        if memory is not None:
            memory.kv_set("email_provisioning_state", attempt)
        payload = _configure_payload_mailbox(
            config,
            tenant_id=tenant_id,
            token=tenant_token,
            domain=resolved_email_domain,
            address=address,
            env=resolved_env,
        )
        result = {
            "state": "active",
            "tenant": tenant_id,
            "domain": resolved_email_domain,
            "emailDomainSetting": requested_email_domain,
            "siteDomain": raw_domain,
            "address": address,
            "worker": worker,
            "cloudflareZoneId": provider["zoneId"],
            "sendingDomainId": provider["sendingDomainId"],
            "routingRuleId": provider["routingRuleId"],
            "routingStatus": provider["routingStatus"],
            "payloadMailboxState": payload["state"],
            "preflightSha256": preflight["snapshotSha256"],
            "completedAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env
    except EmailWorkerReadinessError as exc:
        result = {
            **state,
            "state": "waiting_for_worker_release",
            "tenant": tenant_id,
            "domain": resolved_email_domain,
            "emailDomainSetting": requested_email_domain,
            "siteDomain": raw_domain,
            "address": address,
            "error": str(exc)[:500],
            "lastAttemptAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env
    except Exception as exc:  # noqa: BLE001 - preserve a durable retry state without blocking other tenant tools
        result = {
            **state,
            **attempt,
            "state": "failed",
            "tenant": tenant_id,
            "domain": resolved_email_domain,
            "emailDomainSetting": requested_email_domain,
            "siteDomain": raw_domain,
            "address": address,
            "error": str(exc)[:500],
            "lastAttemptAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env


__all__ = ["EmailWorkerReadinessError", "auto_provision_email", "prepare_email_plan"]
