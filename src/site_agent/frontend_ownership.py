"""The single allowlist for tenant-owned presentation files.

Platform/schema/admin/auth/runtime source is intentionally absent. This list is
shared by Ada's editor, design candidates and owner-facing frontend restores.
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath


FRONTEND_OWNED_PATTERNS: tuple[str, ...] = (
    "src/app/(frontend)/*.css",
    "src/components/site/presentation/**",
    "src/components/site/TenantChrome.tsx",
    "public/site/**",
    "public/fonts/**",
)

# A separate, exact capability: crawl/discovery metadata may be authored on
# Next sites without making it general frontend ownership for restores/builds.
CRAWL_METADATA_PATTERNS: tuple[str, ...] = (
    "src/app/robots.ts",
    "src/app/sitemap.ts",
    "src/app/robots.txt/route.ts",
    "src/app/sitemap.xml/route.ts",
    "public/robots.txt",
    "public/sitemap.xml",
)

PLATFORM_PROTECTED_PATHS: tuple[str, ...] = (
    "src/middleware.ts", "src/lib/workspace-preview-path.ts",
    ".env", ".github", "node_modules", ".next", ".open-next", "out",
    "package.json", "package-lock.json", "next.config.mjs", "next.config.js", "next.config.ts",
    "tsconfig.json", "eslint.config.mjs", "payload.config.ts", "open-next.config.ts", "wrangler.jsonc",
    "src/app/api", "src/app/(payload)", "src/app/(frontend)/layout.tsx",
    "src/app/(frontend)/[[...slug]]/page.tsx", "src/app/(frontend)/articles",
    "src/collections", "src/globals", "src/migrations", "src/lib/content.ts",
    "src/lib/helloada-auth.ts", "src/lib/helloada-upstream.ts", "src/lib/growth-contract.ts",
    "src/components/admin", "src/components/PublicDocument.tsx", "src/components/SiteChrome.tsx",
    "src/components/BlogIndex.tsx", "src/components/platform", "src/components/site/TenantSections.tsx",
    "src/payload-types.ts", "public/brand",
    "helloada-content-contract.json", "template-manifest.json",
)


def is_frontend_owned_path(path: str) -> bool:
    """Return true only for a normalized path explicitly owned by the tenant."""
    raw = str(path or "").replace("\\", "/")
    normalized = PurePosixPath(raw).as_posix()
    parts = PurePosixPath(normalized).parts
    if not normalized or normalized.startswith("/") or ".." in parts or "." in parts:
        return False
    if any(
        normalized == protected or normalized.startswith(protected.rstrip("/") + "/")
        for protected in PLATFORM_PROTECTED_PATHS
    ):
        return False
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in FRONTEND_OWNED_PATTERNS)


def is_crawl_metadata_path(path: str) -> bool:
    """Return true only for exact root robots/sitemap files on Next sites."""
    raw = str(path or "").replace("\\", "/")
    normalized = PurePosixPath(raw).as_posix()
    parts = PurePosixPath(normalized).parts
    if not normalized or normalized.startswith("/") or ".." in parts or "." in parts:
        return False
    return normalized in CRAWL_METADATA_PATTERNS
