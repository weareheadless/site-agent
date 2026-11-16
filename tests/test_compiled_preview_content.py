from types import SimpleNamespace

import pytest

from site_agent.application.compiled_preview_content import MAX_PREVIEW_DOCUMENTS, canonical_preview_snapshot

CONTRACT = {
    "locales": ["en"], "defaultLocale": "en",
    "enabled": {"collections": ["pages"]},
    "authoring": {"collections": {"pages": []}, "globals": {"navigation": [], "siteSettings": []}},
}


def _gateway(draft_revision="a", indexed=None):
    effect_revision = "sha256:" + draft_revision * 64
    draft = {"id": 1, "title": "Candidate", "_helloadaRevision": effect_revision}
    index = ([{"collection": "pages", "id": "1", "status": "published"}]
             if indexed is None else indexed)
    return SimpleNamespace(
        base_url="https://tenant.example",
        require_authoring_contract=lambda: CONTRACT,
        workspace_index=lambda: {"routes": [], "documents": index},
        read=lambda collection, identifier, **kwargs: dict(draft),
        read_global=lambda slug, **kwargs: {"siteName": "Site", "_status": "published"},
        list_media=lambda **kwargs: [],
        read_media=lambda identifier, **kwargs: {"id": identifier},
    )


def _effect():
    return {"kind": "collection", "target": "pages", "document_id": "1", "locale": "en",
            "revision": "sha256:" + "a" * 64}


def test_preview_import_uses_the_exact_candidate_revision():
    snapshot = canonical_preview_snapshot(_gateway(), [_effect()])
    assert snapshot["defaultLocale"] == "en"
    assert snapshot["documents"] == [{"collection": "pages", "id": "1",
                                      "locales": {"en": {"id": 1, "title": "Candidate",
                                                         "_helloadaRevision": "sha256:" + "a" * 64}}}]
    # Rendered pages read the shared globals, so the preview always carries the
    # published values even when the candidate does not touch them.
    assert [item["slug"] for item in snapshot["globals"]] == ["navigation", "siteSettings"]


def test_preview_rejects_a_changed_candidate_revision():
    with pytest.raises(ValueError, match="revision changed"):
        canonical_preview_snapshot(_gateway(draft_revision="b"), [_effect()])


def test_preview_reads_every_document_not_only_one_gateway_page():
    """A catalog larger than one list page is previewed completely.

    Casamigo has 365 published products. The preview used to ask the collection
    list for one page of 100 and then refuse the build because a full page
    proved it could not see the rest of the site; the complete snapshot is
    every document the workspace index names.
    """
    index = [{"collection": "pages", "id": str(number), "status": "published"}
             for number in range(250)]
    gateway = _gateway(indexed=index)
    gateway.require_authoring_contract = lambda: {
        **CONTRACT, "enabled": {"collections": ["pages", "products"]},
        "authoring": {"collections": {"pages": [], "products": []},
                      "globals": {"navigation": [], "siteSettings": []}},
    }
    def read(collection, identifier, **kwargs):
        return {"id": identifier, "_status": "published", "slug": f"page-{identifier}"}
    gateway.read = read

    snapshot = canonical_preview_snapshot(gateway, [])

    assert len(snapshot["documents"]) == 250
    assert [item["id"] for item in snapshot["documents"]] == [str(number) for number in range(250)]


def test_preview_refuses_a_site_beyond_the_declared_bound_instead_of_truncating():
    index = [{"collection": "pages", "id": str(number), "status": "published"}
             for number in range(MAX_PREVIEW_DOCUMENTS + 1)]
    with pytest.raises(ValueError, match=f"at most {MAX_PREVIEW_DOCUMENTS}"):
        canonical_preview_snapshot(_gateway(indexed=index), [])


def test_preview_copies_the_media_its_documents_reference(monkeypatch):
    """Upload relations travel as IDs, so the schema decides what is media.

    The bounded library copy alone cannot cover a large catalog: Casamigo's
    properties reference gallery IDs outside the newest part of its library, and
    the seed drops any upload whose bytes were not copied.
    """
    from site_agent.hands.payload_gateway import PayloadMediaService

    seen = {}
    monkeypatch.setattr(PayloadMediaService, "read_preview",
                        lambda self, asset_id, **kwargs: (b"image", "image/jpeg"))
    gateway = _gateway()
    gateway.require_authoring_contract = lambda: {
        **CONTRACT,
        "authoring": {
            "collections": {"pages": [
                {"name": "featuredImage", "type": "upload"},
                {"name": "gallery", "type": "upload", "hasMany": True},
            ]},
            "globals": {"navigation": [], "siteSettings": []},
        },
    }
    gateway.read = lambda collection, identifier, **kwargs: {
        "id": identifier, "_status": "published", "slug": "home",
        "featuredImage": 41, "gallery": [507, 508],
    }
    def read_media(identifier, **kwargs):
        seen[str(identifier)] = kwargs
        return {"id": identifier, "filename": f"{identifier}.jpg", "mimeType": "image/jpeg",
                "url": f"/media/{identifier}.jpg"}
    gateway.read_media = read_media

    snapshot = canonical_preview_snapshot(gateway, [])

    assert [item["document"]["id"] for item in snapshot["media"]] == ["41", "507", "508"]


