from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate-static-tenants-to-registry.py"
SPEC = importlib.util.spec_from_file_location("tenant_registry_migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def _inputs(tmp_path: Path, *, mismatch: bool = False):
    root = tmp_path / "websites"
    config_path = tmp_path / "site-agent-api.yaml"
    env_path = tmp_path / "site-agent-api.env"
    declarations = {}
    for tenant in ("atelier-harmonie", "oceanicvibes"):
        source_dir = tmp_path / "configs" / tenant
        source_dir.mkdir(parents=True)
        token_name = "PROVISIONED_" + tenant.replace("-", "_").upper() + "_TOKEN"
        source_config = source_dir / "config.yaml"
        source_config.write_text(yaml.safe_dump({
            "instance_name": tenant,
            "data_dir": str(tmp_path / "data" / tenant),
            "site": {"payload": {"enabled": True, "token_env": token_name}},
        }))
        declarations[tenant] = {
            "config_path": str(source_config),
            "api_token_env": token_name,
        }
    (tmp_path / "configs" / "oceanicvibes" / "tenant.env").write_text(
        "CRAWLSEO_SERVICE_TOKEN=test-crawlseo-token\n"
        "PROVISIONED_OCEANICVIBES_TOKEN="
        + ("different-token" if mismatch else "oceanic-api-token")
        + "\n"
    )
    host = {
        "data_dir": str(tmp_path / "host-data"),
        "workspace_api": {"enabled": True, "provisioned_root": str(root), "tenants": declarations},
    }
    config_path.write_text(yaml.safe_dump(host))
    env_path.write_text(
        "SITE_AGENT_LLM_API_KEY=host-llm-token\n"
        "PROVISIONED_ATELIER_HARMONIE_TOKEN=atelier-api-token\n"
        "PROVISIONED_OCEANICVIBES_TOKEN=oceanic-api-token\n"
    )
    return config_path, env_path, root


def test_registry_migration_dry_run_does_not_write_or_generate_secrets(tmp_path):
    config_path, env_path, root = _inputs(tmp_path)

    receipt = migration.migrate(config_path, env_path, apply=False)

    assert receipt["status"] == "would-migrate"
    assert receipt["payloadSecretsToCreate"] == 2
    assert not (root / "tenants.json").exists()
    assert "atelier-harmonie" in yaml.safe_load(config_path.read_text())["workspace_api"]["tenants"]
    assert "PROVISIONED_ATELIER_HARMONIE_TOKEN" in env_path.read_text()


def test_registry_migration_moves_tenants_and_canonicalizes_runtime_secrets(tmp_path):
    config_path, env_path, root = _inputs(tmp_path)

    receipt = migration.migrate(config_path, env_path, apply=True)

    assert receipt["status"] == "migrated"
    assert receipt["tenantIds"] == ["atelier-harmonie", "oceanicvibes"]
    assert receipt["payloadSecretsCreated"] == 2
    assert yaml.safe_load(config_path.read_text())["workspace_api"]["tenants"] == {}
    registry = json.loads((root / "tenants.json").read_text())
    assert set(registry) == {"atelier-harmonie", "oceanicvibes"}
    for tenant, entry in registry.items():
        assert entry["config_path"] == str(root / tenant / "config.yaml")
        values = migration.read_tenant_env(root / tenant / "tenant.env")
        assert values[entry["api_token_env"]]
        assert len(values["PAYLOAD_SECRET"]) == 72
    oceanic_env = migration.read_tenant_env(root / "oceanicvibes" / "tenant.env")
    assert oceanic_env["CRAWLSEO_SERVICE_TOKEN"] == "test-crawlseo-token"
    host_env = env_path.read_text()
    assert "SITE_AGENT_LLM_API_KEY=host-llm-token" in host_env
    assert "PROVISIONED_ATELIER_HARMONIE_TOKEN=" not in host_env
    assert "PROVISIONED_OCEANICVIBES_TOKEN=" not in host_env


def test_registry_migration_uses_the_active_host_token_and_removes_its_duplicate(tmp_path):
    config_path, env_path, root = _inputs(tmp_path, mismatch=True)

    receipt = migration.migrate(config_path, env_path, apply=True)

    assert receipt["status"] == "migrated"
    oceanic = migration.read_tenant_env(root / "oceanicvibes" / "tenant.env")
    assert oceanic["PROVISIONED_OCEANICVIBES_TOKEN"] == "oceanic-api-token"
    assert "PROVISIONED_OCEANICVIBES_TOKEN=" not in env_path.read_text()
