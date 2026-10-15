from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from site_agent.application.bootstrap import WebsiteBootstrapService
from site_agent.application.tenant_registration import TenantRegistrationService
from site_agent.application.workspace import TenantRegistry
from site_agent.config import load
from site_agent.hands.cloudflare_resources import CloudflareResourceProvisioner
from site_agent.hands.github_provisioning import GitHubRepositoryProvisioner
from site_agent.web.workspace import create_workspace_api_app

_TEST_HANDOFF_PUBLIC_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAoIThyhKH-lq0spevMAnsVT1aVp0yNYV07Ndd_aE1VIlfkMCxA5y_VLFmltt215rts1eaHvoYczPvRGfvR9Vc9ctssM5vSorWBH2v_gRCEH__ZKgAVrZh9K12jG8wXU3j06rn45bNIPVQV9ETOfUqK7cBXtrRKF_yCrM999Ov8N_D_OBkr54NIl-3xVjcHCmToiE9iDupQ-QqPeOCUAaS4oji9cmOnovaxchO_ZRKNQOpfl3gyYEO3uXRg11fthFB8MFtGoymisHqcSUi6UcYy3_v8TajD80Zp_o024PfgbjXxmGt-taTZ3kEvgmSXHZcbf15w3ha3rT0pvfaebDsAwIDAQAB"


def _host(tmp_path):
    root_config = tmp_path / "config.yaml"
    root_config.write_text(
        "\n".join([
            f"data_dir: {tmp_path / 'root'}",
            "workspace_api:",
            "  enabled: true",
            f"  provisioned_root: {tmp_path / 'websites'}",
            "  tenants: {}",
            "",
        ]),
        encoding="utf-8",
    )
    env: dict[str, str] = {}
    return (*load(root_config, env), env)


