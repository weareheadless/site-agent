"""Canonical Payload site scaffolding and isolated design experiments."""

from __future__ import annotations

import json
import shutil
import unicodedata
from pathlib import Path

from . import __version__


_GENERATED_TEMPLATE_ENTRIES = frozenset({
    ".next",
    ".open-next",
    ".turbo",
    ".wrangler",
    ".pytest_cache",
    ".cache",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
})


def payload_template_copy_ignore(_directory: str, names: list[str]) -> set[str]:
    """Keep local build output, caches and credentials out of tenant sources."""
    return {
        name for name in names
        if name in _GENERATED_TEMPLATE_ENTRIES
        or name == ".env"
        or name.startswith(".env.")
        or name.endswith((".tsbuildinfo", ".pyc"))
        or name == ".DS_Store"
    }


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def initialize_payload_site(directory: str | Path, name: str = "New Website", url: str = "") -> Path:
    """Materialize the canonical Next/Payload site template for a new tenant."""
    root = _copy_payload_template(directory)
    normalized_name = unicodedata.normalize("NFKD", str(name or "new-website")).encode("ascii", "ignore").decode("ascii")
    tenant_id = "-".join(
        part
        for part in "".join(character.lower() if character.isalnum() else "-" for character in normalized_name).split("-")
        if part
    )[:63] or "new-website"
    config_path = root / "src" / "helloada.config.ts"
    source = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        source.replace("'__HELLOADA_TENANT_ID__'", json.dumps(tenant_id))
        .replace("'__HELLOADA_SITE_NAME__'", json.dumps(str(name or "New Website").strip())),
        encoding="utf-8",
    )
    if url:
        wrangler = root / "wrangler.jsonc"
        if wrangler.is_file():
            source = wrangler.read_text(encoding="utf-8")
            source = source.replace('"__WORKER_URL__"', json.dumps(str(url).strip().rstrip("/")))
            wrangler.write_text(source, encoding="utf-8")
    wrangler = root / "wrangler.jsonc"
    if wrangler.is_file():
        source = wrangler.read_text(encoding="utf-8")
        source = source.replace('"__TENANT_ID__"', json.dumps(tenant_id))
        source = source.replace('"__SITE_NAME__"', json.dumps(str(name or "New Website").strip()))
        source = source.replace('"__SITE_AGENT_VERSION__"', json.dumps(__version__))
        wrangler.write_text(source, encoding="utf-8")
    return root


def initialize_managed_site(directory: str | Path, name: str = "New Website") -> Path:
    """Initialize the canonical managed baseline without inventing tenant identity."""
    del name
    return _copy_payload_template(directory)


def _copy_payload_template(directory: str | Path) -> Path:
    root = Path(directory).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"site directory is not empty: {root}")
    template = Path(__file__).resolve().parent / "templates" / "next-payload"
    if not template.is_dir():
        raise FileNotFoundError(f"canonical Payload template is unavailable: {template}")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, root, dirs_exist_ok=True, ignore=payload_template_copy_ignore)
    return root


_NEXT_VERSION = "16.3.4"
_GSAP_REACT_VERSION = "2.1.2"
_REACT_VERSION = "19.2.6"
_REACT_DOM_VERSION = "19.2.6"
_GSAP_VERSION = "3.12.5"
_TYPES_NODE_VERSION = "22.19.9"
_TYPES_REACT_VERSION = "19.2.14"
_TYPES_REACT_DOM_VERSION = "19.2.3"
_TYPESCRIPT_VERSION = "5.7.3"
_PAYLOAD_VERSION = "3.88.0"
_OPENNEXT_VERSION = "1.20.6"
_WRANGLER_VERSION = "4.130.0"
_ESLINT_VERSION = "9.16.0"
_ESLINT_CONFIG_NEXT_VERSION = "16.3.4"
_TYPESX_VERSION = "4.22.4"
_PRETTIER_VERSION = "3.6.2"
_CROSS_ENV_VERSION = "7.0.3"
_DOTENV_VERSION = "16.6.1"
_GRAPHQL_VERSION = "16.11.0"


