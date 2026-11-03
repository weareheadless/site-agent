import pytest

from site_agent.application.payload_publication import (
    PayloadPublicationError,
    publish_reviewed_effects,
)


def effects():
    return [
        {"kind": "collection", "target": "pages", "document_id": "1", "locale": "en",
         "revision": "sha256:" + "1" * 64, "fields": ["title", "sections"]},
        {"kind": "collection", "target": "pages", "document_id": "1", "locale": "es",
         "revision": "sha256:" + "2" * 64, "fields": ["title", "sections"]},
        {"kind": "global", "target": "siteSettings", "document_id": "siteSettings", "locale": "en",
         "revision": "sha256:" + "3" * 64, "fields": ["siteName"]},
        {"kind": "global", "target": "siteSettings", "document_id": "siteSettings", "locale": "es",
         "revision": "sha256:" + "4" * 64, "fields": ["siteName"]},
    ]


class Gateway:
    def __init__(self, *, published=None, drafts=None, publish_result=None):
        self.calls = []
        self.published = dict(published or {})
        self.drafts = dict(drafts or {})
        self.publish_result = dict(publish_result or {})

    @staticmethod
    def key(kind, target, locale):
        return (kind, target, locale)

    def read(self, collection, *, identifier, identifier_kind, draft, locale):
        assert identifier_kind == "id"
        kind = "collection" if draft else "published-collection"
        return {"_helloadaRevision": self.drafts.get(("collection", collection, locale), "")} if draft else {
            "_helloadaRevision": self.published.get(("collection", collection, locale), ""), "_status": "published"}

    def read_global(self, slug, *, draft, locale):
        if draft:
            return {"_helloadaRevision": self.drafts.get(("global", slug, locale), "")}
        return {"_helloadaRevision": self.published.get(("global", slug, locale), ""), "_status": "published"}

    def publish(self, collection, document_id, *, locale, expected_hash, expected_fields):
        self.calls.append(("publish", collection, document_id, locale, expected_hash, tuple(expected_fields)))
        return {"_helloadaRevision": self.publish_result.get((collection, locale), expected_hash)}

    def publish_global(self, slug, *, locale, expected_hash):
        self.calls.append(("publish_global", slug, locale, expected_hash))
        return {"_helloadaRevision": self.publish_result.get((slug, locale), expected_hash)}


def drafts_from(effect_list):
    return {(item["kind"], item["target"], item["locale"]): item["revision"] for item in effect_list}


def test_publishes_each_exact_reviewed_revision_once():
    effect_list = effects()
    gateway = Gateway(drafts=drafts_from(effect_list))
    receipt = publish_reviewed_effects(gateway, effect_list, revision_set_hash="abc")
    assert receipt["revisionSetHash"] == "abc"
    assert receipt["published"] == 4 and receipt["satisfied"] == 0
    # Collections are published before globals, deterministically.
    assert [call[0] for call in gateway.calls] == ["publish", "publish", "publish_global", "publish_global"]
    assert gateway.calls[0][4] == effect_list[0]["revision"]
    assert gateway.calls[2][3] == effect_list[2]["revision"]


def test_identical_content_in_an_unpublished_base_row_is_not_a_publication_receipt():
    effect_list = effects()[:1]

    class DraftBaseGateway(Gateway):
        def read(self, collection, *, identifier, identifier_kind, draft, locale):
            return {"_helloadaRevision": effect_list[0]["revision"], "_status": "draft"}

    gateway = DraftBaseGateway()
    receipt = publish_reviewed_effects(gateway, effect_list, revision_set_hash="reviewed")
    assert receipt["published"] == 1
    assert receipt["satisfied"] == 0
    assert len(gateway.calls) == 1


def test_already_published_revision_is_satisfied_without_rewriting():
    effect_list = effects()
    gateway = Gateway(published=drafts_from(effect_list))
    receipt = publish_reviewed_effects(gateway, effect_list)
    assert receipt["published"] == 0 and receipt["satisfied"] == 4
    assert gateway.calls == []


def test_changed_draft_revision_fails_closed_before_any_write():
    effect_list = effects()
    drafts = drafts_from(effect_list)
    drafts[("collection", "pages", "es")] = "sha256:" + "f" * 64
    gateway = Gateway(drafts=drafts)
    with pytest.raises(PayloadPublicationError, match="changed before publication"):
        publish_reviewed_effects(gateway, effect_list)
    assert gateway.calls == []


def test_published_result_must_match_the_approved_revision():
    effect_list = effects()
    gateway = Gateway(
        drafts=drafts_from(effect_list),
        publish_result={("pages", "en"): "sha256:" + "9" * 64},
    )
    with pytest.raises(PayloadPublicationError, match="different revision"):
        publish_reviewed_effects(gateway, effect_list)


def test_empty_effect_set_is_not_a_successful_publication():
    with pytest.raises(PayloadPublicationError, match="no reviewed Payload effects"):
        publish_reviewed_effects(Gateway(), [])


def test_unsupported_destination_is_rejected():
    with pytest.raises(PayloadPublicationError, match="unsupported destination"):
        publish_reviewed_effects(Gateway(), [{"kind": "media", "target": "media", "document_id": "1",
                                             "locale": "es", "revision": "sha256:" + "a" * 64}])
