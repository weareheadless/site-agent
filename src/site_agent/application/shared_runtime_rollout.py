"""Plan deterministic fan-out of Site-Agent runtime releases to tenants."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_SHA = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_TENANT = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SUCCESS = {"deployed", "verified"}
_TERMINAL_FAILURE = {"failed", "interrupted"}


class SharedRuntimeRolloutError(RuntimeError):
    """A shared-runtime rollout cannot be planned from canonical evidence."""


def _receipt(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise SharedRuntimeRolloutError("release receipt must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise SharedRuntimeRolloutError("release receipt path is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SharedRuntimeRolloutError("release receipt is not valid JSON") from error
    if not isinstance(value, dict):
        raise SharedRuntimeRolloutError("release receipt root must be an object")
    return value


def _request_receipt(root: Path, tenant: str, request: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(request, Mapping):
        return None
    release_id = str(request.get("id") or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", release_id):
        raise SharedRuntimeRolloutError("queued release has an invalid receipt identity")
    return _receipt(root / "runs" / tenant / release_id / "receipt.json")


def _successful_receipts(root: Path, tenant: str) -> list[dict[str, Any]]:
    tenant_root = root / "runs" / tenant
    if tenant_root.is_symlink():
        raise SharedRuntimeRolloutError("tenant release receipt directory must not be a symlink")
    if not tenant_root.exists():
        return []
    if not tenant_root.is_dir():
        raise SharedRuntimeRolloutError("tenant release receipt path is not a directory")
    result: list[dict[str, Any]] = []
    for run in tenant_root.iterdir():
        if run.is_symlink() or not run.is_dir():
            raise SharedRuntimeRolloutError("tenant release history contains an unexpected filesystem object")
        value = _receipt(run / "receipt.json")
        if value and value.get("status") in _SUCCESS:
            if not _SHA.fullmatch(str(value.get("sourceSha") or "")):
                raise SharedRuntimeRolloutError("successful release receipt has no immutable source SHA")
            result.append(value)
    return sorted(result, key=lambda item: str(item.get("finishedAt") or ""), reverse=True)


def _release_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")
    return f"runtime-{timestamp}-{secrets.token_hex(4)}"


def plan_shared_runtime_rollout(
    registry: Mapping[str, Any],
    queue: Mapping[str, Any],
    release_root: Path,
    fingerprint: str,
    *,
    batch_size: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the next canary or bounded tenant batch without mutating state.

    Existing desired releases are never replaced while pending or after failure.
    Fan-out always reuses each tenant's latest successfully deployed source SHA.
    """
    if not _FINGERPRINT.fullmatch(str(fingerprint or "")):
        raise SharedRuntimeRolloutError("shared-runtime fingerprint must be a full SHA-256")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise SharedRuntimeRolloutError("runtime rollout batch size must be a positive integer")
    customers = registry.get("customers")
    releases = queue.get("releases")
    if not isinstance(customers, Mapping) or not isinstance(releases, Mapping):
        raise SharedRuntimeRolloutError("runtime rollout requires the canonical registry and release queue")

    canaries = sorted(
        tenant for tenant, customer in customers.items()
        if isinstance(customer, Mapping) and customer.get("sharedRuntimeUpdate") == "canary"
    )
    automatic = sorted(
        tenant for tenant, customer in customers.items()
        if isinstance(customer, Mapping) and customer.get("sharedRuntimeUpdate") == "automatic"
    )
    invalid_policies = [
        tenant for tenant, customer in customers.items()
        if not isinstance(customer, Mapping)
        or customer.get("sharedRuntimeUpdate", "manual") not in {"manual", "canary", "automatic"}
    ]
    if invalid_policies:
        raise SharedRuntimeRolloutError("tenant sharedRuntimeUpdate policy is invalid")
    if automatic and len(canaries) != 1:
        raise SharedRuntimeRolloutError("automatic runtime fan-out requires exactly one registered canary")
    if not automatic and not canaries:
        return {"state": "no-automatic-tenants", "canaryTenant": None, "queued": {}, "blocked": []}
    if len(canaries) != 1:
        raise SharedRuntimeRolloutError("runtime rollout requires exactly one registered canary")

    canary = canaries[0]
    if not _TENANT.fullmatch(canary):
        raise SharedRuntimeRolloutError("registered canary tenant identity is invalid")
    canary_history = _successful_receipts(release_root, canary)
    canary_has_target = any(
        item.get("sharedRuntimeFingerprint") == fingerprint for item in canary_history
    )
    queued: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []

    if not canary_has_target:
        current = releases.get(canary)
        current_receipt = _request_receipt(release_root, canary, current)
        if current_receipt and current_receipt.get("status") in _TERMINAL_FAILURE:
            return {
                "state": "canary-failed",
                "canaryTenant": canary,
                "queued": {},
                "blocked": [canary],
            }
        if (current and current_receipt is None
                and current.get("sharedRuntimeFingerprint") in (None, fingerprint)):
            return {
                "state": "canary-pending",
                "canaryTenant": canary,
                "queued": {},
                "blocked": [],
            }
        if not canary_history:
            return {
                "state": "canary-needs-first-release",
                "canaryTenant": canary,
                "queued": {},
                "blocked": [canary],
            }
        queued[canary] = {
            "id": _release_id(now),
            "sha": canary_history[0]["sourceSha"],
            "sharedRuntimeFingerprint": fingerprint,
        }
        return {
            "state": "canary-queued",
            "canaryTenant": canary,
            "queued": queued,
            "blocked": [],
        }

    for tenant in automatic:
        if not _TENANT.fullmatch(tenant):
            raise SharedRuntimeRolloutError("registered automatic tenant identity is invalid")
        history = _successful_receipts(release_root, tenant)
        if any(item.get("sharedRuntimeFingerprint") == fingerprint for item in history):
            continue
        current = releases.get(tenant)
        current_receipt = _request_receipt(release_root, tenant, current)
        if (current and current_receipt is None
                and current.get("sharedRuntimeFingerprint") in (None, fingerprint)):
            continue
        if current_receipt and current_receipt.get("status") in _TERMINAL_FAILURE:
            blocked.append(tenant)
            continue
        if not history:
            continue
        queued[tenant] = {
            "id": _release_id(now),
            "sha": history[0]["sourceSha"],
            "sharedRuntimeFingerprint": fingerprint,
        }
        if len(queued) == batch_size:
            break

    return {
        "state": "batch-queued" if queued else ("blocked" if blocked else "complete"),
        "canaryTenant": canary,
        "queued": queued,
        "blocked": blocked,
    }


__all__ = ["SharedRuntimeRolloutError", "plan_shared_runtime_rollout"]
