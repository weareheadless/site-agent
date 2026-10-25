"""Managed, config-only CrawlSEO connector preparation for a tenant."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

from ..config import ConfigError, CrawlSEOSettings
from ..hands.crawlseo_connector_credentials import (
    CONNECTOR_TOKEN_ENV,
    load_connector_environment,
    install_connector_credential,
)
from ..hands.crawlseo import CrawlSEOClient
from .crawlseo import CrawlSEOApplicationService
from .seo_bootstrap import load_tenant_environment
from .tenant_registration import TenantRegistrationError, TenantRegistrationService

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class CrawlSEOConfigurationCutoverError(ValueError):
    """A managed CrawlSEO connector configuration request was rejected."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return _digest(encoded)


def _path_for_tenant(tenant: Any) -> Path:
    raw_path = str(getattr(tenant, "config_path", "") or "").strip()
    if not raw_path:
        raise CrawlSEOConfigurationCutoverError("registered tenant config path is unavailable")
    path = Path(raw_path).expanduser()
    try:
        path.lstat()
    except OSError as exc:
        raise CrawlSEOConfigurationCutoverError("registered tenant config is unavailable") from exc
    if path.is_symlink() or not path.is_file():
        raise CrawlSEOConfigurationCutoverError("registered tenant config path is invalid")
    return path.resolve()


def _read_config(tenant: Any) -> tuple[Path, dict[str, Any], bytes]:
    path = _path_for_tenant(tenant)
    try:
        raw_bytes = path.read_bytes()
        decoded = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CrawlSEOConfigurationCutoverError("registered tenant config is unreadable") from exc
    if not isinstance(decoded, dict) or decoded.get("instance_name") != getattr(tenant, "tenant_id", None):
        raise CrawlSEOConfigurationCutoverError("registered tenant config identity does not match")
    return path, decoded, raw_bytes


