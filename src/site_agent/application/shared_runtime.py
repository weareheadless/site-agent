"""Materialize Site-Agent-owned runtime into an immutable tenant build workspace.

Customer repositories remain the source of approved design and content. This
module overlays only the centrally declared runtime boundary and never changes
a tenant checkout or its Payload migration history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

_MANIFEST_PATH = Path("deploy/shared-runtime-overlay.json")
_TEMPLATE_PATH = Path("src/site_agent/templates/next-payload")
_PACKAGE_NAMES = (
    "@weareheadless/helloada-payload-admin",
    "@weareheadless/helloada-payload-core",
)
_CENTRAL_VAR_NAMES = {
    "HELLOADA_TEMPLATE_SCHEMA",
    "HELLOADA_WORKSPACE_API_VERSION",
    "HELLOADA_PAYLOAD_ADMIN_VERSION",
    "HELLOADA_PAYLOAD_CORE_VERSION",
    "HELLOADA_PAYLOAD_SCHEMA_REVISION",
    "HELLOADA_CONTENT_CONTRACT_VERSION",
    "HELLOADA_SCHEMA_IDENTITY",
    "HELLOADA_PAYLOAD_MIGRATION_HEAD",
    "HELLOADA_SITE_AGENT_VERSION",
    "HELLOADA_MAILFLARE_INBOUND_QUEUE_NAME",
    "HELLOADA_MAILFLARE_OUTBOUND_QUEUE_NAME",
    "HELLOADA_MAILFLARE_AGENT_QUEUE_NAME",
    "HELLOADA_HANDOFF_ISSUER",
    "HELLOADA_HANDOFF_PUBLIC_KEY",
}
_TENANT_VARS = {
    "SITE_AGENT_URL",
    "NEXT_PUBLIC_SITE_URL",
    "HELLOADA_TENANT_ID",
    "HELLOADA_SITE_NAME",
}
_RETIRED_VARS = {"HELLOADA_MESSAGES_QUEUE_NAME", "HELLOADA_MESSAGES_DLQ_NAME"}
_FORBIDDEN_PATHS = (
    Path("template-manifest.json"),
    Path("helloada-content-contract.json"),
    Path("src/migrations"),
    Path("src/components/site"),
)


class SharedRuntimeError(RuntimeError):
    """A shared runtime overlay cannot be materialized without changing tenant-owned state."""


def shared_package_versions(control_root: Path) -> dict[str, str]:
    """Return package versions from the canonical, integrity-pinned lockfile."""
    template = control_root / _TEMPLATE_PATH
    lock = _read_json(template / "package-lock.json", "canonical package lock")
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise SharedRuntimeError("canonical package lock must use npm lockfile version 3")
    result: dict[str, str] = {}
    for name in _PACKAGE_NAMES:
        entry = packages.get(f"node_modules/{name}")
        version = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(version, str) or not re.fullmatch(r"\\d+\\.\\d+\\.\\d+", version):
            raise SharedRuntimeError(f"canonical shared package version is invalid: {name}")
        result[name] = version
    return result


def _safe_path(root: Path, raw: Any) -> Path:
    relative = Path(str(raw or ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SharedRuntimeError("shared-runtime manifest contains an unsafe relative path")
    path = root / relative
    if path.resolve() != root.resolve() and root.resolve() not in path.resolve().parents:
        raise SharedRuntimeError("shared-runtime path escaped its source or tenant workspace")
    return path


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SharedRuntimeError(f"{label} must be valid strict JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise SharedRuntimeError(f"{label} root must be an object")
    return value


def _validate_manifest(root: Path, path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SharedRuntimeError("shared-runtime overlay manifest is missing or invalid") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or manifest.get("contract") != "helloada-shared-runtime-v1"
        or set(manifest) != {"schema", "contract", "copy", "remove"}
        or not isinstance(manifest.get("copy"), list)
        or not isinstance(manifest.get("remove"), list)
    ):
        raise SharedRuntimeError("shared-runtime overlay manifest does not match schema 1")
    copy_paths = [str(item) for item in manifest["copy"]]
    remove_paths = [str(item) for item in manifest["remove"]]
    if (
        len(copy_paths) != len(set(copy_paths))
        or len(remove_paths) != len(set(remove_paths))
        or set(copy_paths) & set(remove_paths)
    ):
        raise SharedRuntimeError("shared-runtime overlay paths must be unique and non-overlapping")
    for raw_path in copy_paths + remove_paths:
        relative = Path(raw_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise SharedRuntimeError("shared-runtime overlay contains an unsafe path")
        if any(relative == forbidden or forbidden in relative.parents for forbidden in _FORBIDDEN_PATHS):
            raise SharedRuntimeError("shared runtime cannot replace tenant Payload schema or presentation")
    if "wrangler.jsonc" in copy_paths or "wrangler.jsonc" in remove_paths:
        raise SharedRuntimeError("Wrangler configuration must be merged through the typed runtime contract")
    return manifest, raw


def shared_runtime_fingerprint(root: Path, manifest_path: Path | None = None) -> str:
    """Hash only the centrally owned runtime contract and its exact source bytes."""
    root = root.resolve()
    manifest_path = (manifest_path or root / _MANIFEST_PATH).resolve()
    manifest, raw_manifest = _validate_manifest(root, manifest_path)
    entries: list[tuple[str, bytes]] = [
        (str(_MANIFEST_PATH), raw_manifest),
        ("src/site_agent/application/shared_runtime.py", (root / "src/site_agent/application/shared_runtime.py").read_bytes()),
    ]
    template = root / _TEMPLATE_PATH
    for relative in sorted(str(item) for item in manifest["copy"]):
        source = _safe_path(template, relative)
        if not source.is_file() or source.is_symlink():
            raise SharedRuntimeError(f"central runtime source is missing or unsafe: {relative}")
        entries.append((f"template/{relative}", source.read_bytes()))
    for relative in ("package.json", "package-lock.json", "wrangler.jsonc"):
        source = template / relative
        if not source.is_file() or source.is_symlink():
            raise SharedRuntimeError(f"central runtime package contract is missing: {relative}")
        entries.append((f"template/{relative}", source.read_bytes()))
    digest = hashlib.sha256()
    for name, data in entries:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def _resource(items: Any, binding: str, identity_key: str, label: str) -> dict[str, Any]:
    if not isinstance(items, list):
        raise SharedRuntimeError(f"tenant {label} bindings are missing")
    matches = [item for item in items if isinstance(item, dict) and item.get("binding") == binding]
    if len(matches) != 1:
        raise SharedRuntimeError(f"tenant {label} binding {binding} must be declared exactly once")
    return matches[0]


def _merge_wrangler(template: dict[str, Any], tenant: dict[str, Any], customer: Mapping[str, Any],
                     tenant_id: str, shared_vars: Mapping[str, str], site_agent_version: str) -> dict[str, Any]:
    old_vars = tenant.get("vars")
    if not isinstance(old_vars, dict):
        raise SharedRuntimeError("tenant Wrangler vars must be an object")
    if tenant.get("name") != customer.get("worker"):
        raise SharedRuntimeError("tenant Worker name differs from the registered Worker identity")
    if old_vars.get("HELLOADA_TENANT_ID") != tenant_id:
        raise SharedRuntimeError("tenant Wrangler identity differs from the registered tenant")
    site_agent_url = old_vars.get("SITE_AGENT_URL")
    public_url = old_vars.get("NEXT_PUBLIC_SITE_URL")
    if not isinstance(site_agent_url, str) or not urlsplit(site_agent_url).hostname:
        raise SharedRuntimeError("tenant Site-Agent URL is not explicitly configured")
    parsed_public_url = urlsplit(str(public_url or ""))
    if parsed_public_url.scheme != "https" or not parsed_public_url.hostname:
        raise SharedRuntimeError("tenant public website origin must be an explicit HTTPS URL")

    database = _resource(tenant.get("d1_databases"), "D1", "database_id", "D1")
    if (database.get("database_id") != customer.get("d1DatabaseId")
            or database.get("database_name") != customer.get("d1DatabaseName")):
        raise SharedRuntimeError("tenant Payload D1 identity differs from the registered database")
    public_bucket = _resource(tenant.get("r2_buckets"), "R2", "bucket_name", "R2")
    private_bucket = _resource(tenant.get("r2_buckets"), "PRIVATE_EMAIL", "bucket_name", "private email")
    if (public_bucket.get("bucket_name") != customer.get("r2BucketName")
            or private_bucket.get("bucket_name") != customer.get("privateEmailR2BucketName")):
        raise SharedRuntimeError("tenant media or private email bucket differs from the registered resource")

    config = copy.deepcopy(template)
    config["name"] = customer["worker"]
    if "routes" in tenant:
        if not isinstance(tenant["routes"], list):
            raise SharedRuntimeError("tenant custom-domain routes must be a list")
        config["routes"] = copy.deepcopy(tenant["routes"])
    else:
        config.pop("routes", None)

    template_vars = config.get("vars")
    if not isinstance(template_vars, dict):
        raise SharedRuntimeError("canonical Worker vars are invalid")
    merged_vars = {
        key: value for key, value in old_vars.items()
        if key not in _CENTRAL_VAR_NAMES and key not in _RETIRED_VARS
    }
    tenant_identity = {
        "SITE_AGENT_URL": site_agent_url,
        "NEXT_PUBLIC_SITE_URL": public_url,
        "HELLOADA_TENANT_ID": tenant_id,
    }
    if isinstance(old_vars.get("HELLOADA_SITE_NAME"), str) and old_vars["HELLOADA_SITE_NAME"].strip():
        tenant_identity["HELLOADA_SITE_NAME"] = old_vars["HELLOADA_SITE_NAME"]
    for key, value in tenant_identity.items():
        merged_vars[key] = value
    merged_vars["HELLOADA_HANDOFF_PUBLIC_KEY"] = shared_vars.get("HELLOADA_HANDOFF_PUBLIC_KEY", "")
    if not merged_vars["HELLOADA_HANDOFF_PUBLIC_KEY"]:
        raise SharedRuntimeError("central HelloAda handoff public key is unavailable")

    central_values = {
        "HELLOADA_SITE_AGENT_VERSION": site_agent_version,
        "HELLOADA_PAYLOAD_ADMIN_VERSION": str(customer["payloadAdmin"]),
        "HELLOADA_PAYLOAD_CORE_VERSION": str(customer["payloadCore"]),
        "HELLOADA_PAYLOAD_SCHEMA_REVISION": str(customer["schemaRevision"]),
        "HELLOADA_CONTENT_CONTRACT_VERSION": str(customer["contentContract"]),
        "HELLOADA_SCHEMA_IDENTITY": str(customer["schemaIdentity"]),
        "HELLOADA_PAYLOAD_MIGRATION_HEAD": str(customer["migrationHead"]),
        "HELLOADA_MAILFLARE_INBOUND_QUEUE_NAME": str(customer["mailflareInboundQueueName"]),
        "HELLOADA_MAILFLARE_OUTBOUND_QUEUE_NAME": str(customer["mailflareOutboundQueueName"]),
        "HELLOADA_MAILFLARE_AGENT_QUEUE_NAME": str(customer["mailflareAgentQueueName"]),
    }
    for key, value in template_vars.items():
        if key in central_values:
            merged_vars[key] = central_values[key]
        elif key == "HELLOADA_HANDOFF_ISSUER":
            merged_vars[key] = "https://helloada.app"
        elif key in tenant_identity or key == "HELLOADA_SITE_NAME":
            continue
        elif key == "HELLOADA_HANDOFF_PUBLIC_KEY":
            continue
        elif isinstance(value, str) and value.startswith("__"):
            raise SharedRuntimeError(f"unresolved canonical Worker variable: {key}")
        else:
            merged_vars[key] = value
    config["vars"] = merged_vars

    template_d1 = config.get("d1_databases")
    if not isinstance(template_d1, list) or len(template_d1) != 2:
        raise SharedRuntimeError("canonical Payload and Mailflare D1 declarations are invalid")
    payload_d1 = next((item for item in template_d1 if item.get("binding") == "D1"), None)
    mailflare_d1 = next((item for item in template_d1 if item.get("binding") == "MAILFLARE_DB"), None)
    if not isinstance(payload_d1, dict) or not isinstance(mailflare_d1, dict):
        raise SharedRuntimeError("canonical D1 bindings are missing")
    payload_d1.update(database_id=customer["d1DatabaseId"], database_name=customer["d1DatabaseName"])
    mailflare_d1.update(
        database_id=customer["mailflareD1DatabaseId"],
        database_name=customer["mailflareD1DatabaseName"],
    )
    config["d1_databases"] = template_d1

    r2 = config.get("r2_buckets")
    if not isinstance(r2, list) or len(r2) != 3:
        raise SharedRuntimeError("canonical R2 declarations are invalid")
    r2_by_binding = {item.get("binding"): item for item in r2 if isinstance(item, dict)}
    if set(r2_by_binding) != {"R2", "PRIVATE_EMAIL", "MAILFLARE_BUCKET"}:
        raise SharedRuntimeError("canonical R2 bindings are incomplete")
    r2_by_binding["R2"]["bucket_name"] = customer["r2BucketName"]
    r2_by_binding["PRIVATE_EMAIL"]["bucket_name"] = customer["privateEmailR2BucketName"]
    r2_by_binding["PRIVATE_EMAIL"]["preview_bucket_name"] = customer["privateEmailR2BucketName"]
    r2_by_binding["MAILFLARE_BUCKET"]["bucket_name"] = customer["mailflareR2BucketName"]
    config["r2_buckets"] = r2

    producers = config.get("queues", {}).get("producers")
    if not isinstance(producers, list) or len(producers) != 3:
        raise SharedRuntimeError("canonical Mailflare Queue producers are invalid")
    queue_names = {
        "MAILFLARE_INBOUND_QUEUE": customer["mailflareInboundQueueName"],
        "MAILFLARE_OUTBOUND_QUEUE": customer["mailflareOutboundQueueName"],
        "MAILFLARE_AGENT_QUEUE": customer["mailflareAgentQueueName"],
    }
    for producer in producers:
        if not isinstance(producer, dict) or producer.get("binding") not in queue_names:
            raise SharedRuntimeError("canonical Mailflare Queue producer binding is invalid")
        producer["queue"] = queue_names[producer["binding"]]
    for consumer in config["queues"].get("consumers", []):
        if not isinstance(consumer, dict):
            raise SharedRuntimeError("canonical Mailflare Queue consumer is invalid")
        producer = next((item for item in producers if item["queue"] == consumer.get("queue")), None)
        if producer is None:
            raise SharedRuntimeError("canonical Mailflare Queue consumer has no producer")
    config["queues"]["consumers"] = [
        {**consumer, "queue": queue_names[next(
            producer["binding"] for producer in producers if producer["queue"] == consumer["queue"]
        )]}
        for consumer in config["queues"]["consumers"]
    ]
    return config


def _update_shared_packages(tenant_root: Path, template_root: Path) -> None:
    package_path = tenant_root / "package.json"
    lock_path = tenant_root / "package-lock.json"
    package = _read_json(package_path, "tenant package manifest")
    lock = _read_json(lock_path, "tenant package lock")
    canonical_package = _read_json(template_root / "package.json", "canonical package manifest")
    canonical_lock = _read_json(template_root / "package-lock.json", "canonical package lock")
    dependencies = package.get("dependencies")
    lock_root = lock.get("packages", {}).get("")
    canonical_root = canonical_lock.get("packages", {}).get("")
    if not isinstance(dependencies, dict) or not isinstance(lock_root, dict) or not isinstance(canonical_root, dict):
        raise SharedRuntimeError("tenant lockfile must use the canonical npm lockfile-v3 structure")
    for name in _PACKAGE_NAMES:
        url = canonical_package.get("dependencies", {}).get(name)
        source_lock = canonical_lock.get("packages", {}).get(f"node_modules/{name}")
        if not isinstance(url, str) or not isinstance(source_lock, dict) or source_lock.get("resolved") != url:
            raise SharedRuntimeError(f"canonical shared package is not immutably pinned: {name}")
        if name not in dependencies or name not in lock_root.get("dependencies", {}):
            raise SharedRuntimeError(f"tenant does not declare the shared package: {name}")
        dependencies[name] = url
        lock_root["dependencies"][name] = url
        lock.setdefault("packages", {})[f"node_modules/{name}"] = copy.deepcopy(source_lock)
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def apply_shared_runtime_overlay(
    control_root: Path,
    tenant_root: Path,
    customer: Mapping[str, Any],
    *,
    shared_vars: Mapping[str, str],
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Apply exact Site-Agent-owned runtime files to one fresh disposable checkout."""
    control_root = control_root.resolve()
    tenant_root = tenant_root.resolve()
    template_root = control_root / _TEMPLATE_PATH
    manifest_path = manifest_path or control_root / _MANIFEST_PATH
    manifest, _raw = _validate_manifest(control_root, manifest_path)
    tenant_id = str(customer.get("tenantId") or "")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", tenant_id):
        raise SharedRuntimeError("registered tenant identity is invalid")
    tenant_config_path = tenant_root / "wrangler.jsonc"
    template_config_path = template_root / "wrangler.jsonc"
    tenant_config = _read_json(tenant_config_path, "tenant Wrangler config")
    template_config = _read_json(template_config_path, "canonical Wrangler config")
    version_match = re.search(r'(?m)^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$', (control_root / "pyproject.toml").read_text())
    if not version_match:
        raise SharedRuntimeError("Site-Agent version is not pinned in pyproject.toml")
    runtime_fingerprint = shared_runtime_fingerprint(control_root, manifest_path)
    rendered = _merge_wrangler(template_config, tenant_config, customer, tenant_id,
                               shared_vars, version_match.group(1))

    for raw_path in manifest["copy"]:
        source = _safe_path(template_root, raw_path)
        target = _safe_path(tenant_root, raw_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for raw_path in manifest["remove"]:
        target = _safe_path(tenant_root, raw_path)
        if target.is_symlink():
            raise SharedRuntimeError(f"tenant runtime path is a symlink: {raw_path}")
        if target.is_file():
            target.unlink()
        elif target.exists():
            raise SharedRuntimeError(f"retired tenant runtime path is not a regular file: {raw_path}")

    _update_shared_packages(tenant_root, template_root)
    tenant_config_path.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    config_hash = hashlib.sha256(tenant_config_path.read_bytes()).hexdigest()
    package = json.loads((template_root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((template_root / "package-lock.json").read_text(encoding="utf-8"))
    return {
        "contract": manifest["contract"],
        "fingerprint": runtime_fingerprint,
        "wranglerSha256": config_hash,
        "copiedPaths": sorted(manifest["copy"]),
        "removedPaths": sorted(manifest["remove"]),
        "changedPaths": sorted(set(manifest["copy"]) | set(manifest["remove"]) | {
            "wrangler.jsonc", "package.json", "package-lock.json",
        }),
        "payloadAdmin": lock["packages"][f"node_modules/{_PACKAGE_NAMES[0]}"]["version"],
        "payloadCore": lock["packages"][f"node_modules/{_PACKAGE_NAMES[1]}"]["version"],
    }
