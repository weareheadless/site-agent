"""Shared repository path policy for editor proposals and builders."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath


HARD_DENY = (
    "admin.html", ".env", ".github/", "CNAME", "package.json", "wrangler.",
    "node_modules/",
)


def normalize_path(path: str) -> str:
    """Return a safe relative POSIX path, or an empty string when invalid."""
    raw = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        return ""
    parts = PurePosixPath(raw).parts
    if any(part in ("", ".", "..") for part in parts):
        return ""
    return "/".join(parts)


def writable(path: str, patterns: list[str], *, allowed_hard_denied_paths: set[str] | None = None) -> bool:
    """Check the configured allowlist after path normalization."""
    clean = normalize_path(path)
    exceptions = allowed_hard_denied_paths or set()
    if not clean or any(denied in clean and clean not in exceptions for denied in HARD_DENY):
        return False
    return any(fnmatch.fnmatch(clean, pattern) for pattern in patterns)
