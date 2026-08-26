"""Pelican-backed blog content helpers.

Pelican treats Markdown files and their frontmatter as the blog database.  The
agent therefore only needs to commit one article file; archives, categories,
feeds and pagination are derived by the site's Pelican build.
"""

from __future__ import annotations

import datetime as _datetime
from pathlib import PurePosixPath
from typing import Any

import yaml


def settings(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("blog") or {}


def enabled(config: dict[str, Any]) -> bool:
    return str(settings(config).get("engine", "legacy")).lower() == "pelican"


def article_directory(config: dict[str, Any]) -> str:
    blog = settings(config)
    configured = str(blog.get("articles_dir", "content/articles")).strip()
    return configured.strip("/") or "content/articles"


def article_path(config: dict[str, Any], slug: str) -> str:
    safe_slug = slug.strip().strip("/")
    if not safe_slug or "/" in safe_slug or "\\" in safe_slug or safe_slug in (".", ".."):
        raise ValueError("invalid article slug")
    return str(PurePosixPath(article_directory(config)) / f"{safe_slug}.md")


def _frontmatter(config: dict[str, Any], title: str, meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = meta or {}
    today = _datetime.date.today().isoformat()
    slug = str(meta.get("slug") or "").strip()
    data: dict[str, Any] = {
        "Title": title.strip(),
        "Date": str(meta.get("date") or today),
        "Status": str(meta.get("status") or "published"),
    }
    if slug:
        data["Slug"] = slug
    for source, target in (
        ("summary", "Summary"),
        ("description", "Summary"),
        ("author", "Author"),
        ("category", "Category"),
        ("tags", "Tags"),
        ("image", "Image"),
        ("canonical", "Canonical_URL"),
    ):
        value = meta.get(source)
        if value not in (None, "") and target not in data:
            data[target] = value
    site_url = str(settings(config).get("site_url") or "").strip()
    if site_url and "Canonical_URL" not in data:
        data["Canonical_URL"] = site_url.rstrip("/") + "/" + slug if slug else site_url
    return data


def document(config: dict[str, Any], title: str, body: str, meta: dict[str, Any] | None = None) -> bytes:
    """Return a Pelican-compatible Markdown document with deterministic YAML."""
    frontmatter = yaml.safe_dump(
        _frontmatter(config, title, meta),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    content = (body or "").strip()
    return f"---\n{frontmatter}\n---\n\n{content}\n".encode("utf-8")


def build_command(config: dict[str, Any]) -> str:
    """Return the configured Cloudflare/local build command."""
    return str(
        settings(config).get(
            "build_command",
            "pelican content -o output -s pelicanconf.py",
        )
    )
