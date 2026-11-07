from __future__ import annotations

import ipaddress

import pytest

from site_agent.hands import web_read
from site_agent.hands.web_read import WebReadError, _Text, _check_url


def test_a_loopback_link_is_refused():
    with pytest.raises(WebReadError, match="private or reserved"):
        _check_url("http://127.0.0.1:3014/v1/workspace/health")


def test_a_link_local_link_is_refused():
    with pytest.raises(WebReadError, match="private or reserved"):
        _check_url("http://169.254.169.254/latest/meta-data/")


def test_a_file_link_is_refused():
    with pytest.raises(WebReadError, match="only http and https"):
        _check_url("file:///etc/passwd")


def test_a_link_with_credentials_is_refused(monkeypatch):
    monkeypatch.setattr(web_read, "_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")])
    with pytest.raises(WebReadError, match="credentials"):
        _check_url("https://user:pass@example.com/")


def test_a_public_link_is_allowed(monkeypatch):
    monkeypatch.setattr(web_read, "_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")])
    parts = _check_url("https://example.com/about")
    assert parts.hostname == "example.com"


def test_a_redirect_target_is_validated_before_it_is_followed(monkeypatch):
    def addresses(host):
        return [ipaddress.ip_address("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34")]

    monkeypatch.setattr(web_read, "_addresses", addresses)
    guard = web_read._Guard()

    class Request:
        full_url = "https://example.com/"

    class Headers(dict):
        def get_all(self, name, default=None):
            return default

    with pytest.raises(WebReadError, match="private or reserved"):
        guard.redirect_request(Request(), None, 302, "Found", Headers(), "http://127.0.0.1/")


def test_readable_text_keeps_block_structure_and_drops_scripts():
    parser = _Text()
    parser.feed(
        "<html><head><title>Profile</title><style>b{}</style></head><body>"
        "<h1>Peter Abaji</h1><p>Master Instructor</p><script>secret()</script>"
        "<ul><li>15 students</li><li>Active</li></ul></body></html>"
    )
    text = parser.text()

    assert parser.title == "Profile"
    assert "Peter Abaji" in text
    assert "Master Instructor" in text
    assert "15 students" in text
    assert "secret()" not in text
    assert "b{}" not in text
    assert "\n" in text


def test_the_character_set_is_taken_from_the_response():
    assert web_read._decode("café".encode("latin-1"), "text/html; charset=latin-1") == "café"
    assert web_read._decode(b"plain", "text/html") == "plain"
