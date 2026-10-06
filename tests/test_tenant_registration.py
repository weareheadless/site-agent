from __future__ import annotations

import json

from fastapi.testclient import TestClient
import yaml

from site_agent.application.tenant_registration import (
    TenantRegistrationService,
    load_provisioned_tenants,
)
from site_agent.application.workspace import TenantRegistry
from site_agent.config import ConfigError, load
from site_agent.web.workspace import create_workspace_api_app


def _host(tmp_path):
    root_config = tmp_path / "config.yaml"
    root_config.write_text(
        "\n".join(
            [
                f"data_dir: {tmp_path / 'host-root'}",
                "workspace_api:",
                "  enabled: true",
                f"  provisioned_root: {tmp_path / 'websites'}",
                "  tenants: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = {"HOST_TOKEN": "host-secret"}
    config, _ = load(root_config, env)
    return config, env


def test_registration_creates_pending_identity_without_a_temporary_site(tmp_path):
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
        assert not site_root.exists()
        assert registry.for_tenant_id("new-site") is None
        index = (tmp_path / "websites" / "tenants.json").read_text(encoding="utf-8")
        assert '"bootstrap_state": "pending"' in index

        declared, extra_env = load_provisioned_tenants(config, env)
        assert "new-site" not in declared
        assert first["api_token_env"] not in extra_env

        retry_registry = TenantRegistry.from_config(config, env)
        retry_service = TenantRegistrationService(config, env, registry=retry_registry)
        retried = retry_service.register("new-site", display_name="New Site")
        assert retried["created"] is False
        assert retried["api_token_env"] == first["api_token_env"]
        assert (tmp_path / "websites" / "new-site" / "site").exists() is False
        retry_registry.close()
    finally:
        registry.close()


def test_host_configuration_cannot_declare_a_second_tenant_registry(tmp_path):
    config, env = _host(tmp_path)
    config["workspace_api"]["tenants"] = {"unregistered": {"config_path": "/tmp/site.yaml"}}

    try:
        TenantRegistry.from_config(config, env)
    except ConfigError as error:
        assert "canonical tenant registry" in str(error)
    else:
        raise AssertionError("host-declared tenants must not bypass the canonical registry")


def test_shared_build_toolchain_is_inherited_by_new_site_tenants(tmp_path):
    config, env = _host(tmp_path)
    config["source_deployment"] = {
        "node_path": "/opt/helloada/node/bin",
        "node_version": "22.14.0",
        "npm_command": "/opt/helloada/npm/bin/npm",
        "npm_version": "11.13.0",
    }
    registry = TenantRegistry.from_config(config, env)
    service = TenantRegistrationService(config, env, registry=registry)
    try:
        service.register("new-site", display_name="New Site")
        assert registry.for_tenant_id("new-site") is None
        assert not (tmp_path / "websites" / "new-site" / "site").exists()
    finally:
        registry.close()


def test_only_a_configured_payload_runtime_becomes_restart_loadable(tmp_path):
    config, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    service = TenantRegistrationService(config, env, registry=registry)
    try:
        service.register("new-site", display_name="New Site")
        tenant_path = tmp_path / "websites" / "new-site" / "config.yaml"
        tenant_config = yaml.safe_load(tenant_path.read_text(encoding="utf-8"))
        tenant_config["site"]["payload"]["enabled"] = True
        TenantRegistrationService._replace_config(tenant_path, tenant_config)

        service.mark_runtime_configured("new-site")

        declared, extra_env = load_provisioned_tenants(config, env)
        assert declared["new-site"]["config_path"] == str(tenant_path)
        assert extra_env["PROVISIONED_NEW_SITE_TOKEN"]
        index = json.loads((tmp_path / "websites" / "tenants.json").read_text(encoding="utf-8"))
        assert index["new-site"]["bootstrap_state"] == "ready"
        assert registry.for_tenant_id("new-site") is None
    finally:
        registry.close()


def test_registration_fails_closed_on_a_corrupt_registry(tmp_path):
    config, env = _host(tmp_path)
    registry = TenantRegistry.from_config(config, env)
    service = TenantRegistrationService(config, env, registry=registry)
    try:
        service.register("first-site", display_name="First Site")
        index_path = tmp_path / "websites" / "tenants.json"
        index_path.write_text("not-json", encoding="utf-8")

        try:
            service.register("second-site", display_name="Second Site")
        except ValueError as error:
            assert "registry is unreadable" in str(error)
        else:
            raise AssertionError("a corrupt registry must not be overwritten")
        assert index_path.read_text(encoding="utf-8") == "not-json"
        assert not (tmp_path / "websites" / "second-site").exists()
    finally:
        registry.close()


def test_startup_fails_closed_on_an_invalid_registry_path(tmp_path):
    config, env = _host(tmp_path)
    root = tmp_path / "websites"
    root.mkdir()
    (root / "tenants.json").write_text(json.dumps({
        "broken-site": {
            "config_path": str(tmp_path / "outside" / "config.yaml"),
            "api_token_env": "PROVISIONED_BROKEN_SITE_TOKEN",
            "bootstrap_state": "pending",
        },
    }), encoding="utf-8")

    try:
        load_provisioned_tenants(config, env)
    except ValueError as error:
        assert "registration paths are invalid" in str(error)
    else:
        raise AssertionError("invalid tenant paths must stop startup rather than disappear")


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
        assert client.get("/healthz").json() == {"ok": True}
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
        assert recommendations.status_code == 404


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
