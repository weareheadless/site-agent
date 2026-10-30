from types import SimpleNamespace

from site_agent.application.workspace import ChatService


def test_pending_payload_inventory_is_durable_and_duplicate_notifications_do_not_reanalyze():
    class Payload:
        base_url = "https://tenant.example"

        def __init__(self):
            self.document = {"id": 5, "mimeType": "image/png", "url": "/logo.png",
                             "analysisStatus": "pending", "_helloadaRevision": "sha256:" + "a" * 64}

        def list_media(self, **kwargs):
            return [dict(self.document), {"id": 6, "mimeType": "image/png", "analysisStatus": "failed"}]

        def read_media(self, *args, **kwargs):
            return dict(self.document)

        def update_media(self, media_id, data, **kwargs):
            self.document.update(data)
            return dict(self.document)

    class Analyzer:
        model = "conversation-model"
        provider_id = "conversation-provider"
        calls = 0

        def analyze_images(self, urls, instruction):
            self.calls += 1
            return {"description": "Logo", "tags": ["logo"], "alt_text": "Owner logo"}

    payload, analyzer = Payload(), Analyzer()
    tenant = SimpleNamespace(context={"payload_gateway": payload, "media_analyzer": analyzer})
    service = ChatService(memory=object(), llm=object())
    assert service.analyze_pending_media(tenant=tenant) == {"analyzed": ["5"], "failed": []}
    assert service.analyze_pending_media(tenant=tenant) == {"analyzed": [], "failed": []}
    service.analyze_media({"media_id": "5"}, tenant=tenant)
    assert analyzer.calls == 1
    assert payload.document["analysisModel"] == "conversation-model"
    assert payload.document["tags"] == [{"value": "logo"}]
    payload.document["analysisStatus"] = "failed"
    service.analyze_media({"media_id": "5"}, tenant=tenant)
    assert analyzer.calls == 1


def test_media_contract_write_rejects_fields_outside_the_analysis_contract():
    """Analysis must be able to persist: the contract check needs instance state."""
    from site_agent.hands.payload_gateway import PayloadGatewayClient, PayloadGatewayError

    class Contract:
        media_fields = frozenset({"alt", "description"})

    client = object.__new__(PayloadGatewayClient)
    object.__setattr__(client, "contract", Contract())

    assert client._media_data({"alt": "Owner logo"}) == {"alt": "Owner logo"}
    try:
        client._media_data({"alt": "x", "unexpected": 1})
    except PayloadGatewayError as exc:
        assert "outside the analysis contract" in str(exc)
    else:
        raise AssertionError("an unknown media field must be refused")


def test_one_unreadable_upload_does_not_block_the_rest_of_the_batch():
    class Payload:
        base_url = "https://tenant.example"

        def __init__(self):
            self.documents = [
                {"id": 1, "mimeType": "image/png", "url": "/a.png", "analysisStatus": "pending"},
                {"id": 2, "mimeType": "image/png", "url": "/b.png", "analysisStatus": "pending"},
            ]

        def list_media(self, **kwargs):
            return [dict(item) for item in self.documents]

        def read_media(self, media_id, **kwargs):
            document = next(item for item in self.documents if str(item["id"]) == str(media_id))
            if document["id"] == 1:
                raise RuntimeError("provider could not download the image")
            return {**document, "_helloadaRevision": "sha256:" + "b" * 64}

        def update_media(self, media_id, data, **kwargs):
            for item in self.documents:
                if str(item["id"]) == str(media_id):
                    item.update(data)
            return next(item for item in self.documents if str(item["id"]) == str(media_id))

    class Analyzer:
        model = "conversation-model"
        provider_id = "conversation-provider"

        def analyze_images(self, urls, instruction):
            return {"description": "Photo", "tags": ["photo"], "alt_text": "Owner photo"}

    tenant = SimpleNamespace(context={"payload_gateway": Payload(), "media_analyzer": Analyzer()})
    result = ChatService(memory=object(), llm=object()).analyze_pending_media(tenant=tenant)

    assert result["analyzed"] == ["2"]
    assert result["failed"][0]["media_id"] == "1"
