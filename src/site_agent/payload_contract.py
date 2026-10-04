"""Validation for the immutable Payload schema and migration artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


_MIGRATION_NAME = re.compile(r"^\d{8}_\d{6}(?:_[A-Za-z0-9_]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMPORT = re.compile(r"import\s+\*\s+as\s+migration_(\w+)\s+from\s+'\.\/([^']+)'\s*;?")


class PayloadContractError(ValueError):
    """The canonical Payload manifest or its migration chain is invalid."""


def validate_payload_migrations(site_root: str | Path, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Verify manifest, exact migration index, source files and snapshots."""
    root = Path(site_root).resolve()
    try:
        value = dict(manifest) if manifest is not None else json.loads(
            (root / "template-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PayloadContractError("canonical Payload template manifest is missing or invalid") from exc
    if not isinstance(value, dict):
        raise PayloadContractError("canonical Payload template manifest must be an object")

    migrations = value.get("migrations")
    if not isinstance(migrations, list) or not migrations:
        raise PayloadContractError("canonical Payload template has no committed migration chain")
    migration_dir = root / "src/migrations"
    try:
        index = (migration_dir / "index.ts").read_bytes()
        index_text = index.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise PayloadContractError("canonical Payload migration index is unavailable") from exc
    matches = list(_IMPORT.finditer(index_text))
    index_names = [match.group(2) for match in matches]
    if not matches or any(match.group(1) != match.group(2) for match in matches):
        raise PayloadContractError("Payload migration index contains an invalid import identity")
    if len(set(index_names)) != len(index_names):
        raise PayloadContractError("Payload migration index contains duplicate identities")
    actual_names = sorted(path.stem for path in migration_dir.glob("*.ts") if path.name != "index.ts")
    if sorted(index_names) != actual_names:
        raise PayloadContractError("Payload migration files and index do not match exactly")

    expected_records: list[dict[str, str]] = []
    for entry in migrations:
        if not isinstance(entry, Mapping):
            raise PayloadContractError("Payload migration manifest entry is invalid")
        name = str(entry.get("name") or "")
        file_sha = str(entry.get("fileSha256") or "")
        snapshot_sha = str(entry.get("snapshotSha256") or "")
        if not _MIGRATION_NAME.fullmatch(name) or not _SHA256.fullmatch(file_sha) or not _SHA256.fullmatch(snapshot_sha):
            raise PayloadContractError("Payload migration identity is incomplete")
        try:
            actual_file_sha = hashlib.sha256((migration_dir / f"{name}.ts").read_bytes()).hexdigest()
            actual_snapshot_sha = hashlib.sha256((migration_dir / f"{name}.json").read_bytes()).hexdigest()
        except OSError as exc:
            raise PayloadContractError(f"Payload migration artifact is missing: {name}") from exc
        if actual_file_sha != file_sha or actual_snapshot_sha != snapshot_sha:
            raise PayloadContractError(f"Payload migration artifact hash mismatch: {name}")
        expected_records.append({"fileSha256": file_sha, "name": name, "snapshotSha256": snapshot_sha})

    if [entry["name"] for entry in expected_records] != index_names:
        raise PayloadContractError("Payload migration manifest order differs from the executable index")
    index_sha = hashlib.sha256(index).hexdigest()
    if value.get("migrationIndexSha256") != index_sha:
        raise PayloadContractError("Payload migration index hash differs from the template manifest")
    head_payload = {"indexSha256": index_sha, "migrations": expected_records}
    head = hashlib.sha256(json.dumps(head_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if value.get("migrationHead") != head:
        raise PayloadContractError("Payload migration chain identity differs from the template manifest")
    return value


__all__ = ["PayloadContractError", "validate_payload_migrations"]
