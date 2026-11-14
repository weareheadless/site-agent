"""Record the receipt a repository's own deploy run produced.

A credential-free deploy happens on the repository's runner, so the platform
never sees the run's files. The run reports the receipt it wrote; the platform
keeps it in the same immutable store the queued lane uses, which is what the
runtime activation reads.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

# A runner names its release after the GitHub run, which keeps it out of the
# queued lane's rel-/runtime- namespace and makes an accidental overwrite of a
# platform receipt impossible.
RUNNER_RELEASE_ID = re.compile(r"ci-\d{1,20}-\d{1,6}")
_SHA = re.compile(r"[0-9a-f]{40}")
_VERIFIED_STAGES = {
    "verify-deployment",
    "verify-connection",
    "awaiting-browser-verification",
    "verified",
}


class DeployReceiptError(RuntimeError):
    """A reported receipt does not prove the release it claims."""


def record_runner_receipt(
    release_root: Path,
    tenant: str,
    receipt: Any,
    *,
    source_sha: str,
    runtime_fingerprint: str,
) -> dict[str, Any]:
    """Keep one runner receipt, refusing anything the run cannot prove."""
    if not isinstance(receipt, Mapping):
        raise DeployReceiptError("the reported receipt is not an object")
    release_id = str(receipt.get("releaseId") or "")
    if not RUNNER_RELEASE_ID.fullmatch(release_id):
        raise DeployReceiptError("only a runner release receipt can be reported")
    if receipt.get("tenant") != tenant:
        raise DeployReceiptError("the reported receipt belongs to a different site")
    if not _SHA.fullmatch(source_sha) or receipt.get("sourceSha") != source_sha:
        raise DeployReceiptError("the reported receipt is not for this run's commit")
    if receipt.get("status") != "deployed" or receipt.get("stage") not in _VERIFIED_STAGES:
        raise DeployReceiptError("the reported receipt is not a deployed release")
    if receipt.get("sharedRuntimeFingerprint") != runtime_fingerprint:
        raise DeployReceiptError(
            "the release was built for a different shared runtime than the platform ships"
        )
    health = receipt.get("health")
    if not isinstance(health, Mapping) or health.get("releaseSha") != source_sha:
        raise DeployReceiptError("the reported receipt has no live health for this commit")
    if not isinstance(receipt.get("currentVerification"), Mapping):
        raise DeployReceiptError("the reported receipt has no verified Worker version")

    directory = Path(release_root) / "runs" / tenant / release_id
    path = directory / "receipt.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise DeployReceiptError("the stored release receipt is unreadable") from exc
        if not isinstance(existing, Mapping) or existing.get("sourceSha") != source_sha:
            raise DeployReceiptError("a different release already uses this run identity")
        return dict(existing)

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / f".receipt.{os.getpid()}.tmp"
    try:
        temporary.write_text(json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(receipt)


__all__ = ["DeployReceiptError", "RUNNER_RELEASE_ID", "record_runner_receipt"]