def test_github_repository_provisioner_is_idempotent_and_does_not_expose_token(monkeypatch):
    provisioner = GitHubRepositoryProvisioner("secret-token")
    calls: list[tuple[str, str]] = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path))
        if method == "GET" and path == "/repos/weareheadless/helloada-demo":
            return 200, {
                "full_name": "weareheadless/helloada-demo",
                "name": "helloada-demo",
                "clone_url": "https://github.com/weareheadless/helloada-demo.git",
                "ssh_url": "git@github.com:weareheadless/helloada-demo.git",
                "html_url": "https://github.com/weareheadless/helloada-demo",
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_repository("weareheadless", "helloada-demo")
    assert receipt.created is False
    assert "secret-token" not in receipt.html_url
    assert calls == [("GET", "/repos/weareheadless/helloada-demo")]


def test_cloudflare_d1_provisioner_reuses_existing_database(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")

    def fake_request(method, path, *, payload=None):
        assert method == "GET"
        assert "name=helloada-demo" in path
        return 200, {"success": True, "result": [{"uuid": "db-123", "name": "helloada-demo"}]}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_d1("helloada-demo")
    assert receipt.database_id == "db-123"
    assert receipt.created is False


def test_cloudflare_worker_provisioner_reuses_existing_identity(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")

    def fake_request(method, path, *, payload=None):
        assert method == "GET"
        assert path.endswith("/workers/workers?page=1&per_page=100")
        assert payload is None
        return 200, {"success": True, "result": [{"id": "worker-123", "name": "helloada-demo"}]}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_worker("helloada-demo")
    assert receipt.to_dict() == {"worker_id": "worker-123", "name": "helloada-demo", "created": False}


def test_cloudflare_worker_provisioner_creates_identity_before_version_upload(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    calls: list[tuple[str, str]] = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path))
        if method == "GET":
            return 200, {"success": True, "result": []}
        assert method == "POST"
        assert path == f"/accounts/{'a' * 32}/workers/workers"
        assert payload == {"name": "helloada-demo"}
        return 200, {"success": True, "result": {"id": "worker-123", "name": "helloada-demo"}}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_worker("helloada-demo")
    assert receipt.to_dict() == {"worker_id": "worker-123", "name": "helloada-demo", "created": True}
    assert [method for method, _path in calls] == ["GET", "POST"]


def test_cloudflare_worker_provisioner_reconciles_concurrent_creation(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    list_calls = 0

    def fake_request(method, path, *, payload=None):
        nonlocal list_calls
        if method == "GET":
            list_calls += 1
            rows = [] if list_calls == 1 else [{"id": "worker-123", "name": "helloada-demo"}]
            return 200, {"success": True, "result": rows}
        assert method == "POST"
        return 409, {"success": False, "errors": [{"message": "already exists"}]}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_worker("helloada-demo")
    assert receipt.worker_id == "worker-123"
    assert receipt.created is False
    assert list_calls == 2


def test_cloudflare_worker_provisioner_searches_every_list_page(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    paths: list[str] = []

    def fake_request(method, path, *, payload=None):
        assert method == "GET"
        assert payload is None
        paths.append(path)
        page = int(path.split("page=", 1)[1].split("&", 1)[0])
        if page == 1:
            return 200, {
                "success": True,
                "result": [{"id": str(i), "name": f"worker-{i}"} for i in range(100)],
                "result_info": {"total_pages": 2},
            }
        return 200, {
            "success": True,
            "result": [{"id": "worker-123", "name": "helloada-demo"}],
            "result_info": {"total_pages": 2},
        }

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_worker("helloada-demo")
    assert receipt.worker_id == "worker-123"
    assert len(paths) == 2


def test_cloudflare_worker_provisioner_rejects_incomplete_pagination(monkeypatch):
    from site_agent.hands.cloudflare_resources import CloudflareResourceError
    import pytest

    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")

    def fake_request(_method, _path, *, payload=None):
        assert payload is None
        return 200, {"success": True, "result": [{"id": str(i), "name": f"worker-{i}"} for i in range(100)]}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    with pytest.raises(CloudflareResourceError, match="omitted pagination metadata"):
        provisioner.ensure_worker("helloada-demo")


def test_cloudflare_worker_url_uses_the_configured_account_subdomain(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        assert method == "GET"
        assert path == f"/accounts/{'a' * 32}/workers/subdomain"
        assert payload is None
        return 200, {"success": True, "result": {"subdomain": "weareheadless"}}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    assert provisioner.workers_dev_url("helloada-demo") == (
        "https://helloada-demo.weareheadless.workers.dev"
    )
    assert len(calls) == 1


def test_cloudflare_worker_url_fails_closed_without_account_subdomain(monkeypatch):
    import pytest

    from site_agent.hands.cloudflare_resources import CloudflareResourceError

    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    monkeypatch.setattr(
        provisioner,
        "_request",
        lambda *_args, **_kwargs: (200, {"success": True, "result": {"subdomain": ""}}),
    )
    with pytest.raises(CloudflareResourceError, match="subdomain is not configured"):
        provisioner.workers_dev_url("helloada-demo")


def test_cloudflare_worker_route_is_enabled_after_upload_and_idempotent(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    calls = []
    path = f"/accounts/{'a' * 32}/workers/scripts/helloada-demo/subdomain"

    def fake_request(method, request_path, *, payload=None):
        calls.append((method, request_path, payload))
        if method == "GET":
            return 200, {"success": True, "result": {"enabled": False, "previews_enabled": False}}
        assert method == "POST"
        assert payload == {"enabled": True}
        return 200, {"success": True, "result": {"enabled": True, "previews_enabled": False}}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    provisioner.ensure_workers_dev_route("helloada-demo")
    assert calls == [("GET", path, None), ("POST", path, {"enabled": True})]


def test_cloudflare_worker_route_does_not_change_an_enabled_subdomain(monkeypatch):
    provisioner = CloudflareResourceProvisioner("a" * 32, "secret-token")
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        return 200, {"success": True, "result": {"enabled": True, "previews_enabled": True}}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    provisioner.ensure_workers_dev_route("helloada-demo")
    assert len(calls) == 1 and calls[0][0] == "GET"


def test_bootstrap_control_route_is_explicit_when_external_bootstrap_is_not_wired(tmp_path):
    config, _unused, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    registration = TenantRegistrationService(config, env, registry=registry)
    app = create_workspace_api_app(registry, control_token="control", registration=registration)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/control-plane/websites/demo/bootstrap",
                headers={"Authorization": "Bearer control"},
                json={"display_name": "Demo"},
            )
            assert response.status_code == 503
            assert "unavailable" in response.text
    finally:
        registry.close()


def test_bootstrap_status_is_durable_before_worker_starts(tmp_path):
    config, _unused, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    registration = TenantRegistrationService(config, env, registry=registry)
    service = WebsiteBootstrapService(config, env, registration=registration, registry=registry)
    try:
        registered = registration.register("demo", display_name="Demo")
        state = service.status("demo")
        assert registered["tenant_id"] == "demo"
        assert state["status"] == "queued"
        assert state["step"] == "requested"
    finally:
        service.close()
        registry.close()


def test_pending_bootstrap_status_is_visible_before_runtime_activation(tmp_path):
    config, _unused, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    registration = TenantRegistrationService(config, env, registry=registry)
    service = WebsiteBootstrapService(config, env, registration=registration, registry=registry)
    app = create_workspace_api_app(
        registry,
        control_token="control",
        registration=registration,
        bootstrap=service,
    )
    try:
        registration.register("demo", display_name="Demo")
        assert registry.for_tenant_id("demo") is None
        with TestClient(app) as client:
            response = client.get(
                "/v1/control-plane/websites/demo/bootstrap",
                headers={"Authorization": "Bearer control"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "queued"
            assert response.json()["step"] == "requested"

            missing = client.get(
                "/v1/control-plane/websites/unknown/bootstrap",
                headers={"Authorization": "Bearer control"},
            )
            assert missing.status_code == 404
    finally:
        service.close()
        registry.close()


def _adoption_fixture(tmp_path, *, registered=True):
    import threading

    tenant_id = "oceanicvibes"
    release_id = "20261008-oceanic-messages-schema-3"
    source_sha = "a" * 40
    uploaded_version = "903fba29-2211-4d6b-a7e4-5e3236a2c02a"
    worker_version = "18499a63-18ab-49bb-aa9a-3ba1311c328a"
    releases = tmp_path / "releases"
    receipt_path = releases / "runs" / tenant_id / release_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    identity = {
        "payloadAdmin": "0.10.2",
        "payloadCore": "0.5.6",
        "contentContract": "helloada-content-v3",
        "schemaRevision": 6,
        "schemaIdentity": "b" * 64,
        "migrationHead": "c" * 64,
    }
    receipt = {
        "tenant": tenant_id,
        "worker": tenant_id,
        "repository": "https://github.com/weareheadless/oceanicvibes.git",
        "releaseId": release_id,
        "sourceSha": source_sha,
        "status": "deployed",
        "approvalId": None,
        "uploadedVersion": uploaded_version,
        "deployment": {"versions": [{"version_id": uploaded_version, "percentage": 100}]},
        "currentVerification": {
            "releaseId": release_id,
            "sourceSha": source_sha,
            "uploadedVersion": uploaded_version,
            "workerVersion": worker_version,
            "deploymentId": "secret-rotation-deployment",
            "trafficPercentage": 100,
            "uploadedScriptEtag": "d" * 64,
            "activeScriptEtag": "d" * 64,
            "uploadedBindingIdentity": "e" * 64,
            "activeBindingIdentity": "e" * 64,
            "mode": "secret_rotation",
            "verifiedAt": "2026-10-08T11:45:27.168209Z",
        },
        "startedAt": "2026-10-08T11:38:27.168209Z",
        "connectionVerifiedAt": "2026-10-08T11:39:27.167607Z",
        "finishedAt": "2026-10-08T11:39:27.168209Z",
        "websitePresent": True,
        **identity,
        "health": {
            "ok": True,
            "tenant": tenant_id,
            "releaseSha": source_sha,
            **identity,
        },
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    class Registration:
        def is_registered(self, selected_tenant):
            return registered and selected_tenant == tenant_id

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"deployment_pipeline": {"release_root": str(releases)}}
    service.root = tmp_path / "websites"
    tenant_config_path = service.root / tenant_id / "config.yaml"
    tenant_config_path.parent.mkdir(parents=True)
    tenant_config_path.write_text(
        "site:\n  public_url: https://oceanicvibes.com/\n  source_deployment:\n    worker_name: oceanicvibes\n",
        encoding="utf-8",
    )
    service._lock = threading.RLock()
    service.registration = Registration()
    activated = []
    service._activate_runtime = lambda selected_tenant, _state: activated.append(selected_tenant)
    return service, tenant_id, release_id, source_sha, worker_version, receipt_path, activated, tenant_config_path


def test_adopt_verified_release_writes_readiness_and_is_idempotent(tmp_path):
    service, tenant, release, source_sha, version, _path, activated, _config = _adoption_fixture(tmp_path)

    result = service.adopt_verified_release(
        tenant,
        release_id=release,
        source_sha=source_sha,
    )
    state_path = service._state_path(tenant)
    saved = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["workspace_ready"] is True
    assert result["status"] == "done"
    assert saved["adoption"]["kind"] == "verified_existing_release"
    assert saved["adoption"]["release_id"] == release
    assert saved["adoption"]["source_sha"] == source_sha
    assert saved["adoption"]["worker_version"] == version
    assert saved["steps"]["adopting_existing_release"]["status"] == "done"
    assert saved["adoption"]["admin_origin"] == "https://oceanicvibes.com"
    assert saved["adoption"]["verified_at"] == "2026-10-08T11:39:27.167607Z"
    assert saved["resource_receipts"]["creating_worker"]["worker_url"] == "https://oceanicvibes.com"
    assert activated == [tenant]

    again = service.adopt_verified_release(
        tenant,
        release_id=release,
        source_sha=source_sha,
    )
    assert again["workspace_ready"] is True
    assert activated == [tenant]


def test_adopt_verified_release_rejects_unregistered_or_mismatched_identity(tmp_path):
    import pytest
    from site_agent.application.bootstrap import BootstrapError

    service, tenant, release, source_sha, version, _path, _activated, _config = _adoption_fixture(
        tmp_path / "unregistered",
        registered=False,
    )
    with pytest.raises(BootstrapError, match="canonical registry"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )

    service, tenant, release, source_sha, version, _path, _activated, _config = _adoption_fixture(
        tmp_path / "mismatch",
    )
    with pytest.raises(BootstrapError, match="deployed tenant identity"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha="d" * 40,
        )
    assert not service._state_path(tenant).exists()


def test_adopt_verified_release_rejects_stale_release_and_mismatched_admin_origin(tmp_path):
    import pytest
    from site_agent.application.bootstrap import BootstrapError

    service, tenant, release, source_sha, version, receipt_path, _activated, _config = _adoption_fixture(
        tmp_path / "stale",
    )
    newer_id = "20261008-oceanic-messages-schema-4"
    newer = json.loads(receipt_path.read_text(encoding="utf-8"))
    newer.update(
        releaseId=newer_id,
        sourceSha="d" * 40,
        startedAt="2026-10-08T11:40:27.168209Z",
        finishedAt="2026-10-08T11:40:27.168209Z",
    )
    newer_path = receipt_path.parent.parent / newer_id / "receipt.json"
    newer_path.parent.mkdir(parents=True)
    newer_path.write_text(json.dumps(newer), encoding="utf-8")
    with pytest.raises(BootstrapError, match="not the latest successful"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )
    assert not service._state_path(tenant).exists()

    service, tenant, release, source_sha, version, _path, _activated, config_path = _adoption_fixture(
        tmp_path / "origin",
    )
    config_path.write_text(
        "site:\n  public_url: https://wrong.example/\n  source_deployment:\n    worker_name: oceanicvibes\n",
        encoding="utf-8",
    )
    with pytest.raises(BootstrapError, match="does not match the release health origin"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )

def test_adopt_verified_release_rejects_nonactive_version_and_conflicting_state(tmp_path):
    import pytest
    from site_agent.application.bootstrap import BootstrapError

    service, tenant, release, source_sha, version, receipt_path, _activated, _config = _adoption_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["currentVerification"]["trafficPercentage"] = 50
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(BootstrapError, match="deployed tenant identity"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )
    receipt["currentVerification"]["trafficPercentage"] = 100
    receipt["health"]["schemaIdentity"] = "z" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(BootstrapError, match="health does not match"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )

    receipt["health"]["schemaIdentity"] = "b" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    state_path = service._state_path(tenant)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"tenant_id": tenant, "status": "queued"}), encoding="utf-8")
    with pytest.raises(BootstrapError, match="refusing to overwrite"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )


def test_adopt_verified_release_requires_resolved_active_worker_version(tmp_path):
    import pytest
    from site_agent.application.bootstrap import BootstrapError

    service, tenant, release, source_sha, _version, receipt_path, _activated, _config = _adoption_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["currentVerification"]["workerVersion"] = ""
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(BootstrapError, match="deployed tenant identity"):
        service.adopt_verified_release(
            tenant, release_id=release, source_sha=source_sha,
        )
    assert not service._state_path(tenant).exists()


def test_bootstrap_runtime_activation_requires_exact_live_health_receipt(tmp_path):
    import threading
    import pytest
    from site_agent.application.bootstrap import BootstrapError

    tenant_id = "demo"
    release_id = "rel-20261006123456-aabbccdd"
    source_sha = "a" * 40
    releases = tmp_path / "releases"
    receipt_path = releases / "runs" / tenant_id / release_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt = {
        "tenant": tenant_id,
        "releaseId": release_id,
        "sourceSha": source_sha,
        "status": "running",
        "stage": "verify-connection",
        "approvalId": None,
        "initialSchemaHead": "c" * 64,
        "uploadedVersion": "version-demo",
        "deployment": {"versions": [{"version_id": "version-demo", "percentage": 100}]},
        "payloadAdmin": "0.10.1",
        "payloadCore": "0.5.1",
        "contentContract": "helloada-content-v3",
        "schemaRevision": 5,
        "schemaIdentity": "b" * 64,
        "migrationHead": "c" * 64,
        "websitePresent": False,
    }
    receipt["health"] = {
        "ok": True,
        "tenant": tenant_id,
        "releaseSha": source_sha,
        **{key: receipt[key] for key in (
            "payloadAdmin", "payloadCore", "contentContract", "schemaRevision",
            "schemaIdentity", "migrationHead",
        )},
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"deployment_pipeline": {"release_root": str(releases)}}
    service._lock = threading.RLock()
    service._read_state = lambda _tenant: {
        "tenant_id": tenant_id,
        "step": "deploying_shell",
        "release": {"tenant_id": tenant_id, "release_id": release_id, "source_sha": source_sha},
    }
    activated = []
    service._mount_runtime = lambda selected_tenant, state, **kwargs: activated.append((selected_tenant, state, kwargs))

    result = service.activate_runtime_after_health(
        tenant_id, release_id=release_id, source_sha=source_sha,
    )
    assert result == {
        "tenant_id": tenant_id,
        "release_id": release_id,
        "source_sha": source_sha,
        "runtime_active": True,
    }
    assert len(activated) == 1

    receipt["stage"] = "verify-deployment"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(BootstrapError, match="verified Worker boundary"):
        service.activate_runtime_after_health(
            tenant_id, release_id=release_id, source_sha=source_sha,
        )

    receipt["stage"] = "verify-connection"
    receipt["health"]["schemaIdentity"] = "d" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(BootstrapError, match="health does not match"):
        service.activate_runtime_after_health(
            tenant_id, release_id=release_id, source_sha=source_sha,
        )
    assert len(activated) == 1


def test_read_only_runtime_activation_requires_verified_current_worker_proof(tmp_path):
    import pytest
    from site_agent.application.bootstrap import BootstrapError

    service, tenant, release, source_sha, _version, receipt_path, _activated, _config = _adoption_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update(status="failed", stage="verify-deployment")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    mounted = []
    service._mount_runtime = lambda selected_tenant, state, **_kwargs: mounted.append((selected_tenant, state))

    result = service.activate_runtime_after_health(
        tenant, release_id=release, source_sha=source_sha,
        verification=receipt["currentVerification"],
    )
    assert result["runtime_active"] is True
    assert mounted == [(tenant, {"tenant_id": tenant})]

    invalid = {**receipt["currentVerification"], "activeScriptEtag": "f" * 64}
    with pytest.raises(BootstrapError, match="verified Worker boundary"):
        service.activate_runtime_after_health(
            tenant, release_id=release, source_sha=source_sha, verification=invalid,
        )
    assert len(mounted) == 1


def test_regular_release_activation_syncs_contract_without_bootstrap_state(tmp_path):
    import threading

    tenant_id = "oceanicvibes"
    release_id = "rel-20261007123456-aabbccdd"
    source_sha = "a" * 40
    releases = tmp_path / "releases"
    receipt = {
        "tenant": tenant_id,
        "releaseId": release_id,
        "sourceSha": source_sha,
        "status": "running",
        "stage": "verify-connection",
        "approvalId": None,
        "uploadedVersion": "version-current",
        "deployment": {"versions": [{"version_id": "version-current", "percentage": 100}]},
        "payloadAdmin": "0.10.1",
        "payloadCore": "0.5.2",
        "contentContract": "helloada-content-v3",
        "schemaRevision": 5,
        "schemaIdentity": "b" * 64,
        "migrationHead": "c" * 64,
        "websitePresent": True,
    }
    receipt["health"] = {
        "ok": True,
        "tenant": tenant_id,
        "releaseSha": source_sha,
        "payloadAdmin": receipt["payloadAdmin"],
        "payloadCore": receipt["payloadCore"],
        "contentContract": receipt["contentContract"],
        "schemaRevision": receipt["schemaRevision"],
        "schemaIdentity": receipt["schemaIdentity"],
        "migrationHead": receipt["migrationHead"],
    }
    path = releases / "runs" / tenant_id / release_id / "receipt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"deployment_pipeline": {"release_root": str(releases)}}
    service._lock = threading.RLock()

    class Registration:
        def is_registered(self, selected_tenant):
            return selected_tenant == tenant_id

    service.registration = Registration()
    activated = []
    service._mount_runtime = lambda selected_tenant, state, **kwargs: activated.append(
        (selected_tenant, state, kwargs)
    )

    result = service.activate_runtime_after_health(
        tenant_id, release_id=release_id, source_sha=source_sha,
    )

    assert result["runtime_active"] is True
    assert activated == [(
        tenant_id,
        {"tenant_id": tenant_id},
        {
            "runtime_identity": {
                "adminVersion": "0.10.1",
                "contract": "helloada-content-v3",
                "coreVersion": "0.5.2",
                "schemaRevision": 5,
                "schemaIdentity": "b" * 64,
                "migrationHead": "c" * 64,
            },
            "website_present": True,
        },
    )]


def test_control_plane_activates_pending_tenant_only_with_authenticated_health_handoff(tmp_path):
    tenant_id = "demo"
    release_id = "rel-20261006123456-aabbccdd"
    source_sha = "a" * 40
    config, _unused, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    registration = TenantRegistrationService(config, env, registry=registry)
    service = WebsiteBootstrapService(config, env, registration=registration, registry=registry)
    releases = tmp_path / "releases"
    service.config["deployment_pipeline"] = {"release_root": str(releases)}
    registration.register(tenant_id, display_name="Demo")
    state = {
        "tenant_id": tenant_id,
        "status": "awaiting_release",
        "step": "deploying_shell",
        "release": {"tenant_id": tenant_id, "release_id": release_id, "source_sha": source_sha},
        "steps": {},
    }
    service._state_path(tenant_id).write_text(json.dumps(state), encoding="utf-8")
    receipt = {
        "tenant": tenant_id,
        "releaseId": release_id,
        "sourceSha": source_sha,
        "status": "running",
        "stage": "verify-connection",
        "approvalId": None,
        "initialSchemaHead": "c" * 64,
        "uploadedVersion": "version-demo",
        "deployment": {"versions": [{"version_id": "version-demo", "percentage": 100}]},
        "payloadAdmin": "0.10.1",
        "payloadCore": "0.5.1",
        "contentContract": "helloada-content-v3",
        "schemaRevision": 5,
        "schemaIdentity": "b" * 64,
        "migrationHead": "c" * 64,
        "websitePresent": False,
    }
    receipt["health"] = {
        "ok": True,
        "tenant": tenant_id,
        "releaseSha": source_sha,
        **{key: receipt[key] for key in (
            "payloadAdmin", "payloadCore", "contentContract", "schemaRevision",
            "schemaIdentity", "migrationHead",
        )},
    }
    receipt_path = releases / "runs" / tenant_id / release_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    activated = []
    service._mount_runtime = lambda selected_tenant, selected_state, **kwargs: activated.append(selected_tenant)
    app = create_workspace_api_app(
        registry,
        control_token="control",
        registration=registration,
        bootstrap=service,
    )
    try:
        with TestClient(app) as client:
            path = f"/v1/control-plane/websites/{tenant_id}/activate-runtime"
            body = {"release_id": release_id, "source_sha": source_sha}
            assert client.post(path, json=body).status_code == 401
            response = client.post(
                path,
                headers={"Authorization": "Bearer control"},
                json=body,
            )
            assert response.status_code == 200
            assert response.json()["runtime_active"] is True
            assert response.json()["release_id"] == release_id
            assert activated == [tenant_id]

            receipt.update(status="failed", stage="verify-deployment")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            proof = {
                "releaseId": release_id,
                "sourceSha": source_sha,
                "uploadedVersion": "version-demo",
                "workerVersion": "version-demo",
                "deploymentId": "deployment-demo",
                "trafficPercentage": 100,
                "uploadedScriptEtag": "d" * 64,
                "activeScriptEtag": "d" * 64,
                "uploadedBindingIdentity": "e" * 64,
                "activeBindingIdentity": "e" * 64,
                "mode": "exact",
                "verifiedAt": "2026-10-08T18:00:00Z",
            }
            proof_response = client.post(
                path,
                headers={"Authorization": "Bearer control"},
                json={**body, "verification": proof},
            )
            assert proof_response.status_code == 200
            assert proof_response.json()["runtime_active"] is True
            assert activated == [tenant_id, tenant_id]

            malformed = client.post(
                path,
                headers={"Authorization": "Bearer control"},
                json={**body, "verification": []},
            )
            assert malformed.status_code == 400
    finally:
        service.close()
        registry.close()


def test_bootstrap_worker_names_fit_the_workers_dev_preview_limit():
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {"resource_prefix": "helloada"}}
    tenant_id = "northstar-coffee-e2e-validation-8fbf2e6fea671768"

    first = service._names(tenant_id)
    second = service._names("northstar-coffee-e2e-validation-54bf2e6fea671768")

    assert len(first["worker"]) == 54
    assert first["worker"] == service._names(tenant_id)["worker"]
    assert first["worker"] != second["worker"]
    assert first["repo"] == f"helloada-{tenant_id}"


def test_bootstrap_resource_names_remain_bounded_for_maximum_tenant_ids():
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {"resource_prefix": "helloada"}}
    tenant_id = "northstar-coffee-e2e-validation-" + "a" * 31

    assert len(tenant_id) == 63
    names = service._names(tenant_id)

    assert len(names["worker"]) <= 54
    assert len(names["repo"]) <= 63
    assert len(names["d1"]) <= 63
    assert len(names["r2"]) <= 63
    assert len(names["email_r2"]) <= 63
    assert len(names["mailflare_inbound"]) <= 63
    assert len(names["mailflare_outbound"]) <= 63
    assert len(names["mailflare_agent"]) <= 63


def test_bootstrap_short_resource_names_keep_the_existing_stable_identity():
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {"resource_prefix": "helloada"}}

    names = service._names("oceanicvibes")

    assert names == {
        "worker": "helloada-oceanicvibes",
        "repo": "helloada-oceanicvibes",
        "d1": "helloada-oceanicvibes",
        "r2": "helloada-oceanicvibes-media",
        "email_r2": "helloada-oceanicvibes-email",
        "mailflare_d1": "helloada-oceanicvibes-mail",
        "mailflare_r2": "helloada-oceanicvibes-mail-files",
        "mailflare_inbound": "helloada-oceanicvibes-mail-inbound",
        "mailflare_outbound": "helloada-oceanicvibes-mail-outbound",
        "mailflare_agent": "helloada-oceanicvibes-mail-agent",
    }


def test_bootstrap_configures_generic_seo_provisioning_for_new_sites(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("instance_name: demo\nsite: {}\n", encoding="utf-8")
    site_dir = tmp_path / "site"
    from site_agent.site_scaffold import initialize_managed_site

    initialize_managed_site(site_dir)
    (site_dir / ".gitignore").unlink()

    class Registry:
        def reload_tenant(self, *args, **kwargs):
            return None

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {"resource_prefix": "helloada"}}
    service.env = {"HELLOADA_HANDOFF_PUBLIC_KEY": _TEST_HANDOFF_PUBLIC_KEY}
    service.registry = Registry()
    service._worker_url = lambda worker_name: (
        f"https://{worker_name}.weareheadless.workers.dev"
    )

    service._configure_source(
        "demo",
        "Demo",
        config_path,
        {"full_name": "weareheadless/helloada-demo", "site_dir": str(site_dir)},
        {
            "d1": {
                "name": "helloada-demo",
                "database_id": "56d3f277-fbaf-43d4-91e5-b3a195653a05",
            },
            "mailflare_d1": {
                "name": "helloada-demo-mail",
                "database_id": "66d3f277-fbaf-43d4-91e5-b3a195653a05",
            },
            "private_email_r2": {"bucket": "helloada-demo-email"},
            "mailflare_r2": {"bucket": "helloada-demo-mail-files"},
            "queues": {
                "messages": {"name": "helloada-demo-messages"},
                "dead_letter": {"name": "helloada-demo-messages-dlq"},
            },
            "mailflare_queues": {
                "inbound": {"name": "helloada-demo-mail-inbound"},
                "outbound": {"name": "helloada-demo-mail-outbound"},
                "agent": {"name": "helloada-demo-mail-agent"},
            },
        },
    )

    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["site"]["repository"] == "weareheadless/helloada-demo"
    template_manifest = json.loads((site_dir / "template-manifest.json").read_text(encoding="utf-8"))
    assert config["site"]["public_url"] == "https://helloada-demo.weareheadless.workers.dev/"
    assert config["ga"]["enabled"] is True
    assert config["ga"]["source"] == "crawlseo"
    assert config["seo"]["enabled"] is True
    assert config["seo"]["provisioning"]["auto"] is True
    assert config["seo"]["site_url"] == "https://helloada-demo.weareheadless.workers.dev/"
    assert config["seo"]["gsc_property"] == "https://helloada-demo.weareheadless.workers.dev/"
    assert config["site"]["payload"]["contract"]["adminVersion"] == template_manifest["payloadAdmin"]
    assert config["site"]["payload"]["contract"]["contract"] == template_manifest["contentContract"]
    assert config["site"]["payload"]["contract"]["schemaIdentity"] == template_manifest["schemaIdentity"]
    assert config["site"]["payload"]["contract"]["migrationHead"] == template_manifest["migrationHead"]
    assert config["site"]["payload"]["contract"]["locales"] == ["en"]
    assert (site_dir / ".gitignore").read_bytes() == (
        Path(__file__).resolve().parents[1]
        / "src/site_agent/templates/next-payload/.gitignore"
    ).read_bytes()
    wrangler = json.loads((site_dir / "wrangler.jsonc").read_text(encoding="utf-8"))
    assert wrangler["vars"]["HELLOADA_TEMPLATE_SCHEMA"] == str(template_manifest["templateSchema"])
    assert wrangler["vars"]["HELLOADA_PAYLOAD_SCHEMA_REVISION"] == str(template_manifest["schemaRevision"])
    assert wrangler["vars"]["HELLOADA_SCHEMA_IDENTITY"] == template_manifest["schemaIdentity"]
    assert wrangler["vars"]["HELLOADA_PAYLOAD_MIGRATION_HEAD"] == template_manifest["migrationHead"]
    from site_agent.application.release_queue import customer_release_identity

    tenant, _identity = customer_release_identity(config)
    assert tenant == "demo"


def test_bootstrap_release_accepts_the_canonical_owner_repository_identity(tmp_path, monkeypatch):
    import yaml

    from site_agent.application import bootstrap as bootstrap_module

    site_dir = tmp_path / "site"
    site_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "instance_name": "demo",
            "site": {"repository": "weareheadless/helloada-demo"},
        }),
        encoding="utf-8",
    )
    release_root = tmp_path / "releases"
    release_root.mkdir()
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"deployment_pipeline": {"release_root": str(release_root)}}
    service.env = {}

    git_calls = []
    status_output = " M wrangler.jsonc\n?? .gitignore"

    def fake_git(_site_dir, *args):
        git_calls.append(args)
        return {
            ("remote", "get-url", "origin"): "git@github.com:weareheadless/helloada-demo.git",
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): status_output,
            ("diff", "--cached", "--name-only"): ".gitignore\nwrangler.jsonc",
            ("rev-parse", "HEAD"): "a" * 40,
        }.get(args, "")

    captured = {}

    def fake_request_release(config, _env, source_sha, *, initialize_schema=False, release_id=None):
        captured["repository"] = config["site"]["repository"]
        captured["source_sha"] = source_sha
        captured["initialize_schema"] = initialize_schema
        captured["release_id"] = release_id
        return {"release_id": "bootstrap-demo", "source_sha": source_sha}

    monkeypatch.setattr(service, "_git", fake_git)
    monkeypatch.setattr(bootstrap_module, "request_release", fake_request_release)

    result = service._queue_release(
        "demo",
        config_path,
        {
            "site_dir": str(site_dir),
            "worker_name": "helloada-demo",
            "worker_url": "https://helloada-demo.weareheadless.workers.dev",
        },
        release_id="rel-20261006000000-1234abcd",
    )

    assert captured == {
        "repository": "weareheadless/helloada-demo",
        "source_sha": "a" * 40,
        "initialize_schema": True,
        "release_id": "rel-20261006000000-1234abcd",
    }
    assert result["tenant_id"] == "demo"
    assert result["release_id"] == "bootstrap-demo"
    assert git_calls[2:] == [
        ("status", "--porcelain"),
        ("add", "--", ".gitignore", "wrangler.jsonc"),
        ("diff", "--cached", "--name-only"),
        ("commit", "-qm", "Configure canonical Payload Worker files"),
        ("push", "origin", "main"),
        ("rev-parse", "HEAD"),
    ]

    from site_agent.application.bootstrap import BootstrapError
    import pytest

    status_output = "?? src/app/page.tsx"
    with pytest.raises(BootstrapError, match="outside canonical Worker files"):
        service._queue_release(
            "demo",
            config_path,
            {
                "site_dir": str(site_dir),
                "worker_name": "helloada-demo",
                "worker_url": "https://helloada-demo.weareheadless.workers.dev",
            },
        )


