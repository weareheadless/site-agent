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


@pytest.mark.parametrize("drift", ["status", "health", "deployment", "path", "contract", "website"])
def test_all_receipt_and_registered_authority_is_rechecked_after_verification(tmp_path, monkeypatch, drift):
    from site_agent.hands import cloudflare_worker_verification as verifier
    service, registry, receipt_path, receipt, _binding = _setup(tmp_path)
    config_path = Path(registry.for_tenant_id("new-site").config_path)
    def mutate(*_args):
        changed = json.loads(json.dumps(receipt))
        if drift == "status": changed["status"] = "failed"
        elif drift == "health": changed["health"]["schemaIdentity"] = "bad"
        elif drift == "deployment": changed["deployment"]["versions"][0]["percentage"] = 50
        elif drift == "path":
            receipt_path.unlink()
            receipt_path.parent.rmdir()
        elif drift in {"contract", "website"}:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if drift == "contract": config["site"]["payload"]["contract"]["schemaIdentity"] = "bad"
            else: config["site"]["website_present"] = False
            TenantRegistrationService._replace_config(config_path, config)
        if drift not in {"contract", "website", "path"}:
            receipt_path.write_text(json.dumps(changed), encoding="utf-8")
        return _verified()
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", mutate)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    try:
        with pytest.raises(RuntimeResolutionError):
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
        assert request.get_method() == "GET"
        calls.append(request.full_url)
        if request.full_url.endswith("/deployments"):
            return Response({"success": True, "result": {"deployments": [deployment]}})
        return Response({"success": True, "result": version})
    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    service, registry, _path, _receipt, _binding = _setup(tmp_path)
    config_path = Path(registry.for_tenant_id("new-site").config_path)
    config_before = config_path.read_bytes()
    service.env = {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "private-token"}
    try:
        evidence = service.resolve("new-site")
        assert evidence.active_version == "version-1"
        assert evidence.deployment_id == "live-deployment"
        assert len(calls) == 4
        assert config_path.read_bytes() == config_before
        assert all("private-token" not in value and "never-retain-this" not in repr(evidence) for value in calls)
    finally:
        registry.close()


@pytest.mark.parametrize("case", [
    "missing-binding", "malformed-binding", "wrong-tenant", "wrong-release",
    "wrong-source", "wrong-control", "wrong-fingerprint", "wrong-upload",
    "missing-receipt", "malformed-receipt", "nonterminal", "health-contract",
    "website-mismatch", "receipt-deployment", "unregistered", "unmounted",
])
def test_initial_invalid_registered_authority_fails_without_mutation(tmp_path, monkeypatch, case):
    from site_agent.hands import cloudflare_worker_verification as verifier
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", _verified)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    service, registry, receipt_path, receipt, binding = _setup(tmp_path)
    config_path = Path(registry.for_tenant_id("new-site").config_path)
    if case in {"missing-binding", "malformed-binding", "wrong-tenant"}:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if case == "missing-binding":
            del config["site"]["payload"]["runtime_activation"]
        elif case == "malformed-binding":
            config["site"]["payload"]["runtime_activation"] = {"tenant_id": "new-site"}
        else:
            config["site"]["payload"]["runtime_activation"]["tenant_id"] = "other-site"
        TenantRegistrationService._replace_config(config_path, config)
    elif case == "missing-receipt":
        receipt_path.unlink()
    elif case == "malformed-receipt":
        receipt_path.write_text("{", encoding="utf-8")
    elif case in {"wrong-release", "wrong-source", "wrong-control", "wrong-fingerprint", "wrong-upload", "nonterminal", "health-contract", "website-mismatch", "receipt-deployment"}:
        if case == "wrong-release": receipt["releaseId"] = "different-release"
        elif case == "wrong-source": receipt["sourceSha"] = "f" * 40
        elif case == "wrong-control": receipt["pipelineSha"] = "f" * 40
        elif case == "wrong-fingerprint": receipt["sharedRuntimeFingerprint"] = "f" * 64
        elif case == "wrong-upload": receipt["uploadedVersion"] = "different-version"
        elif case == "nonterminal": receipt["status"] = "running"
        elif case == "health-contract": receipt["health"]["schemaIdentity"] = "f" * 64
        elif case == "website-mismatch": receipt["websitePresent"] = False
        elif case == "receipt-deployment": receipt["deployment"]["versions"][0]["percentage"] = 50
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif case == "unregistered":
        original = service.registration.is_registered
        monkeypatch.setattr(service.registration, "is_registered", lambda _tenant: False)
    elif case == "unmounted":
        monkeypatch.setattr(service.registry, "for_tenant_id", lambda _tenant: None)
    before_receipt, before_config = receipt_path.read_bytes() if receipt_path.exists() else None, config_path.read_bytes()
    try:
        with pytest.raises(RuntimeResolutionError):
            service.resolve("new-site")
        assert (receipt_path.read_bytes() if receipt_path.exists() else None) == before_receipt
        assert config_path.read_bytes() == before_config
    finally:
        registry.close()


