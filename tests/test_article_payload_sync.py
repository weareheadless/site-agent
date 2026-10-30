from copy import deepcopy
import json
import pytest

from site_agent.core.jobs import _mark_article_payload_blocked, _mirror_article_draft_to_workspace, _mirror_article_drafts
from site_agent.core.memory import Memory
from site_agent.hands.payload_gateway import PayloadGatewayError


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
        self.conflict_after_create = False
        self.media = [{
            "id": "media-1",
            "sourceId": "media:cover-1",
            "filename": "training-cover.jpg",
            "url": "/media/training-cover.jpg",
            "alt": "A freediver preparing for a course in clear water",
            "description": "Freediving course preparation in clear water.",
            "tags": [{"value": "freediving"}, {"value": "course"}],
            "suggestedUses": [{"value": "freediving course article cover"}],
            "sourceKind": "owner_upload",
            "analysisStatus": "ready",
            "_helloadaRevision": "sha256:" + "9" * 64,
        }]

    def require_authoring_contract(self):
        return self.authoring_contract

    def authoring_fields(self, kind, slug, *, authoring_contract=None):
        assert kind == "collection" and slug == "posts"
        contract = authoring_contract or self.authoring_contract
        return tuple(field["name"] for field in contract["authoring"]["collections"][slug])

    def list(self, collection, *, draft=True, limit=100, locale=None):
        assert collection == "posts" and locale == "en"
        return [
            deepcopy(item) for item in self.documents[:limit]
            if bool(item.get("published")) is (not draft)
        ] if not draft else [deepcopy(item) for item in self.documents[:limit]]

    def list_media(self, *, draft=True, limit=100):
        assert draft is True
        return [deepcopy(item) for item in self.media[:limit]]

    def read_media(self, identifier, *, identifier_kind="id", draft=True):
        assert identifier_kind == "id" and draft is True
        document = next((item for item in self.media if str(item.get("id")) == str(identifier)), None)
        if document is None:
            raise PayloadGatewayError("media not found", status_code=404)
        return deepcopy(document)

    def create(self, collection, data, *, locale=None):
        assert collection == "posts"
        self.locales.append(locale)
        self.creates += 1
        self.created_data.append(deepcopy(data))
        document = {**deepcopy(data), "sourceId": f"posts:{data['slug']}", "id": "post-1", "_status": "draft", "_helloadaRevision": "sha256:" + "a" * 64}
        self.documents.append(document)
        if self.conflict_after_create:
            self.conflict_after_create = False
            raise PayloadGatewayError("Payload gateway returned 409: route conflict", status_code=409)
        return deepcopy(document)

    def read(self, collection, *, identifier, identifier_kind, draft, locale=None):
        assert collection == "posts" and identifier_kind in {"id", "slug"} and draft is True
        self.locales.append(locale)
        key = "id" if identifier_kind == "id" else "slug"
        document = next((item for item in self.documents if str(item.get(key)) == str(identifier)), None)
        if document is None:
            raise PayloadGatewayError("not found", status_code=404)
        return deepcopy(document)

    def update(self, collection, document_id, data, *, locale=None, expected_hash=None):
        self.locales.append(locale)
        document = next(item for item in self.documents if str(item["id"]) == str(document_id))
        assert expected_hash == document["_helloadaRevision"]
        self.updates += 1
        document.update(deepcopy(data), _helloadaRevision="sha256:" + "b" * 64)
        return deepcopy(document)


