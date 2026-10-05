from __future__ import annotations

import json

from fastapi.testclient import TestClient

from site_agent.application.bootstrap import WebsiteBootstrapService
from site_agent.application.tenant_registration import TenantRegistrationService
from site_agent.application.workspace import TenantRegistry
from site_agent.config import load
from site_agent.hands.cloudflare_resources import CloudflareResourceProvisioner
from site_agent.hands.github_provisioning import GitHubRepositoryProvisioner
from site_agent.web.workspace import create_workspace_api_app


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


def test_bootstrap_configures_generic_seo_provisioning_for_new_sites(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("site: {}\n", encoding="utf-8")
    site_dir = tmp_path / "site"
    from site_agent.site_scaffold import initialize_managed_site

    initialize_managed_site(site_dir)

    class Registry:
        def reload_tenant(self, *args, **kwargs):
            return None

    service = WebsiteBootstrapService.__new__(WebsiteBootstrapService)
    service.config = {"bootstrap": {"resource_prefix": "helloada"}}
    service.env = {}
    service.registry = Registry()

    service._configure_source(
        "demo",
        "Demo",
        config_path,
        {"full_name": "weareheadless/helloada-demo", "site_dir": str(site_dir)},
        {"d1": {"name": "helloada-demo"}},
    )

    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    template_manifest = json.loads((site_dir / "template-manifest.json").read_text(encoding="utf-8"))
    assert config["site"]["public_url"] == "https://helloada-demo.workers.dev/"
    assert config["ga"]["enabled"] is True
    assert config["ga"]["source"] == "crawlseo"
    assert config["seo"]["enabled"] is True
    assert config["seo"]["provisioning"]["auto"] is True
    assert config["seo"]["site_url"] == "https://helloada-demo.workers.dev/"
    assert config["seo"]["gsc_property"] == "https://helloada-demo.workers.dev/"
    assert config["site"]["payload"]["contract"]["contract"] == "helloada-content-v2"
    assert config["site"]["payload"]["contract"]["schemaIdentity"] == template_manifest["schemaIdentity"]
    assert config["site"]["payload"]["contract"]["locales"] == ["en"]
    wrangler = json.loads((site_dir / "wrangler.jsonc").read_text(encoding="utf-8"))
    assert wrangler["vars"]["HELLOADA_TEMPLATE_SCHEMA"] == "4"
    assert wrangler["vars"]["HELLOADA_PAYLOAD_SCHEMA_REVISION"] == "2"
    assert wrangler["vars"]["HELLOADA_SCHEMA_IDENTITY"] == template_manifest["schemaIdentity"]
    assert wrangler["vars"]["HELLOADA_PAYLOAD_MIGRATION_HEAD"] == template_manifest["migrationHead"]


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
    assert marker == {
        "tenantId": "demo",
        "templateSchema": 4,
        "payloadAdmin": "0.8.10",
        "payloadCore": "0.2.0",
        "contentContract": "helloada-content-v2",
        "schemaRevision": 2,
        "schemaIdentity": json.loads((site_dir / "template-manifest.json").read_text())["schemaIdentity"],
        "migrationHead": json.loads((site_dir / "template-manifest.json").read_text())["migrationHead"],
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
