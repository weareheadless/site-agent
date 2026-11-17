"""Gateway reads reuse one connection per thread instead of one per request.

A whole-site preview snapshot reads every document and every referenced media
file, so a handshake per read dominated it. These tests pin the pool's contract:
a reused connection, one reconnect when the peer closed it, and byte-for-byte
the same errors the urllib client raised.
"""

from __future__ import annotations

import http.server
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from site_agent.hands.payload_gateway import (
    PayloadContract,
    PayloadGatewayClient,
    PayloadGatewayError,
    PayloadMediaService,
    _OriginConnections,
)

_DOCUMENT_HASH = "sha256:" + "a" * 64


class _Recorder:
    def __init__(self) -> None:
        self.connections = 0
        self.requests: list[str] = []


@contextmanager
def _server(document: dict, media: bytes = b"", *, close_after_first: bool = False,
            document_status: int = 200):
    """Serve one gateway JSON document and one media file over plain HTTP."""
    recorder = _Recorder()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            recorder.connections += 1
            super().setup()

        def log_message(self, *args) -> None:  # keep test output clean
            return

        def do_GET(self) -> None:
            recorder.requests.append(self.path)
            if self.path.startswith("/api/media/file/") and media:
                body, content_type, status = media, "image/webp", 200
            elif "/media" in self.path and document_status == 200:
                body, content_type, status = json.dumps(document).encode(), "application/json", 200
            else:
                body, content_type, status = b'{"message": "no public route"}', "application/json", 404
            if close_after_first and len(recorder.requests) == 1:
                # The peer closes a connection the client still believes is
                # reusable: no ``Connection: close`` header, just an empty read
                # on the next request.
                self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", recorder
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _client(base_url: str) -> PayloadGatewayClient:
    return PayloadGatewayClient(
        base_url, "test-token", PayloadContract(frozenset(), "helloada-content-v4", "0.6.0", 10, "a" * 64),
    )


@dataclass
class _Payload:
    base_url: str
    timeout_seconds: float = 30.0


def test_sequential_gateway_reads_share_one_connection():
    document = {"media": {"id": 7, "filename": "reef.webp"}, "documentHash": _DOCUMENT_HASH}
    with _server(document) as (base_url, recorder):
        client = _client(base_url)
        first = client.read_media("7")
        second = client.read_media("7")

    assert first["filename"] == second["filename"] == "reef.webp"
    assert recorder.connections == 1
    assert len(recorder.requests) == 2


def test_a_connection_the_peer_closed_is_reopened_once():
    document = {"media": {"id": 7, "filename": "reef.webp"}, "documentHash": _DOCUMENT_HASH}
    with _server(document, close_after_first=True) as (base_url, recorder):
        client = _client(base_url)
        assert client.read_media("7")["filename"] == "reef.webp"
        # The pooled connection is dead without saying so; the read still
        # answers instead of surfacing a transport error to the owner.
        assert client.read_media("7")["filename"] == "reef.webp"

    assert recorder.connections == 2


def test_gateway_errors_keep_their_status_and_message():
    with _server({}, document_status=404) as (base_url, _recorder):
        with pytest.raises(PayloadGatewayError) as raised:
            _client(base_url).read_media("7")

    assert raised.value.status_code == 404
    assert str(raised.value) == "Payload gateway returned 404: no public route"


def test_preview_media_reads_the_bytes_through_the_same_pool():
    with _server({}, media=b"webp-bytes") as (base_url, recorder):
        service = PayloadMediaService(_Payload(base_url))
        url = f"{base_url}/api/media/file/reef.webp"
        data, content_type = service.read_preview(7, url=url)
        again, _ = service.read_preview(7, url=url)

    assert data == again == b"webp-bytes"
    assert content_type == "image/webp"
    assert recorder.connections == 1


def test_a_missing_media_file_still_reads_as_unreachable():
    with _server({}, media=b"") as (base_url, _recorder):
        service = PayloadMediaService(_Payload(base_url))
        with pytest.raises(PayloadGatewayError) as raised:
            service.read_preview(7, url=f"{base_url}/missing")

    assert str(raised.value) == "Payload media preview is unreachable"


def test_the_pool_reads_at_most_the_limit():
    with _server({}, media=b"x" * 64) as (base_url, _recorder):
        pool = _OriginConnections()
        status, _headers, body = pool.request("GET", f"{base_url}/api/media/file/big", limit=16)

    assert status == 200
    assert body == b"x" * 16