def test_git_status_preserves_porcelain_columns(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from site_agent.application import bootstrap as bootstrap_module

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {}
    service.env = {}
    monkeypatch.setattr(service, "_git_env", lambda: {})
    monkeypatch.setattr(
        bootstrap_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=" M wrangler.jsonc\n",
            stderr="",
        ),
    )

    assert service._git(tmp_path, "status", "--porcelain") == " M wrangler.jsonc"


def test_bootstrap_retry_reconciles_a_completed_source_configuration_step(tmp_path):
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.root = tmp_path
    state = {
        "tenant_id": "demo",
        "steps": {
            "creating_worker": {
                "status": "done",
                "receipt": {"schemaIdentity": "old-template"},
            },
        },
        "resource_receipts": {},
    }

    result = service._run_step(
        state,
        "creating_worker",
        lambda: {"schemaIdentity": "current-template"},
        refresh_completed=True,
    )

    assert result == {"schemaIdentity": "current-template"}
    assert state["steps"]["creating_worker"]["receipt"] == result
    persisted = json.loads((tmp_path / "demo" / "bootstrap.json").read_text(encoding="utf-8"))
    assert persisted["steps"]["creating_worker"]["receipt"] == result


def test_bootstrap_retry_queues_again_only_after_the_previous_release_failed(tmp_path):
    from site_agent.application.bootstrap import BootstrapError
    import pytest

    release_root = tmp_path / "releases"
    receipt_path = release_root / "runs" / "demo" / "bootstrap-demo" / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps({
            "tenant": "demo",
            "releaseId": "bootstrap-demo",
            "sourceSha": "a" * 40,
            "approvalId": None,
            "status": "failed",
        }),
        encoding="utf-8",
    )
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"deployment_pipeline": {"release_root": str(release_root)}}
    state = {
        "tenant_id": "demo",
        "release": {"tenant_id": "demo", "release_id": "bootstrap-demo", "source_sha": "a" * 40},
        "steps": {
            "queueing_shell_release": {
                "status": "done",
                "receipt": {"tenant_id": "demo", "release_id": "bootstrap-demo", "source_sha": "a" * 40},
            },
        },
        "resource_receipts": {"queueing_shell_release": {"release_id": "bootstrap-demo"}},
    }

    assert service._prepare_failed_release_retry(state) is True
    assert re.fullmatch(r"rel-\d{14}-[0-9a-f]{8}", state["release_retry_id"])
    assert "queueing_shell_release" not in state["steps"]
    assert "queueing_shell_release" not in state["resource_receipts"]
    assert "release" not in state

    receipt_path.write_text(
        json.dumps({
            "tenant": "demo",
            "releaseId": "bootstrap-demo",
            "sourceSha": "a" * 40,
            "approvalId": None,
            "status": "running",
        }),
        encoding="utf-8",
    )
    state["release"] = {"tenant_id": "demo", "release_id": "bootstrap-demo", "source_sha": "a" * 40}
    state["steps"]["queueing_shell_release"] = {
        "status": "done",
        "receipt": {"tenant_id": "demo", "release_id": "bootstrap-demo", "source_sha": "a" * 40},
    }
    assert service._prepare_failed_release_retry(state) is False
    assert state["release"]["release_id"] == "bootstrap-demo"

    state["release"]["source_sha"] = "b" * 40
    with pytest.raises(BootstrapError, match="does not match its recorded step"):
        service._prepare_failed_release_retry(state)