def _package_manifest(name: str) -> dict[str, object]:
    """Return exact Next/React/Payload dependencies, with no visual defaults."""
    return {
        "name": f"ada-{name.lower().replace(' ', '-')}-site" if name else "ada-site",
        "private": True,
        "type": "module",
        "scripts": {
            "typecheck": "tsc --noEmit",
            "lint": "eslint .",
            "build": "next build",
            "dev": "next dev",
            "start": "next start",
        },
        "dependencies": {
            "@gsap/react": _GSAP_REACT_VERSION,
            "@opennextjs/cloudflare": _OPENNEXT_VERSION,
            "@payloadcms/db-d1-sqlite": _PAYLOAD_VERSION,
            "@payloadcms/next": _PAYLOAD_VERSION,
            "@payloadcms/richtext-lexical": _PAYLOAD_VERSION,
            "@payloadcms/storage-r2": _PAYLOAD_VERSION,
            "@payloadcms/translations": _PAYLOAD_VERSION,
            "@payloadcms/ui": _PAYLOAD_VERSION,
            "cross-env": _CROSS_ENV_VERSION,
            "dotenv": _DOTENV_VERSION,
            "graphql": _GRAPHQL_VERSION,
            "gsap": _GSAP_VERSION,
            "next": _NEXT_VERSION,
            "payload": _PAYLOAD_VERSION,
            "react": _REACT_VERSION,
            "react-dom": _REACT_DOM_VERSION,
        },
        "devDependencies": {
            "@types/node": _TYPES_NODE_VERSION,
            "@types/react": _TYPES_REACT_VERSION,
            "@types/react-dom": _TYPES_REACT_DOM_VERSION,
            "@eslint/eslintrc": "3.3.1",
            "eslint": _ESLINT_VERSION,
            "eslint-config-next": _ESLINT_CONFIG_NEXT_VERSION,
            "prettier": _PRETTIER_VERSION,
            "tsx": _TYPESX_VERSION,
            "typescript": _TYPESCRIPT_VERSION,
            "wrangler": _WRANGLER_VERSION,
        },
    }


def initialize_toolchain_workspace(directory: str | Path, name: str = "") -> Path:
    """Create a blank Next/React/Payload workspace for a new design experiment.

    This is intentionally not a site template: it creates only package/config
    metadata, a technical App Router entrypoint, and empty source directories.
    The first page, styles, copy, imagery, fonts, components, and motion are
    authored by the isolated model.
    """
    root = Path(directory).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"site directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    _write(root, "package.json", json.dumps(_package_manifest(str(name or "")), indent=2) + "\n")
    _write(root, "next.config.mjs", """/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
};

export default nextConfig;
""")
    _write(root, "tsconfig.json", """{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{"name": "next"}]
  },
  "include": ["next-env.d.ts", ".next/types/**/*.ts", "src/**/*.ts", "src/**/*.tsx"],
  "exclude": ["node_modules"]
}
""")
    _write(root, "next-env.d.ts", """/// <reference types="next" />
/// <reference types="next/image-types/global" />

// NOTE: This file should not be edited
""")
    _write(root, "eslint.config.mjs", """import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FlatCompat } from '@eslint/eslintrc';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const compat = new FlatCompat({ baseDirectory: __dirname });

export default [...compat.extends('next/core-web-vitals', 'next/typescript')];
""")
    _write(root, ".gitignore", """node_modules/
.next/
out/
.open-next/
.opencode/
.agent-home/
""")
    for relative in (
        "src/app/layout.tsx",
        "src/app/page.tsx",
        "src/components/.gitkeep",
        "src/styles/.gitkeep",
        "public/.gitkeep",
        "design/.gitkeep",
    ):
        _write(root, relative, "")
    _write(root, "src/app/layout.tsx", """import type { ReactNode } from 'react';

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
""")
    _write(root, "src/app/page.tsx", """export default function HomePage() {
  return null;
}
""")
    _write(root, "payload.config.ts", """import { buildConfig } from 'payload';

export default buildConfig({
  secret: process.env.PAYLOAD_SECRET || 'local-development-secret',
  collections: [],
});
""")
    return root


__all__ = ["initialize_payload_site", "initialize_toolchain_workspace"]
