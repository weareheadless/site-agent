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
        },
    )

    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["site"]["repository"] == "weareheadless/helloada-demo"
    template_manifest = json.loads((site_dir / "template-manifest.json").read_text(encoding="utf-8"))
    assert config["site"]["public_url"] == "https://helloada-demo.workers.dev/"
    assert config["ga"]["enabled"] is True
    assert config["ga"]["source"] == "crawlseo"
    assert config["seo"]["enabled"] is True
    assert config["seo"]["provisioning"]["auto"] is True
    assert config["seo"]["site_url"] == "https://helloada-demo.workers.dev/"
    assert config["seo"]["gsc_property"] == "https://helloada-demo.workers.dev/"
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
            "worker_url": "https://helloada-demo.workers.dev",
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
                "worker_url": "https://helloada-demo.workers.dev",
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
