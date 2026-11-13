from types import SimpleNamespace

import pytest

from site_agent.application.compiled_preview_content import canonical_preview_snapshot

CONTRACT = {"locales": ["en"], "defaultLocale": "en", "enabled": {"collections": ["pages"]}}


def _gateway(draft_revision="a", rows=None):
    effect_revision = "sha256:" + draft_revision * 64
    draft = {"id": 1, "title": "Candidate", "_helloadaRevision": effect_revision}
    return SimpleNamespace(
        require_authoring_contract=lambda: CONTRACT,
        list=lambda *args, **kwargs: rows if rows is not None else [{"id": 1}],
        read=lambda collection, identifier, **kwargs: dict(draft),
        read_global=lambda slug, **kwargs: {"siteName": "Site", "_status": "published"},
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


def test_preview_never_truncates_canonical_content():
    with pytest.raises(ValueError, match="complete bounded"):
        canonical_preview_snapshot(_gateway(rows=[{"id": number} for number in range(100)]), [])


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
