import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from site_agent.application.crawlseo_cutover import (
    CrawlSEOConfigurationCutoverError,
    apply_connector_configuration,
    build_connector_configuration,
)
from site_agent.application.seo_bootstrap import load_tenant_environment
from site_agent.application.tenant_registration import TenantRegistrationError, TenantRegistrationService
from site_agent.hands.crawlseo_connector_credentials import (
    CONNECTOR_TOKEN_ENV,
    CrawlSEOConnectorCredentialError,
    install_connector_credential,
    load_connector_environment,
)
from site_agent.core.memory import Memory


TOKEN = "cseo_12345678901234567890"
SNAPSHOT = "sha256:" + "a" * 64
CAPABILITIES = {
    "schemaVersion": "1.0",
    "siteId": "site-1",
    "projectId": "project-1",
    "binding": {
        "siteId": "site-1",
        "status": "active",
        "executor": "helloada",
        "generation": 4,
        "executionSupported": True,
    },
}


def _config(tmp_path, *, connector_url=""):
    return {
        "instance_name": "tenant-a",
        "data_dir": str(tmp_path / "tenant-a" / "data"),
        "providers": {
            "crawlseo": {
                "enabled": True,
                "url": "https://crawlseo.example/mcp",
                "token_env": "CRAWLSEO_SERVICE_TOKEN",
                "research_authority": "local",
                **({"connector_url": connector_url, "connector_token_env": CONNECTOR_TOKEN_ENV} if connector_url else {}),
            }
        },
    }


def _tenant(tmp_path, *, authority="local"):
    config = _config(tmp_path)
    config["providers"]["crawlseo"]["research_authority"] = authority
    directory = tmp_path / "tenant-a"
    directory.mkdir(parents=True)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    memory = Memory(directory / "memory.db")
    tenant = SimpleNamespace(
        tenant_id="tenant-a", config_path=str(path), config=config, memory=memory,
        api_token="host-token", api_token_env="HOST_TOKEN", context={},
    )
    return tenant


def _plan():
    return {
        "tenant": "tenant-a",
        "snapshotHash": SNAPSHOT,
        "siteId": "site-1",
        "crawlseo": {"projectId": "project-1", "bindingSiteIdentityVerified": True, "binding": dict(CAPABILITIES["binding"])},
    }


def _body(tenant, *, mode="plan", request_id="cutover-req-0001", url="https://crawlseo.example/api/connector/v1"):
    raw = Path(tenant.config_path).read_bytes()
    return {
        "mode": mode,
        "expectedSnapshotHash": SNAPSHOT,
        "expectedConfigHash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "operatorRequestId": request_id,
        "connectorUrl": url,
        "connectorTokenEnv": CONNECTOR_TOKEN_ENV,
        "reason": "Prepare verified read-only connector configuration",
    }


def _client_factory(_config, _env):
    return SimpleNamespace(
        start=lambda: None,
        close=lambda: None,
        connector_capabilities=lambda **_kwargs: CAPABILITIES,
    )


def _install(tenant, token=TOKEN):
    install_connector_credential(tenant.config, CONNECTOR_TOKEN_ENV, token)


