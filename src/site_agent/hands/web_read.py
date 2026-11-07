"""Read one public web page for Ada, with a strict network policy.

The owner sends links. The chat agent needs to open them, and it runs on the
host that also serves the workspace API and holds provider credentials, so a
plain fetch tool would let a link (or a page that redirects) reach loopback,
link-local or private addresses.

Policy: http/https only, no credentials in the URL, every redirect hop
re-validated, every resolved address must be public, text content only, bounded
size and time.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 2_000_000
MAX_CHARS = 24_000
TIMEOUT_SECONDS = 15
MAX_REDIRECTS = 4
ALLOWED_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/xml")


class WebReadError(RuntimeError):
    """A page that cannot be read under the owner-facing policy."""


def _addresses(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebReadError(f"could not resolve {host}") from exc
    found: list[ipaddress._BaseAddress] = []
    for info in infos:
        try:
            found.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return found


def _check_url(url: str) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https"):
        raise WebReadError("only http and https links can be read")
    if not parts.hostname:
        raise WebReadError("the link has no host")
    if parts.username or parts.password:
        raise WebReadError("links with embedded credentials are not allowed")
    for address in _addresses(parts.hostname):
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise WebReadError("the link points to a private or reserved address")
    return parts


class _Guard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - stdlib hook
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Text(HTMLParser):
    """Keep readable text and block structure, drop scripts and styles."""

    BLOCK = {
        "p", "div", "section", "article", "header", "footer", "li", "tr", "br",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table",
    }
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text + " ")

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def _decode(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for chunk in content_type.split(";")[1:]:
        name, _, value = chunk.strip().partition("=")
        if name.lower() == "charset" and value:
            charset = value.strip().strip('"')
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_text(url: str) -> str:
    """Fetch one public page and return its readable text."""
    _check_url(url)
    opener = urllib.request.build_opener(_Guard)
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; HelloAda/1.0; +https://helloada.app)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
    })
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if not any(kind in content_type for kind in ALLOWED_TYPES):
                raise WebReadError(f"the link is not a readable page ({content_type.split(';')[0] or 'unknown type'})")
            body = response.read(MAX_BYTES + 1)
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        raise WebReadError(f"the page returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise WebReadError(f"the page could not be reached ({exc.reason})") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise WebReadError("the page took too long to respond") from exc
    if len(body) > MAX_BYTES:
        raise WebReadError("the page is larger than the readable limit")

    document = _decode(body, content_type)
    if "html" in content_type or "xml" in content_type:
        parser = _Text()
        parser.feed(document)
        text = parser.text()
        title = " ".join(parser.title.split())
    else:
        text = "\n".join(line for line in document.splitlines() if line.strip())
        title = ""
    if not text.strip():
        raise WebReadError("the page had no readable text")
    header = f"Source: {final_url}\n"
    if title:
        header += f"Title: {title}\n"
    body_text = text[:MAX_CHARS]
    if len(text) > MAX_CHARS:
        body_text += "\n\n[page truncated]"
    return header + "\n" + body_text
