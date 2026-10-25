"""Shared repository path policy for editor proposals and builders."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from ..frontend_ownership import (
    CRAWL_METADATA_PATTERNS,
    is_crawl_metadata_path,
    is_frontend_owned_path,
)


def source_authoring_contract(config: dict[str, Any]) -> dict[str, Any]:
    from ..frontend_ownership import (
        FRONTEND_OWNED_PATTERNS,
        PLATFORM_PROTECTED_PATHS,
    )

    frontend_only = (config.get('design_engine') or {}).get('build_profile') == 'next_react'
    configured_patterns = list((config.get('site') or {}).get('writable_patterns') or [])
    # Crawl metadata is a narrow shared source capability for Next sites. Make
    # it explicit in the contract sent to Ada and delegated editors, without
    # widening the tenant's general configured source allowlist.
    authoring_patterns = list(dict.fromkeys(
        configured_patterns + (list(CRAWL_METADATA_PATTERNS) if frontend_only else [])
    ))
    return {
        'configured_patterns': authoring_patterns,
        'tenant_configured_patterns': configured_patterns,
        'crawl_metadata_patterns': list(CRAWL_METADATA_PATTERNS) if frontend_only else [],
        'crawl_metadata_rule': (
            'For crawl/discovery requests, exact robots and sitemap route/static files are writable. '
            'Keep origin resolution in the selected metadata file; do not edit shared helpers.'
            if frontend_only else ''
        ),
        'frontend_only': frontend_only,
        'frontend_patterns': list(FRONTEND_OWNED_PATTERNS) if frontend_only else [],
        'protected_paths': list(PLATFORM_PROTECTED_PATHS) if frontend_only else list(HARD_DENY),
        'rule': (
            'A source path must pass the configured tenant allowlist and tenant ownership policy. '
            'For Next sites, exact crawl metadata files listed in crawl_metadata_patterns are a '
            'narrow exception to the tenant allowlist. Platform changes require a shared Site-Agent release.'
        ),
    }


def source_path_allowed(config: dict[str, Any], path: str) -> bool:
    contract = source_authoring_contract(config)
    clean = normalize_path(path)
    if not clean:
        return False
    if contract['frontend_only']:
        crawl_path = is_crawl_metadata_path(clean)
        if not is_frontend_owned_path(clean) and not crawl_path:
            return False
    return writable(clean, contract['configured_patterns'])


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
