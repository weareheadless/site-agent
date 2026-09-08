"""Bounded public RSS/Atom transport for incubation research."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit

import feedparser

from ..core.incubation_contracts import ResearchSource


class FeedDiscoveryError(ValueError):
    """A source failed the public feed policy or could not be read."""

    def __init__(self, message: str, *, code: str = "unavailable") -> None:
        super().__init__(message)
        self.code = code


class ResearchReader(Protocol):
    def read(self, source: ResearchSource) -> tuple["ResearchDocument", ...]:
        ...


@dataclass(frozen=True)
class ResearchDocument:
    source_id: str
    url: str
    title: str
    summary: str
    published_at: str | None
    content_hash: str


def canonical_public_url(value: str) -> str:
    """Validate a public URL before DNS or network access."""
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise FeedDiscoveryError("research URL must be a public HTTP(S) URL", code="invalid_url")
    if parsed.fragment:
        raise FeedDiscoveryError("research URL must not contain a fragment", code="invalid_url")
    hostname = parsed.hostname.rstrip(".").casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise FeedDiscoveryError("research URL has an invalid port", code="invalid_url") from exc
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise FeedDiscoveryError("research URL points to a private hostname", code="private_target")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast):
        raise FeedDiscoveryError("research URL points to a private address", code="private_target")
    host = f"[{hostname}]" if ":" in hostname else hostname
    return urlunsplit((parsed.scheme.lower(), host + (f":{port}" if port else ""), parsed.path or "/", parsed.query, ""))


def _resolved_public_host(hostname: str) -> None:
    """Reject obvious DNS rebinding targets without making local data visible."""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except OSError:
        return
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            raise FeedDiscoveryError("research URL resolves to a private address", code="private_target")


class _LimitedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self.count += 1
        if self.count > self.maximum:
            raise FeedDiscoveryError("research feed exceeded redirect limit", code="redirect_limit")
        canonical_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BoundedFeedReader:
    """Read public feeds with explicit byte, item, timeout, and redirect limits."""

    def __init__(self, *, timeout_seconds: float = 15.0, max_response_bytes: int = 1_000_000, max_items: int = 15, max_redirects: int = 3, opener: Any = None) -> None:
        self.timeout_seconds = max(0.1, min(float(timeout_seconds), 120.0))
        self.max_response_bytes = max(1_024, min(int(max_response_bytes), 16 * 1024 * 1024))
        self.max_items = max(1, min(int(max_items), 100))
        self.max_redirects = max(0, min(int(max_redirects), 10))
        self.opener = opener

    def _read_bytes(self, url: str) -> bytes:
        canonical = canonical_public_url(url)
        _resolved_public_host(urlsplit(canonical).hostname or "")
        handler = _LimitedRedirectHandler(self.max_redirects)
        opener = self.opener or urllib.request.build_opener(handler)
        request = urllib.request.Request(canonical, headers={"User-Agent": "site-agent/0.1 read-only incubation research"})
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > self.max_response_bytes:
                    raise FeedDiscoveryError("research feed response is too large", code="response_too_large")
                data = response.read(self.max_response_bytes + 1)
        except FeedDiscoveryError:
            raise
        except urllib.error.HTTPError as exc:
            code = {
                403: "private_or_quarantined",
                404: "not_found",
                429: "rate_limited",
            }.get(int(exc.code), "unavailable")
            raise FeedDiscoveryError(f"research feed fetch failed ({code})", code=code) from exc
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise FeedDiscoveryError("research feed fetch failed (unavailable)", code="unavailable") from exc
        if len(data) > self.max_response_bytes:
            raise FeedDiscoveryError("research feed response is too large", code="response_too_large")
        return data

    def read(self, source: ResearchSource) -> tuple[ResearchDocument, ...]:
        payload = self._read_bytes(source.feed_url)
        parsed = feedparser.parse(payload)
        documents: list[ResearchDocument] = []
        for entry in parsed.entries[: self.max_items]:
            title = _clean_text(getattr(entry, "title", ""), 500)
            summary = _clean_text(getattr(entry, "summary", "") or getattr(entry, "description", ""), 2_000)
            link = str(getattr(entry, "link", "") or source.url).strip()
            try:
                link = canonical_public_url(link)
            except FeedDiscoveryError:
                link = source.url
            published = _entry_timestamp(entry)
            content = f"{title}\n{summary}\n{link}"
            documents.append(ResearchDocument(
                source_id=source.source_id,
                url=link,
                title=title,
                summary=summary,
                published_at=published,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            ))
        return tuple(documents)


class UrlFeedDiscovery:
    """Discover only owner-supplied public feed URLs in the first adapter."""

    def discover(self, urls: Sequence[str]) -> tuple[ResearchSource, ...]:
        result: list[ResearchSource] = []
        seen: set[str] = set()
        for raw in list(urls)[:50]:
            url = canonical_public_url(str(raw))
            if url in seen:
                continue
            seen.add(url)
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            result.append(ResearchSource.from_dict({
                "source_id": f"src_{digest}",
                "kind": "rss",
                "url": url,
                "feed_url": url,
                "title": "",
                "discovered_by": "owner",
            }))
        return tuple(result)


class RedditFeedDiscovery:
    """Turn validated subreddit-name candidates into public RSS sources."""

    _NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")

    def discover(self, candidates: Sequence[Mapping[str, Any]]) -> tuple[ResearchSource, ...]:
        result: list[ResearchSource] = []
        seen: set[str] = set()
        for raw in list(candidates)[:50]:
            if not isinstance(raw, Mapping):
                continue
            name = self._normalize_name(raw.get("name"))
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            feed_url = f"https://www.reddit.com/r/{name}/.rss"
            source_id = "src_" + hashlib.sha256(f"reddit:{name.casefold()}".encode("utf-8")).hexdigest()[:32]
            result.append(ResearchSource.from_dict({
                "source_id": source_id,
                "kind": "rss",
                "url": f"https://www.reddit.com/r/{name}/",
                "feed_url": feed_url,
                "title": f"r/{name}",
                "discovered_by": "research_planner",
                "language": str(raw.get("language") or "").strip().lower(),
            }))
        return tuple(result)

    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        raw = str(value or "").strip()
        if "://" in raw:
            return ""
        name = re.sub(r"^/?r/", "", raw, flags=re.IGNORECASE).strip("/")
        return name if cls._NAME.fullmatch(name) else ""


def _clean_text(value: Any, maximum: int) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())[:maximum]


def _entry_timestamp(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, key, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                continue
    return None


__all__ = [
    "BoundedFeedReader",
    "FeedDiscoveryError",
    "ResearchDocument",
    "ResearchReader",
    "RedditFeedDiscovery",
    "UrlFeedDiscovery",
    "canonical_public_url",
]