def test_managed_connector_loader_is_strict_and_separate_from_legacy_mcp(tmp_path):
    config = _config(tmp_path)
    path = tmp_path / "tenant-a" / "crawlseo-connector.env"
    path.parent.mkdir(parents=True)
    path.write_text(f"{CONNECTOR_TOKEN_ENV}={TOKEN}\n", encoding="utf-8")
    path.chmod(0o600)
    assert load_connector_environment(config) == {CONNECTOR_TOKEN_ENV: TOKEN}
    assert load_tenant_environment(config, {"CRAWLSEO_SERVICE_TOKEN": "mcp-secret"}) == {
        "CRAWLSEO_SERVICE_TOKEN": "mcp-secret", CONNECTOR_TOKEN_ENV: TOKEN,
    }
    path.write_text("UNKNOWN_TOKEN=secret\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(CrawlSEOConnectorCredentialError, match="unknown key"):
        load_connector_environment(config)
    path.write_text(f"{CONNECTOR_TOKEN_ENV}={TOKEN}\n", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(CrawlSEOConnectorCredentialError, match="0600"):
        load_connector_environment(config)


def test_configured_connector_requires_existing_managed_credential(tmp_path):
    config = _config(tmp_path, connector_url="https://crawlseo.example/api/connector/v1")
    with pytest.raises(CrawlSEOConnectorCredentialError, match="missing"):
        load_connector_environment(config)


def test_credential_installer_conflict_requires_file_hash_cas(tmp_path):
    config = _config(tmp_path)
    first = install_connector_credential(config, CONNECTOR_TOKEN_ENV, TOKEN)
    assert first["installed"] is True
    with pytest.raises(CrawlSEOConnectorCredentialError, match="different"):
        install_connector_credential(config, CONNECTOR_TOKEN_ENV, "cseo_abcdefghijklmnopqrstuv")
    second_token = "cseo_abcdefghijklmnopqrstuv"
    replaced = install_connector_credential(
        config, CONNECTOR_TOKEN_ENV, second_token, expected_file_sha256=first["fileSha256"],
    )
    assert replaced["installed"] is True
    assert load_connector_environment(config)[CONNECTOR_TOKEN_ENV] == second_token


def test_preview_preserves_mcp_and_authority_and_rejects_other_origin(tmp_path):
    tenant = _tenant(tmp_path, authority="crawlseo")
    tenant.config["providers"]["crawlseo"]["connector_url"] = "https://crawlseo.example/api/connector/v1"
    tenant.config["providers"]["crawlseo"]["connector_token_env"] = CONNECTOR_TOKEN_ENV
    Path(tenant.config_path).write_text(yaml.safe_dump(tenant.config, sort_keys=False), encoding="utf-8")
    _install(tenant)
    result = build_connector_configuration(
        tenant, _plan(), _body(tenant), {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=_client_factory,
    )
    assert result["valid"] is True
    assert result["authorityChanged"] is False
    assert result["paidOperationsAllowed"] is False
    proposed = yaml.safe_load(Path(tenant.config_path).read_text())
    assert proposed["providers"]["crawlseo"]["url"] == "https://crawlseo.example/mcp"
    assert proposed["providers"]["crawlseo"]["token_env"] == "CRAWLSEO_SERVICE_TOKEN"
    assert proposed["providers"]["crawlseo"]["research_authority"] == "crawlseo"
    body = _body(tenant, url="https://evil.example/api/connector/v1")
    with pytest.raises(CrawlSEOConfigurationCutoverError, match="origin"):
        build_connector_configuration(tenant, _plan(), body, {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=_client_factory)


def test_distinct_mcp_and_connector_mounts_and_plan_without_remote_binding(tmp_path):
    tenant = _tenant(tmp_path)
    tenant.config["providers"]["crawlseo"]["url"] = "https://crawlseo.example/mcp"
    Path(tenant.config_path).write_text(yaml.safe_dump(tenant.config, sort_keys=False), encoding="utf-8")
    _install(tenant)
    plan = {"tenant": "tenant-a", "snapshotHash": SNAPSHOT, "siteId": "site-1", "projectId": "project-1"}
    result = build_connector_configuration(
        tenant, plan, _body(tenant, url="https://crawlseo.example/crawlseo/api/connector/v1"),
        {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=_client_factory,
    )
    assert result["valid"] is True


def test_capabilities_project_id_is_authoritative_without_nested_site_id(tmp_path):
    tenant = _tenant(tmp_path)
    _install(tenant)
    capabilities = {"schemaVersion": "1.0", "siteId": "site-1", "projectId": "project-1",
                    "binding": {"status": "active", "executor": "helloada", "generation": 4,
                                "executionSupported": True}}
    client_factory = lambda _config, _env: SimpleNamespace(
        connector_capabilities=lambda **_kwargs: capabilities,
        start=lambda: pytest.fail("capability probe started the legacy MCP client"),
    )
    result = build_connector_configuration(
        tenant, {"tenant": "tenant-a", "snapshotHash": SNAPSHOT, "siteId": "site-1", "projectId": "project-1"}, _body(tenant), {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"},
        client_factory=client_factory,
    )
    assert result["binding"]["siteId"] == "site-1"
    wrong_project_factory = lambda _config, _env: SimpleNamespace(
        connector_capabilities=lambda **_kwargs: {"schemaVersion": "1.0", "projectId": "other-site"},
    )
    with pytest.raises(CrawlSEOConfigurationCutoverError, match="expected active site binding"):
        build_connector_configuration(
            tenant, _plan(), _body(tenant), {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"},
            client_factory=wrong_project_factory,
        )


@pytest.mark.parametrize("url", [
    "http://crawlseo.example/api/connector/v1",
    "https://user:pass@crawlseo.example/api/connector/v1",
    "https://crawlseo.example/api/connector/v1?token=x",
])
def test_malformed_connector_endpoint_is_rejected(tmp_path, url):
    tenant = _tenant(tmp_path)
    with pytest.raises(CrawlSEOConfigurationCutoverError, match="HTTPS"):
        build_connector_configuration(
            tenant, _plan(), _body(tenant, url=url), {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"},
            client_factory=_client_factory,
        )


def test_custom_legacy_connector_token_env_loads_without_managed_file(tmp_path):
    config = _config(tmp_path)
    config["providers"]["crawlseo"].update({
        "connector_url": "https://crawlseo.example/crawlseo/api/connector/v1",
        "connector_token_env": "CRAWLSEO_OLD_CONNECTOR_TOKEN",
    })
    loaded = load_tenant_environment(config, {
        "CRAWLSEO_SERVICE_TOKEN": "mcp-secret",
        "CRAWLSEO_OLD_CONNECTOR_TOKEN": "legacy-connector-secret",
    })
    assert loaded["CRAWLSEO_SERVICE_TOKEN"] == "mcp-secret"
    assert loaded["CRAWLSEO_OLD_CONNECTOR_TOKEN"] == "legacy-connector-secret"


def test_cutover_uses_registered_config_path_without_filename_or_parent_assumptions(tmp_path):
    tenant = _tenant(tmp_path)
    arbitrary = tmp_path / "registered-records" / "tenant-settings.yml"
    arbitrary.parent.mkdir()
    arbitrary.write_bytes(Path(tenant.config_path).read_bytes())
    tenant.config_path = str(arbitrary)
    _install(tenant)
    result = build_connector_configuration(
        tenant, _plan(), _body(tenant), {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"},
        client_factory=_client_factory,
    )
    assert result["valid"] is True


@pytest.mark.parametrize("mutation", [
    lambda caps: caps.pop("binding"),
    lambda caps: caps["binding"].update(status="inactive"),
    lambda caps: caps["binding"].update(executor="other"),
    lambda caps: caps["binding"].update(generation=0),
    lambda caps: caps["binding"].update(generation=True),
    lambda caps: caps["binding"].update(executionSupported=False),
    lambda caps: caps.update(projectId="other-project"),
])
def test_cutover_rejects_inactive_or_wrong_remote_binding(tmp_path, mutation):
    tenant = _tenant(tmp_path)
    tenant.config["providers"]["crawlseo"].update({
        "connector_url": "https://crawlseo.example/api/connector/v1",
        "connector_token_env": CONNECTOR_TOKEN_ENV,
    })
    Path(tenant.config_path).write_text(yaml.safe_dump(tenant.config, sort_keys=False), encoding="utf-8")
    _install(tenant)
    capabilities = {**CAPABILITIES, "binding": dict(CAPABILITIES["binding"])}
    mutation(capabilities)
    client_factory = lambda _config, _env: SimpleNamespace(connector_capabilities=lambda **_kwargs: capabilities)
    with pytest.raises(CrawlSEOConfigurationCutoverError, match="active site binding"):
        build_connector_configuration(tenant, _plan(), _body(tenant),
            {"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=client_factory)


def test_apply_reloads_persists_and_replays_without_changing_authority(tmp_path):
    tenant = _tenant(tmp_path)
    _install(tenant)

    class Registry:
        tenants = {"tenant-a": tenant}

        def reload_tenant(self, tenant_id, config_path, **kwargs):
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            service = SimpleNamespace(connector_capabilities=lambda _site_id: CAPABILITIES)
            tenant.memory.close()
            replacement_memory = Memory(Path(config_path).with_name("memory.db"))
            replacement = SimpleNamespace(tenant_id=tenant_id, config_path=config_path, config=config, memory=replacement_memory, context={"crawlseo_service": service})
            self.tenants[tenant_id] = replacement
            return replacement

    registry = Registry()
    body = _body(tenant, mode="apply")
    result = apply_connector_configuration(
        registry, registry.tenants["tenant-a"], _plan(), body,
        env={"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=_client_factory,
    )
    assert result["status"] == "configured_read_only"
    assert registry.tenants["tenant-a"].memory is not tenant.memory
    saved = yaml.safe_load(Path(tenant.config_path).read_text())
    assert saved["providers"]["crawlseo"]["research_authority"] == "local"
    assert saved["providers"]["crawlseo"]["connector_url"] == body["connectorUrl"]
    replay = apply_connector_configuration(
        registry, registry.tenants["tenant-a"], _plan(), body,
        env={"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=_client_factory,
    )
    assert replay["idempotent"] is True
    conflict = dict(body, connectorUrl="https://crawlseo.example/mount/api/connector/v1")
    with pytest.raises(CrawlSEOConfigurationCutoverError, match="conflicting"):
        apply_connector_configuration(registry, registry.tenants["tenant-a"], _plan(), conflict)


def test_reload_failure_is_durable_checkpoint_without_authority_activation(tmp_path):
    tenant = _tenant(tmp_path)
    _install(tenant)

    class Registry:
        tenants = {"tenant-a": tenant}

        def reload_tenant(self, *_args, **_kwargs):
            raise RuntimeError("simulated reload failure")

    result = apply_connector_configuration(
        Registry(), tenant, _plan(), _body(tenant, mode="apply"),
        env={"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=_client_factory,
    )
    assert result["status"] == "config_saved_runtime_unverified"
    assert result["authorityChanged"] is False
    assert result["paidOperationsAllowed"] is False
    assert tenant.config["providers"]["crawlseo"]["research_authority"] == "local"
    receipts = tenant.memory.crawlseo_migration_receipts()
    assert {receipt["state"] for receipt in receipts if receipt.get("type") == "connector_configuration"} >= {
        "configuration_begin", "config_saved_runtime_unverified",
    }


def test_config_compare_and_swap_rejects_stale_hash(tmp_path):
    path = tmp_path / "tenant" / "config.yaml"
    path.parent.mkdir()
    path.write_text("instance_name: tenant\n", encoding="utf-8")
    old_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text("instance_name: tenant\nsite: changed\n", encoding="utf-8")
    with pytest.raises(TenantRegistrationError, match="changed"):
        TenantRegistrationService._replace_config(
            path, {"instance_name": "tenant", "site": "new"},
            expected_sha256=old_hash,
        )
    assert "changed" in path.read_text(encoding="utf-8")


def test_unconditional_config_writer_takes_shared_lock(tmp_path, monkeypatch):
    import fcntl
    path = tmp_path / "tenant" / "arbitrary-config.yml"
    path.parent.mkdir()
    acquired = []
    real_flock = fcntl.flock
    def observing_flock(fd, operation):
        if operation == fcntl.LOCK_EX:
            acquired.append(True)
        return real_flock(fd, operation)
    monkeypatch.setattr(fcntl, "flock", observing_flock)
    TenantRegistrationService._replace_config(path, {"instance_name": "tenant"})
    assert acquired
    assert path.exists()


def test_apply_does_not_overwrite_config_changed_during_capability_probe(tmp_path):
    tenant = _tenant(tmp_path)
    _install(tenant)

    class Registry:
        tenants = {"tenant-a": tenant}

    path = Path(tenant.config_path)

    def racing_factory(_config, _env):
        changed = yaml.safe_load(path.read_text(encoding="utf-8"))
        changed["site"] = {"operator_note": "concurrent update"}
        path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
        return _client_factory(_config, _env)

    original = path.read_bytes()
    with pytest.raises(CrawlSEOConfigurationCutoverError, match="changed"):
        apply_connector_configuration(
            Registry(), tenant, _plan(), _body(tenant, mode="apply"),
            env={"CRAWLSEO_SERVICE_TOKEN": "mcp-token"}, client_factory=racing_factory,
        )
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["site"]["operator_note"] == "concurrent update"
    assert path.read_bytes() != original
