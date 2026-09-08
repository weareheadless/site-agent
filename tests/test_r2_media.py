from urllib.parse import parse_qs, urlsplit

import pytest

from site_agent.hands.r2_media import R2MediaError, R2MediaStore


def test_signed_get_url_has_bounded_expiry_and_sorted_query():
    store = R2MediaStore("a" * 32, "media-bucket", "access", "secret")
    url = store.signed_get_url("media/id/thumbnail.webp", 900)
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.path == "/media/id/thumbnail.webp"
    query = parse_qs(parsed.query)
    assert query["X-Amz-Expires"] == ["900"]
    assert "X-Amz-Signature" in query
    assert list(parse_qs(parsed.query).keys()) == sorted(parse_qs(parsed.query).keys())


def test_storage_rejects_path_traversal_and_bad_ttl():
    store = R2MediaStore("a" * 32, "media-bucket", "access", "secret")
    with pytest.raises(R2MediaError):
        store.signed_get_url("media/../secret", 900)
    with pytest.raises(R2MediaError):
        store.signed_get_url("media/file", 3601)
