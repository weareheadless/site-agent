"""Canonical public paths for Payload articles."""

from __future__ import annotations

from typing import Any


def public_article_path(slug: Any) -> str:
    """Return the one public route used by the shared Payload renderer."""
    normalized = str(slug or "").strip().strip("/")
    return f"/blog/{normalized}" if normalized else ""
