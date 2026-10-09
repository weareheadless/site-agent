"""Automatic domain-email reconciliation after the tenant Worker supports it."""

from __future__ import annotations

import copy
import datetime
import fcntl
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlsplit

from ..credentials import cloudflare_api_token, cloudflare_dns_api_token, cloudflare_email_api_token, cloudflare_env_names, credential_environment, resend_api_key
from ..hands.cloudflare_email import CloudflareEmailClient
from ..hands.cloudflare_worker import CloudflareWorkerSecretsClient
from ..hands.resend import ResendProvisioner, ResendVerificationPending
from .email_provisioning import EmailProvisioningError, EmailProvisioningService
from .mailbox_identity import PLATFORM_EMAIL_DOMAIN
from .tenant_registration import tenant_token_env


class EmailWorkerReadinessError(EmailProvisioningError):
    """The exact registered Worker release is not ready for email routing."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _tenant_env_path(config: Mapping[str, Any], tenant_id: str) -> Path:
    raw_data_dir = Path(str(config.get("data_dir") or "")).expanduser()
    raw_tenant_dir = raw_data_dir.parent
    if raw_data_dir.is_symlink() or raw_tenant_dir.is_symlink():
        raise EmailProvisioningError("The registered tenant secret path cannot contain symbolic links")
    data_dir = raw_data_dir.resolve(strict=True)
    tenant_dir = data_dir.parent
    if data_dir.name != "data" or tenant_dir.name != tenant_id or tenant_dir == Path(tenant_dir.anchor):
        raise EmailProvisioningError("The registered tenant secret path is not canonical")
    path = tenant_dir / "tenant.env"
    if path.is_symlink() or not path.is_file() or tenant_dir.is_symlink():
        raise EmailProvisioningError("The registered tenant secret file is unavailable")
    return path


def _tenant_secret_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                raise EmailProvisioningError("The registered tenant secret file is malformed")
            name, value = line.split("=", 1)
            name = name.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in values:
                raise EmailProvisioningError("The registered tenant secret names are invalid")
            values[name] = value.strip()
    except (OSError, UnicodeError) as exc:
        raise EmailProvisioningError("The registered tenant secret file could not be read") from exc
    return values


def _write_tenant_secrets(path: Path, values: Mapping[str, str]) -> None:
    for name, value in values.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)) or any(char in str(value) for char in "\r\n\0"):
            raise EmailProvisioningError("The tenant secret update contains an invalid name or value")
    lock_fd = os.open(path.with_name(".tenant-env.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    temporary: Path | None = None
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        current = _tenant_secret_values(path)
        for name, value in current.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or any(char in value for char in "\r\n\0"):
                raise EmailProvisioningError("The registered tenant secret file contains an invalid name or value")
        current.update({name: str(value) for name, value in values.items()})
        descriptor, filename = tempfile.mkstemp(prefix=".tenant-env-", suffix=".tmp", dir=path.parent)
        temporary = Path(filename)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                for name, value in sorted(current.items()):
                    stream.write(f"{name}={value}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _ensure_tenant_resend_key(
    *,
    path: Path,
    tenant_id: str,
    domain_id: str,
    worker: str,
    config: Mapping[str, Any],
    env: Mapping[str, str],
    resend: ResendProvisioner,
) -> str:
    """Install one domain-scoped sender key and reconcile interrupted rotations."""
    lock_fd = os.open(path.with_name(".resend-key-provisioning.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        values = _tenant_secret_values(path)
        api_key = str(values.get("RESEND_API_KEY") or "").strip()
        key_id = str(values.get("RESEND_API_KEY_ID") or "").strip()
        key_domain_id = str(values.get("RESEND_API_KEY_DOMAIN_ID") or "").strip()
        installed_id = str(values.get("RESEND_API_KEY_INSTALLED_ID") or "").strip()
        previous_ids = [
            item for item in str(values.get("RESEND_API_KEY_PREVIOUS_IDS") or "").split(",")
            if item.strip()
        ]
        pending_name = str(values.get("RESEND_API_KEY_PENDING_NAME") or "").strip()

        if bool(api_key) != bool(key_id):
            raise EmailProvisioningError("The tenant Resend sending credential is incomplete; operator reconciliation is required")
        key_id_pattern = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        if (key_id and not re.fullmatch(key_id_pattern, key_id)) or any(
            not re.fullmatch(key_id_pattern, item) for item in previous_ids
        ):
            raise EmailProvisioningError("The tenant Resend key ledger contains an invalid provider identity")

        # A create request may have succeeded at Resend while its response was
        # lost. The intent name is persisted before POST; remove any matching
        # token (which cannot be retrieved again) before starting a new create.
        if pending_name:
            pending = resend.api_keys_named(pending_name)
            for item in pending:
                identity = str(item.get("id") or "").strip()
                if not identity:
                    raise EmailProvisioningError("Resend returned an API key without an identity during retry reconciliation")
                resend.delete_api_key(identity)
            if resend.api_keys_named(pending_name):
                raise EmailProvisioningError("Resend did not confirm cleanup of an interrupted tenant key creation")
            _write_tenant_secrets(path, {"RESEND_API_KEY_PENDING_NAME": ""})

        if api_key and key_id and key_domain_id == domain_id:
            if installed_id != key_id:
                _worker_secret_client(config, env, worker).put_secret("RESEND_API_KEY", api_key)
                _write_tenant_secrets(path, {"RESEND_API_KEY_INSTALLED_ID": key_id})
            for old_id in dict.fromkeys(previous_ids):
                if old_id and old_id != key_id:
                    resend.delete_api_key(old_id)
            if previous_ids:
                _write_tenant_secrets(path, {"RESEND_API_KEY_PREVIOUS_IDS": ""})
            return key_id

        old_ids = list(dict.fromkeys([*previous_ids, *([key_id] if key_id else [])]))
        pending_name = f"HA-{tenant_id[:20]}-{uuid4().hex[:12]}"
        _write_tenant_secrets(path, {"RESEND_API_KEY_PENDING_NAME": pending_name})
        new_id, new_key = resend.create_sending_key(pending_name, domain_id)
        _write_tenant_secrets(path, {
            "RESEND_API_KEY": new_key,
            "RESEND_API_KEY_ID": new_id,
            "RESEND_API_KEY_DOMAIN_ID": domain_id,
            "RESEND_API_KEY_PREVIOUS_IDS": ",".join(old_ids),
            "RESEND_API_KEY_PENDING_NAME": "",
        })
        _worker_secret_client(config, env, worker).put_secret("RESEND_API_KEY", new_key)
        _write_tenant_secrets(path, {"RESEND_API_KEY_INSTALLED_ID": new_id})
        for old_id in old_ids:
            if old_id and old_id != new_id:
                resend.delete_api_key(old_id)
        if old_ids:
            _write_tenant_secrets(path, {"RESEND_API_KEY_PREVIOUS_IDS": ""})
        return new_id
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _worker_secret_client(config: Mapping[str, Any], env: Mapping[str, str], worker: str) -> CloudflareWorkerSecretsClient:
    token = cloudflare_api_token(config, env)
    _token_name, account_name = cloudflare_env_names(config)
    account = str(env.get(account_name) or "").strip()
    return CloudflareWorkerSecretsClient(token, account, worker)


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
        data=json.dumps({
            "domain": domain,
            "address": address,
            "outboundProvider": "resend",
            "outboundMode": "business_correspondence",
        }).encode("utf-8"),
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
    return {"state": "active", "domain": domain, "address": address, "outboundProvider": "resend"}


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

    local_part = _configured_local_part(email, policy_overrides, tenant_id=tenant_id, domain=domain)
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
    plan["operations"] = [
        *list(plan.get("operations") or []),
        f"verify the Resend sending domain and add only its declared, conflict-free DNS records for {domain}",
        f"install or rotate the domain-restricted Resend sending key for {address}",
    ]
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
    if host and host.endswith(".workers.dev"):
        return PLATFORM_EMAIL_DOMAIN
    return host


def _configured_local_part(
    email: Mapping[str, Any],
    policy_overrides: Mapping[str, Any] | None,
    *,
    tenant_id: str,
    domain: str,
) -> str:
    overrides = _mapping(policy_overrides)
    configured = str(overrides.get("localPart") or email.get("local_part") or "").strip().lower()
    if domain == PLATFORM_EMAIL_DOMAIN:
        if not configured or (configured == "hello" and str(tenant_id).strip().lower() != "hello"):
            raise EmailProvisioningError("A tenant-unique mailbox local part must be registered for helloada.app")
        return configured
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
        local_part = _configured_local_part(
            email, policy_overrides, tenant_id=tenant_id, domain=requested_email_domain,
        )
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

    if not resend_api_key(config, resolved_env):
        result = {
            **state,
            "state": "action_required",
            "tenant": tenant_id,
            "domain": requested_email_domain,
            "error": "The protected Resend management API key is not configured.",
            "lastAttemptAt": _now(),
        }
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
        and state.get("outboundProvider") == "resend"
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
        cloudflare_email = CloudflareEmailClient(email_token, dns_token)
        resend = ResendProvisioner(resend_api_key(config, resolved_env), cloudflare_email)
        resend_domain = resend.ensure_domain(resolved_email_domain)
        secret_path = _tenant_env_path(config, tenant_id)
        send_key_id = _ensure_tenant_resend_key(
            path=secret_path,
            tenant_id=tenant_id,
            domain_id=str(resend_domain["id"]),
            worker=worker,
            config=config,
            env=resolved_env,
            resend=resend,
        )

        provider = EmailProvisioningService(cloudflare_email).provision(preflight, policy)
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
            "outboundProvider": "resend",
            "resendDomain": resend_domain["domain"],
            "resendDomainStatus": resend_domain["status"],
            "resendSendingKeyProvisioned": True,
            "payloadMailboxState": payload["state"],
            "preflightSha256": preflight["snapshotSha256"],
            "completedAt": _now(),
        }
        if memory is not None:
            memory.kv_set("email_provisioning_state", result)
        return result, resolved_env
    except ResendVerificationPending as exc:
        result = {
            **state,
            **attempt,
            "state": "provisioning",
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
