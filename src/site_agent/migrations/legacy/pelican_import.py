"""Parse legacy Pelican Markdown without importing or running Pelican.

The importer is deliberately a pure data transform. It produces Payload-shaped
records and explicit redirect candidates; writing to D1/R2 remains a separate,
reviewed migration step owned by the customer bootstrap workflow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class MigrationError(ValueError):
    """Legacy content cannot be mapped safely into the Payload contract."""


@dataclass(frozen=True)
class MigrationBundle:
    documents: tuple[dict[str, Any], ...]
    redirects: tuple[dict[str, str], ...]
    rejected: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents": [dict(item) for item in self.documents],
            "redirects": [dict(item) for item in self.redirects],
            "rejected": [dict(item) for item in self.rejected],
            "counts": {
                "documents": len(self.documents),
                "redirects": len(self.redirects),
                "rejected": len(self.rejected),
            },
        }


_FRONTMATTER = re.compile(r"\A---\s*\n(?P<header>.*?)(?:\n---\s*\n|\Z)(?P<body>.*)\Z", re.S)
_TITLE_HEADING = re.compile(r"\A#{1,6}\s+(.+?)(?:\s+#+)?\s*\Z")


def _value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        return [part.strip().strip("'\"") for part in value[1:-1].split(",") if part.strip()]
    if "," in value:
        return [part.strip() for part in value.split(",") if part.strip()]
    return value.strip("'\"")


def _parse(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MigrationError(f"could not read {path}: {exc}") from exc
    match = _FRONTMATTER.match(raw)
    if not match:
        return {}, raw.strip()
    metadata: dict[str, Any] = {}
    for line in match.group("header").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().casefold()] = _value(value)
    body = match.group("body").strip()
    title = str(metadata.get("title") or "").strip()
    heading = _TITLE_HEADING.match(body.splitlines()[0].strip()) if body else None
    if not title and heading:
        title = heading.group(1).strip()
    if heading and title and heading.group(1).strip().casefold() == title.casefold():
        body = "\n".join(body.splitlines()[1:]).lstrip()
    if title:
        metadata["title"] = title
    return metadata, body


def _slug(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip().strip("/")
    raw = re.sub(r"[^a-zA-Z0-9/_-]+", "-", raw).strip("-")
    raw = re.sub(r"/{2,}", "/", raw)
    if not raw or any(part in {".", ".."} for part in raw.split("/")):
        raise MigrationError("invalid legacy slug")
    return raw.lower()


def _record(path: Path, root: Path, collection: str, route_prefix: str) -> tuple[dict[str, Any], dict[str, str]]:
    metadata, body = _parse(path)
    slug = _slug(metadata.get("slug"), path.stem)
    title = str(metadata.get("title") or slug.replace("-", " ").title()).strip()
    route = "/" if collection == "pages" and slug in {"index", "home"} else f"/{route_prefix.strip('/')}/{slug}".replace("//", "/")
    relative = path.relative_to(root).as_posix()
    data: dict[str, Any] = {
        "title": title,
        "slug": slug,
        "summary": str(metadata.get("summary") or metadata.get("description") or "").strip(),
        "body": body,
        "published": str(metadata.get("status") or "published").casefold() not in {"draft", "unpublished"},
        "legacyPath": relative,
    }
    if metadata.get("date"):
        data["publishedAt"] = str(metadata["date"])
    if metadata.get("author"):
        data["author"] = str(metadata["author"])
    legacy_route = "/index.html" if route == "/" else f"/{route_prefix.strip('/') + '/' if route_prefix else ''}{slug}.html"
    return {"collection": collection, "data": data}, {"from": legacy_route.replace('//', '/'), "to": route}


def import_pelican_tree(root: str | Path) -> MigrationBundle:
    """Read `content/pages` and `content/articles` into a reviewable bundle."""
    source = Path(root).expanduser().resolve()
    content = source / "content"
    if not content.is_dir():
        raise MigrationError(f"legacy content directory is unavailable: {content}")
    documents: list[dict[str, Any]] = []
    redirects: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    routes: set[str] = set()
    locations = ((content / "pages", "pages", ""), (content / "articles", "posts", "articles"))
    for directory, collection, route_prefix in locations:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            try:
                document, redirect = _record(path, source, collection, route_prefix)
                route = redirect["from"]
                if route in routes:
                    raise MigrationError(f"duplicate legacy route: {route}")
                routes.add(route)
                documents.append(document)
                redirects.append(redirect)
            except MigrationError as exc:
                rejected.append({"path": path.relative_to(source).as_posix(), "reason": str(exc)})
    return MigrationBundle(tuple(documents), tuple(redirects), tuple(rejected))
