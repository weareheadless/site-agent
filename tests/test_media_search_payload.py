from __future__ import annotations

import json

from site_agent.brain import editor
from site_agent.hands.payload_gateway import PayloadMediaService


class _Payload:
    base_url = "https://tenant.test"

    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    def list_media(self, *, draft: bool = True, limit: int = 100):
        self.calls.append((draft, limit))
        return list(self.documents)


def _service():
    return PayloadMediaService(_Payload([
        {
            "id": 4, "filename": "abaji.webp", "mimeType": "image/webp",
            "width": 170, "height": 170, "alt": "abaji.webp",
            "url": "/api/media/file/abaji.webp",
        },
        {
            "id": 9, "filename": "reef.jpg", "mimeType": "image/jpeg",
            "width": 1600, "height": 900, "description": "underwater reef",
        },
    ]))


def test_payload_media_search_reads_the_tenant_gallery():
    service = _service()

    rows = service.search("abaji", limit=8)

    assert [row["id"] for row in rows] == [4]
    assert rows[0]["asset_id"] == 4
    assert rows[0]["url"] == "https://tenant.test/api/media/file/abaji.webp"


def test_payload_media_search_never_returns_an_unrelated_local_asset():
    service = _service()

    rows = service.search("portrait", limit=8)

    assert rows == []


def test_the_agent_media_tool_uses_the_payload_gallery():
    service = _service()
    context = {"memory": None, "media_service": service}

    result = editor._execute_tool(
        context, None, "search_media", {"query": "abaji", "limit": 8}, lambda _text: None,
    )

    rows = json.loads(result)
    assert [row["id"] for row in rows] == [4]
