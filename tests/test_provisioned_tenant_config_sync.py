from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "provisioned_tenant_config_sync_test", ROOT / "scripts/sync-provisioned-tenant-configs.py"
)
assert SPEC is not None and SPEC.loader is not None
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def _fixture(tmp_path: Path):
    root = tmp_path / "websites"
    tenant_dir = root / "oceanicvibes"
    tenant_dir.mkdir(parents=True)
    host = tmp_path / "host.yaml"
    host.write_text(yaml.safe_dump({
        "data_dir": str(tmp_path / "host-data"),
        "workspace_api": {"enabled": True, "provisioned_root": str(root), "tenants": {}},
    }))
    (root / "tenants.json").write_text(json.dumps({"oceanicvibes": {
        "config_path": str(tenant_dir / "config.yaml"),
        "api_token_env": "PROVISIONED_OCEANICVIBES_TOKEN",
        "bootstrap_state": "ready",
    }}))
    (tenant_dir / "tenant.env").write_text("PROVISIONED_OCEANICVIBES_TOKEN=not-a-real-token\n")
    config = {
        "instance_name": "oceanicvibes",
        "site": {
            "adapter": "payload_gateway",
            "payload": {
                "enabled": True,
                "url": "https://oceanicvibes.com",
                "api_prefix": "/api/workspace",
                "token_env": "PROVISIONED_OCEANICVIBES_TOKEN",
                "contract": {
                    "collections": {"pages": ["title"], "posts": ["title"]},
                    "globals": {"navigation": ["items"]},
                    "media_fields": ["alt", "description"],
                    "locales": ["en", "fr"],
                    "defaultLocale": "en",
                },
            },
        },
    }
    config_path = tenant_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    config_path.chmod(0o600)
    customer = {
        "payloadCore": "0.2.0",
        "contentContract": "helloada-content-v2",
        "schemaRevision": 2,
        "schemaIdentity": "a" * 64,
        "websitePresent": True,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"customers": {"oceanicvibes": customer}}))
    return host, manifest, config_path, customer


def test_sync_is_dry_run_by_default_and_removes_duplicate_schema_field_maps(tmp_path):
    host, manifest, config_path, customer = _fixture(tmp_path)
    before = config_path.read_bytes()
    result = sync.sync_tenant_config(config_path, "oceanicvibes", customer, apply=False)
    assert result["status"] == "would_update"
    assert config_path.read_bytes() == before

    applied = sync.sync_tenant_config(config_path, "oceanicvibes", customer, apply=True)
    updated = yaml.safe_load(config_path.read_text())
    contract = updated["site"]["payload"]["contract"]
    assert applied["status"] == "updated"
    assert contract == {
        "contract": "helloada-content-v2",
        "coreVersion": "0.2.0",
        "schemaRevision": 2,
        "schemaIdentity": "a" * 64,
        "media_fields": ["alt", "description"],
        "locales": ["en", "fr"],
        "defaultLocale": "en",
    }
    assert updated["site"]["website_present"] is True
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert sync.validate_runtime_configs(host, manifest, {"PROVISIONED_OCEANICVIBES_TOKEN": "not-a-real-token"}) == {
        "validatedTenants": ["oceanicvibes"],
        "payloadTenants": ["oceanicvibes"],
    }


def test_sync_refuses_conflicting_explicit_identity_or_website_state(tmp_path):
    _host, _manifest, config_path, customer = _fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config["site"]["website_present"] = False
    config["site"]["payload"]["contract"]["schemaIdentity"] = "b" * 64
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    before = config_path.read_bytes()
    for _ in range(2):
        try:
            sync.sync_tenant_config(config_path, "oceanicvibes", customer, apply=True)
        except ValueError:
            pass
        else:
            raise AssertionError("conflicting runtime identity must stop the config migration")
        assert config_path.read_bytes() == before


def test_runtime_preflight_requires_explicit_journey_and_pinned_payload_identity(tmp_path):
    host, manifest, config_path, _customer = _fixture(tmp_path)
    with pytest.raises(ValueError, match="website_present"):
        sync.validate_runtime_configs(host, manifest, {"PROVISIONED_OCEANICVIBES_TOKEN": "not-a-real-token"})
    config = yaml.safe_load(config_path.read_text())
    config["site"]["website_present"] = True
    config["site"]["payload"]["contract"].update({
        "contract": "helloada-content-v2",
        "coreVersion": "0.2.0",
        "schemaRevision": 2,
        "schemaIdentity": "a" * 64,
    })
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    release_manifest = json.loads(manifest.read_text())
    release_manifest["customers"]["oceanicvibes"]["schemaIdentity"] = "b" * 64
    manifest.write_text(json.dumps(release_manifest))
    with pytest.raises(ValueError, match="release manifest"):
        sync.validate_runtime_configs(host, manifest, {"PROVISIONED_OCEANICVIBES_TOKEN": "not-a-real-token"})


def test_runtime_preflight_does_not_accept_a_manifest_tenant_without_payload_enabled(tmp_path):
    host, manifest, config_path, _customer = _fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config["site"]["website_present"] = True
    config["site"]["payload"]["enabled"] = False
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    with pytest.raises(ValueError, match="enabled canonical Payload gateway"):
        sync.validate_runtime_configs(host, manifest, {"PROVISIONED_OCEANICVIBES_TOKEN": "not-a-real-token"})


def test_runtime_preflight_allows_a_dormant_tenant_without_a_payload_instance(tmp_path):
    host, manifest, config_path, customer = _fixture(tmp_path)
    sync.sync_tenant_config(config_path, "oceanicvibes", customer, apply=True)
    root = config_path.parents[1]
    tenant_dir = root / "dormant-studio"
    tenant_dir.mkdir()
    dormant = tenant_dir / "config.yaml"
    dormant.write_text(yaml.safe_dump({
        "instance_name": "dormant-studio",
        "site": {"adapter": "payload_gateway", "website_present": False},
    }))
    (tenant_dir / "tenant.env").write_text("PROVISIONED_DORMANT_STUDIO_TOKEN=not-a-real-token\n")
    registry_path = root / "tenants.json"
    registry = json.loads(registry_path.read_text())
    registry["dormant-studio"] = {
        "config_path": str(dormant),
        "api_token_env": "PROVISIONED_DORMANT_STUDIO_TOKEN",
        "bootstrap_state": "ready",
    }
    registry_path.write_text(json.dumps(registry))

    result = sync.validate_runtime_configs(host, manifest, {
        "PROVISIONED_OCEANICVIBES_TOKEN": "not-a-real-token",
        "PROVISIONED_DORMANT_STUDIO_TOKEN": "not-a-real-token",
    })

    assert result == {
        "validatedTenants": ["dormant-studio", "oceanicvibes"],
        "payloadTenants": ["oceanicvibes"],
    }
