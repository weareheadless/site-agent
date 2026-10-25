"""Fail-closed, resumable CrawlSEO research-authority activation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

import yaml

from ..config import ConfigError, CrawlSEOSettings
from ..core.research_authority import CONNECTOR_DISPATCH_HOLD_KEY
from ..hands.crawlseo_connector_credentials import CONNECTOR_RUNTIME_TOKEN_ENV, load_connector_runtime_environment
from ..hands.crawlseo import CrawlSEOClient
from .crawlseo import CrawlSEOApplicationService
from .crawlseo_cutover import _digest, _read_config, _replace_config_cas
from .crawlseo_migration import evidence_hash

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_LEGACY_JOBS = {
    "growth_initial", "growth_daily", "growth_weekly", "growth_monthly",
    "article_research", "article_research_cycle", "seo_research_cycle",
    "seo_site_report_cycle", "seo_insight", "seo_outcomes",
}
_KNOWN_PROVIDER_TERMINAL = {"succeeded", "failed", "cancelled", "verified", "reconciled", "settled", "released"}
_KNOWN_RECEIPT_TERMINAL = {"succeeded", "failed", "cancelled", "verified", "reconciled", "completed", "rejected"}


class CrawlSEOActivationError(ValueError):
    """CrawlSEO authority activation is not safe to continue."""


def _request(body: Mapping[str, Any]) -> dict[str, str]:
    fields = {"mode", "expectedSnapshotHash", "expectedConfigHash", "operatorRequestId", "reason"}
    if not isinstance(body, Mapping) or set(body) != fields or body.get("mode") not in {"plan", "apply"}:
        raise CrawlSEOActivationError("activation request fields are invalid")
    snapshot = str(body.get("expectedSnapshotHash") or "")
    config_hash = str(body.get("expectedConfigHash") or "")
    request_id = str(body.get("operatorRequestId") or "")
    reason = str(body.get("reason") or "").strip()
    if not _SHA256.fullmatch(snapshot) or not _SHA256.fullmatch(config_hash):
        raise CrawlSEOActivationError("expected snapshot and config hashes must be SHA-256 values")
    if not _REQUEST_ID.fullmatch(request_id):
        raise CrawlSEOActivationError("operatorRequestId must be a stable 8-128 character identifier")
    if not 8 <= len(reason) <= 500:
        raise CrawlSEOActivationError("reason must contain 8 to 500 characters")
    return {"mode": str(body["mode"]), "expectedSnapshotHash": snapshot,
            "expectedConfigHash": config_hash, "operatorRequestId": request_id, "reason": reason}


def _site_id(tenant: Any, plan: Mapping[str, Any]) -> str:
    if plan.get("tenant") != getattr(tenant, "tenant_id", None):
        raise CrawlSEOActivationError("preflight proof does not match the registered tenant")
    site_id = str(plan.get("siteId") or "").strip()
    remote = plan.get("crawlseo") if isinstance(plan.get("crawlseo"), Mapping) else {}
    if not site_id or not isinstance(remote, Mapping):
        raise CrawlSEOActivationError("preflight proof has no CrawlSEO site identity")
    return site_id


def _validate_preflight(tenant: Any, plan: Mapping[str, Any], expected_snapshot: str) -> tuple[str, Mapping[str, Any]]:
    site_id = _site_id(tenant, plan)
    if plan.get("snapshotHash") != expected_snapshot or plan.get("preflightReady") is not True:
        raise CrawlSEOActivationError("canonical migration preflight is stale or not ready")
    checks = plan.get("checks")
    if not isinstance(checks, list):
        raise CrawlSEOActivationError("canonical migration checks are unavailable")
    preflight = [row for row in checks if isinstance(row, Mapping) and row.get("phase") == "preflight"]
    if not preflight or any(row.get("state") not in {"passed", "reviewed"} for row in preflight):
        raise CrawlSEOActivationError("every canonical preflight check must be passed or reviewed")
    route = plan.get("canonicalRouteVerification")
    if not isinstance(route, Mapping) or route.get("state") != "current_server_verified":
        raise CrawlSEOActivationError("current canonical route server verification is required")
    expected_activation_blockers = (
        "Tenant is not yet configured for CrawlSEO authority;",
        "Legacy research settings remain enabled and need an explicit retirement disposition:",
    )
    blockers = plan.get("blockers")
    if not isinstance(blockers, list) or any(
        not any(str(item).startswith(prefix) for prefix in expected_activation_blockers)
        for item in blockers
    ):
        raise CrawlSEOActivationError("canonical migration preflight has unresolved blockers")
    inventory = plan.get("inventory")
    if not isinstance(inventory, Mapping):
        raise CrawlSEOActivationError("canonical migration inventory is unavailable")
    jobs = inventory.get("activeJobs") if isinstance(inventory.get("activeJobs"), Mapping) else {}
    if jobs.get("truncated") is not False or jobs.get("total") != 0:
        raise CrawlSEOActivationError("active or truncated activeJobs inventory blocks activation")
    bindings = inventory.get("executionBindings") if isinstance(inventory.get("executionBindings"), Mapping) else {}
    if bindings.get("truncated") is not False:
        raise CrawlSEOActivationError("truncated execution binding inventory blocks activation")
    reservations = inventory.get("budgetReservations") if isinstance(inventory.get("budgetReservations"), Mapping) else {}
    if reservations.get("truncated") is not False:
        raise CrawlSEOActivationError("truncated paid reservation inventory blocks activation")
    for row in reservations.get("items", []):
        status = str(row.get("status") or "").lower() if isinstance(row, Mapping) else ""
        if (status not in _KNOWN_PROVIDER_TERMINAL
                or status == "settled" and row.get("recorded_actual_cost_micros") is None):
            from .crawlseo_accounting import imported_row_for_reservation, terminal_import_execution_resolved
            imported = imported_row_for_reservation(tenant.memory, plan, row)
            if not terminal_import_execution_resolved(imported, row):
                raise CrawlSEOActivationError("unresolved paid reservation outcome blocks activation")
    receipts = inventory.get("providerReceipts") if isinstance(inventory.get("providerReceipts"), Mapping) else {}
    if receipts.get("truncated") is not False:
        raise CrawlSEOActivationError("truncated provider outcome inventory blocks activation")
    for row in receipts.get("items", []):
        status = str(row.get("status") or "").lower() if isinstance(row, Mapping) else ""
        if status not in _KNOWN_RECEIPT_TERMINAL:
            raise CrawlSEOActivationError("unknown provider outcome blocks activation")
    freeze = tenant.memory.crawlseo_producer_freeze_status()
    if (freeze.get("active") is not True or freeze.get("registrationsVerified") is not True
            or freeze.get("pendingDrain") is not False):
        raise CrawlSEOActivationError("local producers must be frozen, scheduler registrations verified, and pending drain complete")
    scheduler = getattr(getattr(tenant, "runtime", None), "scheduler", None)
    if scheduler is None or not isinstance(getattr(scheduler, "jobs", None), list):
        raise CrawlSEOActivationError("actual scheduler registrations could not be inspected")
    active_legacy = sorted({str(row[0]) for row in scheduler.jobs
                            if isinstance(row, (tuple, list)) and row and str(row[0]) in _LEGACY_JOBS})
    if active_legacy:
        raise CrawlSEOActivationError("legacy producer registrations remain active: " + ", ".join(active_legacy))
    return site_id, inventory


def _capability_binding(capabilities: Mapping[str, Any], site_id: str, project_id: str) -> dict[str, Any]:
    binding = capabilities.get("binding") if isinstance(capabilities.get("binding"), Mapping) else {}
    scopes = capabilities.get("credentialScopes")
    scopes = {str(value).lower() for value in scopes} if isinstance(scopes, list) else set()
    if (capabilities.get("schemaVersion") != "1.0"
            or capabilities.get("siteId") != site_id
            or capabilities.get("projectId") != project_id
            or binding.get("status") != "active"
            or binding.get("executor") != "helloada"
            or binding.get("siteId") not in (None, site_id)
            or isinstance(binding.get("generation"), bool)
            or not isinstance(binding.get("generation"), int) or binding["generation"] < 1
            or binding.get("executionSupported") is not True
            or scopes != {"connector:read", "connector:write"}):
        raise CrawlSEOActivationError("runtime connector lacks exact binding or read/write credential scopes")
    return {"siteId": site_id, "projectId": project_id, "generation": binding["generation"],
            "status": binding["status"], "executor": binding["executor"], "credentialScopes": sorted(scopes)}


def _updated_config(config: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(config)
    providers = dict(config.get("providers") or {})
    provider = providers.get("crawlseo")
    if not isinstance(provider, Mapping) or provider.get("enabled") is not True or not provider.get("connector_url"):
        raise CrawlSEOActivationError("managed CrawlSEO connector must be configured before authority activation")
    active = dict(provider)
    active["research_authority"] = "crawlseo"
    active["connector_token_env"] = CONNECTOR_RUNTIME_TOKEN_ENV
    providers["crawlseo"] = active
    updated["providers"] = providers
    seo = dict(config.get("seo") or {})
    for key in ("research", "site_report", "article_research"):
        section = dict(seo.get(key) or {})
        section["enabled"] = False
        seo[key] = section
    updated["seo"] = seo
    return updated


def _client(config: Mapping[str, Any], env: Mapping[str, str]) -> Any:
    client = CrawlSEOClient.from_config(dict(config), dict(env))
    if client is None:
        raise CrawlSEOActivationError("CrawlSEO runtime connector is unavailable")
    return client


def _probe(config: Mapping[str, Any], env: Mapping[str, str], site_id: str,
           project_id: str, client_factory: Any) -> dict[str, Any]:
    client = client_factory(config, env)
    try:
        service = client if isinstance(client, CrawlSEOApplicationService) else CrawlSEOApplicationService(client)
        return _capability_binding(service.connector_capabilities(site_id), site_id, project_id)
    except CrawlSEOActivationError:
        raise
    except Exception as exc:
        raise CrawlSEOActivationError("runtime connector capability verification failed") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _project_id(plan: Mapping[str, Any]) -> str:
    remote = plan.get("crawlseo") if isinstance(plan.get("crawlseo"), Mapping) else {}
    value = str(remote.get("projectId") or "").strip()
    if not value:
        raise CrawlSEOActivationError("preflight proof has no authorized CrawlSEO project identity")
    return value


def _prepare(tenant: Any, plan: Mapping[str, Any], request: Mapping[str, str], env: Mapping[str, str], client_factory: Any):
    site_id, inventory = _validate_preflight(tenant, plan, request["expectedSnapshotHash"])
    path, config, raw = _read_config(tenant)
    if _digest(raw) != request["expectedConfigHash"]:
        raise CrawlSEOActivationError("tenant config changed; refresh activation plan")
    updated = _updated_config(config)
    runtime_env = load_connector_runtime_environment(config)
    if not runtime_env.get(CONNECTOR_RUNTIME_TOKEN_ENV):
        raise CrawlSEOActivationError("separate read/write CrawlSEO runtime credential is missing")
    merged = dict(env)
    merged.update(runtime_env)
    try:
        settings = CrawlSEOSettings.from_config(updated, merged)
    except ConfigError as exc:
        raise CrawlSEOActivationError("proposed authority config is invalid") from exc
    if (settings.research_authority != "crawlseo" or settings.connector_token_env != CONNECTOR_RUNTIME_TOKEN_ENV
            or settings.token_env != str((config.get("providers") or {}).get("crawlseo", {}).get("token_env") or "CRAWLSEO_SERVICE_TOKEN")):
        raise CrawlSEOActivationError("proposed authority config did not preserve MCP settings")
    project_id = _project_id(plan)
    binding = _probe(updated, merged, site_id, project_id, client_factory or _client)
    return path, config, raw, updated, _dump(updated), site_id, project_id, inventory, binding


def _dump(config: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True).encode("utf-8")


def _receipt_id(request_id: str, phase: str, content: Mapping[str, Any]) -> str:
    digest = json.dumps(dict(content), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return "sha256:" + hashlib.sha256(request_id.encode() + b":" + phase.encode() + b":" + digest).hexdigest()


def _persist(memory: Any, base_id: str, phase: str, values: Mapping[str, Any], inventory_hash: str) -> dict[str, Any]:
    payload = {**dict(values), "type": "crawlseo_activation", "operatorRequestId": f"{base_id}:{phase}",
               "receiptId": _receipt_id(base_id, phase, values), "state": phase,
               "decision": "activate_crawlseo_authority", "currentKeys": [f"crawlseo_activation:{phase}"]}
    stored, _ = memory.persist_crawlseo_migration_receipt(
        payload, validate_snapshot=lambda live: evidence_hash(live) == inventory_hash)
    return stored


def build_crawlseo_activation(tenant: Any, preflight: Mapping[str, Any], body: Mapping[str, Any],
                              env: Mapping[str, str] | None = None, *, client_factory: Any = None) -> dict[str, Any]:
    request = _request(body)
    prepared = _prepare(tenant, preflight, request, dict(env or {}), client_factory)
    path, _config, raw, _updated, proposed, site_id, project_id, inventory, binding = prepared
    return {"valid": True, "mode": request["mode"], "tenant": tenant.tenant_id, "siteId": site_id,
            "projectId": project_id, "expectedSnapshotHash": request["expectedSnapshotHash"],
            "expectedConfigHash": _digest(raw), "proposedConfigHash": _digest(proposed),
            "binding": binding, "producerFreezePreserved": True, "paidOperationsAllowed": False,
            "budgetPolicyImported": False, "wouldPersist": request["mode"] == "apply"}


def apply_crawlseo_activation(registry: Any, tenant: Any, preflight: Mapping[str, Any], body: Mapping[str, Any], *,
                              env: Mapping[str, str] | None = None, client_factory: Any = None) -> dict[str, Any]:
    request = _request(body)
    if request["mode"] != "apply":
        raise CrawlSEOActivationError("apply_crawlseo_activation requires mode=apply")
    tenant_id = str(getattr(tenant, "tenant_id", "") or "").strip().lower()
    if getattr(registry, "tenants", {}).get(tenant_id) is not tenant:
        raise CrawlSEOActivationError("tenant is not the active registered tenant")
    memory = tenant.memory
    phases_allowed = {"begin", "config_saved", "runtime_verified", "runtime_unverified"}
    allowed_request_ids = {f"{request['operatorRequestId']}:{phase}" for phase in phases_allowed}
    phases = {row.get("state"): row for row in memory.crawlseo_migration_receipts()
              if isinstance(row, Mapping) and row.get("type") == "crawlseo_activation"
              and row.get("operatorRequestId") in allowed_request_ids}
    for checkpoint in phases.values():
        if any(checkpoint.get(key) != request.get(key) for key in (
            "expectedSnapshotHash", "expectedConfigHash", "reason",
        )):
            raise CrawlSEOActivationError("operatorRequestId already has a conflicting activation receipt")
    if "runtime_verified" in phases:
        verified = phases["runtime_verified"]
        _path, config, current_raw = _read_config(tenant)
        if _digest(current_raw) != verified.get("proposedConfigHash"):
            raise CrawlSEOActivationError("tenant config changed after authority activation")
        _verify_active_runtime(tenant, verified, dict(env or {}))
        _finish_dispatch_hold(memory, request["operatorRequestId"], verified)
        return {"status": "authority_active", "idempotent": True, "paidOperationsAllowed": False,
                "receipt": verified}
    if "config_saved" in phases:
        _pause_dispatch(memory, request["operatorRequestId"])
        begin = phases.get("begin")
        saved = phases["config_saved"]
        if not isinstance(begin, Mapping) or any(saved.get(key) != begin.get(key) for key in (
            "tenant", "siteId", "projectId", "expectedSnapshotHash", "expectedConfigHash", "proposedConfigHash", "inventoryHash", "reason",
        )):
            raise CrawlSEOActivationError("saved activation checkpoint is inconsistent")
        path, config, current_raw = _read_config(tenant)
        if _digest(current_raw) != saved.get("proposedConfigHash"):
            raise CrawlSEOActivationError("saved authority config changed during activation recovery")
        inventory_hash = str(begin.get("inventoryHash") or "")
        if evidence_hash(memory.crawlseo_migration_snapshot()) != inventory_hash:
            raise CrawlSEOActivationError("local inventory changed during activation recovery")
        _require_frozen_runtime(tenant)
        return _verify_saved_runtime(registry, tenant, path, config, request, begin, dict(env or {}), client_factory)
    begin = phases.get("begin")
    if begin:
        if any(begin.get(key) != request.get(key) for key in (
            "expectedSnapshotHash", "expectedConfigHash", "reason",
        )) or begin.get("tenant") != tenant_id:
            raise CrawlSEOActivationError("operatorRequestId already has a conflicting activation receipt")
        site_id, inventory = _validate_preflight(tenant, preflight, request["expectedSnapshotHash"])
        inventory_hash = evidence_hash(inventory)
        if inventory_hash != begin.get("inventoryHash") or evidence_hash(memory.crawlseo_migration_snapshot()) != inventory_hash:
            raise CrawlSEOActivationError("local inventory changed during activation recovery")
        _require_frozen_runtime(tenant)
        path, config, raw = _read_config(tenant)
        disk_hash = _digest(raw)
        if disk_hash == begin.get("expectedConfigHash"):
            prepared = _prepare(tenant, preflight, request, dict(env or {}), client_factory)
            path, config, raw, updated, proposed, site_id, project_id, inventory, binding = prepared
            if _digest(proposed) != begin.get("proposedConfigHash") or binding != begin.get("binding"):
                raise CrawlSEOActivationError("activation recovery no longer matches the begin checkpoint")
        elif disk_hash == begin.get("proposedConfigHash"):
            updated = config
            proposed = raw
            project_id = str(begin.get("projectId") or "")
            binding = _probe(updated, {
                **dict(env or {}), **load_connector_runtime_environment(config),
            }, site_id, project_id, client_factory or _client)
            if binding != begin.get("binding"):
                raise CrawlSEOActivationError("saved authority binding differs from the begin checkpoint")
        else:
            raise CrawlSEOActivationError("tenant config changed during activation recovery")
        base = {key: begin.get(key) for key in (
            "tenant", "siteId", "projectId", "expectedSnapshotHash", "expectedConfigHash",
            "proposedConfigHash", "reason", "binding", "inventoryHash",
        )}
    else:
        prepared = _prepare(tenant, preflight, request, dict(env or {}), client_factory)
        path, config, raw, updated, proposed, site_id, project_id, inventory, binding = prepared
        inventory_hash = evidence_hash(inventory)
        base = {"tenant": tenant_id, "siteId": site_id, "projectId": project_id,
                "expectedSnapshotHash": request["expectedSnapshotHash"], "expectedConfigHash": request["expectedConfigHash"],
                "proposedConfigHash": _digest(proposed), "reason": request["reason"],
                "binding": binding, "inventoryHash": inventory_hash}
        _persist(memory, request["operatorRequestId"], "begin", base, inventory_hash)
    _pause_dispatch(memory, request["operatorRequestId"])
    begin = base
    # Persist the explicit hold before changing authority config. There is no
    # reviewed legacy-budget import path, so scheduler reconciliation must not
    # submit new paid CrawlSEO work after this cutover request.
    memory.kv_set("crawlseo_activation:paid_dispatch_hold", {
        "active": True, "operatorRequestId": request["operatorRequestId"],
        "reason": "CrawlSEO paid policy import is not implemented",
    })
    try:
        if _digest(path.read_bytes()) != _digest(proposed):
            _replace_config_cas(path, updated, request["expectedConfigHash"], tenant)
        saved = path.read_bytes()
        if _digest(saved) != _digest(proposed):
            raise CrawlSEOActivationError("saved authority config does not match the proposed hash")
        _persist(memory, request["operatorRequestId"], "config_saved", base, inventory_hash)
    except Exception as exc:
        # Never clear the durable producer fence or restore local authority.
        if isinstance(exc, CrawlSEOActivationError):
            raise
        raise CrawlSEOActivationError("authority config could not be saved; producer freeze remains active") from exc
    runtime_tenant = tenant
    try:
        runtime_tenant = registry.reload_tenant(
            tenant_id, str(path), api_token=str(getattr(tenant, "api_token", "") or ""),
            api_token_env=str(getattr(tenant, "api_token_env", "") or "") or None,
            env={**dict(env or {}), **load_connector_runtime_environment(updated)},
        )
        memory = runtime_tenant.memory
        _require_frozen_runtime(runtime_tenant)
        settings = CrawlSEOSettings.from_config(runtime_tenant.config, {**dict(env or {}), **load_connector_runtime_environment(runtime_tenant.config)})
        if settings.research_authority != "crawlseo" or settings.connector_token_env != CONNECTOR_RUNTIME_TOKEN_ENV:
            raise CrawlSEOActivationError("reloaded tenant did not adopt managed CrawlSEO authority")
        service = runtime_tenant.context.get("crawlseo_service")
        if service is None:
            raise CrawlSEOActivationError("reloaded tenant has no CrawlSEO application service")
        verified_binding = _capability_binding(service.connector_capabilities(site_id), site_id, project_id)
        if verified_binding != binding:
            raise CrawlSEOActivationError("reloaded runtime binding differs from preflight capability proof")
        verified = _persist(memory, request["operatorRequestId"], "runtime_verified", {**base, "binding": verified_binding}, inventory_hash)
        _finish_dispatch_hold(memory, request["operatorRequestId"], verified)
        return {"status": "authority_active", "idempotent": False, "paidOperationsAllowed": False,
                "budgetPolicyImported": False, "receipt": verified}
    except Exception as exc:
        # The replacement Memory is the live durable handle after reload closes the prior one.
        try:
            _persist(memory, request["operatorRequestId"], "runtime_unverified", base, inventory_hash)
        except Exception:
            pass
        return {"status": "config_saved_runtime_unverified", "idempotent": False,
                "paidOperationsAllowed": False, "retryRequired": True,
                "notice": "Authority config is saved but runtime verification failed. The producer freeze remains active.",
                "error": "Runtime verification failed; retry with the same operatorRequestId."}


def _require_frozen_runtime(tenant: Any) -> None:
    freeze = tenant.memory.crawlseo_producer_freeze_status()
    scheduler = getattr(getattr(tenant, "runtime", None), "scheduler", None)
    if (freeze.get("active") is not True or freeze.get("registrationsVerified") is not True
            or freeze.get("pendingDrain") is not False):
        raise CrawlSEOActivationError("producer freeze, scheduler verification, or drain completion was lost")
    if scheduler is None or not isinstance(getattr(scheduler, "jobs", None), list):
        raise CrawlSEOActivationError("actual scheduler registrations could not be inspected")
    active = sorted({str(row[0]) for row in scheduler.jobs
                     if isinstance(row, (tuple, list)) and row and str(row[0]) in _LEGACY_JOBS})
    if active:
        raise CrawlSEOActivationError("legacy producer registrations remain active: " + ", ".join(active))


def _verify_saved_runtime(registry: Any, tenant: Any, path: Any, config: Mapping[str, Any],
                          request: Mapping[str, str], begin: Mapping[str, Any], env: Mapping[str, str],
                          client_factory: Any) -> dict[str, Any]:
    tenant_id = str(tenant.tenant_id)
    base = {key: begin.get(key) for key in (
        "tenant", "siteId", "projectId", "expectedSnapshotHash", "expectedConfigHash",
        "proposedConfigHash", "reason", "binding", "inventoryHash",
    )}
    runtime_tenant = tenant
    memory = tenant.memory
    try:
        runtime_tenant = registry.reload_tenant(
            tenant_id, str(path), api_token=str(getattr(tenant, "api_token", "") or ""),
            api_token_env=str(getattr(tenant, "api_token_env", "") or "") or None,
            env={**dict(env), **load_connector_runtime_environment(config)},
        )
        memory = runtime_tenant.memory
        _verify_active_runtime(runtime_tenant, begin, env)
        binding = dict(begin["binding"])
        receipt = _persist(memory, request["operatorRequestId"], "runtime_verified", {**base, "binding": binding},
                           str(begin["inventoryHash"]))
        _finish_dispatch_hold(memory, request["operatorRequestId"], receipt)
        return {"status": "authority_active", "idempotent": True, "paidOperationsAllowed": False,
                "budgetPolicyImported": False, "receipt": receipt}
    except Exception as exc:
        try:
            _persist(memory, request["operatorRequestId"], "runtime_unverified", base, str(begin["inventoryHash"]))
        except Exception:
            pass
        return {"status": "config_saved_runtime_unverified", "idempotent": True,
                "paidOperationsAllowed": False, "retryRequired": True,
                "notice": "Authority config is saved but runtime verification failed. The producer freeze remains active.",
                "error": "Runtime verification failed; retry with the same operatorRequestId."}


def _verify_active_runtime(tenant: Any, checkpoint: Mapping[str, Any], env: Mapping[str, str]) -> None:
    """Revalidate active config, freeze, scheduler, paid hold, and live binding."""
    _require_frozen_runtime(tenant)
    hold = tenant.memory.kv_get("crawlseo_activation:paid_dispatch_hold", None)
    if not isinstance(hold, Mapping) or hold.get("active") is not True:
        raise CrawlSEOActivationError("CrawlSEO paid dispatch hold is missing")
    runtime_env = {**dict(env), **load_connector_runtime_environment(tenant.config)}
    settings = CrawlSEOSettings.from_config(tenant.config, runtime_env)
    if settings.research_authority != "crawlseo" or settings.connector_token_env != CONNECTOR_RUNTIME_TOKEN_ENV:
        raise CrawlSEOActivationError("active tenant config does not select the managed CrawlSEO authority")
    service = tenant.context.get("crawlseo_service") if isinstance(tenant.context, Mapping) else None
    if service is None:
        raise CrawlSEOActivationError("active tenant has no CrawlSEO application service")
    binding = _capability_binding(service.connector_capabilities(str(checkpoint["siteId"])),
                                  str(checkpoint["siteId"]), str(checkpoint["projectId"]))
    if binding != checkpoint.get("binding"):
        raise CrawlSEOActivationError("active runtime binding differs from the activation checkpoint")


def _pause_dispatch(memory: Any, request_id: str) -> None:
    current = memory.kv_get(CONNECTOR_DISPATCH_HOLD_KEY, None)
    if current is not None and (not isinstance(current, Mapping)
            or current.get("operatorRequestId") != request_id):
        raise CrawlSEOActivationError("another activation owns the connector dispatch hold")
    memory.kv_set(CONNECTOR_DISPATCH_HOLD_KEY, {"active": True, "operatorRequestId": request_id})


def _finish_dispatch_hold(memory: Any, request_id: str, receipt: Mapping[str, Any]) -> None:
    current = memory.kv_get(CONNECTOR_DISPATCH_HOLD_KEY, None)
    if not isinstance(current, Mapping) or current.get("operatorRequestId") != request_id:
        raise CrawlSEOActivationError("activation connector dispatch hold is missing or changed")
    memory.kv_set(CONNECTOR_DISPATCH_HOLD_KEY, {"active": False, "operatorRequestId": request_id,
        "verificationReceiptId": receipt["receiptId"]})


__all__ = ["CrawlSEOActivationError", "build_crawlseo_activation", "apply_crawlseo_activation"]
