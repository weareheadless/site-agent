"""Shared repository path policy for editor proposals and builders."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from ..frontend_ownership import is_frontend_owned_path


def source_authoring_contract(config: dict[str, Any]) -> dict[str, Any]:
    from ..frontend_ownership import PLATFORM_PROTECTED_PATHS, PRESENTATION_SOURCE_PATTERNS

    frontend_only = (config.get('design_engine') or {}).get('build_profile') == 'next_react'
    configured_patterns = list((config.get('site') or {}).get('writable_patterns') or [])
    # A source-authored Next site is a whole repository the owner owns, so the
    # enforced allowlist is everything and PLATFORM_PROTECTED_PATHS is the
    # boundary. A pattern list cannot describe a composition the tenant
    # replaced with its own routes and content modules; the shipped default
    # list only described the scaffold. Workspaces without that profile keep
    # their configured allowlist.
    patterns = list(PRESENTATION_SOURCE_PATTERNS) if frontend_only else configured_patterns
    if frontend_only:
        rule = (
            'This repository is yours to author. Every path is editable except protected_paths, '
            'which are host-owned platform source: Payload schema, migrations, admin and '
            'authentication, the HelloAda bridge and runtime, package pins, build and runtime '
            'configuration, and the shared route shell. A platform change requires a shared '
            'Site-Agent release.'
        )
    else:
        rule = (
            'A source path must match the configured tenant allowlist. Platform changes '
            'require a shared Site-Agent release.'
        )
    return {
        'configured_patterns': patterns,
        'frontend_only': frontend_only,
        'protected_paths': list(PLATFORM_PROTECTED_PATHS) if frontend_only else list(HARD_DENY),
        'rule': rule,
    }


# What the platform itself commits to a site's branch after an approval: the
# fleet-installed workflow bytes and the canonical presentation check they run.
# None of it decides anything an owner sees, so a branch that only moved by
# these files has not moved past the change it carries.
RELEASE_MATERIAL_PATHS = (".github/", "scripts/check-presentation.mjs")


def is_release_material(path: str) -> bool:
    """True when a path is the platform's release machinery, not site work."""
    clean = normalize_path(path)
    if not clean:
        return False
    return any(
        clean == prefix or (prefix.endswith("/") and clean.startswith(prefix))
        for prefix in RELEASE_MATERIAL_PATHS
    )


def source_path_allowed(config: dict[str, Any], path: str) -> bool:
    contract = source_authoring_contract(config)
    clean = normalize_path(path)
    if not clean:
        return False
    return writable(
        clean,
        contract['configured_patterns'],
        frontend_only=contract['frontend_only'],
    )


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
