"""Shared item model for feed-derived content.

Dedupe identity is ported from Ada's news.py: normalized-title hash plus a
canonical-link hash (tracking params stripped), so the same story arriving
from different feeds counts once.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref"}
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text)).strip()


def canonical_link(link: str) -> str:
    if not link:
        return ""
    parts = urlsplit(link.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_KEYS
    ]
    canonical = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower().removeprefix("www."),
            parts.path.rstrip("/"),
            urlencode(query),
            "",
        )
    )
    return hashlib.sha1(canonical.encode()).hexdigest() if canonical else ""


@dataclass
class Item:
    title: str
    summary: str
    link: str
    source: str
    published: int = 0
    score: float = 0.0
    matched: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        norm = " ".join(self.title.lower().split())
        return hashlib.sha1(norm.encode()).hexdigest()

    @property
    def link_id(self) -> str:
        return canonical_link(self.link)

    @property
    def identity_keys(self) -> set[str]:
        return {key for key in (self.id, self.link_id) if key}

    @property
    def clean_summary(self) -> str:
        return strip_html(self.summary)


def published_ts(entry: Any) -> int:
    for attr in ("published_parsed", "updated_parsed"):
        stamp = getattr(entry, attr, None)
        if stamp:
            try:
                return int(time.mktime(stamp))
            except (OverflowError, ValueError):
                pass
    return int(time.time())


def score_item(item: Item, keywords: list[str]) -> Item:
    text = f"{item.title} {item.clean_summary}".lower()
    matched = [keyword for keyword in keywords if keyword.lower() in text]
    item.matched = matched
    item.score = min(1.0, len(matched) / 4.0) if matched else 0.0
    return item