def test_bootstrap_verified_failed_retry_persists_and_requests_a_fresh_release_id(tmp_path, monkeypatch):
    import threading

    release_root = tmp_path / "releases"
    receipt_path = release_root / "runs" / "demo" / "bootstrap-demo" / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({
        "tenant": "demo",
        "releaseId": "bootstrap-demo",
        "sourceSha": "a" * 40,
        "approvalId": None,
        "status": "failed",
    }), encoding="utf-8")
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"deployment_pipeline": {"release_root": str(release_root)}}
    service._lock = threading.RLock()
    service._futures = {"demo": object()}
    state = {
        "tenant_id": "demo",
        "config_path": str(tmp_path / "config.yaml"),
        "release": {"tenant_id": "demo", "release_id": "bootstrap-demo", "source_sha": "a" * 40},
        "steps": {
            "queueing_shell_release": {
                "status": "done",
                "receipt": {"tenant_id": "demo", "release_id": "bootstrap-demo", "source_sha": "a" * 40},
            },
        },
        "resource_receipts": {},
    }
    monkeypatch.setattr(service, "_read_state", lambda _tenant_id: state)
    monkeypatch.setattr(service, "_write_state", lambda _state: None)
    monkeypatch.setattr(service, "_repository", lambda *_args: {"repository": "demo"})
    monkeypatch.setattr(service, "_data_resources", lambda *_args: {"resources": "ready"})
    monkeypatch.setattr(service, "_worker_resource", lambda *_args: {"worker_id": "worker-123"})
    monkeypatch.setattr(service, "_configure_source", lambda *_args: {"worker_name": "helloada-demo"})
    monkeypatch.setattr(service, "_refresh_release_state", lambda _state: None)
    queued = {}

    def queue_release(_tenant_id, _config_path, _worker, *, release_id=None):
        queued["release_id"] = release_id
        return {"release_id": release_id, "source_sha": "b" * 40}

    monkeypatch.setattr(service, "_queue_release", queue_release)

    service._run("demo", "Demo")

    assert queued["release_id"] is not None
    assert state["steps"]["creating_worker_identity"]["receipt"] == {"worker_id": "worker-123"}
    assert state["release"]["release_id"] == queued["release_id"]
    assert state["status"] == "awaiting_release"
    assert "release_retry_id" not in state


