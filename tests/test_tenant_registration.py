from __future__ import annotations

from fastapi.testclient import TestClient

from site_agent.application.tenant_registration import (
    TenantRegistrationService,
    load_provisioned_tenants,
)
from site_agent.application.workspace import TenantRegistry
from site_agent.config import load
from site_agent.web.workspace import create_workspace_api_app


def _host(tmp_path):
    host_config = tmp_path / "host.yaml"
    host_config.write_text(
        f"instance_name: host\ndata_dir: {tmp_path / 'host-data'}\n",
        encoding="utf-8",
    )
    root_config = tmp_path / "config.yaml"
    root_config.write_text(
        "\n".join(
            [
                f"data_dir: {tmp_path / 'host-root'}",
                "workspace_api:",
                "  enabled: true",
                f"  provisioned_root: {tmp_path / 'websites'}",
                "  tenants:",
                "    host:",
                f"      config_path: {host_config}",
                "      api_token_env: HOST_TOKEN",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = {"HOST_TOKEN": "host-secret"}
    config, _ = load(root_config, env)
    return config, env


def test_registration_creates_an_isolated_idempotent_tenant(tmp_path):
    config, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    service = TenantRegistrationService(config, env, registry=registry)

    try:
        first = service.register("new-site", display_name="New Site")
        second = service.register("new-site", display_name="New Site")

        assert first["created"] is True
        assert second["created"] is False
        assert first["tenant_id"] == "new-site"
        assert first["api_token_env"] == "PROVISIONED_NEW_SITE_TOKEN"
        assert first["schema_version"] > 0
        assert (tmp_path / "websites" / "new-site" / "config.yaml").is_file()
        assert (tmp_path / "websites" / "new-site" / "tenant.env").is_file()
        site_root = tmp_path / "websites" / "new-site" / "site"
        assert (site_root / ".git").is_dir()
        assert registry.for_tenant_id("new-site") is not None
        tenant = registry.for_tenant_id("new-site")
        assert tenant.config["design_engine"]["intake_advisor"]["max_tokens"] == 4096
        assert tenant.config["design_engine"]["enabled"] is True
        assert tenant.config["builder"]["enabled"] is True
        assert tenant.config["site"]["clone_path"] == str(site_root)
        assert tenant.context["design_adapter"].__class__.__name__ == "NeutralScaffold"
        assert tenant.context["source_deployment"] is None
        assert tenant.context["source_editor"].adapter.__class__.__name__ == "NeutralScaffold"

        declared, extra_env = load_provisioned_tenants(config, env)
        assert declared["new-site"]["config_path"].endswith("new-site/config.yaml")
        assert extra_env[first["api_token_env"]]
    finally:
        registry.close()


def test_control_plane_registers_a_tenant_without_leaking_the_token(tmp_path):
    config, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    service = TenantRegistrationService(config, env, registry=registry)
    app = create_workspace_api_app(
        registry,
        control_token="control-secret",
        registration=service,
    )

    with TestClient(app) as client:
        assert client.post(
            "/v1/control-plane/websites/new-site/register",
            json={"display_name": "New Site"},
        ).status_code == 401

        response = client.post(
            "/v1/control-plane/websites/new-site/register",
            headers={"Authorization": "Bearer control-secret"},
            json={"display_name": "New Site"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == "new-site"
        assert "token" not in response.text.lower()

        recommendations = client.get(
            "/v1/control-plane/websites/new-site/design/recommendations",
            headers={"Authorization": "Bearer control-secret"},
        )
        assert recommendations.status_code == 200
        assert recommendations.json()["recommendations"] == []


def test_control_plane_can_start_with_no_declared_tenants(tmp_path):
    root_config = tmp_path / "config.yaml"
    root_config.write_text(
        "\n".join(
            [
                f"data_dir: {tmp_path / 'root'}",
                "workspace_api:",
                "  enabled: true",
                f"  provisioned_root: {tmp_path / 'websites'}",
                "  tenants: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env: dict[str, str] = {}
    config, _ = load(root_config, env)
    registry = TenantRegistry.from_config(config, env)
    app = create_workspace_api_app(
        registry,
        control_token="control-secret",
        registration=TenantRegistrationService(config, env, registry=registry),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/control-plane/websites/first-site/register",
            headers={"Authorization": "Bearer control-secret"},
            json={},
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "first-site"
