from types import SimpleNamespace

from site_agent.application.workspace import ChatService
from site_agent.core.memory import Memory


class Payload:
    def __init__(self, document):
        self.document = document

    def read(self, collection, **kwargs):
        assert collection == "posts"
        return dict(self.document)


def service_for(tmp_path, meta, payload=None):
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft(
        title="An article that belongs to the owner",
        body="# Original draft\n\nThis copy must remain inspectable.",
        kind="article",
        meta=meta,
    )
    config = {"site": {"website_present": True, "payload": {"enabled": True}}}
    tenant = SimpleNamespace(
        tenant_id="growth-demo",
        memory=memory,
        config=config,
        context={"payload_gateway": payload},
    )
    return memory, draft_id, ChatService(memory, object()), tenant


def test_blocked_article_detail_shows_saved_draft_without_approval_authority(tmp_path):
    memory, draft_id, service, tenant = service_for(
        tmp_path,
        {"payload_sync": {"state": "blocked", "validation": {"status": "blocked", "reason": "private implementation detail"}}},
    )

    result = service.growth_article_review(draft_id, tenant=tenant)

    assert result["reviewable"] is False
    assert result["reviewPackageHash"] is None
    assert result["blockedReasonCode"] == "articlePayloadSyncBlocked"
    assert "private implementation detail" not in str(result)
    assert result["article"]["body"] == "# Original draft\n\nThis copy must remain inspectable."
    assert result["article"]["bodyFormat"] == "markdown"
    memory.close()



def test_unlinked_nonempty_payload_conflict_has_a_specific_safe_reason(tmp_path):
    memory, draft_id, service, tenant = service_for(
        tmp_path,
        {
            "payload_sync": {
                "state": "blocked",
                "validation": {
                    "status": "blocked",
                    "reason": "An existing Payload post at this route is neither Ada's exact draft nor an empty schema draft; its content remains unchanged for owner review.",
                },
            },
        },
    )

    result = service.growth_article_review(draft_id, tenant=tenant)

    assert result["reviewable"] is False
    assert result["blockedReasonCode"] == "articlePayloadConflict"
    assert result["article"]["bodyFormat"] == "markdown"
    memory.close()


def test_changed_payload_revision_is_visible_but_not_reviewable(tmp_path):
    body = {
        "root": {
            "type": "root",
            "version": 1,
            "children": [{
                "type": "paragraph",
                "version": 1,
                "children": [{"type": "text", "version": 1, "text": "Owner-edited current text", "format": 0, "mode": "normal", "style": "", "detail": 0}],
                "direction": "ltr",
                "format": "",
                "indent": 0,
            }],
            "direction": "ltr",
            "format": "",
            "indent": 0,
        }
    }
    sync = {
        "state": "ready_for_review",
        "collection": "posts",
        "document_id": "post-42",
        "draft_hash": "revision-1",
        "locale": "en",
        "validation": {"status": "passed", "checks": {"canonicalSchema": True}},
    }
    payload = Payload({
        "id": "post-42",
        "sourceId": "ada-article-1",
        "slug": "owner-article",
        "title": "The current title",
        "summary": "The current summary",
        "seo": {"description": "The current description"},
        "body": body,
        "_helloadaRevision": "revision-2",
    })
    memory, draft_id, service, tenant = service_for(
        tmp_path,
        {"payload_sync": sync, "review_package_hash": "sha256:review-revision-1"},
        payload,
    )

    result = service.growth_article_review(draft_id, tenant=tenant)

    assert result["reviewable"] is False
    assert result["reviewPackageHash"] is None
    assert result["blockedReasonCode"] == "articlePayloadChanged"
    assert result["article"]["body"] == body
    assert result["article"]["bodyFormat"] == "lexical"
    assert result["article"]["title"] == "The current title"
    memory.close()


def test_changed_cover_image_revision_is_not_reviewable(tmp_path):
    body = {
        "root": {
            "type": "root",
            "version": 1,
            "children": [{
                "type": "paragraph",
                "version": 1,
                "children": [{"type": "text", "version": 1, "text": "Reviewed article text", "format": 0, "mode": "normal", "style": "", "detail": 0}],
                "direction": "ltr",
                "format": "",
                "indent": 0,
            }],
            "direction": "ltr",
            "format": "",
            "indent": 0,
        }
    }

    class PayloadWithChangedImage(Payload):
        def read_media(self, identifier, *, identifier_kind="id", draft=True):
            assert identifier == "cover-1" and identifier_kind == "id" and draft is True
            return {
                "id": "cover-1",
                "sourceId": "media:cover-1",
                "analysisStatus": "ready",
                "alt": "A reviewed cover image",
                "url": "/media/cover.jpg",
                "_helloadaRevision": "revision-2",
            }

    sync = {
        "state": "ready_for_review",
        "collection": "posts",
        "document_id": "post-42",
        "draft_hash": "revision-1",
        "locale": "en",
        "featured_image": {
            "id": "cover-1",
            "revision": "revision-1",
            "source_id": "media:cover-1",
        },
        "validation": {"status": "passed", "checks": {"canonicalSchema": True}},
    }
    payload = PayloadWithChangedImage({
        "id": "post-42",
        "sourceId": "ada-article-1",
        "slug": "owner-article",
        "title": "The current title",
        "summary": "The current summary",
        "seo": {"description": "The current description"},
        "body": body,
        "_helloadaRevision": "revision-1",
    })
    memory, draft_id, service, tenant = service_for(
        tmp_path,
        {"payload_sync": sync, "review_package_hash": "sha256:review-revision-1"},
        payload,
    )

    result = service.growth_article_review(draft_id, tenant=tenant)

    assert result["reviewable"] is False
    assert result["reviewPackageHash"] is None
    assert result["blockedReasonCode"] == "articlePayloadChanged"
    memory.close()