def _request_body(body: Mapping[str, Any]) -> dict[str, str]:
    allowed = {
        "mode", "expectedSnapshotHash", "expectedConfigHash", "operatorRequestId",
        "connectorUrl", "connectorTokenEnv", "reason",
    }
    if not isinstance(body, Mapping) or set(body) != allowed:
        raise CrawlSEOConfigurationCutoverError("connector configuration request fields are invalid")
    if body.get("mode") not in {"plan", "apply"}:
        raise CrawlSEOConfigurationCutoverError("mode must be plan or apply")
    snapshot_hash = str(body.get("expectedSnapshotHash") or "")
    config_hash = str(body.get("expectedConfigHash") or "")
    request_id = str(body.get("operatorRequestId") or "")
    connector_url = str(body.get("connectorUrl") or "").strip()
    token_env = str(body.get("connectorTokenEnv") or "").strip()
    reason = str(body.get("reason") or "").strip()
    if not _SHA256.fullmatch(snapshot_hash) or not _SHA256.fullmatch(config_hash):
        raise CrawlSEOConfigurationCutoverError("expected snapshot and config hashes must be SHA-256 values")
    if not _REQUEST_ID.fullmatch(request_id):
        raise CrawlSEOConfigurationCutoverError("operatorRequestId must be a stable 8-128 character identifier")
    if token_env != CONNECTOR_TOKEN_ENV:
        raise CrawlSEOConfigurationCutoverError("connector token environment name is not managed")
    parsed = urlsplit(connector_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise CrawlSEOConfigurationCutoverError("connectorUrl must be a credential-free HTTPS connector endpoint")
    if not 8 <= len(reason) <= 500:
        raise CrawlSEOConfigurationCutoverError("reason must contain 8 to 500 characters")
    return {
        "mode": str(body["mode"]),
        "expectedSnapshotHash": snapshot_hash,
        "expectedConfigHash": config_hash,
        "operatorRequestId": request_id,
        "connectorUrl": connector_url,
        "connectorTokenEnv": token_env,
        "reason": reason,
    }


def _tenant_plan_identity(tenant: Any, plan: Mapping[str, Any]) -> str:
    tenant_id = str(getattr(tenant, "tenant_id", "") or "").strip().lower()
    if plan.get("tenant") != tenant_id or not isinstance(plan.get("snapshotHash"), str):
        raise CrawlSEOConfigurationCutoverError("migration plan does not match the registered tenant")
    site_id = str(plan.get("siteId") or "").strip()
    if not site_id:
        raise CrawlSEOConfigurationCutoverError("migration plan has no bound CrawlSEO site")
    remote = plan.get("crawlseo") if isinstance(plan.get("crawlseo"), Mapping) else {}
    # The migration plan's top-level siteId is the authoritative binding.
    # Older plans predate remote binding verification and need not repeat it.
    return site_id


def _plan_project_identity(tenant: Any, plan: Mapping[str, Any]) -> str:
    remote = plan.get("crawlseo") if isinstance(plan.get("crawlseo"), Mapping) else {}
    site_state = getattr(tenant, "context", {})
    provisioning = site_state.get("seo_provisioning_state") if isinstance(site_state, Mapping) else {}
    crawlseo_state = provisioning.get("crawlseo") if isinstance(provisioning, Mapping) else {}
    project_id = str(plan.get("projectId") or remote.get("projectId") or
                     (crawlseo_state.get("project_id") or crawlseo_state.get("projectId") or "")).strip()
    if not project_id:
        raise CrawlSEOConfigurationCutoverError("migration plan has no registered CrawlSEO project identity")
    return project_id


def _updated_config(config: Mapping[str, Any], request: Mapping[str, str]) -> dict[str, Any]:
    updated = dict(config)
    providers = dict(config.get("providers") or {})
    current = providers.get("crawlseo")
    if not isinstance(current, Mapping) or current.get("enabled") is not True:
        raise CrawlSEOConfigurationCutoverError("CrawlSEO MCP must already be enabled before connector preparation")
    provider = dict(current)
    token_env = str(provider.get("token_env") or "CRAWLSEO_SERVICE_TOKEN").strip()
    if token_env == request["connectorTokenEnv"]:
        raise CrawlSEOConfigurationCutoverError("managed connector token must be separate from the existing MCP token")
    provider["connector_url"] = request["connectorUrl"]
    provider["connector_token_env"] = request["connectorTokenEnv"]
    providers["crawlseo"] = provider
    updated["providers"] = providers
    if provider.get("research_authority") != current.get("research_authority"):
        raise CrawlSEOConfigurationCutoverError("read-only connector preparation cannot change research authority")
    return updated


def _validate_connector_origin(config: Mapping[str, Any], connector_url: str) -> None:
    """Keep the read-only bearer token on the already configured MCP origin."""
    provider = (config.get("providers") or {}).get("crawlseo") or {}
    mcp_url = str(provider.get("url") or "").strip()
    old = urlsplit(mcp_url)
    new = urlsplit(connector_url)
    try:
        old_port = old.port or (443 if old.scheme == "https" else 80)
        new_port = new.port or (443 if new.scheme == "https" else 80)
    except ValueError as exc:
        raise CrawlSEOConfigurationCutoverError("CrawlSEO connector URL is invalid") from exc
    if (
        old.scheme != "https"
        or new.scheme != "https"
        or not old.hostname
        or not new.hostname
        or old.username is not None
        or old.password is not None
        or old.hostname.lower() != new.hostname.lower()
        or old_port != new_port
        or not new.path.rstrip("/").endswith("/api/connector/v1")
    ):
        raise CrawlSEOConfigurationCutoverError("connector URL must use the configured CrawlSEO origin and mount")


def _config_bytes(config: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True).encode("utf-8")


def _binding_summary(capabilities: Mapping[str, Any], site_id: str, project_id: str) -> dict[str, Any]:
    binding = capabilities.get("binding") if isinstance(capabilities.get("binding"), Mapping) else {}
    generation = binding.get("generation")
    if (
        capabilities.get("schemaVersion") != "1.0"
        or capabilities.get("siteId") != site_id
        or capabilities.get("projectId") != project_id
        or binding.get("status") != "active"
        or binding.get("executor") != "helloada"
        or (binding and binding.get("siteId") not in (None, site_id))
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
        or binding.get("executionSupported") is not True
    ):
        raise CrawlSEOConfigurationCutoverError("CrawlSEO connector did not verify the expected active site binding")
    return {
        "siteId": site_id,
        "projectId": project_id,
        "status": binding["status"],
        "executor": binding["executor"],
        "generation": generation,
        "executionSupported": True,
    }


def _default_client_factory(config: Mapping[str, Any], env: Mapping[str, str]) -> Any:
    client = CrawlSEOClient.from_config(dict(config), dict(env))
    if client is None:
        raise CrawlSEOConfigurationCutoverError("CrawlSEO client is disabled")
    return client


def _probe_capabilities(
    config: Mapping[str, Any],
    env: Mapping[str, str],
    site_id: str,
    project_id: str,
    client_factory: Callable[[Mapping[str, Any], Mapping[str, str]], Any],
) -> dict[str, Any]:
    client = client_factory(config, env)
    try:
        service = client if isinstance(client, CrawlSEOApplicationService) else CrawlSEOApplicationService(client)
        capabilities = service.connector_capabilities(site_id)
        return _binding_summary(capabilities, site_id, project_id)
    except CrawlSEOConfigurationCutoverError:
        raise
    except Exception as exc:
        raise CrawlSEOConfigurationCutoverError("CrawlSEO connector capability verification failed") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _prepared(
    tenant: Any,
    plan: Mapping[str, Any],
    body: Mapping[str, Any],
    env: Mapping[str, str],
    client_factory: Callable[[Mapping[str, Any], Mapping[str, str]], Any],
):
    request = _request_body(body)
    if request["expectedSnapshotHash"] != plan.get("snapshotHash"):
        raise CrawlSEOConfigurationCutoverError("migration snapshot changed; refresh the plan before preparing connector config")
    site_id = _tenant_plan_identity(tenant, plan)
    path, config, raw_bytes = _read_config(tenant)
    if request["expectedConfigHash"] != _digest(raw_bytes):
        raise CrawlSEOConfigurationCutoverError("tenant config changed; refresh config hash before preparing connector config")
    updated = _updated_config(config, request)
    _validate_connector_origin(config, request["connectorUrl"])
    proposed_bytes = _config_bytes(updated)
    managed_env = load_connector_environment(config)
    if not managed_env.get(request["connectorTokenEnv"]):
        raise CrawlSEOConfigurationCutoverError("managed read-only connector credential is missing")
    merged_env = load_tenant_environment(config, env)
    merged_env.update(managed_env)
    if not merged_env.get(request["connectorTokenEnv"]):
        raise CrawlSEOConfigurationCutoverError("managed read-only connector credential is missing")
    try:
        settings = CrawlSEOSettings.from_config(updated, merged_env)
    except ConfigError as exc:
        raise CrawlSEOConfigurationCutoverError("proposed CrawlSEO connector config is invalid") from exc
    existing_provider = config["providers"]["crawlseo"]
    if (
        settings.connector_url != request["connectorUrl"]
        or settings.connector_token_env != request["connectorTokenEnv"]
        or settings.token_env != str(existing_provider.get("token_env") or "CRAWLSEO_SERVICE_TOKEN")
        or settings.research_authority != str(existing_provider.get("research_authority") or "local")
    ):
        raise CrawlSEOConfigurationCutoverError("proposed config does not preserve the existing CrawlSEO authority and MCP settings")
    project_id = _plan_project_identity(tenant, plan)
    binding = _probe_capabilities(updated, merged_env, site_id, project_id, client_factory)
    return request, site_id, path, config, updated, raw_bytes, proposed_bytes, merged_env, binding


def build_connector_configuration(
    tenant: Any,
    plan: Mapping[str, Any],
    body: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    *,
    client_factory: Callable[[Mapping[str, Any], Mapping[str, str]], Any] | None = None,
) -> dict[str, Any]:
    """Preview only the read-only endpoint/token-env config delta."""
    request, site_id, _path, config, updated, raw_bytes, proposed_bytes, _env, binding = _prepared(
        tenant, plan, body, dict(env or {}), client_factory or _default_client_factory,
    )
    before = config["providers"]["crawlseo"]
    after = updated["providers"]["crawlseo"]
    return {
        "valid": True,
        "mode": request["mode"],
        "tenant": tenant.tenant_id,
        "siteId": site_id,
        "expectedSnapshotHash": request["expectedSnapshotHash"],
        "expectedConfigHash": _digest(raw_bytes),
        "proposedConfigHash": _digest(proposed_bytes),
        "changes": {
            "connector_url": {"before": before.get("connector_url") or "", "after": after["connector_url"]},
            "connector_token_env": {"before": before.get("connector_token_env") or "", "after": after["connector_token_env"]},
        },
        "binding": binding,
        "researchAuthority": after.get("research_authority") or "local",
        "authorityChanged": False,
        "paidOperationsAllowed": False,
        "wouldPersist": request["mode"] == "apply",
    }


def _receipts(memory: Any, request_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    suffixes = {
        ":begin": "begin",
        ":applied": "applied",
        ":runtime_unverified": "runtime_unverified",
    }
    for receipt in memory.crawlseo_migration_receipts():
        if not isinstance(receipt, Mapping) or receipt.get("type") != "connector_configuration":
            continue
        for suffix, key in suffixes.items():
            if receipt.get("operatorRequestId") == request_id + suffix:
                result[key] = dict(receipt)
    return result


def _persist(
    memory: Any,
    receipt: dict[str, Any],
    *,
    validate_snapshot: Callable[[Mapping[str, Any]], bool] | None = None,
) -> tuple[dict[str, Any], bool]:
    return memory.persist_crawlseo_migration_receipt(receipt, validate_snapshot=validate_snapshot)


def _receipt_id(request_id: str, phase: str, source: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(source), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return _digest((request_id + ":" + phase).encode("utf-8") + b":" + hashlib.sha256(encoded).digest())


def _request_matches(receipt: Mapping[str, Any], request: Mapping[str, str]) -> bool:
    return all(receipt.get(key) == request.get(key) for key in (
        "expectedSnapshotHash", "expectedConfigHash", "connectorUrl", "connectorTokenEnv", "reason",
    ))


def _save_unverified(tenant: Any, begin: Mapping[str, Any]) -> None:
    values = {key: begin.get(key) for key in (
        "expectedSnapshotHash", "expectedConfigHash", "proposedConfigHash", "connectorUrl",
        "connectorTokenEnv", "researchAuthority", "localInventoryHash",
    )}
    base_request_id = str(begin["baseRequestId"])
    receipt = {
        **values,
        "type": "connector_configuration",
        "operatorRequestId": base_request_id + ":runtime_unverified",
        "receiptId": _receipt_id(base_request_id, "runtime_unverified", values),
        "state": "config_saved_runtime_unverified",
        "decision": "configure_read_only_connector",
        "currentKeys": ["connector_configuration:runtime_unverified"],
    }
    _persist(tenant.memory, receipt)


def _active_service_binding(tenant: Any, site_id: str, project_id: str) -> dict[str, Any]:
    context = getattr(tenant, "context", {})
    service = context.get("crawlseo_service") if isinstance(context, Mapping) else None
    if service is None:
        raise CrawlSEOConfigurationCutoverError("reloaded tenant has no CrawlSEO application service")
    try:
        capabilities = service.connector_capabilities(site_id)
    except Exception as exc:
        raise CrawlSEOConfigurationCutoverError("reloaded tenant could not verify CrawlSEO connector capabilities") from exc
    return _binding_summary(capabilities, site_id, project_id)


def apply_connector_configuration(
    registry: Any,
    tenant: Any,
    plan: Mapping[str, Any],
    body: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[Mapping[str, Any], Mapping[str, str]], Any] | None = None,
) -> dict[str, Any]:
    """CAS-persist and reload the read-only connector config without activation."""
    request = _request_body(body)
    if request["mode"] != "apply":
        raise CrawlSEOConfigurationCutoverError("apply_connector_configuration requires mode=apply")
    tenant_id = str(getattr(tenant, "tenant_id", "") or "").strip().lower()
    if getattr(registry, "tenants", {}).get(tenant_id) is not tenant:
        raise CrawlSEOConfigurationCutoverError("tenant is not the active registered tenant")

    memory = tenant.memory
    prior = _receipts(memory, request["operatorRequestId"])
    if prior.get("applied"):
        if not _request_matches(prior["applied"], request):
            raise CrawlSEOConfigurationCutoverError("operatorRequestId already has a conflicting connector config receipt")
        _path, _config, current_bytes = _read_config(tenant)
        if _digest(current_bytes) != prior["applied"].get("proposedConfigHash"):
            raise CrawlSEOConfigurationCutoverError("tenant config changed after this operator request completed")
        return {
            "status": "configured_read_only",
            "idempotent": True,
            "configHash": prior["applied"].get("proposedConfigHash"),
            "authorityChanged": False,
            "paidOperationsAllowed": False,
            "receipt": prior["applied"],
        }
    begin = prior.get("begin")
    if begin and not _request_matches(begin, request):
        raise CrawlSEOConfigurationCutoverError("operatorRequestId already has a conflicting connector config receipt")

    path, on_disk_config, current_bytes = _read_config(tenant)
    current_hash = _digest(current_bytes)
    if begin:
        proposed_hash = str(begin.get("proposedConfigHash") or "")
        if current_hash not in {request["expectedConfigHash"], proposed_hash}:
            raise CrawlSEOConfigurationCutoverError("tenant config changed during connector config recovery")
        if current_hash == proposed_hash:
            updated = on_disk_config
            proposed_bytes = current_bytes
            site_id = str(begin.get("siteId") or "")
            binding = dict(begin.get("binding") or {})
            merged_env = load_tenant_environment(on_disk_config, env)
            local_inventory_hash = str(begin.get("localInventoryHash") or "")
        else:
            prepared = _prepared(tenant, plan, request, dict(env or {}), client_factory or _default_client_factory)
            request, site_id, path, _original, updated, current_bytes, proposed_bytes, merged_env, binding = prepared
            if _digest(proposed_bytes) != proposed_hash or begin.get("siteId") != site_id:
                raise CrawlSEOConfigurationCutoverError("connector config recovery does not match its durable begin receipt")
            local_inventory_hash = str(begin.get("localInventoryHash") or "")
    else:
        prepared = _prepared(tenant, plan, request, dict(env or {}), client_factory or _default_client_factory)
        request, site_id, path, _original, updated, current_bytes, proposed_bytes, merged_env, binding = prepared
        local_inventory = memory.crawlseo_migration_snapshot()
        local_inventory_hash = _json_digest(local_inventory)
        values = {
            "baseRequestId": request["operatorRequestId"],
            "tenant": tenant_id,
            "siteId": site_id,
            "expectedSnapshotHash": request["expectedSnapshotHash"],
            "expectedConfigHash": request["expectedConfigHash"],
            "proposedConfigHash": _digest(proposed_bytes),
            "connectorUrl": request["connectorUrl"],
            "connectorTokenEnv": request["connectorTokenEnv"],
            "reason": request["reason"],
            "researchAuthority": (updated.get("providers") or {}).get("crawlseo", {}).get("research_authority") or "local",
            "localInventoryHash": local_inventory_hash,
            "binding": binding,
        }
        begin_receipt = {
            **values,
            "type": "connector_configuration",
            "operatorRequestId": request["operatorRequestId"] + ":begin",
            "receiptId": _receipt_id(request["operatorRequestId"], "begin", values),
            "state": "configuration_begin",
            "decision": "configure_read_only_connector",
            "currentKeys": ["connector_configuration:begin"],
        }
        def local_snapshot_current(live_inventory: Mapping[str, Any]) -> bool:
            return _json_digest(live_inventory) == local_inventory_hash
        try:
            _persist(memory, begin_receipt, validate_snapshot=local_snapshot_current)
        except Exception as exc:
            raise CrawlSEOConfigurationCutoverError("connector config begin receipt could not be persisted") from exc
        begin = begin_receipt
        try:
            _replace_config_cas(path, updated, request["expectedConfigHash"], tenant)
        except CrawlSEOConfigurationCutoverError:
            raise
        except Exception as exc:
            raise CrawlSEOConfigurationCutoverError("connector config could not be saved") from exc
        current_bytes = path.read_bytes()
        if _digest(current_bytes) != begin_receipt["proposedConfigHash"]:
            raise CrawlSEOConfigurationCutoverError("saved connector config did not match the proposed hash")

    if _digest(current_bytes) != begin.get("proposedConfigHash"):
        try:
            _replace_config_cas(path, updated, request["expectedConfigHash"], tenant)
        except Exception as exc:
            raise CrawlSEOConfigurationCutoverError("connector config could not be saved") from exc
        current_bytes = path.read_bytes()
        if _digest(current_bytes) != begin.get("proposedConfigHash"):
            raise CrawlSEOConfigurationCutoverError("saved connector config did not match the proposed hash")

    try:
        reloaded = registry.reload_tenant(
            tenant_id,
            str(path),
            api_token=str(getattr(tenant, "api_token", "") or ""),
            api_token_env=str(getattr(tenant, "api_token_env", "") or "") or None,
            env=merged_env,
        )
        # reload_tenant closes the previous Memory handle. All subsequent
        # receipts must use the replacement tenant's live handle.
        tenant = reloaded
        memory = reloaded.memory
        actual_config = reloaded.config
        actual_env = load_tenant_environment(actual_config, merged_env)
        settings = CrawlSEOSettings.from_config(actual_config, actual_env)
        expected_token = str(actual_env.get(request["connectorTokenEnv"]) or "")
        if (
            settings.connector_url != request["connectorUrl"]
            or settings.connector_token_env != request["connectorTokenEnv"]
            or settings.research_authority != begin.get("researchAuthority")
            or not expected_token
            or not hmac.compare_digest(
                hashlib.sha256(settings.connector_token.encode()).digest(),
                hashlib.sha256(expected_token.encode()).digest(),
            )
        ):
            raise CrawlSEOConfigurationCutoverError("reloaded connector settings do not match the managed configuration")
        project_id = str(binding.get("projectId") or "")
        post_binding = _active_service_binding(reloaded, site_id, project_id)
        if any(post_binding.get(key) != binding.get(key) for key in ("siteId", "projectId", "status", "executor", "generation")):
            raise CrawlSEOConfigurationCutoverError("reloaded connector binding differs from the verified binding")
    except Exception:
        # A failed runtime restart may already have closed the previous
        # tenant's Memory handle. Use the registry's live replacement when it
        # exists; otherwise retain the durable begin receipt for startup
        # recovery and avoid turning a verification failure into a write crash.
        receipt_tenant = getattr(registry, "tenants", {}).get(tenant_id) or tenant
        try:
            _save_unverified(receipt_tenant, begin)
        except Exception:
            pass
        return {
            "status": "config_saved_runtime_unverified",
            "idempotent": bool(prior.get("begin")),
            "configHash": begin.get("proposedConfigHash"),
            "authorityChanged": False,
            "paidOperationsAllowed": False,
            "retryRequired": True,
            "notice": "Connector config is saved, but tenant runtime verification failed. Retry config verification; no authority activation was performed.",
        }

    applied_values = {
        "baseRequestId": request["operatorRequestId"],
        "tenant": tenant_id,
        "siteId": site_id,
        "expectedSnapshotHash": request["expectedSnapshotHash"],
        "expectedConfigHash": request["expectedConfigHash"],
        "proposedConfigHash": begin.get("proposedConfigHash"),
        "connectorUrl": request["connectorUrl"],
        "connectorTokenEnv": request["connectorTokenEnv"],
        "reason": request["reason"],
        "researchAuthority": begin.get("researchAuthority"),
        "localInventoryHash": begin.get("localInventoryHash"),
        "binding": post_binding,
    }
    applied_receipt = {
        **applied_values,
        "type": "connector_configuration",
        "operatorRequestId": request["operatorRequestId"] + ":applied",
        "receiptId": _receipt_id(request["operatorRequestId"], "applied", applied_values),
        "state": "configured_read_only",
        "decision": "configure_read_only_connector",
        "currentKeys": ["connector_configuration"],
    }
    try:
        stored, idempotent = _persist(memory, applied_receipt)
    except Exception:
        _save_unverified(tenant, begin)
        return {
            "status": "config_saved_runtime_unverified",
            "idempotent": bool(prior.get("begin")),
            "configHash": begin.get("proposedConfigHash"),
            "authorityChanged": False,
            "paidOperationsAllowed": False,
            "retryRequired": True,
            "notice": "Connector runtime verified but its applied receipt could not be persisted. Retry safely using the same operatorRequestId.",
        }
    return {
        "status": "configured_read_only",
        "idempotent": idempotent,
        "configHash": begin.get("proposedConfigHash"),
        "binding": post_binding,
        "authorityChanged": False,
        "paidOperationsAllowed": False,
        "receipt": stored,
    }


def _replace_config_cas(path: Path, config: Mapping[str, Any], expected_hash: str, tenant: Any) -> None:
    try:
        TenantRegistrationService._replace_config(
            path,
            config,
            expected_sha256=expected_hash.removeprefix("sha256:"),
        )
    except TenantRegistrationError as exc:
        raise CrawlSEOConfigurationCutoverError(str(exc)) from exc


__all__ = [
    "CrawlSEOConfigurationCutoverError",
    "build_connector_configuration",
    "apply_connector_configuration",
    "install_connector_credential",
]
