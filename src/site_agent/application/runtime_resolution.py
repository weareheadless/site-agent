"""Read-only authority check for a registered tenant's active runtime."""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..credentials import credential_environment
from ..hands import cloudflare_worker_verification
from .release_queue import release_root
from .runtime_activation import RuntimeActivation


class RuntimeResolutionError(ValueError):
    """Registered runtime evidence is unavailable or no longer authoritative."""


@dataclass(frozen=True, slots=True)
class RuntimeResolution:
    activation: RuntimeActivation
    deployment_id: str
    active_version: str
    script_etag: str
    binding_identity: str


def _contract(config: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    site = config.get("site") if isinstance(config.get("site"), Mapping) else {}
    payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
    raw = payload.get("contract")
    if not isinstance(raw, Mapping):
        raise RuntimeResolutionError("registered Payload runtime contract is unavailable")
    identity = {
        "adminVersion": raw.get("adminVersion"), "contract": raw.get("contract"),
        "coreVersion": raw.get("coreVersion"), "schemaRevision": raw.get("schemaRevision"),
        "schemaIdentity": raw.get("schemaIdentity"), "migrationHead": raw.get("migrationHead"),
    }
    if any(value is None for value in identity.values()):
        raise RuntimeResolutionError("registered Payload runtime contract is incomplete")
    website = site.get("website_present")
    journey = config.get("ada_journey") or config.get("journey") or {}
    if isinstance(journey, Mapping) and "website_present" in journey:
        website = journey["website_present"]
    if not isinstance(website, bool):
        raise RuntimeResolutionError("registered websitePresent state is unavailable")
    return identity, website


def _receipt_path(config: Mapping[str, Any], activation: RuntimeActivation) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", activation.tenant_id) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,79}", activation.release_id
    ):
        raise RuntimeResolutionError("runtime activation path identity is invalid")
    runs = release_root(config) / "runs"
    path = runs / activation.tenant_id / activation.release_id / "receipt.json"
    try:
        for component in (runs, runs / activation.tenant_id, runs / activation.tenant_id / activation.release_id):
            if component.is_symlink() or not stat.S_ISDIR(component.stat().st_mode):
                raise RuntimeResolutionError("canonical release receipt path is unsafe")
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeResolutionError("canonical release receipt is not a regular file")
        if not path.resolve().is_relative_to(runs.resolve()):
            raise RuntimeResolutionError("canonical release receipt escapes the release root")
    except OSError as exc:
        raise RuntimeResolutionError("canonical release receipt is unavailable") from exc
    return path


