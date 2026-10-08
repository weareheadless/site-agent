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

from ..credentials import cloudflare_api_token, credential_environment
from .worker_origin import WorkerOriginError, canonical_worker_preview_url
from ..hands.cloudflare_email import CloudflareEmailClient
from .email_provisioning import EmailProvisioningError, EmailProvisioningService
from .tenant_registration import tenant_token_env


class EmailWorkerReadinessError(EmailProvisioningError):
    """The exact registered Worker release is not ready for email routing."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _worker_readiness(
    config: Mapping[str, Any],
    tenant_id: str,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    site = _mapping(config.get("site"))
    deployment = _mapping(site.get("source_deployment"))
    worker = str(deployment.get("worker_name") or "").strip().lower()
    preview = str(site.get("preview_url") or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
        return "", "The registered Cloudflare Worker identity is unavailable."
    try:
        expected_preview = canonical_worker_preview_url(config, env)
    except WorkerOriginError:
        return "", "Cloudflare could not confirm the registered account-qualified Worker origin."
    parsed = urlsplit(preview)
    expected = urlsplit(expected_preview)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected.hostname
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return "", "The registered Worker preview origin does not match the Cloudflare account."
    request = urllib.request.Request(
        urllib.parse.urljoin(preview.rstrip("/") + "/", "api/health"),
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
) -> dict[str, Any]:
    site = _mapping(config.get("site"))
    preview = str(site.get("preview_url") or "").rstrip("/")
    request = urllib.request.Request(
        preview + "/api/helloada/internal/messages/configure-mailbox",
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
    site = _mapping(config.get("site"))
    domain = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if not domain:
        origin = str(site.get("public_url") or site.get("url") or "").strip()
        host = str(urlsplit(origin if "://" in origin else f"https://{origin}").hostname or "").lower().rstrip(".")
        if host and not host.endswith(".workers.dev"):
            domain = host
    if not domain or domain.endswith(".workers.dev"):
        raise EmailProvisioningError("A registered custom domain is required before email can be provisioned")

    # The local part is stable across domain changes. Resolve the actual
    # Cloudflare zone first so a www/custom-host registration still provisions
    # the conventional mailbox at its managed zone apex.
    local_part = str(email.get("local_part") or "hello").strip().lower()
    worker, readiness_error = _worker_readiness(config, tenant_id, resolved_env)
    if readiness_error:
        raise EmailWorkerReadinessError(readiness_error)
    token = cloudflare_api_token(config, resolved_env)
    if not token:
        raise EmailProvisioningError("The host Cloudflare API token is not configured for Email provisioning")
    client = CloudflareEmailClient(token)
    zone = client.zone(domain)
    email_domain = str(zone.get("name") or "").strip().lower().rstrip(".")
    if not email_domain or (domain != email_domain and not domain.endswith("." + email_domain)):
        raise EmailProvisioningError("The registered custom domain is not owned by an accessible Cloudflare zone")
    address = f"{local_part}@{email_domain}"
    policy: dict[str, Any] = {
        **dict(email),
        **dict(provisioning),
        **dict(policy_overrides or {}),
        "domain": email_domain,
        "address": address,
        "worker": worker,
    }
    plan = EmailProvisioningService(client).plan(tenant_id, policy)
    return plan, policy, resolved_env


def auto_provision_email(
    config: Mapping[str, Any],
    *,
    tenant_id: str,
    memory: Any,
    env: Mapping[str, str] | None = None,
    policy_overrides: Mapping[str, Any] | None = None,
    expected_snapshot_sha256: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    """Provision email automatically for a ready custom-domain tenant.

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
    raw_domain = str(site.get("custom_domain") or "").strip().lower().rstrip(".")
    if not raw_domain:
        origin = str(site.get("public_url") or site.get("url") or "").strip()
        host = str(urlsplit(origin if "://" in origin else f"https://{origin}").hostname or "").lower().rstrip(".")
        if host and not host.endswith(".workers.dev"):
            raw_domain = host
    if not raw_domain or raw_domain.endswith(".workers.dev"):
        result = {**state, "state": "domain_required", "lastAttemptAt": _now()}
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env

    address = f"{str(email.get('local_part') or 'hello').strip().lower()}@{raw_domain}"
    configured_worker = str(_mapping(site.get("source_deployment")).get("worker_name") or "").strip().lower()
    if (
        not expected_snapshot_sha256
        and state.get("state") == "active"
        and state.get("siteDomain") == raw_domain
        and state.get("worker") == configured_worker
    ):
        return state, resolved_env
    policy: dict[str, Any] = {
        **dict(email),
        **dict(provisioning),
        **dict(policy_overrides or {}),
        "domain": raw_domain,
        "address": address,
    }
    attempt: dict[str, Any] = {}
    email_domain = raw_domain
    try:
        preflight, policy, resolved_env = prepare_email_plan(
            config,
            tenant_id=tenant_id,
            env=resolved_env,
            policy_overrides=policy_overrides,
        )
        if expected_snapshot_sha256 and preflight.get("snapshotSha256") != expected_snapshot_sha256:
            raise EmailProvisioningError("Cloudflare email/DNS state changed after the reviewed CLI preflight; re-run the plan")
        email_domain = str(preflight["domain"])
        address = str(preflight["address"])
        worker = str(policy["worker"])
        tenant_token = str(resolved_env.get(tenant_token_env(tenant_id)) or "").strip()
        if not tenant_token:
            raise EmailProvisioningError("The tenant Worker service token is unavailable for Payload provisioning")

        attempt = {
            "state": "applying",
            "tenant": tenant_id,
            "domain": email_domain,
            "siteDomain": raw_domain,
            "address": address,
            "worker": worker,
            "preflightSha256": preflight["snapshotSha256"],
            "operations": preflight["operations"],
            "lastAttemptAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", attempt)

        token = cloudflare_api_token(config, resolved_env)
        provider = EmailProvisioningService(CloudflareEmailClient(token)).provision(preflight, policy)
        attempt.update(state="configuring_payload", cloudflareRouteId=provider["routingRuleId"])
        if memory is not None:
            memory.kv_set("email_provisioning_state", attempt)
        payload = _configure_payload_mailbox(
            config,
            tenant_id=tenant_id,
            token=tenant_token,
            domain=email_domain,
            address=address,
        )
        result = {
            "state": "active",
            "tenant": tenant_id,
            "domain": email_domain,
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
            "domain": email_domain,
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
            "domain": email_domain,
            "siteDomain": raw_domain,
            "address": address,
            "error": str(exc)[:500],
            "lastAttemptAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env


__all__ = ["EmailWorkerReadinessError", "auto_provision_email", "prepare_email_plan"]
