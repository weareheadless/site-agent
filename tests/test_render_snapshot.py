import hashlib
import json

import pytest

from site_agent.core.render_snapshot import RenderSnapshot, RenderSnapshotError
from site_agent.hands.payload_gateway import PayloadContract, PayloadGatewayClient, PayloadGatewayError


IDENTITY = dict(tenant="alpha", source_sha="a" * 40, schema_identity="b" * 64)


def snapshot():
    return dict(schema=1, tenant="alpha", sourceSha="a" * 40, schemaIdentity="b" * 64,
                locales=["en"], defaultLocale="en", documents={"en": {"pages": [{"id": 1, "title": "Océan"}]}},
                globals={"en": {"navigation": {}, "siteSettings": {}}}, media=[],
                seed={"collections": {"pages": [{"id": 1, "title": {"en": "Océan"}}]}, "globals": {"navigation": {}, "siteSettings": {}}})


def envelope(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return dict(version=1, snapshotJson=raw, hash="sha256:" + hashlib.sha256(raw.encode()).hexdigest())


def test_preserves_exact_gateway_bytes():
    source = envelope(snapshot())
    result = RenderSnapshot.verify(source, **IDENTITY)
    assert result.json_bytes == source["snapshotJson"].encode()
    assert result.digest == source["hash"]


def test_tampered_bytes_are_rejected():
    source = envelope(snapshot())
    source["snapshotJson"] += " "
    with pytest.raises(RenderSnapshotError, match="digest"):
        RenderSnapshot.verify(source, **IDENTITY)


@pytest.mark.parametrize("field,value", [("tenant", "other"), ("sourceSha", "c" * 40), ("schemaIdentity", "d" * 64)])
def test_wrong_revision_is_rejected(field, value):
    data = snapshot()
    data[field] = value
    with pytest.raises(RenderSnapshotError, match="identity"):
        RenderSnapshot.verify(envelope(data), **IDENTITY)


@pytest.mark.parametrize("mutate", [
    lambda data: data["documents"]["en"].update(users=[]),
    lambda data: data["globals"]["en"].update(messageMailbox={}),
    lambda data: data["documents"].update(fr={"pages": []}),
    lambda data: data["documents"]["en"]["pages"].append({"id": 1}),
    lambda data: data["media"].append({"id": 2, "filename": "a.png", "mimeType": "image/png", "token": "private"}),
])
def test_incomplete_or_private_scope_is_rejected(mutate):
    data = snapshot()
    mutate(data)
    with pytest.raises(RenderSnapshotError):
        RenderSnapshot.verify(envelope(data), **IDENTITY)


def test_gateway_preserves_configured_prefix_and_checks_exact_base(monkeypatch):
    client = PayloadGatewayClient("https://example.test", "not-a-secret", PayloadContract(
        frozenset(), "helloada-content-v4", "0.5.9", 8, "b" * 64,
    ), gateway_prefix="/private/workspace")
    requests = []
    def request(self, method, path):
        requests.append((method, path))
        return envelope(snapshot())
    monkeypatch.setattr(PayloadGatewayClient, "_request", request)
    assert client.capture_render_snapshot(tenant="alpha", source_sha="a" * 40).digest.startswith("sha256:")
    assert requests == [("GET", "/private/workspace/render-snapshot")]
    with pytest.raises(PayloadGatewayError, match="identity"):
        client.capture_render_snapshot(tenant="alpha", source_sha="c" * 40)


def test_render_media_uses_exact_frozen_url_and_never_sends_service_token(monkeypatch):
    import io
    from email.message import Message
    from site_agent.hands import payload_gateway
    client = PayloadGatewayClient('https://example.test', 'must-not-leak', PayloadContract(frozenset(), 'helloada-content-v4', '0.5.9', 8, 'b' * 64))
    class Response(io.BytesIO):
        headers = Message()
    Response.headers['Content-Type'] = 'image/png'
    class Opener:
        def open(self, request, **kwargs):
            assert request.full_url == 'https://example.test/api/media/file/hero.png'
            assert not request.has_header('Authorization')
            return Response(b'png')
    monkeypatch.setattr(payload_gateway.urllib.request, 'build_opener', lambda *args: Opener())
    metadata = {'filename': 'hero.png', 'url': '/api/media/file/hero.png', 'filesize': 3, 'mimeType': 'image/png'}
    assert client.read_render_media(metadata) == (b'png', 'image/png')
    for url in ['https://other.test/hero.png', '/api/media/file/other.png', '/admin', '/api/media/file/hero.png?token=bad']:
        with pytest.raises(PayloadGatewayError, match='exact canonical'):
            client.read_render_media({**metadata, 'url': url})
    with pytest.raises(PayloadGatewayError, match='size'):
        client.read_render_media({**metadata, 'filesize': 4})