def test_two_registered_tenants_resolve_only_their_own_activation_and_receipt(tmp_path, monkeypatch):
    from site_agent.hands import cloudflare_worker_verification as verifier
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", _verified)
    monkeypatch.setattr(verifier, "require_active_worker_snapshot", lambda *_args: None)
    service, registry, _path, _receipt, _binding = _setup(tmp_path)
    registration = TenantRegistrationService(service.root_config, {}, registry=registry)
    second_path = Path(registration.register("second-site")["config_path"])
    second_config = yaml.safe_load(second_path.read_text(encoding="utf-8"))
    second_binding = RuntimeActivation(1, "second-site", "release-1", "1" * 40, "2" * 40, "3" * 64, "version-1")
    second_config["site"].update(adapter="payload_gateway", website_present=True,
        source_deployment={"worker_name": "second-site-worker"})
    from site_agent.application.tenant_registration import tenant_token_env
    second_config["site"]["payload"].update(enabled=True, token_env=tenant_token_env("second-site"),
        url="https://second-site.example", api_prefix="/api/workspace", runtime_activation=second_binding.to_dict(),
        contract={"adminVersion": "1.0", "contract": "helloada-content-v1", "coreVersion": "2.0.0",
            "schemaRevision": 3, "schemaIdentity": "4" * 64, "migrationHead": "5" * 64, "media_fields": []})
    TenantRegistrationService._replace_config(second_path, second_config)
    registration.mark_runtime_mounted("second-site")
    registry.close()
    registry = TenantRegistry.from_config(service.root_config, {})
    registration = TenantRegistrationService(service.root_config, {}, registry=registry)
    service = RuntimeResolutionService(service.root_config, registry=registry, registration=registration, env={})
    second_receipt = json.loads(json.dumps(_receipt))
    second_receipt.update(tenant="second-site", sourceSha=second_binding.source_sha,
        pipelineSha=second_binding.control_sha, sharedRuntimeFingerprint=second_binding.shared_runtime_fingerprint)
    second_receipt["health"].update(tenant="second-site", releaseSha=second_binding.source_sha)
    second_receipt["health"].update(schemaIdentity="4" * 64, migrationHead="5" * 64)
    second_receipt_path = tmp_path / "releases/runs/second-site/release-1/receipt.json"
    second_receipt_path.parent.mkdir(parents=True)
    second_receipt_path.write_text(json.dumps(second_receipt), encoding="utf-8")
    calls = []
    def verify(customer, *_args):
        calls.append(customer["worker"])
        return _verified()
    monkeypatch.setattr(verifier, "resolve_verified_active_worker", verify)
    try:
        service.resolve("new-site")
        service.resolve("second-site")
        assert calls == ["new-site-worker", "second-site-worker"]
    finally:
        registry.close()


@pytest.mark.parametrize("policy", ["split-traffic", "unauthorized-replacement", "permitted-secret-rotation"])
def test_real_verifier_enforces_worker_policy_and_get_only_transport(tmp_path, monkeypatch, policy):
    from site_agent.hands import cloudflare_worker_verification as verifier
    calls = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps(self.payload).encode()
    active = "version-2" if policy != "split-traffic" else "version-1"
    percentages = ([50, 50] if policy == "split-traffic" else [100])
    versions = ([{"version_id": "version-1", "percentage": 50}, {"version_id": "version-2", "percentage": 50}]
                if policy == "split-traffic" else [{"version_id": active, "percentage": 100}])
    annotations = {"workers/triggered_by": "secret"} if policy == "permitted-secret-rotation" else {}
    deployment = {"id": "live-deployment", "created_on": "2026-01-01T00:00:00Z",
        "annotations": annotations, "versions": versions}
    def transport(request, **_kwargs):
        assert request.get_method() == "GET"
        calls.append(request.full_url)
        if request.full_url.endswith("/deployments"):
            return Response({"success": True, "result": {"deployments": [deployment]}})
        version_id = request.full_url.rsplit("/", 1)[-1]
        secret = "uploaded-secret" if version_id == "version-1" else "rotated-secret"
        version = {"id": version_id, "resources": {"script": {"etag": "same-etag"}, "bindings": [
            {"name": "DB", "type": "d1", "id": "db-id"},
            {"name": "TOKEN", "type": "secret_text", "text": secret}]}}
        return Response({"success": True, "result": version})
    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    service, registry, receipt_path, _receipt, _binding = _setup(tmp_path)
    config_path = Path(registry.for_tenant_id("new-site").config_path)
    before_config = config_path.read_bytes()
    before_receipt = receipt_path.read_bytes()
    service.env = {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "private-token"}
    try:
        if policy == "permitted-secret-rotation":
            evidence = service.resolve("new-site")
            assert evidence.active_version == "version-2"
            assert evidence.script_etag == "same-etag"
            assert "uploaded-secret" not in repr(evidence) and "rotated-secret" not in repr(evidence)
        else:
            with pytest.raises(RuntimeResolutionError):
                service.resolve("new-site")
        assert calls and receipt_path.read_bytes() == before_receipt and config_path.read_bytes() == before_config
        assert all("private-token" not in url for url in calls)
    finally:
        registry.close()
