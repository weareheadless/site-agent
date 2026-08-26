"""senses package — what Ada reads: Reddit RSS, generic feeds, GA4."""

from __future__ import annotations

from typing import Any

from .base import Item, canonical_link, score_item, strip_html
from .reddit import fetch_subreddits
from .rss import fetch_feeds


def collect(config: dict[str, Any], max_total: int = 25) -> list[Item]:
    sources = config.get("sources") or {}
    items: list[Item] = []
    if sources.get("subreddits"):
        items.extend(fetch_subreddits(sources["subreddits"]))
    if sources.get("rss_feeds"):
        items.extend(fetch_feeds(sources["rss_feeds"]))
    keywords = [str(k) for k in (sources.get("keywords") or [])]
    if keywords:
        for item in items:
            score_item(item, keywords)
    return items[:max_total]


__all__ = ["Item", "canonical_link", "collect", "fetch_feeds", "fetch_subreddits", "score_item", "strip_html"]