def test_preview_does_not_import_unpublished_locale_baselines_outside_candidate_effects():
    gateway = _gateway()
    gateway.require_authoring_contract = lambda: {**CONTRACT, "locales": ["en", "es"], "defaultLocale": "es"}
    def read(collection, identifier, *, draft, locale, **kwargs):
        return {"id": 1, "_status": "draft", "sections": [{"label": "Candidate" if locale == "en" else None}],
                "_helloadaRevision": "sha256:" + "a" * 64}
    gateway.read = read
    snapshot = canonical_preview_snapshot(gateway, [_effect()])
    assert set(snapshot["documents"][0]["locales"]) == {"en"}


def test_preview_retains_published_locale_baselines():
    gateway = _gateway()
    gateway.read = lambda *args, **kwargs: {"id": 1, "_status": "published", "title": "Published content"}
    snapshot = canonical_preview_snapshot(gateway, [])
    assert snapshot["documents"][0]["locales"]["en"]["title"] == "Published content"


def test_preview_does_not_publish_a_global_that_was_never_published():
    """A draft-only global has no published content to carry into the preview.

    `inmersion`'s siteSettings was never filled, so its only version is a draft
    with an empty required business name. The preview seed writing that as
    published failed Payload validation and blocked the whole preview, on a
    global the site never reads.
    """
    gateway = _gateway()
    gateway.read_global = lambda slug, **kwargs: (
        {"items": [{"key": "primary.about"}], "_status": "published"} if slug == "navigation"
        else {"address": {}, "_status": "draft"}
    )
    snapshot = canonical_preview_snapshot(gateway, [])
    assert [item["slug"] for item in snapshot["globals"]] == ["navigation"]


def test_preview_carries_a_global_the_live_site_already_renders():
    """A never-published global is what production shows, so the preview shows it.

    Oceanic's navigation global was saved but never published. Its public read
    returns the saved items with `_status: draft`, and every live page renders
    them, so a preview that skipped the global showed a header with no menu.
    """
    gateway = _gateway()
    def read_global(slug, **kwargs):
        if slug == "navigation":
            return {"id": 1, "_status": "draft", "globalType": "navigation",
                    "items": [{"key": "primary.about", "label": "About", "href": "/about"}]}
        return {"id": 1, "_status": "published", "siteName": "OceanicVibes"}
    gateway.read_global = read_global
    snapshot = canonical_preview_snapshot(gateway, [])
    by_slug = {item["slug"]: item for item in snapshot["globals"]}
    assert by_slug["navigation"]["locales"]["en"]["items"][0]["label"] == "About"
    assert by_slug["siteSettings"]["locales"]["en"]["siteName"] == "OceanicVibes"


def test_preview_still_skips_a_global_with_nothing_saved():
    gateway = _gateway()
    gateway.read_global = lambda slug, **kwargs: (
        {"id": 1, "_status": "draft", "globalType": slug, "items": []} if slug == "navigation"
        else {"id": 1, "_status": "draft", "siteName": "", "logo": None, "address": {}}
    )
    assert canonical_preview_snapshot(gateway, [])["globals"] == []

def test_preview_skips_a_locale_the_live_site_cannot_route():
    """A document with no public route in a locale is not part of that site.

    Casamigo's older gateway refuses a published read in a locale whose
    translation has no route slug. The live site cannot link to that document in
    that language, so the preview carries the locales the site actually serves
    instead of failing the whole build.
    """
    from site_agent.hands.payload_gateway import PayloadGatewayError

    gateway = _gateway()
    gateway.require_authoring_contract = lambda: {
        **CONTRACT, "locales": ["en", "es"],
        "authoring": {"collections": {"pages": []}, "globals": {"navigation": [], "siteSettings": []}},
    }
    def read(collection, identifier, *, locale, **kwargs):
        if locale == "es":
            raise PayloadGatewayError("Payload gateway returned 409: no public route", status_code=409)
        return {"id": identifier, "_status": "published", "slug": "home"}
    gateway.read = read

    snapshot = canonical_preview_snapshot(gateway, [])

    assert set(snapshot["documents"][0]["locales"]) == {"en"}
    assert snapshot["omitted"] == [{"collection": "pages", "locale": "es", "documents": 1}]


def test_preview_still_fails_on_a_gateway_error_that_is_not_a_missing_route():
    from site_agent.hands.payload_gateway import PayloadGatewayError

    gateway = _gateway()
    gateway.read = lambda *args, **kwargs: (_ for _ in ()).throw(
        PayloadGatewayError("Payload gateway returned 503: unavailable", status_code=503))

    with pytest.raises(PayloadGatewayError):
        canonical_preview_snapshot(gateway, [])
