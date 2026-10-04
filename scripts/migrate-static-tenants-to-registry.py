#!/usr/bin/env python3
"""Adopt host-declared tenants into the one durable provisioned-tenant registry."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from site_agent.application.tenant_registration import provisioned_root, tenant_token_env


def read_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"malformed environment file at line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in values:
            raise ValueError(f"invalid or duplicate environment key at line {line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values, lines


def read_tenant_env(path: Path) -> dict[str, str]:
    return read_env_file(path)[0]


def render_env(values: Mapping[str, str], original_lines: list[str]) -> str:
    retained = []
    for line in original_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            retained.append(line)
            continue
        name = line.split("=", 1)[0].strip()
        if name in values:
            retained.append(line)
    return "\n".join(retained).rstrip() + "\n"


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, mode)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _existing_registry(root: Path) -> dict[str, Any]:
    path = root / "tenants.json"
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or any(not isinstance(entry, dict) for entry in value.values()):
        raise ValueError("canonical tenant registry is invalid")
    return value


def migrate(config_path: Path, env_path: Path, *, apply: bool) -> dict[str, Any]:
    config_path = config_path.resolve()
    env_path = env_path.resolve()
    host = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(host, dict):
        raise ValueError("host config must be an object")
    workspace = host.get("workspace_api")
    if not isinstance(workspace, dict):
        raise ValueError("workspace_api must be an object")
    declared = workspace.get("tenants") or {}
    if not isinstance(declared, dict):
        raise ValueError("workspace_api.tenants must be an object")
    if not declared:
        return {"status": "already-canonical", "tenantIds": [], "payloadSecretsCreated": 0}

    root = provisioned_root(host)
    host_env, host_env_lines = read_env_file(env_path)
    registry = _existing_registry(root)
    pending: dict[str, dict[str, Any]] = {}
    payload_secrets_created = 0

    for raw_tenant_id, spec in sorted(declared.items()):
        tenant_id = str(raw_tenant_id or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", tenant_id) or not isinstance(spec, Mapping):
            raise ValueError("host tenant declaration has an invalid identity")
        canonical_token_name = tenant_token_env(tenant_id)
        configured_token_name = str(spec.get("api_token_env") or canonical_token_name).strip()
        if configured_token_name != canonical_token_name:
            raise ValueError(f"{tenant_id} has a noncanonical API token name")
        source_config = Path(str(spec.get("config_path") or "")).expanduser().resolve()
        if not source_config.is_file():
            raise ValueError(f"{tenant_id} source config is missing")
        source_raw = yaml.safe_load(source_config.read_text(encoding="utf-8"))
        if not isinstance(source_raw, dict):
            raise ValueError(f"{tenant_id} source config is invalid")
        configured_identity = str(source_raw.get("instance_name") or tenant_id).strip().lower()
        if configured_identity != tenant_id:
            raise ValueError(f"{tenant_id} source config identity does not match")
        source_raw["instance_name"] = tenant_id
        payload = source_raw.get("site", {}).get("payload", {}) if isinstance(source_raw.get("site"), Mapping) else {}
        if isinstance(payload, Mapping) and payload.get("enabled"):
            if str(payload.get("token_env") or "").strip() != canonical_token_name:
                raise ValueError(f"{tenant_id} Payload token name is not synchronized")

        expected_config = (root / tenant_id / "config.yaml").resolve()
        expected_env = root / tenant_id / "tenant.env"
        current = registry.get(tenant_id)
        if current is not None:
            registered_config = Path(str(current.get("config_path") or "")).expanduser().resolve()
            registered_token_name = str(current.get("api_token_env") or canonical_token_name)
            if registered_config != expected_config or registered_token_name != canonical_token_name:
                raise ValueError(f"{tenant_id} has conflicting entries in the canonical registry")
            current_values = read_tenant_env(expected_env)
            token = current_values.get(canonical_token_name, "")
            if not token:
                raise ValueError(f"{tenant_id} canonical tenant token is missing")
            host_token = host_env.get(canonical_token_name, "")
            if host_token and host_token != token:
                raise ValueError(f"{tenant_id} API token differs between host and registry env files")
            continue

        host_token = host_env.get(canonical_token_name, "")
        source_env_path = source_config.parent / "tenant.env"
        values = read_tenant_env(source_env_path)
        if expected_env.exists():
            target_values = read_tenant_env(expected_env)
            for name, value in values.items():
                if name in target_values and target_values[name] != value:
                    raise ValueError(f"{tenant_id} has conflicting values for {name} during registry adoption")
            values = {**target_values, **values}
        tenant_token = values.get(canonical_token_name, "")
        if host_token and tenant_token and host_token != tenant_token:
            raise ValueError(f"{tenant_id} API token differs between host and tenant env files")
        token = tenant_token or host_token
        if not token:
            raise ValueError(f"{tenant_id} canonical API token is missing")
        values[canonical_token_name] = token
        if not values.get("PAYLOAD_SECRET"):
            if apply:
                values["PAYLOAD_SECRET"] = secrets.token_hex(36)
                payload_secrets_created += 1
            else:
                payload_secrets_created += 1
        target_config = expected_config
        if target_config.exists():
            existing_raw = yaml.safe_load(target_config.read_text(encoding="utf-8"))
            if not isinstance(existing_raw, dict) or existing_raw != source_raw:
                raise ValueError(f"{tenant_id} target config conflicts with its declared config")
        pending[tenant_id] = {
            "config_path": str(target_config),
            "api_token_env": canonical_token_name,
            "source_config": source_config,
            "target_config": target_config,
            "config_content": yaml.safe_dump(source_raw, sort_keys=False),
            "tenant_env_path": expected_env,
            "tenant_env_values": values,
        }

    if not apply:
        return {
            "status": "would-migrate",
            "tenantIds": sorted(declared),
            "payloadSecretsToCreate": payload_secrets_created,
        }

    # Keep private, same-host backups before changing any active registry inputs.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for path in (config_path, env_path, root / "tenants.json"):
        if path.exists():
            backup = path.with_name(f"{path.name}.before-tenant-registry-{stamp}")
            atomic_write(backup, path.read_text(encoding="utf-8"), 0o600)

    for tenant_id, item in pending.items():
        tenant_dir = root / tenant_id
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        tenant_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(tenant_dir, 0o700)
        atomic_write(item["target_config"], item["config_content"], 0o600)
        env_content = "\n".join(
            f"{name}={value}" for name, value in sorted(item["tenant_env_values"].items())
        ) + "\n"
        atomic_write(item["tenant_env_path"], env_content, 0o600)
        registry[tenant_id] = {
            "config_path": item["config_path"],
            "api_token_env": item["api_token_env"],
        }

    atomic_write(root / "tenants.json", json.dumps(registry, indent=2, sort_keys=True) + "\n")
    workspace["tenants"] = {}
    atomic_write(config_path, yaml.safe_dump(host, sort_keys=False))
    for tenant_id in declared:
        host_env.pop(tenant_token_env(tenant_id), None)
    atomic_write(env_path, render_env(host_env, host_env_lines))
    return {
        "status": "migrated",
        "tenantIds": sorted(declared),
        "payloadSecretsCreated": payload_secrets_created,
        "registryPath": str(root / "tenants.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="write the canonical registry and remove static declarations")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.config, args.env_file, apply=args.apply), sort_keys=True))
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"tenant registry migration failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
