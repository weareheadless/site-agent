"""One article, as many editions as the site publishes.

A bilingual site does not carry two articles with two approvals. It carries one
article and each locale is an edition of it: the same evidence, the same
argument, told in the reader's language. The landing therefore writes every
edition into the one Payload document and records each edition's exact route and
revision, so publication and readback can walk all of them.
"""

from __future__ import annotations

import json

from site_agent.core.jobs import (
    _mirror_article_draft_to_workspace,
    article_landed_editions,
)
from site_agent.core.memory import Memory

LOCALIZED = ("title", "slug", "summary", "body", "seo", "featuredImage", "author")

POST_FIELDS = [
    "title", "slug", "summary", "body", "featuredImage", "gallery", "author",
    "publishedAt", "modifiedAt", "category", "canonicalUrl", "seo", "published",
]

ES = {
    "locale": "es",
    "title": "Los looks de la alfombra roja",
    "slug": "los-looks-de-la-alfombra-roja",
    "body": "## El look\n\nEl maquillaje se jugó en dos zonas.",
    "excerpt": "Los looks y los productos exactos.",
    "meta_description": "Los looks y los productos exactos de la noche.",
    "primary_keyword": "maquillaje alfombra roja",
}
EN = {
    "locale": "en",
    "title": "The red carpet looks",
    "slug": "the-red-carpet-looks",
    "body": "## The look\n\nThe makeup was decided in two places.",
    "excerpt": "The looks and the exact products.",
    "meta_description": "The looks and the exact products of the night.",
    "primary_keyword": "red carpet makeup",
}


class BilingualPayload:
    """A media library plus one document with a row per locale, like Payload."""

    def __init__(self):
        self.authoring_contract = {
            "locales": ["es", "en"],
            "defaultLocale": "es",
            "enabled": {"collections": ["posts"], "globals": []},
            "authoring": {
                "collections": {
                    "posts": [
                        {"name": "seo", "type": "group", "fields": [
                            {"name": "title"}, {"name": "description"}, {"name": "image"},
                        ]},
                        *[{"name": field} for field in POST_FIELDS if field != "seo"],
                    ],
                },
                "globals": {},
            },
        }
        # One document identity; each locale is a row of it, as Payload stores
        # localized fields.
        self.rows: dict[str, dict[str, dict]] = {}
        self.created_locales: list[str] = []
        self.updated_locales: list[str] = []
        self.media = [{
            "id": "media-1",
            "sourceId": "article-cover:photo-1",
            "alt": "A red carpet staircase",
            "url": "/api/media/file/red.jpg",
            "analysisStatus": "pending",
            "_helloadaRevision": "sha256:" + "9" * 64,
        }]

    def require_authoring_contract(self):
        return self.authoring_contract

    def authoring_fields(self, kind, slug, *, authoring_contract=None):
        contract = authoring_contract or self.authoring_contract
        return tuple(field["name"] for field in contract["authoring"]["collections"][slug])

    def list(self, collection, *, draft=True, limit=100, locale=None):
        return [dict(row) for row in self.rows.get(locale, {}).values()][:limit]

    def list_media(self, *, draft=True, limit=100):
        return [dict(row) for row in self.media]

    def read_media(self, identifier, *, identifier_kind="id", draft=True):
        for row in self.media:
            if str(row.get(identifier_kind)) == str(identifier):
                return dict(row)
        error = RuntimeError("media not found")
        error.status_code = 404
        raise error

    def upload_media(self, *, content, filename, content_type, alt, source_id):
        document = {
            "id": "media-1", "sourceId": source_id, "alt": alt,
            "url": "/api/media/file/red.jpg", "analysisStatus": "pending",
        }
        self.media = [{**document, "_helloadaRevision": "sha256:" + "9" * 64}]
        return {**document, "asset_id": "media-1"}

    def create(self, collection, data, *, locale=None):
        self.created_locales.append(locale)
        document = {
            **data, "id": "post-1", "sourceId": f"posts:{data['slug']}",
            "_status": "draft", "_helloadaRevision": "sha256:" + "a" * 64,
        }
        # Payload stores localized fields per locale. Creating with one locale
        # leaves the other locales present but unwritten, which is exactly the
        # state an untranslated post is in: a document with no route there.
        for enabled in self.authoring_contract["locales"]:
            row = dict(document)
            if enabled != locale:
                for field in LOCALIZED:
                    row[field] = None
                row["_helloadaRevision"] = "sha256:" + "c" * 64
            self.rows.setdefault(enabled, {})["post-1"] = row
        return dict(self.rows[locale]["post-1"])

    def read(self, collection, *, identifier, identifier_kind, draft, locale=None):
        rows = self.rows.get(locale, {})
        for row in rows.values():
            if str(row.get(identifier_kind)) == str(identifier):
                return dict(row)
        error = RuntimeError("not found")
        error.status_code = 404
        raise error

    def update(self, collection, document_id, data, *, locale=None, expected_hash=None):
        self.updated_locales.append(locale)
        row = self.rows[locale][document_id]
        assert expected_hash == row["_helloadaRevision"]
        row.update(data, _helloadaRevision="sha256:" + "b" * 64)
        return dict(row)


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
        "config": {"site": {"url": "https://business.example"}, "persona": {"name": "Ada"}},
    }


