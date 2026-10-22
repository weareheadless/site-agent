import json

from site_agent.application.growth_workflow import _inventory
from site_agent.application.growth_candidates import content_hash


class Payload:
    def __init__(self, documents):
        self.documents = documents

    def require_authoring_contract(self):
        return {"enabled": {"collections": ["pages"]}}

    def authoring_fields(self, *args, **kwargs):
        return ["title", "body", "slug", "sourceId", "seo"]

    def list(self, *args, **kwargs):
        assert kwargs["draft"] is False
        return self.documents


def test_assessment_inventory_keeps_all_documents_without_loading_full_bodies_into_planner():
    documents = [{"id": n, "title": f"Page {n}", "slug": f"page-{n}", "sourceId": f"page:{n}",
                  "seo": {"title": f"Page {n}"}, "body": "long canonical content " * 10000} for n in range(1, 8)]
    inventory = _inventory({"payload_gateway": Payload(documents)})
    assert len(inventory) == len(documents)
    assert len(json.dumps(inventory, ensure_ascii=False).encode()) <= 120000
    for entry, original in zip(inventory, documents):
        assert entry["document"]["id"] == str(original["id"])
        assert entry["sourceRef"] == f"payload:pages:{original['id']}"
        assert "body" not in entry["document"]
        scope = entry["assessmentScope"]
        assert scope["completeDocument"] is False
        assert scope["omittedFields"] == ["body"]
        canonical = {key: original.get(key) for key in sorted(Payload([]).authoring_fields())}
        assert scope["documentHash"] == content_hash(canonical)
        assert scope["previewCharacters"] < scope["totalCharacters"]


def test_unicode_preview_and_seo_identity_remain_within_declared_scope():
    documents = [{"id": n, "title": "Apnée", "slug": f"test-{n}", "body": "🌊" * 10000,
                  "seo": {"title": "Même titre"}} for n in range(1, 61)]
    inventory = _inventory({"payload_gateway": Payload(documents)})
    assert len(inventory) == 60
    assert len(json.dumps(inventory, ensure_ascii=False).encode()) <= 120000
    assert all(row["document"]["seo"]["title"] == "Même titre" for row in inventory)


def test_assessment_metadata_does_not_expand_seo_media_relations():
    documents = [{"id": n, "title": f"Item {n}", "slug": f"item-{n}", "body": "copy",
                  "seo": {"title": "Search title", "description": "Search description", "image": {"analysis": "large relation " * 10000}}}
                 for n in range(1, 101)]
    rows = _inventory({"payload_gateway": Payload(documents)})
    assert len(rows) == 100
    assert all(row["document"]["seo"] == {"title": "Search title", "description": "Search description"} for row in rows)
    assert all("seo" in row["assessmentScope"]["partialFields"] for row in rows)