def _context(memory, payload):
    class MediaSelector:
        def chat(self, messages, **kwargs):
            request = json.loads(messages[-1]["content"])
            return json.dumps({
                "media_id": request["available_images"][0]["id"],
                "reason": "The image subject and its analyzed use match the article topic.",
            })

    return {
        "memory": memory,
        "payload_gateway": payload,
        "llm": MediaSelector(),
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
    assert document["canonicalUrl"] == "https://business.example/blog/a-useful-guide"
    assert document["summary"]
    assert document["body"]["root"]["type"] == "root"
    assert [node["type"] for node in document["body"]["root"]["children"]] == ["heading", "paragraph"]
    assert document["seo"]["description"] == "A description for search."
    assert document["seo"]["focusKeyword"] == "useful guide"
    assert document["featuredImage"] == "media-1"
    assert not {"content", "excerpt", "sourceUrl", "metaDescription"} & set(document)
    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    selection = memory.list_drafts()[0]["meta"]["article_image_selection"]
    assert sync["state"] == "ready_for_review"
    assert sync["validation"]["status"] == "passed"
    assert sync["draft_hash"] == document["_helloadaRevision"]
    assert sync["featured_image"]["id"] == "media-1"
    assert sync["featured_image"]["source_id"] == "media:cover-1"
    assert sync["featured_image"]["revision"] == payload.media[0]["_helloadaRevision"]
    assert selection["media_id"] == "media-1"
    assert selection["media_revision"] == payload.media[0]["_helloadaRevision"]
    memory.close()


def test_normalized_title_collision_at_another_route_blocks_create_without_mutation(tmp_path):
    memory = Memory(tmp_path / "article-title-collision.db")
    payload = Payload()
    draft_id = memory.save_draft(
        title="Why That's Important",
        body="A distinct article body that still needs review.",
        kind="article",
    )
    payload.documents.append({
        "id": "existing-public-post",
        "slug": "why-thats-important-to-your-health",
        "title": "Why That’s Important",
        "published": True,
    })

    with pytest.raises(RuntimeError, match="same normalized title.*another route"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 0
    assert payload.updates == 0
    assert payload.publishes == 0
    assert len(payload.documents) == 1
    memory.close()


def test_title_inventory_does_not_block_nonmatching_title(tmp_path):
    memory = Memory(tmp_path / "article-title-not-a-collision.db")
    payload = Payload()
    draft_id = memory.save_draft(
        title="Why That's Important",
        body="A distinct article body that still needs review.",
        kind="article",
    )
    payload.documents.append({
        "id": "existing-public-post",
        "slug": "why-another-topic-matters",
        "title": "Why That Is Important",
        "published": True,
    })

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 1
    assert payload.publishes == 0
    memory.close()


def test_incomplete_capped_title_inventory_fails_closed_before_create(tmp_path):
    memory = Memory(tmp_path / "article-title-inventory-capped.db")
    payload = Payload()
    draft_id = memory.save_draft(
        title="A new article",
        body="A distinct article body.",
        kind="article",
    )
    payload.documents = [
        {
            "id": f"existing-{index}",
            "slug": f"existing-route-{index}",
            "title": f"Existing article {index}",
            "published": False,
        }
        for index in range(100)
    ]

    with pytest.raises(RuntimeError, match="inventory is incomplete"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 0
    assert payload.updates == 0
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

    assert payload.locales == ["en", "en", "en"]
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
        "id": "foreign-post", "sourceId": "posts:a-guide", "slug": "a-guide",
        "_helloadaRevision": "sha256:" + "d" * 64,
    })

    with pytest.raises(RuntimeError, match="not linked to Ada's exact sync record"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 0
    assert payload.updates == 0
    memory.close()



@pytest.mark.parametrize("modified_at_changed", [False, True])
def test_article_sync_adopts_exact_unpublished_payload_draft_after_local_checkpoint_loss(tmp_path, monkeypatch, modified_at_changed):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="An interrupted guide", body="Exact draft body.", kind="article")

    # Checkpoint-loss reconciliation reads the draft timestamp from the memory
    # mirror. Freeze it across both reads so wall-clock timing cannot decide
    # whether modifiedAt differs.
    original_list_drafts = memory.list_drafts
    fixed_updated_ts = "2026-01-01T00:00:00+00:00"
    def list_drafts_with_fixed_timestamp(*args, **kwargs):
        drafts = original_list_drafts(*args, **kwargs)
        for draft in drafts:
            if draft["id"] == draft_id:
                draft["updated_ts"] = fixed_updated_ts
        return drafts
    monkeypatch.setattr(memory, "list_drafts", list_drafts_with_fixed_timestamp)

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    original_document = deepcopy(payload.documents[0])
    assert original_document["modifiedAt"] == fixed_updated_ts
    payload.documents[0]["modifiedAt"] = "2026-02-01T00:00:00Z" if modified_at_changed else original_document["modifiedAt"]
    expected_updates = int(modified_at_changed)
    memory.update_draft_meta(draft_id, {})
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    current_document = payload.documents[0]
    assert payload.creates == 1
    assert payload.updates == expected_updates
    assert payload.publishes == 0
    assert current_document["modifiedAt"] == fixed_updated_ts
    assert {
        key: value for key, value in current_document.items() if key not in {"modifiedAt", "_helloadaRevision"}
    } == {
        key: value for key, value in original_document.items() if key not in {"modifiedAt", "_helloadaRevision"}
    }
    assert payload.documents[0]["_helloadaRevision"] == ("sha256:" + "b" * 64 if expected_updates else original_document["_helloadaRevision"])
    assert sync["state"] == "ready_for_review"
    assert sync["document_id"] == "post-1"
    assert sync["source_id"] == "posts:an-interrupted-guide"
    memory.close()




def test_article_sync_hydrates_only_an_empty_payload_draft_shell_with_revision_guard(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A migrated guide", body="The exact article body.", kind="article")
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    payload.documents[0].update({
        "title": "",
        "summary": "",
        "sections": [],
        "body": None,
        "seo": {},
        "featuredImage": None,
        "gallery": [],
        "author": "",
        "publishedAt": None,
        "published": True,
        "_status": "draft",
    })
    memory.update_draft_meta(draft_id, {})

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    document = payload.documents[0]
    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert payload.creates == 1
    assert payload.updates == 1
    assert payload.publishes == 0
    assert document["title"] == "A migrated guide"
    assert document["body"]["root"]["type"] == "root"
    assert document["published"] is False
    assert document["_status"] == "draft"
    assert sync["state"] == "ready_for_review"
    assert sync["validation"]["status"] == "passed"
    memory.close()


def test_article_sync_does_not_hydrate_an_empty_published_payload_record(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A protected guide", body="Candidate body.", kind="article")
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    payload.documents[0].update({
        "title": "",
        "summary": "",
        "sections": [],
        "body": None,
        "seo": {},
        "featuredImage": None,
        "gallery": [],
        "author": "",
        "publishedAt": "2026-08-28T00:00:00Z",
        "published": True,
        "_status": "published",
    })
    memory.update_draft_meta(draft_id, {})

    with pytest.raises(RuntimeError, match="neither Ada's exact draft nor an empty schema draft"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 1
    assert payload.updates == 0
    assert payload.publishes == 0
    memory.close()


def test_article_sync_updates_only_system_fields_on_exact_adoption_with_revision_guard(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="An exact guide", body="Exact body.", kind="article")
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    memory.update_draft_meta(draft_id, {})
    payload.documents[0]["canonicalUrl"] = "https://old.example/wrong-route"

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert payload.creates == 1
    assert payload.updates == 1
    assert payload.documents[0]["canonicalUrl"] == "https://business.example/blog/an-exact-guide"
    assert payload.documents[0]["title"] == "An exact guide"
    assert payload.documents[0]["body"] == payload.created_data[0]["body"]
    assert payload.publishes == 0
    assert sync["state"] == "ready_for_review"
    memory.close()

def test_article_sync_recovers_exact_route_conflict_race_without_duplicate_or_publish(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    payload.conflict_after_create = True
    draft_id = memory.save_draft(title="A route race", body="Exact draft body.", kind="article")

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert payload.creates == 1
    assert len(payload.documents) == 1
    assert payload.updates == 0
    assert payload.publishes == 0
    assert sync["state"] == "ready_for_review"
    memory.close()


def test_article_sync_never_adopts_published_or_different_content(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A safe guide", body="Ada's exact body.", kind="article")
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    memory.update_draft_meta(draft_id, {})
    payload.documents[0]["published"] = True

    with pytest.raises(RuntimeError, match="content differs"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 1
    assert payload.updates == 0
    assert payload.documents[0]["published"] is True
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


def test_article_without_analyzed_payload_cover_is_blocked_before_post_creation(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    payload.media = []
    context = _context(memory, payload)
    context["llm"] = None
    draft_id = memory.save_draft(
        title="A guide that needs a cover",
        body="A complete article body.",
        kind="article",
    )

    _mirror_article_drafts(context)

    draft = next(item for item in memory.list_drafts() if item["id"] == draft_id)
    sync = draft["meta"]["payload_sync"]
    assert payload.creates == 0
    assert sync["state"] == "blocked"
    assert sync["validation"]["status"] == "blocked"
    assert "Payload Library has no analyzed image with alt text" in sync["validation"]["reason"]
    memory.close()


def test_article_does_not_attach_an_image_not_returned_by_the_library(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    context = _context(memory, payload)
    context["llm"].chat = lambda *_args, **_kwargs: json.dumps({
        "media_id": "not-in-this-tenant-library",
        "reason": "This cannot be trusted.",
    })
    draft_id = memory.save_draft(title="A safe guide", body="Complete article body.", kind="article")

    _mirror_article_drafts(context)

    draft = next(item for item in memory.list_drafts() if item["id"] == draft_id)
    assert payload.creates == 0
    assert draft["meta"]["payload_sync"]["state"] == "blocked"
    assert "no suitable analyzed Payload Library image" in draft["meta"]["payload_sync"]["validation"]["reason"]
    memory.close()


def test_article_sync_stops_if_selected_cover_revision_changes(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    draft_id = memory.save_draft(title="A cover-safe guide", body="Complete article body.", kind="article")

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    payload.media[0]["_helloadaRevision"] = "sha256:" + "8" * 64

    with pytest.raises(RuntimeError, match="cover image changed after Ada chose it"):
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert payload.creates == 1
    assert payload.updates == 0
    memory.close()