class RuntimeResolutionService:
    """Resolve only the registered tenant's persisted activation and receipt."""

    def __init__(self, root_config: Mapping[str, Any], *, registry: Any,
                 registration: Any, env: Mapping[str, str] | None = None) -> None:
        self.root_config = root_config
        self.registry = registry
        self.registration = registration
        self.env = dict(env or {})

    def _registered(self, tenant_id: str) -> tuple[Any, RuntimeActivation, dict[str, Any], bool, str]:
        if not isinstance(tenant_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", tenant_id):
            raise RuntimeResolutionError("tenant is not registered")
        try:
            if not self.registration.is_registered(tenant_id):
                raise RuntimeResolutionError("tenant is not registered")
        except RuntimeResolutionError:
            raise
        except Exception as exc:
            raise RuntimeResolutionError("tenant registration could not be verified") from None
        tenant = self.registry.for_tenant_id(tenant_id)
        if tenant is None or tenant.tenant_id != tenant_id:
            raise RuntimeResolutionError("registered tenant is not mounted")
        try:
            config_path = Path(tenant.config_path)
            if not config_path.is_file() or config_path.is_symlink():
                raise RuntimeResolutionError("registered tenant config is unavailable")
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except RuntimeResolutionError:
            raise
        except (OSError, UnicodeError, yaml.YAMLError):
            raise RuntimeResolutionError("registered tenant config is unavailable") from None
        if not isinstance(config, Mapping) or config.get("instance_name") != tenant_id:
            raise RuntimeResolutionError("registered tenant config identity is invalid")
        site = config.get("site") if isinstance(config.get("site"), Mapping) else {}
        payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
        try:
            raw_binding = payload.get("runtime_activation")
            if raw_binding is None:
                raise RuntimeResolutionError("tenant has no registered runtime activation")
            activation = RuntimeActivation.from_mapping(raw_binding)
        except RuntimeResolutionError:
            raise
        except (TypeError, ValueError):
            raise RuntimeResolutionError("tenant runtime activation is malformed") from None
        if activation.tenant_id != tenant_id:
            raise RuntimeResolutionError("runtime activation tenant identity mismatch")
        worker_config = site.get("source_deployment") if isinstance(site.get("source_deployment"), Mapping) else {}
        worker = worker_config.get("worker_name")
        if not isinstance(worker, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
            raise RuntimeResolutionError("registered Worker identity is invalid")
        # Use this just-read registered config for contract checks as well.
        identity, website = _contract(config)
        return tenant, activation, identity, website, worker

    def resolve(self, tenant_id: str) -> RuntimeResolution:
        tenant, activation, identity, website, worker = self._registered(tenant_id)
        try:
            receipt_path = _receipt_path(self.root_config, activation)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except RuntimeResolutionError:
            raise
        except (OSError, UnicodeError, ValueError):
            raise RuntimeResolutionError("canonical release receipt is unavailable or malformed") from None
        if not isinstance(receipt, Mapping) or receipt.get("status") not in {"deployed", "verified"}:
            raise RuntimeResolutionError("canonical release receipt is not terminal and successful")
        if (receipt.get("tenant") != tenant_id or receipt.get("releaseId") != activation.release_id
                or receipt.get("sourceSha") != activation.source_sha):
            raise RuntimeResolutionError("canonical release receipt identity mismatch")
        try:
            from_receipt = RuntimeActivation.from_receipt(tenant_id, activation.release_id, receipt)
        except (TypeError, ValueError):
            raise RuntimeResolutionError("canonical release receipt activation is incomplete") from None
        if from_receipt != activation:
            raise RuntimeResolutionError("canonical release receipt differs from registered activation")
        health = receipt.get("health")
        expected_health = {"ok": True, "tenant": tenant_id, "releaseSha": activation.source_sha,
                           "payloadAdmin": identity["adminVersion"], "payloadCore": identity["coreVersion"],
                           "contentContract": identity["contract"], "schemaRevision": identity["schemaRevision"],
                           "schemaIdentity": identity["schemaIdentity"], "migrationHead": identity["migrationHead"]}
        if not isinstance(health, Mapping) or any(health.get(k) != v for k, v in expected_health.items()):
            raise RuntimeResolutionError("canonical receipt health does not match registered runtime")
        if receipt.get("websitePresent") is not website:
            raise RuntimeResolutionError("canonical receipt websitePresent differs from registered runtime")
        deployment = receipt.get("deployment")
        versions = deployment.get("versions") if isinstance(deployment, Mapping) else None
        if (not isinstance(deployment, Mapping) or not isinstance(deployment.get("id"), str)
                or not deployment.get("id") or not isinstance(versions, list) or len(versions) != 1
                or not isinstance(versions[0], Mapping)
                or versions[0].get("version_id") != activation.uploaded_version
                or versions[0].get("percentage") != 100):
            raise RuntimeResolutionError("receipt lacks exact uploaded-version deployment evidence")
        try:
            deploy_env = credential_environment(self.root_config, self.env)
            verified = cloudflare_worker_verification.resolve_verified_active_worker(
                {"worker": worker}, deploy_env, activation.uploaded_version,
            )
            deployment_now, active_version, uploaded_identity, _active_identity = verified
            if not isinstance(uploaded_identity, Mapping):
                raise ValueError("invalid Worker identity")
            deployment_id = deployment_now.get("id")
            if not isinstance(deployment_id, str) or not deployment_id:
                raise ValueError("invalid deployment identity")
            # Re-read registered authority and exact receipt after remote verification.
            current_tenant, current_activation, _, _, current_worker = self._registered(tenant_id)
            if (current_tenant is not tenant or current_activation != activation or current_worker != worker):
                raise RuntimeResolutionError("registered runtime identity drifted during verification")
            current_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(current_receipt, Mapping) or RuntimeActivation.from_receipt(
                tenant_id, activation.release_id, current_receipt
            ) != activation or current_receipt.get("tenant") != tenant_id or current_receipt.get("releaseId") != activation.release_id:
                raise RuntimeResolutionError("canonical receipt identity drifted during verification")
            cloudflare_worker_verification.require_active_worker_snapshot(
                {"worker": worker}, deploy_env, deployment_id, active_version,
            )
        except RuntimeResolutionError:
            raise
        except Exception:
            raise RuntimeResolutionError("registered Worker could not be freshly verified") from None
        etag, binding_identity = uploaded_identity.get("script_etag"), uploaded_identity.get("binding_identity")
        if not all(isinstance(value, str) and value for value in (etag, binding_identity)):
            raise RuntimeResolutionError("verified Worker identity is incomplete")
        return RuntimeResolution(activation, deployment_id, active_version, etag, binding_identity)


__all__ = ["RuntimeResolution", "RuntimeResolutionError", "RuntimeResolutionService"]
