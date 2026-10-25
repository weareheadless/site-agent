"""Read-only evidence checks for a site's published canonical routes."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

MAX_RESPONSE_BYTES = 1_048_576
MAX_SITEMAP_BYTES = 4 * MAX_RESPONSE_BYTES
MAX_SITEMAP_DOCUMENTS = 16
MAX_SITEMAP_DEPTH = 2
MAX_EXPECTED_ROUTES = 500
TIMEOUT_SECONDS = 10.0
USER_AGENT = "SiteAgentCanonicalObserver/1.0 (+read-only canonical route verification)"


class CanonicalRoutesError(ValueError):
    """Invalid observation input or unsafe canonical-route response."""


def _normalize_origin(value: str) -> tuple[str, str, int | None, str]:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
        raise CanonicalRoutesError("origin must be a bare HTTPS origin")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise CanonicalRoutesError("origin must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise CanonicalRoutesError("origin must not contain a path")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.rstrip(".").casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise CanonicalRoutesError("origin has an invalid port") from exc
    if scheme == "http" and not _is_localhost(host):
        raise CanonicalRoutesError("origin must use HTTPS")
    if not host:
        raise CanonicalRoutesError("origin must include a hostname")
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    authority = rendered_host + (f":{port}" if port and port != default_port else "")
    canonical = urlunsplit((scheme, authority, "", "", ""))
    return canonical, scheme, port, host


def _is_localhost(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _canonical_url(value: str, origin: tuple[str, str, int | None, str]) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    canonical_origin, scheme, port, host = origin
    if not parsed.scheme or not parsed.netloc:
        raise CanonicalRoutesError("expected URLs must be absolute canonical URLs")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise CanonicalRoutesError("expected URLs must not contain credentials, query, or fragment")
    parsed_host = (parsed.hostname or "").rstrip(".").casefold()
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise CanonicalRoutesError("expected URL has an invalid port") from exc
    if parsed.scheme.lower() != scheme or parsed_host != host or _effective_port(parsed.scheme.lower(), parsed_port) != _effective_port(scheme, port):
        raise CanonicalRoutesError("expected URL must use the configured canonical origin")
    path = parsed.path or "/"
    if len(path) > 4_096:
        raise CanonicalRoutesError("expected URL path is too long")
    if re.search(r"%(?![0-9a-f]{2})", path, re.IGNORECASE):
        raise CanonicalRoutesError("expected URL has invalid path encoding")
    decoded = path
    for _ in range(8):
        if "\\" in decoded or any(part in {".", ".."} for part in decoded.split("/")):
            raise CanonicalRoutesError("expected URL contains a traversal path")
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    else:
        raise CanonicalRoutesError("expected URL path encoding is too deeply nested")
    if "\\" in decoded or any(part in {".", ".."} for part in decoded.split("/")):
        raise CanonicalRoutesError("expected URL contains a traversal path")
    return urlunsplit((scheme, urlsplit(canonical_origin).netloc, path, "", ""))


def _effective_port(scheme: str, port: int | None) -> int:
    return port or (443 if scheme == "https" else 80)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int | None, str]) -> None:
        super().__init__()
        self.origin = origin

    def redirect_request(self, request, fp, code, message, headers, newurl):  # type: ignore[no-untyped-def]
        try:
            _canonical_url(newurl, self.origin)
        except CanonicalRoutesError as exc:
            raise CanonicalRoutesError("redirect left the canonical origin") from exc
        return super().redirect_request(request, fp, code, message, headers, newurl)


@dataclass(frozen=True)
class _Response:
    url: str
    status: int
    content_type: str
    body: bytes | None
    redirect_error: bool = False


class _Observer:
    def __init__(self, origin: tuple[str, str, int | None, str], opener: Any = None) -> None:
        self.origin = origin
        self.opener = opener or urllib.request.build_opener(_SameOriginRedirectHandler(origin))
        self.sitemap_bytes = 0
        self.sitemap_documents = 0
        self.sitemap_urls: set[str] = set()
        self.sitemap_error: str | None = None
        self.sitemap_evidence: list[dict[str, Any]] = []

    def fetch(self, url: str) -> _Response:
        canonical_url = _canonical_url(url, self.origin)
        request = urllib.request.Request(canonical_url, headers={"User-Agent": USER_AGENT})
        try:
            response = self.opener.open(request, timeout=TIMEOUT_SECONDS)
            with response:
                status = int(getattr(response, "status", response.getcode()))
                headers = response.headers
                location = headers.get("Location")
                if 300 <= status < 400 and location:
                    target = urljoin(canonical_url, location)
                    try:
                        _canonical_url(target, self.origin)
                    except CanonicalRoutesError:
                        return _Response(canonical_url, status, _content_type(headers), None, True)
                length = headers.get("Content-Length")
                if length:
                    try:
                        if int(length) > MAX_RESPONSE_BYTES:
                            return _Response(canonical_url, 413, _content_type(headers), None, False)
                    except ValueError:
                        return _Response(canonical_url, 413, _content_type(headers), None, False)
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    body = None
                    status = 413
                return _Response(canonical_url, status, _content_type(headers), body)
        except CanonicalRoutesError:
            return _Response(canonical_url, 0, "", None, True)
        except urllib.error.HTTPError as exc:
            # Hash bounded error bodies as evidence without ever returning text.
            body: bytes | None = None
            try:
                length = exc.headers.get("Content-Length") if exc.headers else None
                if not length or int(length) <= MAX_RESPONSE_BYTES:
                    candidate = exc.read(MAX_RESPONSE_BYTES + 1)
                    if len(candidate) <= MAX_RESPONSE_BYTES:
                        body = candidate
            except (OSError, ValueError):
                body = None
            finally:
                exc.close()
            return _Response(canonical_url, int(exc.code), _content_type(exc.headers), body)
        except (OSError, ValueError, urllib.error.URLError):
            return _Response(canonical_url, 0, "", None)

    @staticmethod
    def evidence(response: _Response, *, ok: bool, error: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "url": response.url,
            "status": response.status,
            "sha256": hashlib.sha256(response.body).hexdigest() if response.body is not None else None,
            "ok": bool(ok),
        }
        if error:
            result["error"] = error
        return result

    def parse_sitemap(self, sitemap_url: str) -> bool:
        self._read_sitemap(sitemap_url, depth=1)
        return self.sitemap_error is None

    def _read_sitemap(self, sitemap_url: str, *, depth: int) -> None:
        if self.sitemap_error:
            return
        if depth > MAX_SITEMAP_DEPTH:
            self.sitemap_error = "sitemap_depth_exceeded"
            return
        try:
            sitemap_url = _canonical_url(sitemap_url, self.origin)
        except CanonicalRoutesError:
            self.sitemap_error = "foreign_sitemap_url"
            return
        if self.sitemap_documents >= MAX_SITEMAP_DOCUMENTS:
            self.sitemap_error = "sitemap_document_limit"
            return
        self.sitemap_documents += 1
        response = self.fetch(sitemap_url)
        response_bytes = len(response.body or b"")
        self.sitemap_bytes += response_bytes
        error = None
        if response.redirect_error:
            error = "external_redirect"
        elif response.status != 200:
            error = "http_status"
        elif response.content_type not in {"application/xml", "text/xml"} and not response.content_type.endswith("+xml"):
            error = "invalid_content_type"
        elif response.body is None or response_bytes == 0:
            error = "empty_or_oversized_response"
        elif self.sitemap_bytes > MAX_SITEMAP_BYTES:
            error = "sitemap_total_size_exceeded"
        else:
            try:
                xml_text = response.body.decode("utf-8-sig")
            except UnicodeDecodeError:
                xml_text = ""
                error = "invalid_xml_encoding"
            if not error and re.search(r"<!\s*(?:doctype|entity)\b", xml_text, re.IGNORECASE):
                error = "unsafe_xml_declaration"
        if error:
            self.sitemap_evidence.append(self.evidence(response, ok=False, error=error))
            self.sitemap_error = error
            return
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            self.sitemap_evidence.append(self.evidence(response, ok=False, error="invalid_xml"))
            self.sitemap_error = "invalid_xml"
            return
        kind = _xml_local_name(root.tag)
        self.sitemap_evidence.append(self.evidence(response, ok=True))
        if kind == "urlset":
            for loc in _xml_locs(root):
                try:
                    self.sitemap_urls.add(_canonical_url(loc, self.origin))
                except CanonicalRoutesError:
                    self.sitemap_error = "foreign_route_url"
                    return
        elif kind == "sitemapindex":
            locations = _xml_locs(root)
            if not locations:
                self.sitemap_error = "empty_sitemap_index"
                return
            for loc in locations:
                self._read_sitemap(loc, depth=depth + 1)
                if self.sitemap_error:
                    return
        else:
            self.sitemap_error = "invalid_sitemap_root"


def _content_type(headers: Any) -> str:
    return str((headers or {}).get("Content-Type", "")).split(";", 1)[0].strip().lower()


def _xml_local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _xml_locs(root: ET.Element) -> list[str]:
    return [str(node.text or "").strip() for node in root.iter() if _xml_local_name(node.tag) == "loc"]


def _robots_allows(body: bytes, urls: Iterable[str]) -> bool:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return all(parser.can_fetch(USER_AGENT, url) for url in urls)


def observe_canonical_routes(
    origin: str,
    *,
    expected_urls: list[str],
    inventory_revision: str,
    opener: Any = None,
) -> dict[str, Any]:
    """Fetch public route evidence and verify canonical robots/sitemap coverage.

    The injected opener is intended for deterministic tests. It must expose an
    ``open(request, timeout=...)`` method returning a urllib-like response.
    """
    normalized_origin = _normalize_origin(origin)
    revision = str(inventory_revision or "").strip()
    if not revision or len(revision) > 256:
        raise CanonicalRoutesError("inventory revision is required and must be bounded")
    if not isinstance(expected_urls, list) or not expected_urls:
        expected_urls = []
        invalid_inventory = True
    else:
        invalid_inventory = False
    if len(expected_urls) > MAX_EXPECTED_ROUTES:
        raise CanonicalRoutesError("expected route inventory exceeds the observation limit")
    routes: list[str] = []
    for value in expected_urls:
        routes.append(_canonical_url(value, normalized_origin))
    if len(routes) != len(set(routes)):
        raise CanonicalRoutesError("expected URLs must be unique")

    canonical_origin = normalized_origin[0]
    observer = _Observer(normalized_origin, opener)
    robots_url = canonical_origin + "/robots.txt"
    sitemap_url = canonical_origin + "/sitemap.xml"

    robots_response = observer.fetch(robots_url)
    robots_ok = (
        robots_response.status == 200
        and robots_response.content_type == "text/plain"
        and bool(robots_response.body)
    )
    robots_text = robots_response.body.decode("utf-8", errors="replace") if robots_ok else ""
    advertised_sitemaps = [
        line.split(":", 1)[1].strip()
        for line in robots_text.splitlines()
        if ":" in line and line.split(":", 1)[0].strip().casefold() == "sitemap"
    ]
    advertises_canonical = False
    for value in advertised_sitemaps:
        try:
            if _canonical_url(value, normalized_origin) == sitemap_url:
                advertises_canonical = True
        except CanonicalRoutesError:
            continue
    robots_allows = _robots_allows(robots_response.body, [canonical_origin + "/", *routes]) if robots_ok else False
    robots_evidence = observer.evidence(
        robots_response,
        ok=robots_ok and advertises_canonical and robots_allows,
        error=None if robots_ok and advertises_canonical and robots_allows else (
            "http_status" if robots_response.status != 200 else
            "invalid_content_type" if robots_response.content_type != "text/plain" else
            "canonical_sitemap_not_advertised" if not advertises_canonical else
            "route_disallowed"
        ),
    )

    sitemap_complete = observer.parse_sitemap(sitemap_url)
    missing = sorted(set(routes) - observer.sitemap_urls)
    sitemap_complete = sitemap_complete and not missing and bool(routes) and not invalid_inventory
    sitemap_ok = all(entry.get("ok") for entry in observer.sitemap_evidence) and sitemap_complete
    sitemap_evidence = {
        "url": sitemap_url,
        "status": observer.sitemap_evidence[0]["status"] if observer.sitemap_evidence else 0,
        "sha256": observer.sitemap_evidence[0]["sha256"] if observer.sitemap_evidence else None,
        "documents": observer.sitemap_evidence,
        "documentCount": observer.sitemap_documents,
        "urlCount": len(observer.sitemap_urls),
        "complete": sitemap_complete,
        "missingExpectedUrls": missing,
        "ok": sitemap_ok,
    }
    if observer.sitemap_error:
        sitemap_evidence["error"] = observer.sitemap_error
    elif invalid_inventory:
        sitemap_evidence["error"] = "expected_inventory_empty"
    elif missing:
        sitemap_evidence["error"] = "expected_routes_missing"

    route_evidence: list[dict[str, Any]] = []
    for route in routes:
        response = observer.fetch(route)
        html_type = response.content_type in {"text/html", "application/xhtml+xml"}
        okay = response.status == 200 and html_type and bool(response.body) and not response.redirect_error
        error = None if okay else (
            "external_redirect" if response.redirect_error else
            "http_status" if response.status != 200 else
            "invalid_content_type" if not html_type else
            "empty_response"
        )
        route_evidence.append(observer.evidence(response, ok=okay, error=error))

    passed = robots_evidence["ok"] and sitemap_evidence["ok"] and bool(route_evidence) and all(route["ok"] for route in route_evidence)
    return {
        "canonicalOrigin": canonical_origin,
        "inventoryRevision": revision,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "robots": robots_evidence,
        "sitemap": sitemap_evidence,
        "routes": route_evidence,
        "passed": bool(passed),
    }
