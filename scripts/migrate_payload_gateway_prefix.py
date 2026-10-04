"""Migrate registered Payload gateway configs to the canonical workspace route.

This is an explicit host-config migration, not runtime route compatibility.
It validates every registered customer before writing any file and is dry-run
unless --apply is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

CANONICAL_PREFIX = "/api/workspace"
MIGRATION_SOURCE_PREFIX = "/api"


class ConfigMigrationError(ValueError):
    """A registered tenant config cannot be migrated unambiguously."""


def _payload_config(text: str, tenant: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigMigrationError(f"{tenant}: config.yaml is invalid YAML") from exc
    if not isinstance(document, dict):
        raise ConfigMigrationError(f"{tenant}: config.yaml root must be an object")
    site = document.get("site")
    payload = site.get("payload") if isinstance(site, dict) else None
    if not isinstance(payload, dict) or payload.get("enabled") is not True:
        raise ConfigMigrationError(f"{tenant}: registered Payload config must be enabled")
    prefix = payload.get("api_prefix")
    if not isinstance(prefix, str) or not prefix.strip():
        raise ConfigMigrationError(f"{tenant}: site.payload.api_prefix must be explicit")
    return {"prefix": prefix.strip()}


def _replace_prefix_line(text: str, tenant: str) -> str:
    lines = text.splitlines(keepends=True)
    site_start = next(
        (i for i, line in enumerate(lines) if re.fullmatch(r"site:\s*(?:#.*)?(?:\r?\n)?", line)),
        None,
    )
    if site_start is None:
        raise ConfigMigrationError(f"{tenant}: cannot locate site config section")
    site_end = next(
        (
            i for i in range(site_start + 1, len(lines))
            if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:", lines[i])
        ),
        len(lines),
    )
    payload_start = next(
        (
            i for i in range(site_start + 1, site_end)
            if re.fullmatch(r"  payload:\s*(?:#.*)?(?:\r?\n)?", lines[i])
        ),
        None,
    )
    if payload_start is None:
        raise ConfigMigrationError(f"{tenant}: cannot locate site.payload section")
    payload_end = next(
        (
            i for i in range(payload_start + 1, site_end)
            if re.match(r"^  [A-Za-z_][A-Za-z0-9_-]*:", lines[i])
        ),
        site_end,
    )
    prefix_lines = [
        i for i in range(payload_start + 1, payload_end)
        if re.match(r"^    api_prefix\s*:", lines[i])
    ]
    if len(prefix_lines) != 1:
        raise ConfigMigrationError(
            f"{tenant}: expected one explicit api_prefix under site.payload"
        )
    index = prefix_lines[0]
    line = lines[index]
    ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    body = line[:-len(ending)] if ending else line
    key, remainder = body.split(":", 1)
    comment = ""
    if "#" in remainder:
        comment = " #" + remainder.split("#", 1)[1]
    lines[index] = f"{key}: {CANONICAL_PREFIX}{comment}{ending}"
    updated = "".join(lines)
    if _payload_config(updated, tenant)["prefix"] != CANONICAL_PREFIX:
        raise ConfigMigrationError(f"{tenant}: route migration did not validate")
    return updated


def migrate_payload_config_text(text: str, tenant: str) -> tuple[str, str]:
    current = _payload_config(text, tenant)["prefix"]
    if current == CANONICAL_PREFIX:
        return text, current
    if current != MIGRATION_SOURCE_PREFIX:
        raise ConfigMigrationError(
            f"{tenant}: refusing unknown Payload gateway path {current!r}"
        )
    return _replace_prefix_line(text, tenant), current


def _atomic_replace(path: Path, original: bytes, updated: bytes) -> None:
    if path.is_symlink():
        raise ConfigMigrationError(f"refusing symlink config: {path.parent.name}")
    if path.read_bytes() != original:
        raise ConfigMigrationError(f"config changed during migration: {path.parent.name}")
    metadata = path.stat(follow_symlinks=False)
    effective_uid = os.geteuid()
    if effective_uid not in {0, metadata.st_uid}:
        raise PermissionError(f"run as the config owner to update {path.parent.name}")

    fd, temporary_name = tempfile.mkstemp(prefix=".config.yaml.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
        if effective_uid == 0:
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        elif os.getegid() != metadata.st_gid:
            os.chown(temporary, -1, metadata.st_gid)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def migrate_registered_configs(
    registry_path: Path,
    config_root: Path,
    *,
    apply: bool = False,
) -> list[dict[str, Any]]:
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigMigrationError("cannot read Payload customer registry") from exc
    customers = registry.get("customers") if isinstance(registry, dict) else None
    if not isinstance(customers, dict) or not customers:
        raise ConfigMigrationError("Payload customer registry must contain customers")
    root = config_root.resolve(strict=True)

    prepared: list[tuple[str, Path, bytes, bytes, str]] = []
    for tenant in sorted(customers):
        if not isinstance(tenant, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", tenant):
            raise ConfigMigrationError("Payload registry contains an unsafe tenant name")
        directory = root / tenant
        path = directory / "config.yaml"
        if directory.is_symlink() or path.is_symlink() or not directory.is_dir() or not path.is_file():
            raise ConfigMigrationError(f"{tenant}: registered config path is missing or unsafe")
        if path.resolve(strict=True).parent != directory.resolve(strict=True):
            raise ConfigMigrationError(f"{tenant}: config path escapes its registered directory")
        original = path.read_bytes()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigMigrationError(f"{tenant}: config.yaml must be UTF-8") from exc
        updated_text, current = migrate_payload_config_text(text, tenant)
        updated = updated_text.encode("utf-8")
        prepared.append((tenant, path, original, updated, current))

    results = []
    for tenant, path, original, updated, current in prepared:
        changed = updated != original
        if apply and changed:
            _atomic_replace(path, original, updated)
        results.append(
            {
                "tenant": tenant,
                "from": current,
                "to": CANONICAL_PREFIX,
                "changed": changed,
                "applied": bool(apply and changed),
            }
        )
    return results


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=repo_root / "deploy" / "payload-customers.json",
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path("/SOCIAL/site-agent-api/websites"),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="atomically update configs after validating every registered tenant",
    )
    args = parser.parse_args()
    try:
        results = migrate_registered_configs(
            args.registry,
            args.config_root,
            apply=args.apply,
        )
    except (ConfigMigrationError, OSError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for result in results:
        action = "updated" if result["applied"] else "would update" if result["changed"] else "already canonical"
        print(f"{result['tenant']}: {action} ({result['from']} -> {result['to']})")
    if not args.apply and any(result["changed"] for result in results):
        print("Dry run only. Re-run with --apply to write the validated migration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
