"""Shared repository path policy for editor proposals and builders."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from ..frontend_ownership import is_frontend_owned_path


def source_authoring_contract(config: dict[str, Any]) -> dict[str, Any]:
    from ..frontend_ownership import FRONTEND_OWNED_PATTERNS, PLATFORM_PROTECTED_PATHS

    frontend_only = (config.get('design_engine') or {}).get('build_profile') == 'next_react'
    return {
        'configured_patterns': list((config.get('site') or {}).get('writable_patterns') or []),
        'frontend_only': frontend_only,
        'frontend_patterns': list(FRONTEND_OWNED_PATTERNS) if frontend_only else [],
        'protected_paths': list(PLATFORM_PROTECTED_PATHS) if frontend_only else list(HARD_DENY),
        'rule': 'A source path must pass both the configured allowlist and the frontend ownership policy. Platform changes require a shared Site-Agent release.',
    }


def source_path_allowed(config: dict[str, Any], path: str) -> bool:
    contract = source_authoring_contract(config)
    return writable(path, contract['configured_patterns'], frontend_only=contract['frontend_only'])


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


def writable(
    path: str,
    patterns: list[str],
    *,
    allowed_hard_denied_paths: set[str] | None = None,
    frontend_only: bool = False,
) -> bool:
    """Check the configured allowlist after path normalization."""
    clean = normalize_path(path)
    if frontend_only and not is_frontend_owned_path(clean):
        return False
    exceptions = allowed_hard_denied_paths or set()
    if not clean or any(denied in clean and clean not in exceptions for denied in HARD_DENY):
        return False
    return any(fnmatch.fnmatch(clean, pattern) for pattern in patterns)
