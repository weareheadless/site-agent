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
    assert service.analyze_pending_media(tenant=tenant) == {"analyzed": ["5"]}
    assert service.analyze_pending_media(tenant=tenant) == {"analyzed": []}
    service.analyze_media({"media_id": "5"}, tenant=tenant)
    assert analyzer.calls == 1
    assert payload.document["analysisModel"] == "conversation-model"
    assert payload.document["tags"] == [{"value": "logo"}]
