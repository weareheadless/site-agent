from __future__ import annotations

from email.message import Message

import pytest

from site_agent.hands.canonical_routes import (
    MAX_RESPONSE_BYTES,
    CanonicalRoutesError,
    observe_canonical_routes,
)


ORIGIN = "https://example.test"
ROUTES = [f"{ORIGIN}/", f"{ORIGIN}/about"]
ROBOTS = b"User-agent: *\nAllow: /\nSitemap: https://example.test/sitemap.xml\n"


def _urlset(urls=ROUTES):
    return ("<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
            + "".join(f"<url><loc>{url}</loc></url>" for url in urls)
            + "</urlset>").encode()


class FakeResponse:
    def __init__(self, body=b"", *, status=200, content_type="text/html", headers=None):
        self.body = body
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))
        for key, value in (headers or {}).items():
            if self.headers.get(key) is not None:
                self.headers.replace_header(key, value)
            else:
                self.headers[key] = value
        self.offset = 0

    def read(self, size=-1):
        if size < 0:
            size = len(self.body)
        result = self.body[self.offset:self.offset + size]
        self.offset += len(result)
        return result

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeOpener:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, timeout, request.get_header("User-agent")))
        value = self.responses.get(request.full_url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected fetch: {request.full_url}")
        return value


def _responses(*, robots=ROBOTS, sitemap=None, routes=None, extras=None):
    values = {
        f"{ORIGIN}/robots.txt": FakeResponse(robots, content_type="text/plain"),
        f"{ORIGIN}/sitemap.xml": sitemap if isinstance(sitemap, FakeResponse) else FakeResponse(sitemap if sitemap is not None else _urlset(), content_type="application/xml"),
        f"{ORIGIN}/": FakeResponse(b"<html>home</html>"),
        f"{ORIGIN}/about": FakeResponse(b"<html>about</html>"),
    }
    values.update(routes or {})
    values.update(extras or {})
    return values


def observe(opener, expected=ROUTES, revision="inventory-sha256:abc"):
    return observe_canonical_routes(ORIGIN, expected_urls=expected, inventory_revision=revision, opener=opener)


def test_observes_successful_live_routes_robots_and_sitemap_with_hashes():
    opener = FakeOpener(_responses())

    result = observe(opener)

    assert result["passed"] is True
    assert result["canonicalOrigin"] == ORIGIN
    assert result["inventoryRevision"] == "inventory-sha256:abc"
    assert result["checkedAt"].endswith("+00:00")
    assert result["robots"]["ok"] is True
    assert len(result["robots"]["sha256"]) == 64
    assert result["sitemap"]["complete"] is True
    assert result["sitemap"]["documentCount"] == 1
    assert all(route["ok"] and len(route["sha256"]) == 64 for route in result["routes"])
    assert all(timeout == 10.0 and agent and "CanonicalObserver" in agent for _, timeout, agent in opener.calls)


def test_route_404_is_not_hidden_as_empty_or_passed():
    responses = _responses(routes={f"{ORIGIN}/about": FakeResponse(b"missing", status=404)})
    result = observe(FakeOpener(responses))
    assert result["passed"] is False
    assert result["routes"][1]["status"] == 404
    assert result["routes"][1]["ok"] is False
    assert len(result["routes"][1]["sha256"]) == 64
    assert "missing" not in str(result["routes"][1])


def test_html_sitemap_is_rejected_even_with_status_200():
    responses = _responses(sitemap=FakeResponse(b"<html>not XML</html>", content_type="text/html"))
    result = observe(FakeOpener(responses))
    assert result["passed"] is False
    assert result["sitemap"]["error"] == "invalid_content_type"


def test_external_sitemap_redirect_is_rejected_without_following():
    response = FakeResponse(b"", status=302, content_type="text/plain", headers={"Location": "https://evil.test/collect"})
    opener = FakeOpener(_responses(sitemap=response))

    result = observe(opener)

    assert result["passed"] is False
    assert result["sitemap"]["error"] == "external_redirect"
    assert all("evil.test" not in url for url, _, _ in opener.calls)


def test_external_url_in_sitemap_index_is_rejected_without_fetching_it():
    index = b"<sitemapindex><sitemap><loc>https://evil.test/map.xml</loc></sitemap></sitemapindex>"
    opener = FakeOpener(_responses(sitemap=index))
    result = observe(opener)
    assert result["passed"] is False
    assert result["sitemap"]["error"] == "foreign_sitemap_url"
    assert all("evil.test" not in url for url, _, _ in opener.calls)


def test_sitemap_index_fetches_bounded_same_origin_child_documents():
    index = b"<sitemapindex><sitemap><loc>https://example.test/maps/pages.xml</loc></sitemap></sitemapindex>"
    responses = _responses(
        sitemap=index,
        extras={f"{ORIGIN}/maps/pages.xml": FakeResponse(_urlset(), content_type="application/xml")},
    )
    result = observe(FakeOpener(responses))
    assert result["passed"] is True
    assert result["sitemap"]["documentCount"] == 2
    assert len(result["sitemap"]["documents"]) == 2


def test_sitemap_index_depth_is_limited_to_two_documents():
    first = b"<sitemapindex><sitemap><loc>https://example.test/maps/second.xml</loc></sitemap></sitemapindex>"
    second = b"<sitemapindex><sitemap><loc>https://example.test/maps/third.xml</loc></sitemap></sitemapindex>"
    responses = _responses(
        sitemap=first,
        extras={f"{ORIGIN}/maps/second.xml": FakeResponse(second, content_type="application/xml")},
    )
    opener = FakeOpener(responses)
    result = observe(opener)
    assert result["passed"] is False
    assert result["sitemap"]["error"] == "sitemap_depth_exceeded"
    assert all("third.xml" not in url for url, _, _ in opener.calls)


def test_oversized_sitemap_response_is_rejected():
    oversized = FakeResponse(b"", content_type="application/xml", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
    result = observe(FakeOpener(_responses(sitemap=oversized)))
    assert result["passed"] is False
    assert result["sitemap"]["documents"][0]["status"] == 413
    assert result["sitemap"]["error"] == "http_status"


def test_missing_canonical_sitemap_advertisement_fails_robots_evidence():
    result = observe(FakeOpener(_responses(robots=b"User-agent: *\nAllow: /\n")))
    assert result["passed"] is False
    assert result["robots"]["error"] == "canonical_sitemap_not_advertised"


def test_robots_disallow_of_expected_route_fails():
    robots = b"User-agent: *\nDisallow: /about\nSitemap: https://example.test/sitemap.xml\n"
    result = observe(FakeOpener(_responses(robots=robots)))
    assert result["passed"] is False
    assert result["robots"]["error"] == "route_disallowed"


@pytest.mark.parametrize("xml", [
    b"<urlset>",
    b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><urlset>&e;</urlset>",
])
def test_invalid_or_entity_xml_fails(xml):
    result = observe(FakeOpener(_responses(sitemap=xml)))
    assert result["passed"] is False
    assert result["sitemap"]["error"] in {"invalid_xml", "unsafe_xml_declaration"}


def test_sitemap_coverage_is_bound_to_current_inventory_revision_and_routes():
    newer_inventory = [f"{ORIGIN}/", f"{ORIGIN}/about", f"{ORIGIN}/new-page"]
    responses = _responses(routes={f"{ORIGIN}/new-page": FakeResponse(b"<html>new</html>")})
    result = observe(FakeOpener(responses), expected=newer_inventory, revision="inventory-sha256:new")
    assert result["inventoryRevision"] == "inventory-sha256:new"
    assert result["passed"] is False
    assert result["sitemap"]["missingExpectedUrls"] == [f"{ORIGIN}/new-page"]
    assert result["sitemap"]["error"] == "expected_routes_missing"


def test_empty_expected_inventory_never_claims_passed():
    result = observe(FakeOpener(_responses()), expected=[])
    assert result["passed"] is False
    assert result["sitemap"]["complete"] is False
    assert result["sitemap"]["error"] == "expected_inventory_empty"


@pytest.mark.parametrize("origin", ["http://example.test", "https://user:pass@example.test", "https://example.test/path"])
def test_rejects_noncanonical_origin(origin):
    with pytest.raises(CanonicalRoutesError):
        observe_canonical_routes(origin, expected_urls=ROUTES, inventory_revision="rev", opener=FakeOpener({}))


def test_allows_http_only_for_explicit_localhost_tests():
    local = "http://127.0.0.1:8000"
    expected = [local + "/"]
    responses = {
        local + "/robots.txt": FakeResponse(ROBOTS.replace(b"https://example.test", local.encode()), content_type="text/plain"),
        local + "/sitemap.xml": FakeResponse(_urlset([local + "/"]), content_type="application/xml"),
        local + "/": FakeResponse(b"<html>local</html>"),
    }
    result = observe_canonical_routes(local, expected_urls=expected, inventory_revision="local-test", opener=FakeOpener(responses))
    assert result["passed"] is True


@pytest.mark.parametrize("url", [
    "https://evil.test/about",
    "https://user:pass@example.test/about",
    "https://example.test/about?preview=1",
    "https://example.test/about#fragment",
    "https://example.test/a/../about",
    "https://example.test/a/%2e%2e/about",
    "https://example.test/a/%252e%252e/about",
])
def test_rejects_noncanonical_or_unsafe_expected_urls(url):
    with pytest.raises(CanonicalRoutesError):
        observe(FakeOpener(_responses()), expected=[url])
