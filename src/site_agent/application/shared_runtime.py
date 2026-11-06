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
_PACKAGE_NAMES = ("@weareheadless/helloada-payload-core",)
# The admin used to ship as a versioned package. Its source is shared runtime
# now, so a tenant that still declares the dependency loses it at overlay time
# instead of pinning a second copy of the admin.
_RETIRED_PACKAGE_NAMES = ("@weareheadless/helloada-payload-admin",)
_CENTRAL_VAR_NAMES = {
    "HELLOADA_TEMPLATE_SCHEMA",
    "HELLOADA_WORKSPACE_API_VERSION",
    "HELLOADA_SHARED_RUNTIME_FINGERPRINT",
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
_RETIRED_VARS = {"HELLOADA_MESSAGES_QUEUE_NAME", "HELLOADA_MESSAGES_DLQ_NAME", "HELLOADA_STATIC_MANIFEST"}
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
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
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
        or manifest.get("schema") != 3
        or manifest.get("contract") != "helloada-shared-runtime-v3"
        or set(manifest) != {"schema", "contract", "copy", "copyTrees", "remove", "fingerprintTrees"}
        or not isinstance(manifest.get("copy"), list)
        or not isinstance(manifest.get("copyTrees"), list)
        or not isinstance(manifest.get("remove"), list)
        or not isinstance(manifest.get("fingerprintTrees"), list)
    ):
        raise SharedRuntimeError("shared-runtime overlay manifest does not match schema 3")
    copy_paths = [str(item) for item in manifest["copy"]]
    copy_trees = [str(item) for item in manifest["copyTrees"]]
    remove_paths = [str(item) for item in manifest["remove"]]
    fingerprint_trees = [str(item) for item in manifest["fingerprintTrees"]]
    if len(fingerprint_trees) != len(set(fingerprint_trees)):
        raise SharedRuntimeError("shared-runtime fingerprint trees must be unique")
    if (
        len(copy_paths) != len(set(copy_paths))
        or len(copy_trees) != len(set(copy_trees))
        or len(remove_paths) != len(set(remove_paths))
        or set(copy_paths) & set(remove_paths)
        or set(copy_trees) & set(remove_paths)
        or set(copy_trees) & set(copy_paths)
        or any(
            tree == copied or tree in Path(copied).parents
            for tree in copy_trees for copied in copy_paths
        )
    ):
        raise SharedRuntimeError("shared-runtime overlay paths must be unique and non-overlapping")
    for raw_path in copy_paths + copy_trees + remove_paths + fingerprint_trees:
        relative = Path(raw_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise SharedRuntimeError("shared-runtime manifest contains an unsafe path")
        if raw_path in fingerprint_trees and any(
            relative == forbidden or forbidden in relative.parents for forbidden in _FORBIDDEN_PATHS
        ):
            raise SharedRuntimeError("shared runtime cannot fingerprint tenant Payload schema or presentation")
        if raw_path in copy_paths + copy_trees + remove_paths and any(
            relative == forbidden or forbidden in relative.parents for forbidden in _FORBIDDEN_PATHS
        ):
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
        ("scripts/generate-payload-contract.mjs", (root / "scripts/generate-payload-contract.mjs").read_bytes()),
    ]
    template = root / _TEMPLATE_PATH
    for relative in sorted(str(item) for item in manifest["copy"]) + _tree_paths(template, manifest["copyTrees"]):
        source = _safe_path(template, relative)
        if not source.is_file() or source.is_symlink():
            raise SharedRuntimeError(f"central runtime source is missing or unsafe: {relative}")
        entries.append((f"template/{relative}", source.read_bytes()))
    # wrangler.jsonc carries the fingerprint itself, so it is generated output
    # rather than an input; the overlay result records its hash separately.
    for relative in ("package.json", "package-lock.json"):
        source = template / relative
        if not source.is_file() or source.is_symlink():
            raise SharedRuntimeError(f"central runtime package contract is missing: {relative}")
        entries.append((f"template/{relative}", source.read_bytes()))
    for raw_tree in sorted(str(item) for item in manifest["fingerprintTrees"]):
        directory = _safe_path(root, raw_tree)
        if not directory.is_dir() or directory.is_symlink():
            raise SharedRuntimeError(f"central runtime fingerprint tree is missing or unsafe: {raw_tree}")
        files = sorted(directory.rglob("*"))
        if not files:
            raise SharedRuntimeError(f"central runtime fingerprint tree is empty: {raw_tree}")
        for source in files:
            if source.is_symlink():
                raise SharedRuntimeError(f"central runtime fingerprint tree contains a symlink: {source}")
            if source.is_dir():
                continue
            if not source.is_file():
                raise SharedRuntimeError(f"central runtime fingerprint tree contains a special file: {source}")
            entries.append((source.relative_to(root).as_posix(), source.read_bytes()))
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
                     tenant_id: str, shared_vars: Mapping[str, str], site_agent_version: str,
                     shared_runtime_fingerprint: str) -> dict[str, Any]:
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
        "HELLOADA_SHARED_RUNTIME_FINGERPRINT": shared_runtime_fingerprint,
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
    # Presentation mode is deployment configuration, so it must survive the
    # canonical overlay rather than living only in the tenant's own file. The
    # template keeps its Payload asset handling; only an explicit static tenant
    # routes every public request through the Worker so runtime SEO bindings
    # can be injected.
    profile = merged_vars.get("HELLOADA_PRESENTATION_PROFILE") or "payload"
    if profile not in {"payload", "static"}:
        raise SharedRuntimeError("tenant presentation profile is not supported")
    if profile == "static":
        assets = config.get("assets")
        if not isinstance(assets, dict):
            raise SharedRuntimeError("canonical Worker assets declaration is invalid")
        assets["run_worker_first"] = True
        assets["html_handling"] = "none"

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
    producer_bindings = {}
    for producer in producers:
        if not isinstance(producer, dict) or producer.get("binding") not in queue_names:
            raise SharedRuntimeError("canonical Mailflare Queue producer binding is invalid")
        producer_bindings[producer.get("queue")] = producer["binding"]
    if len(producer_bindings) != 3 or len(config["queues"].get("consumers", [])) != 3:
        raise SharedRuntimeError("canonical Mailflare Queue producer and consumer identities must be unique")
    consumer_bindings = {}
    for consumer in config["queues"]["consumers"]:
        if not isinstance(consumer, dict) or consumer.get("queue") not in producer_bindings:
            raise SharedRuntimeError("canonical Mailflare Queue consumer has no producer")
        consumer_bindings[consumer["queue"]] = producer_bindings[consumer["queue"]]
    for producer in producers:
        producer["queue"] = queue_names[producer["binding"]]
    config["queues"]["consumers"] = [
        {**consumer, "queue": queue_names[consumer_bindings[consumer["queue"]]]}
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
    for name in _RETIRED_PACKAGE_NAMES:
        dependencies.pop(name, None)
        lock_root.get("dependencies", {}).pop(name, None)
        lock.get("packages", {}).pop(f"node_modules/{name}", None)
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def _tree_paths(template_root: Path, trees: list[str]) -> list[str]:
    """Expand ``copyTrees`` into explicit, validated template-relative files.

    A directory entry keeps the manifest honest: every file under it is copied
    and fingerprinted, so a new component cannot be forgotten and silently leave
    a stale tenant admin behind. Symlinks and special files fail closed.
    """
    files: list[str] = []
    for raw_tree in trees:
        directory = _safe_path(template_root, raw_tree)
        if not directory.is_dir() or directory.is_symlink():
            raise SharedRuntimeError(f"shared runtime tree is missing or unsafe: {raw_tree}")
        expanded: list[str] = []
        for source in sorted(directory.rglob("*")):
            if source.is_symlink():
                raise SharedRuntimeError(f"shared runtime tree contains a symlink: {raw_tree}")
            if source.is_dir():
                continue
            if not source.is_file():
                raise SharedRuntimeError(f"shared runtime tree contains a special file: {raw_tree}")
            expanded.append(source.relative_to(template_root).as_posix())
        if not expanded:
            raise SharedRuntimeError(f"shared runtime tree is empty: {raw_tree}")
        files.extend(expanded)
    return files


_SITE_CONFIG_PATH = Path("src/helloada.config.ts")
_RETIRED_SITE_CONFIG_IMPORT = "from '@weareheadless/helloada-payload-admin/config'"
_SITE_CONFIG_IMPORT = "from '@/admin/config/site'"


def _migrate_tenant_site_config(tenant_root: Path) -> bool:
    """Point the tenant's site configuration at the shared admin source.

    ``src/helloada.config.ts`` is tenant-owned because it carries the tenant's
    name, locales and features, so the overlay cannot replace it. The one
    platform-owned line in it is the import of the site-config factory, which
    used to come from the retired admin package. Rewrite that line only and
    fail closed on a missing file or a contradictory import.
    """
    path = tenant_root / _SITE_CONFIG_PATH
    if path.is_symlink() or not path.is_file():
        raise SharedRuntimeError("tenant site configuration is missing or unsafe")
    text = path.read_text(encoding="utf-8")
    if _RETIRED_SITE_CONFIG_IMPORT not in text:
        return False
    if _SITE_CONFIG_IMPORT in text:
        raise SharedRuntimeError("tenant site configuration mixes both site-config imports")
    path.write_text(text.replace(_RETIRED_SITE_CONFIG_IMPORT, _SITE_CONFIG_IMPORT), encoding="utf-8")
    return True


def _stamp_preview_runtime_identity(worktree: Path, fingerprint: str) -> bool:
    """Stamp the preview manifest with the exact shared runtime identity.

    The release runner regenerates the whole contract manifest. The preview
    compiles the tenant's committed manifest, which predates the shared runtime
    fingerprint, so it would fail type checking on a field that only the release
    generator writes. The tenant manifest stays authoritative for its locales,
    migrations and schema identity; only the shared runtime field is stamped.
    """
    path = worktree / "template-manifest.json"
    if path.is_symlink() or not path.is_file():
        raise SharedRuntimeError("preview template manifest is missing or unsafe")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SharedRuntimeError("preview template manifest is invalid") from error
    if not isinstance(manifest, dict):
        raise SharedRuntimeError("preview template manifest root must be an object")
    changed = manifest.pop("payloadAdmin", None) is not None or manifest.get("sharedRuntimeFingerprint") != fingerprint
    manifest["sharedRuntimeFingerprint"] = fingerprint
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return changed


def apply_preview_runtime_overlay(
    worktree: Path,
    *,
    package_root: Path,
    runtime_fingerprint: str,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Copy and remove the centrally owned runtime files in a disposable preview.

    A compiled preview must compile exactly what the release will build. The
    release runner materializes the same overlay before its typecheck; without
    this step a preview compiles tenant files the runtime deletes and can fail
    on code that never ships.
    """
    package_root = package_root.resolve()
    template_root = package_root / "templates" / "next-payload"
    manifest_path = (manifest_path or package_root / "templates" / "shared-runtime-overlay.json").resolve()
    manifest, _raw = _validate_manifest(package_root, manifest_path)
    if not re.fullmatch(r"[0-9a-f]{64}", str(runtime_fingerprint or "")):
        raise SharedRuntimeError("preview requires the activated shared runtime fingerprint")
    worktree = worktree.resolve()
    copied: list[str] = []
    removed: list[str] = []
    tree_files = _tree_paths(template_root, manifest["copyTrees"])
    for relative in list(manifest["copy"]) + tree_files:
        source = _safe_path(template_root, relative)
        if not source.is_file() or source.is_symlink():
            raise SharedRuntimeError(f"preview runtime source is missing or unsafe: {relative}")
        target = _safe_path(worktree, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(str(relative))
    for relative in manifest["remove"]:
        target = _safe_path(worktree, relative)
        if target.is_symlink() or target.is_file():
            target.unlink()
            removed.append(str(relative))
    _update_shared_packages(worktree, template_root)
    migrated = [str(_SITE_CONFIG_PATH)] if _migrate_tenant_site_config(worktree) else []
    if _stamp_preview_runtime_identity(worktree, runtime_fingerprint):
        migrated.append("template-manifest.json")
    return {
        "copied": copied,
        "removed": removed,
        "migrated": migrated,
        "fingerprint": runtime_fingerprint,
        "manifest": manifest,
    }


def apply_shared_runtime_overlay(
    control_root: Path,
    tenant_root: Path,
    customer: Mapping[str, Any],
    *,
    shared_vars: Mapping[str, str],
    manifest_path: Path | None = None,
    expected_fingerprint: str | None = None,
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
    if expected_fingerprint is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint):
            raise SharedRuntimeError("expected shared runtime fingerprint is invalid")
    runtime_fingerprint = shared_runtime_fingerprint(control_root, manifest_path)
    if expected_fingerprint is not None and expected_fingerprint != runtime_fingerprint:
        raise SharedRuntimeError("expected shared runtime fingerprint does not match control bytes")
    rendered = _merge_wrangler(template_config, tenant_config, customer, tenant_id,
                               shared_vars, version_match.group(1), runtime_fingerprint)

    tree_files = _tree_paths(template_root, manifest["copyTrees"])
    for raw_path in list(manifest["copy"]) + tree_files:
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
    migrated = [str(_SITE_CONFIG_PATH)] if _migrate_tenant_site_config(tenant_root) else []
    tenant_config_path.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    config_hash = hashlib.sha256(tenant_config_path.read_bytes()).hexdigest()
    package = json.loads((template_root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((template_root / "package-lock.json").read_text(encoding="utf-8"))
    return {
        "contract": manifest["contract"],
        "fingerprint": runtime_fingerprint,
        "wranglerSha256": config_hash,
        "copiedPaths": sorted(list(manifest["copy"]) + tree_files),
        "removedPaths": sorted(manifest["remove"]),
        "migratedPaths": migrated,
        "changedPaths": sorted(set(manifest["copy"]) | set(tree_files) | set(manifest["remove"]) | set(migrated) | {
            "wrangler.jsonc", "package.json", "package-lock.json",
            "template-manifest.json", "helloada-content-contract.json",
        }),
        "sharedRuntimeFingerprint": runtime_fingerprint,
        "payloadCore": lock["packages"][f"node_modules/{_PACKAGE_NAMES[0]}"]["version"],
    }
