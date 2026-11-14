"""What the running platform release says about the runtime it ships.

A tenant deploy must build exactly the shared runtime the platform is running,
so the platform has to be able to name it. The API release writes this file at
build time from the same source it installed; the deploy intake reads it back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

IDENTITY_FILE = "runtime-identity.json"
_SHA = re.compile(r"[0-9a-f]{40}")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


class RuntimeIdentityError(RuntimeError):
    """The running platform release cannot name the runtime it ships."""


def runtime_identity(release_root: Path) -> dict[str, Any]:
    """Return the source SHA and shared-runtime fingerprint of one API release."""
    try:
        value = json.loads((Path(release_root) / IDENTITY_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeIdentityError(
            "this platform release does not declare the shared runtime it ships; release the API again"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeIdentityError("the platform runtime identity is not an object")
    source_sha = str(value.get("sourceSha") or "")
    fingerprint = str(value.get("sharedRuntimeFingerprint") or "")
    if not _SHA.fullmatch(source_sha) or not _FINGERPRINT.fullmatch(fingerprint):
        raise RuntimeIdentityError("the platform runtime identity is incomplete")
    return {"sourceSha": source_sha, "sharedRuntimeFingerprint": fingerprint}


__all__ = ["IDENTITY_FILE", "RuntimeIdentityError", "runtime_identity"]
