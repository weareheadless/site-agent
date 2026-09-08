"""Pelican-backed blog content helpers.

Pelican treats Markdown files and their frontmatter as the blog database.  The
agent therefore only needs to commit one article file; archives, categories,
feeds and pagination are derived by the site's Pelican build.
"""

from __future__ import annotations

import datetime as _datetime
import re
from pathlib import PurePosixPath
from typing import Any


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


def _clean_title(value: Any) -> str:
    """Remove quote characters an LLM may wrap around an article title."""
    title = str(value or "").strip()
    pairs = (("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”"))
    while len(title) >= 2 and any(
        title.startswith(left) and title.endswith(right) for left, right in pairs
    ):
        title = title[1:-1].strip()
    return title


def _without_leading_title_heading(content: str, title: str) -> str:
    """The article template renders the title; keep it out of article content."""
    lines = content.splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    if not first.startswith("#"):
        return content
    heading = re.sub(r"^#{1,6}[ \t]+", "", first)
    heading = re.sub(r"[ \t]+#+[ \t]*$", "", heading)
    if _clean_title(heading).casefold() != _clean_title(title).casefold():
        return content
    return "\n".join(lines[1:]).lstrip()


def _frontmatter(config: dict[str, Any], title: str, meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = meta or {}
    today = _datetime.date.today().isoformat()
    slug = str(meta.get("slug") or "").strip()
    data: dict[str, Any] = {
        "Title": _clean_title(title),
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


def _metadata_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def document(config: dict[str, Any], title: str, body: str, meta: dict[str, Any] | None = None) -> bytes:
    """Return a Pelican-compatible Markdown document with plain metadata."""
    metadata = _frontmatter(config, title, meta)
    frontmatter = "\n".join(
        f"{key}: {_metadata_value(value)}"
        for key, value in metadata.items()
        if value not in (None, "", [])
    )
    content = _without_leading_title_heading((body or "").strip(), metadata["Title"])
    return f"---\n{frontmatter}\n---\n\n{content}\n".encode("utf-8")


def build_command(config: dict[str, Any]) -> str:
    """Return the configured Cloudflare/local build command."""
    return str(
        settings(config).get(
            "build_command",
            "pelican content -o output -s pelicanconf.py",
        )
    )
