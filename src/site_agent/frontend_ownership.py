"""The one boundary between platform source and the tenant's own website.

A managed site is a real repository, authored by the owner together with the
coding agent. Everything in it belongs to the tenant except the platform: the
Payload schema, migrations, admin and authentication, the shared HelloAda
bridge and runtime, package pins and build/runtime configuration, the shared
scaffold's route shell, and every file the shared-runtime release overwrites.

This is deliberately a deny list. The previous positive allowlist described the
default scaffold's presentation surface, so a tenant whose composition replaced
that scaffold - its own routes, sections and content modules - was refused its
own source, while the agent's instructions told it to edit the repository. One
list, one decision, used by Ada's chat and build sandbox, the source editor,
design candidates, the compiled-preview gate and owner-facing frontend restores.
"""

from __future__ import annotations

from pathlib import PurePosixPath


# A source-authored site is a whole repository the owner owns, so the pattern
# form of the authoring boundary is "everything"; PLATFORM_PROTECTED_PATHS is
# the part that is not.
PRESENTATION_SOURCE_PATTERNS: tuple[str, ...] = ("**",)

# The shared scaffold's presentation surfaces. This is the design-run allowlist
# inside a generated site whose pages render through the host-owned Payload
# route shell; it is deliberately NOT the tenant's ownership boundary. A tenant
# that replaced the scaffold with its own composition owns far more than this.
SCAFFOLD_PRESENTATION_PATTERNS: tuple[str, ...] = (
    "src/app/(frontend)/*.css",
    # The tab icon is a brand asset served at the site root, where every browser
    # and every route finds it without a link from a particular page's chrome.
    "public/favicon.ico",
    "src/components/site/presentation/**",
    "src/components/site/TenantChrome.tsx",
    "public/site/**",
    "public/fonts/**",
)

# A separate, exact capability: Growth may propose a crawl/discovery change and
# that change is the exact robots/sitemap implementation. These paths are also
# ordinary presentation source for the tenant; the list exists so a crawl
# capability names the files it may touch.
CRAWL_METADATA_PATTERNS: tuple[str, ...] = (
    "src/app/robots.ts",
    "src/app/sitemap.ts",
    "src/app/robots.txt/route.ts",
    "src/app/sitemap.xml/route.ts",
    "public/robots.txt",
    "public/sitemap.xml",
)

# Host-only first-site preparation; these remain forbidden to Ada's editor.
INITIAL_LOCALE_RUNTIME_PATHS: tuple[str, ...] = (
    "src/middleware.ts", "src/lib/locale-routing.ts", "src/lib/request-locale.ts", "src/lib/content.ts",
    "src/app/(frontend)/layout.tsx", "src/components/SiteChrome.tsx",
)

PLATFORM_PROTECTED_PATHS: tuple[str, ...] = (
    # Repository, toolchain and runtime configuration.
    ".env", ".github", ".gitignore", "AGENTS.md", "node_modules", ".next", ".open-next", "out",
    "package.json", "package-lock.json", "next.config.mjs", "next.config.js", "next.config.ts",
    "tsconfig.json", "eslint.config.mjs", "payload.config.ts", "open-next.config.ts", "wrangler.jsonc",
    "src/middleware.ts", "src/lib/workspace-preview-path.ts", "src/helloada.config.ts",
    ".helloada-managed.json", "helloada-content-contract.json", "template-manifest.json",
    "worker.ts", "scripts", "tests", "packages",
    # Payload schema, admin and authentication.
    "src/collections", "src/globals", "src/migrations", "src/payload-types.ts",
    "src/app/(payload)", "src/app/api", "src/components/admin", "src/lib/content.ts",
    # The shared HelloAda bridge and runtime, including every file the
    # shared-runtime release copies into a tenant build.
    "mailflare-bindings.ts", "mailflare-booking-service.ts", "mailflare-owner-gate.ts",
    "mailflare-payload-migration.ts", "mailflare-provisioning.ts", "mailflare-runtime.ts",
    "src/lib/atelier",
    "src/lib/cloudflare-context.ts", "src/lib/content-routes.ts", "src/lib/growth-contract.ts",
    "src/lib/growth-operations.ts", "src/lib/helloada-admin-entry.ts", "src/lib/helloada-auth.ts",
    "src/lib/helloada-form-runtime.ts", "src/lib/helloada-handoff.ts",
    "src/lib/helloada-preview-claims.ts", "src/lib/helloada-preview-renderer.tsx",
    "src/lib/helloada-preview.ts", "src/lib/helloada-runtime.ts", "src/lib/helloada-upstream.ts",
    "src/lib/mail-alerts.ts", "src/lib/mailflare-inbox.ts", "src/lib/mailflare-provisioning-api.ts",
    "src/lib/message-notifications.ts", "src/lib/message-processing.ts", "src/lib/messages-api.ts",
    "src/lib/messages-service.ts", "src/lib/owner-message-draft-hash.ts", "src/lib/calendar.ts",
    "src/lib/payload-field-match.ts", "src/lib/payload-hash.ts", "src/lib/payload-locale.ts",
    "src/lib/payload-revision.ts", "src/lib/payload-versions.ts", "src/lib/public-content-route.ts",
    "src/lib/public-revision.ts", "src/lib/runtime-env.ts", "src/lib/service-auth.ts",
    "src/lib/site-config.ts", "src/lib/static-website.ts",
    "src/components/platform", "src/components/PublicDocument.tsx", "src/components/SiteChrome.tsx",
    "src/components/BlogIndex.tsx", "src/components/site/TenantSections.tsx",
    # The shared scaffold's route shell: every managed page renders through it.
    "src/app/(frontend)/layout.tsx", "src/app/(frontend)/[[...slug]]/page.tsx",
    "src/app/(frontend)/[...slug]/page.tsx", "src/app/(frontend)/articles",
    "src/app/(frontend)/helloada-preview",
    # Platform brand assets shipped into the tenant repository.
    "public/brand",
)


def is_frontend_owned_path(path: str) -> bool:
    """True when a valid tenant-relative path belongs to the tenant's website."""
    raw = str(path or "").replace("\\", "/")
    normalized = PurePosixPath(raw).as_posix()
    parts = PurePosixPath(normalized).parts
    if not normalized or normalized.startswith("/") or ".." in parts or "." in parts:
        return False
    return not any(
        normalized == protected or normalized.startswith(protected.rstrip("/") + "/")
        for protected in PLATFORM_PROTECTED_PATHS
    )


def is_crawl_metadata_path(path: str) -> bool:
    """Return true only for exact root robots/sitemap files on Next sites."""
    raw = str(path or "").replace("\\", "/")
    normalized = PurePosixPath(raw).as_posix()
    parts = PurePosixPath(normalized).parts
    if not normalized or normalized.startswith("/") or ".." in parts or "." in parts:
        return False
    return normalized in CRAWL_METADATA_PATTERNS
