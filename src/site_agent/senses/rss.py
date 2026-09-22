"""rss.py — generic RSS/Atom feeds (Ada's news.py, slimmed)."""

from __future__ import annotations

from typing import Any

import feedparser

from .base import Item, published_ts

_UA = "site-agent/0.1 (read-only RSS reader)"


def _fetch_feeds(
    feed_configs: list[dict[str, Any]],
    *,
    limit_per_source: int = 15,
    source_prefix: str = "rss",
) -> list[Item]:
    items: list[Item] = []
    for config in feed_configs:
        if isinstance(config, str):
            config = {"url": config}
        url = str(config.get("url", ""))
        if not url:
            continue
        name = str(config.get("name") or url)
        try:
            parsed = feedparser.parse(url, agent=_UA)
            for raw in parsed.entries[:limit_per_source]:
                items.append(
                    Item(
                        title=str(getattr(raw, "title", "")).strip(),
                        summary=str(getattr(raw, "summary", "") or ""),
                        link=str(getattr(raw, "link", "")),
                        source=f"{source_prefix}/{name}",
                        published=published_ts(raw),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            items.append(Item(title=f"[feed error] {name}: {exc}", summary="", link="", source="error"))
    return items


def fetch_feeds(feed_configs: list[dict[str, Any]], limit_per_source: int = 15) -> list[Item]:
    return _fetch_feeds(feed_configs, limit_per_source=limit_per_source, source_prefix="rss")


def fetch_community_feeds(feed_configs: list[dict[str, Any]], limit_per_source: int = 15) -> list[Item]:
    """Read configured forum/community feeds without assuming a platform or niche."""
    return _fetch_feeds(feed_configs, limit_per_source=limit_per_source, source_prefix="community")