def _draft(memory, *, editions=(ES, EN)):
    return memory.save_draft(
        title=ES["title"],
        body=ES["body"],
        kind="article",
        meta={
            "article_editions": [dict(row) for row in editions],
            "article_assets": [{
                "id": "img_1", "role": "cover", "photo_id": "photo-1",
                "url": "https://images.example/photo-1.jpg",
                "alt": "A red carpet staircase",
                "credit": "Photo by Someone on Unsplash",
            }],
        },
    )


def test_both_editions_land_in_the_one_payload_document(tmp_path):
    memory = Memory(tmp_path / "bilingual.db")
    payload = BilingualPayload()
    draft_id = _draft(memory)

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    sync = memory.list_drafts()[0]["meta"]["payload_sync"]
    assert sync["state"] == "ready_for_review", sync["validation"]
    # One article, one approval: both editions of one document.
    assert {row["document_id"] for row in sync["editions"]} == {"post-1"}
    assert [row["locale"] for row in sync["editions"]] == ["es", "en"]
    assert [row["slug"] for row in sync["editions"]] == [ES["slug"], EN["slug"]]

    # Each edition is written in its own language, with its own route.
    spanish = payload.rows["es"]["post-1"]
    english = payload.rows["en"]["post-1"]
    assert spanish["title"] == ES["title"]
    assert spanish["slug"] == ES["slug"]
    assert english["title"] == EN["title"]
    assert english["slug"] == EN["slug"]
    assert english["summary"] == EN["excerpt"]
    assert english["seo"]["description"] == EN["meta_description"]
    # The shared seo group declares no focus keyword.
    assert "focusKeyword" not in english["seo"]
    # One cover, chosen for the piece, shared by its editions.
    assert spanish["featuredImage"] == english["featuredImage"] == "media-1"
    # The article is created once, in the primary locale; its other editions are
    # rows written into that same document, never a second article.
    assert payload.created_locales == ["es"]
    assert payload.updated_locales == ["en"]


def test_each_edition_records_its_own_exact_revision(tmp_path):
    memory = Memory(tmp_path / "revisions.db")
    payload = BilingualPayload()
    draft_id = _draft(memory)

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    editions = article_landed_editions(memory.list_drafts()[0])
    assert len(editions) == 2
    for edition in editions:
        row = payload.rows[edition["locale"]]["post-1"]
        assert edition["draft_hash"] == row["_helloadaRevision"]
        assert edition["document_id"] == "post-1"
        assert edition["slug"] == row["slug"]


def test_repreparing_updates_both_editions_instead_of_duplicating_them(tmp_path):
    memory = Memory(tmp_path / "reprepare.db")
    payload = BilingualPayload()
    draft_id = _draft(memory)

    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    assert len(payload.rows["es"]) == 1
    assert len(payload.rows["en"]) == 1
    assert payload.created_locales == ["es"]
    assert payload.updated_locales == ["en"]
    assert memory.list_drafts()[0]["meta"]["payload_sync"]["state"] == "ready_for_review"


def test_a_missing_second_edition_is_reported_not_silently_published(tmp_path):
    """A bilingual article whose English row vanished must not pass as bilingual."""
    memory = Memory(tmp_path / "missing.db")
    payload = BilingualPayload()
    draft_id = _draft(memory)
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    del payload.rows["en"]["post-1"]
    draft = memory.get_draft(draft_id)
    meta = dict(draft["meta"])
    meta.pop("payload_sync")
    memory.update_draft_meta(draft_id, meta)

    try:
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    except RuntimeError as exc:
        assert "no readable 'en' edition" in str(exc)
    else:  # pragma: no cover - a silent pass would publish one language as two
        raise AssertionError("a missing edition must be reconciled, never ignored")


def test_an_owner_written_second_edition_is_never_overwritten(tmp_path):
    """Landing a new language must not clobber one the owner wrote by hand."""
    memory = Memory(tmp_path / "owner-edition.db")
    payload = BilingualPayload()
    draft_id = _draft(memory, editions=(ES,))
    _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)

    # The owner writes the English edition in Payload themselves.
    payload.rows["en"]["post-1"].update({
        "title": "An owner-written title",
        "slug": "an-owner-written-title",
        "body": {"root": {"type": "root", "children": []}},
        "featuredImage": None,
    })
    payload.updated_locales.clear()

    draft = memory.get_draft(draft_id)
    meta = dict(draft["meta"])
    meta["article_editions"] = [dict(ES), dict(EN)]
    memory.update_draft_meta(draft_id, meta)

    try:
        _mirror_article_draft_to_workspace(_context(memory, payload), draft_id)
    except RuntimeError as exc:
        assert "identity changed" in str(exc) or "not Ada's exact candidate" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an owner-written edition must remain unchanged")
    assert payload.rows["en"]["post-1"]["title"] == "An owner-written title"
