"""reddit.py — read-only Reddit sense.

Ported from Ada's reddit.py with the commenting/OAuth/ledger machinery
removed entirely: site-agent only READS. Subreddits come free via RSS
(https://www.reddit.com/r/<sub>/.rss), no API key needed.
"""

from __future__ import annotations

import time
from typing import Any

import feedparser

from .base import Item, published_ts

_UA = "site-agent/0.1 (read-only RSS reader)"
_BETWEEN_SOURCES = 4      # seconds between subreddits — Reddit throttles bursts
_RETRY_WAITS = (20, 40)   # backoff when Reddit answers 429


def _parse(url: str):
    """Fetch a feed, backing off twice on Reddit's 429 rate limit."""
    parsed = feedparser.parse(url, agent=_UA)
    for wait in _RETRY_WAITS:
        if getattr(parsed, "status", 200) != 429:
            return parsed
        time.sleep(wait)
        parsed = feedparser.parse(url, agent=_UA)
    return parsed


def subreddit_url(entry: str | dict[str, Any]) -> tuple[str, str]:
    """Return (name, rss_url) from a config entry that is 'freediving'
    or {name, url}."""
    if isinstance(entry, str):
        sub = entry.strip().lstrip("r/").strip()
        return sub, f"https://www.reddit.com/r/{sub}/.rss" if sub else ("", "")
    name = str(entry.get("name", "")).strip().lstrip("r/").strip()
    url = str(entry.get("url", "") or f"https://www.reddit.com/r/{name}/.rss")
    return name, url


def fetch_subreddits(entries: list[str | dict[str, Any]], limit_per_source: int = 15) -> list[Item]:
    items: list[Item] = []
    for idx, entry in enumerate(entries):
        if idx:
            time.sleep(_BETWEEN_SOURCES)
        name, url = subreddit_url(entry)
        if not url:
            continue
        try:
            parsed = _parse(url)
            for raw in parsed.entries[:limit_per_source]:
                items.append(
                    Item(
                        title=str(getattr(raw, "title", "")).strip(),
                        summary=str(getattr(raw, "summary", "") or ""),
                        link=str(getattr(raw, "link", "")),
                        source=f"reddit/{name}" if name else "reddit",
                        published=published_ts(raw),
                    )
                )
        except Exception as exc:  # noqa: BLE001 — a dead feed must not kill the digest
            items.append(Item(title=f"[feed error] {name}: {exc}", summary="", link="", source="error"))
    return items
