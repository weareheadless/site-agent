from __future__ import annotations

from site_agent.core.chat_jobs import _with_attachment_context
from site_agent.core.memory import Memory


class _Media:
    def __init__(self) -> None:
        self.ids: list[int] = []

    def resolve_attachments(self, asset_ids):
        self.ids = list(asset_ids)
        return [{
            "asset_id": 4, "position": 0, "width": 170, "height": 170,
            "description": "", "alt_text": "abaji.webp",
        }]


def test_attachments_are_resolved_by_message_identity_not_visible_text(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        conversation = memory.create_conversation(title="about")
        message_id = memory.add_message(
            conversation, "user", "use that picture for profile face",
            [{"asset_id": 4, "position": 0}],
        )
        media = _Media()
        context: dict = {}

        # The job carries the contextual message, which never equals the stored
        # visible text. Attachments must still reach the agent.
        message = _with_attachment_context(
            memory, media, message_id,
            "[Owner workspace context]\n\n[User request]\nuse that picture for profile face",
            context,
        )

        assert media.ids == [4]
        assert context["_media_asset_ids"] == [4]
        assert "Asset #4" in message
        assert "abaji.webp" in message
    finally:
        memory.close()


def test_a_turn_without_attachments_is_unchanged(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        conversation = memory.create_conversation(title="plain")
        message_id = memory.add_message(conversation, "user", "hello", [])
        context: dict = {}

        message = _with_attachment_context(memory, _Media(), message_id, "hello", context)

        assert message == "hello"
        assert context["_media_asset_ids"] == []
    finally:
        memory.close()


def test_an_unknown_message_id_does_not_add_attachment_context(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        context: dict = {}

        message = _with_attachment_context(memory, _Media(), 999, "hello", context)

        assert message == "hello"
        assert context["_media_asset_ids"] == []
    finally:
        memory.close()
