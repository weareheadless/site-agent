from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from scripts.migrate_payload_gateway_prefix import (
    CANONICAL_PREFIX,
    ConfigMigrationError,
    migrate_payload_config_text,
    migrate_registered_configs,
)


def _config(prefix: str) -> str:
    return (
        "site:\n"
        "  payload:\n"
        "    enabled: true\n"
        f"    api_prefix: {prefix} # managed route\n"
        "    token_env: PAYLOAD_GATEWAY_TOKEN\n"
        "  cloudflare:\n"
        "    mode: git\n"
    )


def test_migration_changes_only_explicit_payload_route_and_preserves_comment():
    source = _config("/api")
    updated, old_prefix = migrate_payload_config_text(source, "tenant-one")

    assert old_prefix == "/api"
    assert updated == _config(CANONICAL_PREFIX)
    assert yaml.safe_load(updated)["site"]["payload"]["api_prefix"] == CANONICAL_PREFIX


def test_migration_is_idempotent_for_canonical_route():
    source = _config(CANONICAL_PREFIX)
    updated, old_prefix = migrate_payload_config_text(source, "tenant-one")

    assert old_prefix == CANONICAL_PREFIX
    assert updated == source


@pytest.mark.parametrize("prefix", ["/api/v2", "/custom", ""])
def test_migration_rejects_unknown_or_implicit_routes(prefix):
    with pytest.raises(ConfigMigrationError):
        migrate_payload_config_text(_config(prefix), "tenant-one")


def test_migration_validates_all_registered_configs_before_writing(tmp_path: Path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"customers": {"good": {}, "bad": {}}}))
    root = tmp_path / "websites"
    (root / "good").mkdir(parents=True)
    (root / "bad").mkdir()
    good_path = root / "good" / "config.yaml"
    bad_path = root / "bad" / "config.yaml"
    good_path.write_text(_config("/api"))
    bad_path.write_text(_config("/custom"))

    with pytest.raises(ConfigMigrationError):
        migrate_registered_configs(registry, root, apply=True)

    assert yaml.safe_load(good_path.read_text())["site"]["payload"]["api_prefix"] == "/api"


def test_apply_is_atomic_idempotent_and_preserves_file_mode(tmp_path: Path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"customers": {"tenant-one": {}}}))
    root = tmp_path / "websites"
    tenant_dir = root / "tenant-one"
    tenant_dir.mkdir(parents=True)
    config = tenant_dir / "config.yaml"
    config.write_text(_config("/api"))
    os.chmod(config, 0o600)

    first = migrate_registered_configs(registry, root, apply=True)
    second = migrate_registered_configs(registry, root, apply=True)

    assert first[0]["applied"] is True
    assert second[0]["changed"] is False
    assert config.stat().st_mode & 0o777 == 0o600
    assert yaml.safe_load(config.read_text())["site"]["payload"]["api_prefix"] == CANONICAL_PREFIX