def test_bootstrap_refuses_to_guess_a_payload_contract(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    from site_agent.application.bootstrap import BootstrapError

    import pytest

    with pytest.raises(BootstrapError, match="canonical Payload capability contract"):
        service._load_payload_contract(site_dir)


def test_bootstrap_configures_one_explicit_tenant_ownership_marker(tmp_path):
    from site_agent.site_scaffold import initialize_managed_site

    site_dir = initialize_managed_site(tmp_path / "site")
    WebsiteBootstrapService._configure_template(site_dir, "demo", "Demo")
    marker = json.loads((site_dir / ".helloada-managed.json").read_text())
    manifest = json.loads((site_dir / "template-manifest.json").read_text())
    assert marker == {
        "tenantId": "demo",
        "templateSchema": manifest["templateSchema"],
        "payloadAdmin": manifest["payloadAdmin"],
        "payloadCore": manifest["payloadCore"],
        "contentContract": manifest["contentContract"],
        "schemaRevision": manifest["schemaRevision"],
        "schemaIdentity": manifest["schemaIdentity"],
        "migrationHead": manifest["migrationHead"],
    }
    assert 'tenantId: "demo"' in (site_dir / "src/helloada.config.ts").read_text()


def test_bootstrap_provisions_only_the_three_mailflare_queues(tmp_path):
    from site_agent.site_scaffold import initialize_managed_site

    site_dir = initialize_managed_site(tmp_path / "site")
    WebsiteBootstrapService._configure_template(site_dir, "demo", "Demo")
    template = json.loads((site_dir / "template-manifest.json").read_text())
    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {"resource_prefix": "helloada"}}
    names = service._names("demo")
    WebsiteBootstrapService._configure_wranger(
        site_dir, names, "https://helloada-demo.workers.dev", "https://site-agent.test",
        {
            "d1": {"database_id": "56d3f277-fbaf-43d4-91e5-b3a195653a05", "name": names["d1"]},
            "mailflare_d1": {"database_id": "66d3f277-fbaf-43d4-91e5-b3a195653a05", "name": names["mailflare_d1"]},
            "mailflare_r2": {"bucket": names["mailflare_r2"]},
            "private_email_r2": {"bucket": names["email_r2"]},
            "mailflare_queues": {
                "inbound": {"name": names["mailflare_inbound"]},
                "outbound": {"name": names["mailflare_outbound"]},
                "agent": {"name": names["mailflare_agent"]},
            },
        },
        "Demo", "demo", {
            "coreVersion": template["payloadCore"],
            "schemaRevision": template["schemaRevision"],
            "contract": template["contentContract"],
        },
        _TEST_HANDOFF_PUBLIC_KEY,
    )
    wrangler = json.loads((site_dir / "wrangler.jsonc").read_text())
    assert wrangler["d1_databases"][1]["migrations_dir"] == ".mailflare/migrations"
    assert [consumer["queue"] for consumer in wrangler["queues"]["consumers"]] == [
        names["mailflare_inbound"], names["mailflare_outbound"], names["mailflare_agent"],
    ]
    assert wrangler["durable_objects"]["bindings"] == [
        {"name": "MAILFLARE_REALTIME", "class_name": "RealtimeHub"},
    ]
    assert wrangler["d1_databases"][1]["migrations_dir"] == ".mailflare/migrations"
    assert wrangler["ai"] == {"binding": "MAILFLARE_AI"}
    assert wrangler["triggers"]["crons"] == ["*/5 * * * *", "0 2 * * *"]


