from copy import deepcopy
import pytest

from site_agent.core.jobs import _mark_article_payload_blocked, _mirror_article_draft_to_workspace
from site_agent.core.memory import Memory


POST_FIELDS = frozenset({
    "title", "slug", "summary", "sections", "body", "featuredImage",
    "gallery", "author", "publishedAt", "modifiedAt", "category", "canonicalUrl", "seo", "published",
})


class Payload:
    def __init__(self):
        self.authoring_contract = {
            "locales": ["en"],
            "defaultLocale": "en",
            "enabled": {"collections": ["pages", "posts"], "globals": []},
            "authoring": {
                "collections": {
                    "posts": [{"name": field} for field in sorted(POST_FIELDS)],
                },
                "globals": {},
            },
        }
        self.documents = []
        self.created_data = []
        self.creates = 0
        self.updates = 0
        self.publishes = 0
        self.locales = []

    def require_authoring_contract(self):
        return self.authoring_contract

    def authoring_fields(self, kind, slug, *, authoring_contract=None):
        assert kind == "collection" and slug == "posts"
        contract = authoring_contract or self.authoring_contract
        return tuple(field["name"] for field in contract["authoring"]["collections"][slug])

    def list(self, collection, *, draft=True, limit=100):
        assert collection == "posts" and draft is True
        return [deepcopy(item) for item in self.documents[:limit]]

    def create(self, collection, data, *, locale=None):
        assert collection == "posts"
        self.locales.append(locale)
        self.creates += 1
        self.created_data.append(deepcopy(data))
        document = {**deepcopy(data), "sourceId": f"posts:{data['slug']}", "id": "post-1", "_helloadaRevision": "sha256:" + "a" * 64}
        self.documents.append(document)
        return deepcopy(document)

    def read(self, collection, *, identifier, identifier_kind, draft, locale=None):
        assert collection == "posts" and identifier_kind == "id" and draft is True
        self.locales.append(locale)
        return deepcopy(next(item for item in self.documents if str(item["id"]) == str(identifier)))

    def update(self, collection, document_id, data, *, locale=None, expected_hash=None):
        self.locales.append(locale)
        document = next(item for item in self.documents if str(item["id"]) == str(document_id))
        assert expected_hash == document["_helloadaRevision"]
        self.updates += 1
        document.update(deepcopy(data), _helloadaRevision="sha256:" + "b" * 64)
        return deepcopy(document)


def _context(memory, payload):
    return {
        "memory": memory,
        "payload_gateway": payload,
        "config": {
            "site": {"url": "https://business.example", "language": "en"},
            "persona": {"name": "Ada"},
        },
    }


def test_article_is_written_to_canonical_payload_posts_schema_as_unpublished_lexical(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(
        title="A useful guide",
        body="## A clear heading\n\nA **bold** paragraph with [a source](https://example.test).",
        kind="article",
        meta={"meta_description": "A description for search.", "primary_keyword": "useful guide"},
    )

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    document = payload.documents[0]
    assert payload.creates == 1
    assert payload.publishes == 0
    assert document["published"] is False
    assert document["sourceId"] == "posts:a-useful-guide"
    assert document["canonicalUrl"] == "https://business.example/post/a-useful-guide"
    assert document["summary"]
    assert document["body"]["root"]["type"] == "root"
    assert [node["type"] for node in document["body"]["root"]["children"]] == ["heading", "paragraph"]
    assert document["seo"]["description"] == "A description for search."
    assert document["seo"]["focusKeyword"] == "useful guide"
    assert not {"content", "excerpt", "sourceUrl", "metaDescription"} & set(document)
    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert sync["state"] == "ready_for_review"
    assert sync["validation"]["status"] == "passed"
    assert sync["draft_hash"] == document["_helloadaRevision"]
    memory.close()


def test_article_sync_uses_payload_owned_stable_source_identity_not_authoring_field(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A canonical post", body="Draft body.", kind="article")

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert "sourceId" not in payload.created_data[0]
    assert payload.documents[0]["sourceId"] == "posts:a-canonical-post"
    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert sync["source_id"] == "posts:a-canonical-post"
    assert sync["state"] == "ready_for_review"
    memory.close()


def test_article_sync_uses_payload_default_locale_not_owner_language(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A guide for local visitors", body="Draft body.", kind="article")
    context = _context(memory, payload)
    context["config"]["site"]["language"] = "fr"
    context["config"]["customer_profile"] = {"brand": {"observed_language": "fr"}}

    _mirror_article_draft_to_workspace(context, draft_id)

    assert payload.locales == ["en", "en"]
    assert memory.list_drafts()[0]["meta"]["payload_sync"]["locale"] == "en"
    memory.close()


def test_article_sync_refuses_to_overwrite_a_payload_revision_changed_by_an_owner(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A guide", body="Original article body.", kind="article")
    context = _context(memory, payload)
    _mirror_article_draft_to_workspace(context, draft_id)
    payload.documents[0]["_helloadaRevision"] = "sha256:" + "c" * 64

    with pytest.raises(RuntimeError, match="changed after Ada's last sync"):
        _mirror_article_draft_to_workspace(context, draft_id)

    assert payload.creates == 1
    assert payload.updates == 0
    memory.close()


def test_article_sync_does_not_adopt_an_unlinked_payload_post(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A guide", body="Draft copy.", kind="article")
    payload.documents.append({
        "id": "foreign-post", "sourceId": "posts:a-guide",
        "_helloadaRevision": "sha256:" + "d" * 64,
    })

    with pytest.raises(RuntimeError, match="not linked to Ada's exact sync record"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 0
    assert payload.updates == 0
    memory.close()


def test_blocked_sync_preserves_last_exact_payload_revision_for_reconciliation(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft(title="A guide", body="Draft copy.", kind="article", meta={
        "payload_sync": {
            "state": "ready_for_review",
            "document_id": "post-7",
            "draft_hash": "sha256:" + "e" * 64,
            "source_hash": "sha256:" + "f" * 64,
            "collection": "posts",
        },
    })

    _mark_article_payload_blocked(memory, draft_id, "schema needs repair")

    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert sync["state"] == "blocked"
    assert sync["document_id"] == "post-7"
    assert sync["draft_hash"] == "sha256:" + "e" * 64
    memory.close()
