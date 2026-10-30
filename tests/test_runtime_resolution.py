from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from site_agent.application.runtime_activation import RuntimeActivation
from site_agent.application.runtime_resolution import RuntimeResolutionError, RuntimeResolutionService
from site_agent.application.tenant_registration import TenantRegistrationService
from site_agent.application.workspace import TenantRegistry
from site_agent.config import load


def _setup(tmp_path: Path, tenant_id="new-site"):
    root_file = tmp_path / "host.yaml"
    root_file.write_text(f"data_dir: {tmp_path / 'host'}\nworkspace_api:\n  enabled: true\n  provisioned_root: {tmp_path / 'websites'}\n  tenants: {{}}\ndeployment_pipeline:\n  release_root: {tmp_path / 'releases'}\n", encoding="utf-8")
    env = {"HOST_TOKEN": "host"}
    config, _ = load(root_file, env)
    seed = TenantRegistry.from_config(config, env)
    registration = TenantRegistrationService(config, env, registry=seed)
    registration.register(tenant_id)
    path = tmp_path / "websites" / tenant_id / "config.yaml"
    tenant_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    binding = RuntimeActivation(1, tenant_id, "release-1", "a" * 40, "b" * 40, "c" * 64, "version-1")
    tenant_config["site"].update(adapter="payload_gateway", website_present=True,
        source_deployment={"worker_name": f"{tenant_id}-worker"})
    tenant_config["site"]["payload"].update(enabled=True, token_env=f"PROVISIONED_{tenant_id.upper().replace('-', '_')}_TOKEN",
        url=f"https://{tenant_id}.example", api_prefix="/api/workspace",
        runtime_activation=binding.to_dict(), contract={
        "adminVersion": "1.0", "contract": "helloada-content-v1", "coreVersion": "2.0.0",
        "schemaRevision": 3, "schemaIdentity": "d" * 64, "migrationHead": "e" * 64, "media_fields": [],
    })
    TenantRegistrationService._replace_config(path, tenant_config)
    registration.mark_runtime_mounted(tenant_id)
    receipt = {"status": "deployed", "tenant": tenant_id, "releaseId": binding.release_id,
        "sourceSha": binding.source_sha, "pipelineSha": binding.control_sha,
        "sharedRuntimeFingerprint": binding.shared_runtime_fingerprint,
        "uploadedVersion": binding.uploaded_version, "payloadAdmin": "1.0", "contentContract": "helloada-content-v1",
        "payloadCore": "2.0.0", "schemaRevision": 3, "schemaIdentity": "d" * 64, "migrationHead": "e" * 64,
        "websitePresent": True, "health": {"ok": True, "tenant": tenant_id, "releaseSha": binding.source_sha,
            "payloadAdmin": "1.0", "contentContract": "helloada-content-v1", "payloadCore": "2.0.0",
            "schemaRevision": 3, "schemaIdentity": "d" * 64, "migrationHead": "e" * 64},
        "deployment": {"id": "receipt-deploy", "versions": [{"version_id": binding.uploaded_version, "percentage": 100}]}}
    run = tmp_path / "releases" / "runs" / tenant_id / binding.release_id
    run.mkdir(parents=True)
    receipt_path = run / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    registry = TenantRegistry.from_config(config, env)
    registration = TenantRegistrationService(config, env, registry=registry)
    service = RuntimeResolutionService(config, registry=registry, registration=registration, env={})
    return service, registry, receipt_path, receipt, binding


def _verified(*_args):
    return ({"id": "live-deployment", "versions": [{"version_id": "version-1", "percentage": 100}]},
            "version-1", {"script_etag": "etag", "binding_identity": "f" * 64},
            {"script_etag": "etag", "binding_identity": "f" * 64})


def test_registered_receipt_resolves_secret_free_immutable_evidence(tmp_path, monkeypatch):
    from site_agent.hands import cloudflare_worker_verification as verifier
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", _verified)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    service, registry, receipt_path, _receipt, binding = _setup(tmp_path)
    config_path = Path(registry.for_tenant_id("new-site").config_path)
    receipt_before, config_before = receipt_path.read_bytes(), config_path.read_bytes()
    try:
        result = service.resolve("new-site")
        assert result.activation == binding
        assert result.deployment_id == "live-deployment"
        assert result.active_version == "version-1"
        assert "secret" not in repr(result).lower()
        with pytest.raises((AttributeError, TypeError)):
            result.deployment_id = "changed"
        assert receipt_path.read_bytes() == receipt_before
        assert config_path.read_bytes() == config_before
    finally:
        registry.close()


def test_unknown_tenant_and_symlink_receipt_fail_closed(tmp_path, monkeypatch):
    from site_agent.hands import cloudflare_worker_verification as verifier
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", _verified)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    service, registry, receipt_path, _receipt, _binding = _setup(tmp_path)
    try:
        with pytest.raises(RuntimeResolutionError, match="not registered"):
            service.resolve("other-site")
        outside = tmp_path / "outside.json"
        outside.write_text(receipt_path.read_text(encoding="utf-8"), encoding="utf-8")
        receipt_path.unlink()
        receipt_path.symlink_to(outside)
        with pytest.raises(RuntimeResolutionError, match="regular file"):
            service.resolve("new-site")
    finally:
        registry.close()


def test_failed_receipt_cannot_be_authorized_by_worker_verifier(tmp_path, monkeypatch):
    from site_agent.hands import cloudflare_worker_verification as verifier
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", _verified)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    service, registry, receipt_path, receipt, _binding = _setup(tmp_path)
    receipt["status"] = "failed"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    try:
        with pytest.raises(RuntimeResolutionError, match="terminal"):
            service.resolve("new-site")
    finally:
        registry.close()


def test_registered_activation_drift_during_verification_is_rejected(tmp_path, monkeypatch):
    from site_agent.hands import cloudflare_worker_verification as verifier
    service, registry, _path, _receipt, _binding = _setup(tmp_path)
    config_path = Path(registry.for_tenant_id("new-site").config_path)
    def mutate_registered_config(*_args):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["site"]["payload"]["runtime_activation"]["uploaded_version"] = "version-2"
        TenantRegistrationService._replace_config(config_path, config)
        return _verified()
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", mutate_registered_config)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    try:
        with pytest.raises(RuntimeResolutionError, match="drifted"):
            service.resolve("new-site")
    finally:
        registry.close()


def test_composes_canonical_verifier_and_rechecks_active_snapshot(tmp_path, monkeypatch):
    from site_agent.hands import cloudflare_worker_verification as verifier
    calls = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps(self.payload).encode()
    deployment = {"id": "live-deployment", "created_on": "2026-01-01T00:00:00Z",
        "annotations": {}, "versions": [{"version_id": "version-1", "percentage": 100}]}
    version = {"id": "version-1", "resources": {"script": {"etag": "etag"}, "bindings": [
        {"name": "DB", "type": "d1", "id": "db-id"},
        {"name": "TOKEN", "type": "secret_text", "text": "never-retain-this"}]}}
    def transport(request, **_kwargs):
        calls.append(request.full_url)
        if request.full_url.endswith("/deployments"):
            return Response({"success": True, "result": {"deployments": [deployment]}})
        return Response({"success": True, "result": version})
    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    service, registry, _path, _receipt, _binding = _setup(tmp_path)
    service.env = {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "private-token"}
    try:
        evidence = service.resolve("new-site")
        assert evidence.active_version == "version-1"
        assert evidence.deployment_id == "live-deployment"
        assert len(calls) == 4
        assert all("private-token" not in value and "never-retain-this" not in repr(evidence) for value in calls)
    finally:
        registry.close()
