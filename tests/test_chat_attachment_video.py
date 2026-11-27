"""The owner can attach a clip, and Ada reads it as a clip.

The media library holds videos as well as images, and the gallery hands one to
the chat as an attachment. Every layer that validated an attachment only knew
the word "image", so choosing a clip and pressing "Use in Ada" was rejected
before the owner ever reached the model: the conversation service refused it
with "not an image", and the local library service refused it with "no longer
available". A clip was usable in every other part of the product and unusable
in the one place the gallery points at.
"""

from __future__ import annotations

import pytest

from site_agent.hands.payload_gateway import PayloadGatewayError, PayloadMediaService

CLIP = {
    "id": 21, "filename": "studio-tour.mp4", "mimeType": "video/mp4",
    "url": "/api/media/file/studio-tour.mp4",
}
STILL = {
    "id": 4, "filename": "abaji.webp", "mimeType": "image/webp",
    "width": 170, "height": 170, "url": "/api/media/file/abaji.webp",
}


class _Payload:
    base_url = "https://tenant.test"

    def __init__(self, documents):
        self.documents = {int(document["id"]): document for document in documents}

    def read_media(self, identifier, *, identifier_kind="id", draft=True):
        assert identifier_kind == "id"
        return self.documents[int(identifier)]


def _service(*documents):
    return PayloadMediaService(_Payload(documents))


def test_a_clip_reaches_the_conversation_as_a_clip():
    resolved = _service(STILL, CLIP).resolve_attachments([21])

    assert [row["asset_id"] for row in resolved] == [21]
    # The model has to be told it is a clip; a video described as an image is a
    # lie the turn then builds on.
    assert resolved[0]["content_type"] == "video/mp4"
    assert resolved[0]["kind"] == "video"


def test_a_still_still_reaches_the_conversation_as_a_still():
    resolved = _service(STILL, CLIP).resolve_attachments([4])

    assert resolved[0]["content_type"] == "image/webp"
    assert resolved[0]["kind"] == "image"


def test_a_still_and_a_clip_together_keep_the_owner_s_order():
    resolved = _service(STILL, CLIP).resolve_attachments([21, 4])

    assert [(row["asset_id"], row["position"]) for row in resolved] == [(21, 0), (4, 1)]


def test_a_file_the_library_cannot_describe_is_still_refused():
    # A PDF is in the library but is not something the chat accepts, and a
    # refused attachment must name why rather than arrive as a broken turn.
    document = {"id": 5, "filename": "menu.pdf", "mimeType": "application/pdf", "url": "/api/media/file/menu.pdf"}

    with pytest.raises(PayloadGatewayError, match="video or an image"):
        _service(document).resolve_attachments([5])


def test_the_bridge_queue_accepts_a_clip_through_the_real_enqueue_path(tmp_path):
    """The rejection the owner saw happened before any model ran.

    This drives the same application-service path the bridge uses, so a clip is
    proven attachable end to end rather than only inside the media adapter.
    """
    from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
    from site_agent.core.memory import Memory
    from site_agent.hands.payload_gateway import PayloadMediaService

    class _Payload:
        base_url = "https://tenant.test"

        def read_media(self, identifier, *, identifier_kind="id", draft=True):
            return CLIP

    memory = Memory(tmp_path / "clip.db")
    try:
        tenant = Tenant(
            tenant_id="clip-attachment",
            config={"chat": {"engine": "legacy"}},
            memory=memory,
            runtime=None,
            context={
                "llm": object(),
                "media_service": PayloadMediaService(_Payload()),
            },
            api_token="clip-token",
        )
        service = ChatService(registry=TenantRegistry({tenant.tenant_id: tenant}), llm=object())
        queued = service.enqueue(
            {"message": "Use this clip on the homepage", "attachments": [{"asset_id": 21}]},
            tenant=tenant,
        )
        job = memory.get_chat_job(queued["job_id"])
        assert job is not None
        stored = memory.get_messages(queued["conversation_id"])[-1]
        assert stored["attachments"] == [{"asset_id": 21, "position": 0}]
    finally:
        memory.close()


def test_a_clip_keeps_its_own_container_when_placed_in_a_build(tmp_path):
    """A build must hand the builder the clip, not a WebP of its bytes.

    Materializing every attachment as WebP turned an MP4 into a corrupt file the
    builder then rendered as a broken image, so the clip was attachable but
    unusable in the one place it was attached for.
    """
    import pathlib

    from site_agent.hands.opencode_runner import (
        RunnerError,
        _materialize_media,
        _verify_materialized_media,
    )
    from site_agent.hands.payload_gateway import PayloadMediaAsset

    clip = b"\x00\x00\x00\x18ftypmp42" + b"payload" * 8

    class _Service:
        def __init__(self, name="studio.mp4"):
            self.name = name

        def resolve_attachments(self, ids):
            return [{"asset_id": 21, "position": 0, "kind": "video"}]

        def get(self, asset_id):
            return PayloadMediaAsset(
                asset_id=21, original_name=self.name, content_type="video/mp4",
                original_size=len(clip), width=1920, height=1080, description="",
                tags=(), ocr_text="", analysis={}, url="u", alt_text="",
                analysis_status="ready",
            )

        def read_preview(self, asset_id, thumbnail=False):
            return clip, "video/mp4"

    def build_dir():
        root = pathlib.Path(tmp_path / "worktree")
        (root / "public" / "media").mkdir(parents=True, exist_ok=True)
        return root

    context = {
        "_media_asset_ids": [21],
        "config": {"site": {"media": {"site_asset_dir": "public/media"}}},
    }
    root = build_dir()
    context["media_service"] = _Service()
    paths = _materialize_media(context, root)

    assert paths == ["public/media/ada-21-studio.mp4"]
    assert (root / paths[0]).read_bytes() == clip
    _verify_materialized_media(context, root, paths)

    # A clip with no extension cannot be placed honestly, so it fails closed
    # rather than becoming a WebP-named video.
    context["media_service"] = _Service(name="clip-no-extension")
    with pytest.raises(RunnerError, match="no file extension"):
        _materialize_media(context, build_dir())
