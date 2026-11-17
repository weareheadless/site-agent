"""Provision the visitor assistant's spend-limited provider key for one tenant.

The key is tenant isolation, not configuration: it is issued by the provider,
stored only in that tenant's protected ``tenant.env``, and delivered to the
Worker by the canonical release queue. The spend ceiling lives on the key at the
provider, so changing it needs no release and no code change.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ..senses import openrouter

ASSISTANT_KEY_ENV = "HELLOADA_ASSISTANT_KEY"
KEY_NAME_PREFIX = "site-agent:"
DEFAULT_LIMIT_USD = 5.0


class AssistantKeyError(RuntimeError):
    """A missing or inconsistent assistant-key provisioning input."""


def key_name(tenant_id: str) -> str:
    stable = str(tenant_id or "").strip().lower()
    if not stable:
        raise AssistantKeyError("assistant key provisioning needs a registered tenant")
    return f"{KEY_NAME_PREFIX}{stable}"


def _key_hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        values[name.strip()] = raw.strip().strip('"').strip("'")
    return values


def _write_env(path: Path, name: str, value: str) -> None:
    """Replace exactly one variable, preserving every other line and mode 0600."""
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    rendered: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in stripped and stripped.split("=", 1)[0].strip() == name:
            rendered.append(f"{name}={value}")
            replaced = True
            continue
        rendered.append(line)
    if not replaced:
        rendered.append(f"{name}={value}")
    directory = path.parent
    if not directory.is_dir():
        raise AssistantKeyError(f"registered tenant environment directory is missing: {directory}")
    descriptor, temporary = tempfile.mkstemp(prefix=".tenant-env-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(rendered).rstrip("\n") + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _accepted_by_worker(values: Mapping[str, str], token_env: str) -> bool:
    """A key is staged only into an environment the release gate would accept."""
    return bool(values.get("PAYLOAD_SECRET")) and bool(values.get(str(token_env or "").strip()))


def plan(
    tenant_id: str,
    tenant_env_path: Path,
    *,
    limit_usd: float,
    token: str,
    token_env: str = "",
    transport: openrouter.Transport | None = None,
) -> dict[str, Any]:
    """Read-only: what provisioning would do for this tenant."""
    limit = float(limit_usd)
    if limit <= 0:
        raise AssistantKeyError("assistant key limit must be positive")
    name = key_name(tenant_id)
    existing_env = _read_env(tenant_env_path)
    if not _accepted_by_worker(existing_env, token_env):
        raise AssistantKeyError(
            "the registered tenant environment is incomplete; register the tenant before provisioning its assistant"
        )
    keys = openrouter.list_keys(token, transport=transport)
    matches = [entry for entry in keys if str(entry.get("name") or "") == name]
    if len(matches) > 1:
        raise AssistantKeyError(f"provider has {len(matches)} keys named {name}; reconcile them before provisioning")
    present = bool(existing_env.get(ASSISTANT_KEY_ENV))
    current = matches[0] if matches else None
    return {
        "tenant": str(tenant_id),
        "keyName": name,
        "limitUsd": limit,
        "providerKey": {
            "exists": current is not None,
            "limit": current.get("limit") if current else None,
            "usage": current.get("usage") if current else None,
            "disabled": current.get("disabled") if current else None,
        },
        "workerBinding": {"present": present, "delivered": present and _accepted_by_worker(existing_env, token_env)},
        "action": "reuse" if current is not None else "create",
    }


def apply(
    tenant_id: str,
    tenant_env_path: Path,
    *,
    limit_usd: float,
    token: str,
    token_env: str = "",
    transport: openrouter.Transport | None = None,
) -> dict[str, Any]:
    """Create the provider key when it is absent and stage it for the next release."""
    summary = plan(tenant_id, tenant_env_path, limit_usd=limit_usd, token=token, token_env=token_env,
                   transport=transport)
    if summary["action"] == "create":
        created = openrouter.create_key(token, name=summary["keyName"], limit_usd=float(limit_usd), transport=transport)
        _write_env(tenant_env_path, ASSISTANT_KEY_ENV, str(created["key"]).strip())
        summary["action"] = "created"
        summary["staged"] = True
    else:
        # The provider keeps the ceiling; rewriting the tenant environment would
        # need a release for nothing.
        summary["staged"] = False
    return summary


def write_receipt(data_dir: Path, tenant_id: str, summary: Mapping[str, Any]) -> Path:
    """Persist a secret-free record of what provisioning did."""
    run_id = secrets.token_hex(8)
    directory = Path(data_dir).expanduser().resolve() / "assistant-provisioning" / run_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    path = directory / "receipt.json"
    payload = dict(summary)
    payload["tenant"] = str(tenant_id)
    payload["receiptId"] = run_id
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path