def test_bootstrap_never_replaces_an_existing_site_directory(tmp_path):
    from site_agent.application.bootstrap import BootstrapError

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {}}
    service.env = {}
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    owner_file = site_dir / "owner-work.txt"
    owner_file.write_text("preserve this")

    import pytest

    with pytest.raises(BootstrapError, match="refusing to replace"):
        service._materialize_template(site_dir)
    assert owner_file.read_text() == "preserve this"
def test_host_bootstrap_retires_only_the_verified_legacy_tenant_scheduler(tmp_path):
    import runpy

    retire = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/retire-legacy-tenant-schedulers.py"))[
        "retire_legacy_tenant_schedulers"
    ]
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    unit_path = unit_dir / "site-agent@.service"
    unit_path.write_text("""[Unit]
Description=site-agent (%i)
After=network-online.target
Wants=network-online.target

[Service]
Environment=PYTHONUNBUFFERED=1
Type=simple
User=admin
WorkingDirectory=/SOCIAL/configs/%i
EnvironmentFile=/SOCIAL/configs/%i/.env
ExecStart=/SOCIAL/site-agent/.venv/bin/python -m site_agent run --config /SOCIAL/configs/%i/config.yaml
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
""", encoding="utf-8")

    class Systemctl:
        def __init__(self):
            self.active = {
                "site-agent@oceanicvibes.service": "active",
                "site-agent@atelier-harmonie.service": "inactive",
            }
            self.enabled = {
                "site-agent@oceanicvibes.service": "enabled",
                "site-agent@atelier-harmonie.service": "disabled",
            }
            self.mutations = []

        def __call__(self, command, *, capture=False):
            if command[1] == "list-units":
                return "\n".join(
                    f"{name} loaded {state} {'running' if state == 'active' else 'dead'} service"
                    for name, state in self.active.items()
                )
            if command[1] == "list-unit-files":
                assert command[2:] == ["--type=service", "--plain", "--no-legend"]
                rows = [f"{name} {state}" for name, state in self.enabled.items()]
                rows.append("ssh.service enabled")
                return "\n".join(rows)
            self.mutations.append(command[1:])
            if command[1] == "stop":
                self.active[command[2]] = "inactive"
            elif command[1] == "disable" and command[2] != "site-agent@.service":
                self.enabled[command[2]] = "disabled"
            return ""

    systemctl = Systemctl()
    receipt = retire(unit_dir, runner=systemctl)
    assert receipt == {
        "retired": True,
        "stoppedInstances": ["site-agent@oceanicvibes.service"],
    }
    assert not unit_path.exists()
    assert (unit_dir / "site-agent@.service.retired").is_file()
    assert ["stop", "site-agent@oceanicvibes.service"] in systemctl.mutations
    assert ["disable", "site-agent@oceanicvibes.service"] in systemctl.mutations
    mutation_count = len(systemctl.mutations)
    systemctl.active.clear()
    systemctl.enabled.clear()
    assert retire(unit_dir, runner=systemctl)["retired"] is True
    assert len(systemctl.mutations) == mutation_count


def test_host_bootstrap_fails_closed_on_an_unrecognized_tenant_unit(tmp_path):
    import runpy
    import pytest

    retire = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/retire-legacy-tenant-schedulers.py"))[
        "retire_legacy_tenant_schedulers"
    ]
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    unit_path = unit_dir / "site-agent@.service"
    unit_path.write_text("ExecStart=/usr/bin/python arbitrary-command\n", encoding="utf-8")

    class Systemctl:
        mutations = []

        def __call__(self, command, *, capture=False):
            if command[1] == "list-units":
                return "site-agent@oceanicvibes.service loaded active running service"
            if command[1] == "list-unit-files":
                return "site-agent@oceanicvibes.service enabled"
            self.mutations.append(command[1:])
            return ""

    systemctl = Systemctl()
    with pytest.raises(RuntimeError, match="unit"):
        retire(unit_dir, runner=systemctl)
    assert systemctl.mutations == []
    assert unit_path.exists()
