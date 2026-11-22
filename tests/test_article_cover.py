"""An article's own chosen photograph is a valid cover.

The landing path used to require an already-analysed image in the tenant's
Payload library. On a site whose library holds only a logo, that blocked every
real article on a gallery nobody had filled — while the article itself arrived
with a photograph chosen for it, described and credited. The cover is the
article's, so the landing stores it once and pins its exact revision.
"""

from __future__ import annotations

import io

import pytest

from site_agent.core.jobs import _article_cover_image
from site_agent.core.memory import Memory

COVER = {
    "id": "img_1",
    "role": "cover",
    "source": "unsplash",
    "photo_id": "photo-abc123",
    "url": "https://images.example/photo-abc123.jpg",
    "alt": "A red carpet staircase at an awards venue",
    "credit": "Photo by Krisztian Tabori on Unsplash",
}


class Payload:
    """A media library that behaves like the bridge: upload returns no revision."""

    def __init__(self, *, library=None):
        self.uploads = []
        self.media = {str(row["id"]): dict(row) for row in library or []}
        self.revision = "sha256:" + "c" * 64

    def read_media(self, identifier, *, identifier_kind="id", draft=True):
        for document in self.media.values():
            if identifier_kind == "id" and str(document.get("id")) == str(identifier):
                return dict(document)
            if identifier_kind == "sourceId" and str(document.get("sourceId")) == str(identifier):
                return dict(document)
        error = RuntimeError("media not found")
        error.status_code = 404
        raise error

    def list_media(self, *, draft=True, limit=100):
        return [dict(row) for row in list(self.media.values())[:limit]]

    def upload_media(self, *, content, filename, content_type, alt, source_id):
        self.uploads.append(
            {"filename": filename, "content_type": content_type, "alt": alt, "source_id": source_id}
        )
        document = {
            "id": "media-77",
            "sourceId": source_id,
            "alt": alt,
            "url": "/api/media/file/stored.jpg",
            "analysisStatus": "pending",
        }
        self.media["media-77"] = {**document, "_helloadaRevision": self.revision}
        return {**document, "asset_id": "media-77"}


def _context(tmp_path, *, cover=True):
    memory = Memory(tmp_path / "memory.db")
    meta = {"article_assets": [COVER]} if cover else {}
    draft_id = memory.save_draft(
        title="Los looks de la alfombra",
        body="## Sección\n\nTexto.",
        kind="article",
        meta=meta,
    )
    context = {
        "memory": memory,
        "config": {"site": {"url": "https://business.example", "language": "es"}},
    }
    return context, memory, memory.get_draft(draft_id)


@pytest.fixture(autouse=True)
def public_image(monkeypatch):
    class Response(io.BytesIO):
        headers = {"Content-Type": "image/jpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, timeout=None: Response(b"\xff\xd8\xff" + b"x" * 400),
    )


def test_the_articles_chosen_cover_is_stored_and_pinned(tmp_path):
    payload = Payload()
    context, memory, draft = _context(tmp_path)

    media_id, media, selection = _article_cover_image(context, payload, draft, draft["meta"])

    assert media_id == "media-77"
    assert payload.uploads[0]["source_id"] == "article-cover:photo-abc123"
    assert payload.uploads[0]["alt"] == COVER["alt"]
    assert selection["attributed"] is True
    assert selection["media_revision"] == payload.revision
    saved = memory.list_drafts()[0]["meta"]["article_image_selection"]
    assert saved["media_id"] == "media-77"
    assert saved["media_revision"] == payload.revision


def test_a_second_preparation_reuses_the_stored_cover(tmp_path):
    payload = Payload()
    context, memory, draft = _context(tmp_path)
    first_id, _, _ = _article_cover_image(context, payload, draft, draft["meta"])
    assert first_id == "media-77"
    uploads = list(payload.uploads)

    # Even with the local selection forgotten, the upstream asset identity finds
    # the stored document instead of uploading the photograph again.
    refreshed = memory.get_draft(int(draft["id"]))
    meta = dict(refreshed["meta"])
    meta.pop("article_image_selection", None)
    second_id, _, _ = _article_cover_image(context, payload, refreshed, meta)

    assert second_id == "media-77"
    assert payload.uploads == uploads


def test_a_library_image_without_analysis_still_cannot_be_chosen_by_ada(tmp_path):
    """The relaxation is only for the article's own attributed cover.

    An unanalysed library image is refused at the candidate filter, before Ada
    is asked to choose: analysis is what makes a library image legible to the
    chooser in the first place.
    """
    payload = Payload(
        library=[
            {
                "id": "media-9",
                "sourceId": "media:9",
                "alt": "A logo",
                "url": "/api/media/file/logo.png",
                "analysisStatus": "pending",
                "_helloadaRevision": "sha256:" + "e" * 64,
            }
        ]
    )
    context, memory, draft = _context(tmp_path, cover=False)

    with pytest.raises(RuntimeError, match="no analyzed image"):
        _article_cover_image(context, payload, draft, draft["meta"])


def test_an_analysed_but_irrelevant_library_image_is_refused(tmp_path):
    payload = Payload(
        library=[
            {
                "id": "media-9",
                "sourceId": "media:9",
                "alt": "A black and white logo",
                "url": "/api/media/file/logo.png",
                "analysisStatus": "ready",
                "_helloadaRevision": "sha256:" + "e" * 64,
            }
        ]
    )
    context, memory, draft = _context(tmp_path, cover=False)
    context["llm"] = type(
        "Selector",
        (),
        {
            "chat": lambda self, messages, **kwargs: (
                '{"media_id": null, "reason": "Only a logo is available; a cover needs a photograph."}'
            )
        },
    )()

    with pytest.raises(RuntimeError, match="no suitable analyzed Payload Library image"):
        _article_cover_image(context, payload, draft, draft["meta"])
