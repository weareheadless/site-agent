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
        read_global=lambda slug, **kwargs: {"slug": slug},
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
    assert snapshot["globals"] == []


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
