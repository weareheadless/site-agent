#!/usr/bin/env python3
"""Validate or explicitly migrate provisioned tenants to pinned runtime identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from site_agent.application.tenant_registration import load_provisioned_tenants, provisioned_root
from site_agent.config import load
from site_agent.hands.payload_gateway import PayloadGatewayClient


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _read_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _expected_runtime_contract(customer: Mapping[str, Any]) -> dict[str, Any]:
    contract = str(customer.get("contentContract") or "").strip()
    core_version = str(customer.get("payloadCore") or "").strip()
    revision = customer.get("schemaRevision")
    identity = str(customer.get("schemaIdentity") or "").strip().lower()
    if (
        not re.fullmatch(r"helloada-content-v[1-9][0-9]*", contract)
        or not re.fullmatch(r"\d+\.\d+\.\d+", core_version)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or not re.fullmatch(r"[0-9a-f]{64}", identity)
    ):
        raise ValueError("tenant release manifest has no complete Payload runtime identity")
    return {
        "contract": contract,
        "coreVersion": core_version,
        "schemaRevision": revision,
        "schemaIdentity": identity,
    }


def _registered_config(root: Path, registry: Mapping[str, Any], tenant_id: str) -> Path:
    entry = registry.get(tenant_id)
    if not isinstance(entry, Mapping):
        raise ValueError(f"tenant {tenant_id} is not present in the provisioned registry")
    tenant_dir = root / tenant_id
    configured = Path(str(entry.get("config_path") or "")).expanduser()
    expected = tenant_dir / "config.yaml"
    if (
        not configured.is_absolute()
        or configured.is_symlink()
        or not expected.is_file()
        or expected.is_symlink()
        or configured.resolve() != expected.resolve()
    ):
        raise ValueError(f"tenant {tenant_id} configuration path is not canonical")
    return expected


def _updated_config(raw: Mapping[str, Any], customer: Mapping[str, Any], tenant_id: str) -> dict[str, Any]:
    expected_website = customer.get("websitePresent")
    if not isinstance(expected_website, bool):
        raise ValueError(f"tenant {tenant_id} release manifest must declare websitePresent")
    site_raw = raw.get("site")
    if not isinstance(site_raw, Mapping):
        raise ValueError(f"tenant {tenant_id} has no site configuration")
    site = dict(site_raw)
    if site.get("website_present") is not None and site.get("website_present") is not expected_website:
        raise ValueError(f"tenant {tenant_id} websitePresent conflicts with the release manifest")
    if site.get("adapter") != "payload_gateway":
        raise ValueError(f"tenant {tenant_id} does not use the canonical Payload gateway")

    payload_raw = site.get("payload")
    if not isinstance(payload_raw, Mapping) or payload_raw.get("enabled") is not True:
        raise ValueError(f"tenant {tenant_id} Payload gateway is not explicitly enabled")
    payload = dict(payload_raw)
    contract_raw = payload.get("contract")
    if not isinstance(contract_raw, Mapping):
        raise ValueError(f"tenant {tenant_id} Payload contract is missing")

    expected_contract = _expected_runtime_contract(customer)
    allowed = {
        "contract", "coreVersion", "schemaRevision", "schemaIdentity", "media_fields",
        "locales", "defaultLocale", "collections", "globals",
    }
    unknown = set(contract_raw) - allowed
    if unknown:
        raise ValueError(f"tenant {tenant_id} Payload contract contains unsupported fields")
    for key, expected in expected_contract.items():
        existing = contract_raw.get(key)
        if existing is not None and existing != expected:
            raise ValueError(f"tenant {tenant_id} Payload {key} conflicts with the release manifest")
    media_fields = contract_raw.get("media_fields", [])
    if not isinstance(media_fields, list) or any(not isinstance(item, str) or not item.strip() for item in media_fields):
        raise ValueError(f"tenant {tenant_id} Payload media_fields must be a list of non-empty strings")
    locales = contract_raw.get("locales")
    default_locale = contract_raw.get("defaultLocale")
    if locales is not None or default_locale is not None:
        if (
            not isinstance(locales, list)
            or not locales
            or any(not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z0-9-]{2,20}", locale) for locale in locales)
            or len(set(locales)) != len(locales)
            or default_locale not in locales
        ):
            raise ValueError(f"tenant {tenant_id} Payload locale configuration is invalid")
    for key in ("collections", "globals"):
        if key in contract_raw and not isinstance(contract_raw[key], Mapping):
            raise ValueError(f"tenant {tenant_id} legacy Payload {key} must be an object")

    canonical_contract = dict(expected_contract)
    if media_fields:
        canonical_contract["media_fields"] = list(media_fields)
    if locales is not None:
        canonical_contract["locales"] = list(locales)
        canonical_contract["defaultLocale"] = default_locale
    payload["contract"] = canonical_contract
    site["website_present"] = expected_website
    payload_config = dict(raw)
    payload_config["site"] = {**site, "payload": payload}
    return payload_config


def _write_yaml_atomically(path: Path, document: Mapping[str, Any]) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            yaml.safe_dump(dict(document), stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def sync_tenant_config(
    config_path: Path,
    tenant_id: str,
    customer: Mapping[str, Any],
    *,
    apply: bool,
) -> dict[str, Any]:
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError(f"tenant {tenant_id} config must be a regular file")
    before = config_path.read_bytes()
    updated = _updated_config(_read_yaml(config_path, f"tenant {tenant_id} config"), customer, tenant_id)
    serialized = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True).encode("utf-8")
    changed = serialized != before
    if apply and changed:
        _write_yaml_atomically(config_path, updated)
        if config_path.read_bytes() != serialized:
            raise RuntimeError(f"tenant {tenant_id} config did not match its verified update")
    return {
        "tenant": tenant_id,
        "status": "updated" if apply and changed else "would_update" if changed else "current",
        "configSha256Before": hashlib.sha256(before).hexdigest(),
        "configSha256After": hashlib.sha256(serialized).hexdigest(),
        "websitePresent": customer["websitePresent"],
        "contractKeys": sorted(updated["site"]["payload"]["contract"].keys()),
    }


def validate_runtime_configs(config_path: Path, manifest_path: Path, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    host_config = _read_yaml(config_path, "API host config")
    workspace = host_config.get("workspace_api")
    if not isinstance(workspace, Mapping) or workspace.get("enabled") is not True:
        raise ValueError("workspace_api.enabled must be true")
    if workspace.get("tenants") not in (None, {}):
        raise ValueError("workspace_api.tenants must be empty")
    manifest = _read_json(manifest_path, "tenant release manifest")
    customers = manifest.get("customers")
    if not isinstance(customers, Mapping):
        raise ValueError("tenant release manifest has no customers map")

    process_env = dict(os.environ if env is None else env)
    declared, tenant_env = load_provisioned_tenants(host_config, process_env)
    runtime_env = {**process_env, **tenant_env}
    validated_payload: list[str] = []
    for tenant_id, spec in sorted(declared.items()):
        config_path = Path(str(spec["config_path"]))
        tenant_config, _ = load(config_path, runtime_env)
        if str(tenant_config.get("instance_name") or "").strip().lower() != tenant_id:
            raise ValueError(f"tenant {tenant_id} instance_name does not match its registry identity")
        site = tenant_config.get("site") if isinstance(tenant_config.get("site"), Mapping) else {}
        raw = _read_yaml(config_path, f"tenant {tenant_id} config")
        raw_site = raw.get("site")
        if not isinstance(raw_site, Mapping):
            raise ValueError(f"tenant {tenant_id} must explicitly configure site settings")
        journey = tenant_config.get("ada_journey") or tenant_config.get("journey") or {}
        journey = journey if isinstance(journey, Mapping) else {}
        website_present = journey.get("website_present") if "website_present" in journey else site.get("website_present")
        if not isinstance(website_present, bool):
            raise ValueError(f"tenant {tenant_id} must explicitly configure website_present")

        payload = raw_site.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError(f"tenant {tenant_id} must explicitly configure Payload settings")
        adapter = str(raw_site.get("adapter") or "").strip()
        if not adapter:
            raise ValueError(f"tenant {tenant_id} must explicitly configure its site adapter")
        enabled = payload.get("enabled") is True
        customer = customers.get(tenant_id)
        if isinstance(customer, Mapping):
            if adapter != "payload_gateway" or not enabled:
                raise ValueError(f"manifest tenant {tenant_id} must use the enabled canonical Payload gateway")
            if website_present is not customer.get("websitePresent"):
                raise ValueError(f"tenant {tenant_id} website_present does not match the release manifest")
        if adapter == "payload_gateway" and not enabled:
            if isinstance(customer, Mapping):
                raise ValueError(f"manifest tenant {tenant_id} Payload gateway must be explicitly enabled")
        if enabled and adapter != "payload_gateway":
            raise ValueError(f"tenant {tenant_id} enables Payload without the canonical gateway adapter")
        if not enabled:
            continue

        client = PayloadGatewayClient.from_config(tenant_config, runtime_env)
        if client is None:
            raise ValueError(f"tenant {tenant_id} Payload gateway did not initialize")
        if isinstance(customer, Mapping):
            expected = _expected_runtime_contract(customer)
            contract = client.contract
            actual = {
                "contract": contract.contract_version,
                "coreVersion": contract.core_version,
                "schemaRevision": contract.schema_revision,
                "schemaIdentity": contract.schema_identity,
            }
            if actual != expected:
                raise ValueError(f"tenant {tenant_id} Payload contract does not match the release manifest")
        validated_payload.append(tenant_id)
    return {"validatedTenants": sorted(declared), "payloadTenants": validated_payload}


def _manifest_customers(path: Path) -> dict[str, Any]:
    manifest = _read_json(path, "tenant release manifest")
    customers = manifest.get("customers")
    if not isinstance(customers, dict):
        raise ValueError("tenant release manifest has no customers map")
    return customers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="shared Site-Agent API host config")
    parser.add_argument("--manifest", type=Path, default=ROOT / "deploy/payload-customers.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="validate every ready tenant without changing files")
    mode.add_argument("--sync", action="store_true", help="plan explicit tenant config identity updates")
    parser.add_argument("--tenant", action="append", default=[], help="registered tenant to sync; repeatable")
    parser.add_argument("--apply", action="store_true", help="apply the verified sync plan; default is dry-run")
    args = parser.parse_args()
    try:
        if args.validate:
            if args.tenant or args.apply:
                raise ValueError("--validate cannot be combined with --tenant or --apply")
            result = validate_runtime_configs(args.config, args.manifest)
        else:
            if not args.tenant or len(set(args.tenant)) != len(args.tenant):
                raise ValueError("--sync requires unique explicit --tenant values")
            host_config = _read_yaml(args.config, "API host config")
            root = provisioned_root(host_config)
            registry = _read_json(root / "tenants.json", "provisioned tenant registry")
            declared, _ = load_provisioned_tenants(host_config, os.environ)
            customers = _manifest_customers(args.manifest)
            rows = []
            for tenant_id in args.tenant:
                if tenant_id not in declared:
                    raise ValueError(f"tenant {tenant_id} is not a ready registered tenant")
                customer = customers.get(tenant_id)
                if not isinstance(customer, Mapping):
                    raise ValueError(f"tenant {tenant_id} is missing from the release manifest")
                config_path = _registered_config(root, registry, tenant_id)
                rows.append(sync_tenant_config(config_path, tenant_id, customer, apply=args.apply))
            result = {"mode": "apply" if args.apply else "dry-run", "tenants": rows}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"runtime config validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
