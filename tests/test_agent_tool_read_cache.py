from __future__ import annotations

from site_agent.application import agent_tools
from site_agent.core.memory import Memory

REVISION = "sha256:" + "a" * 64


class _Payload:
    def __init__(self) -> None:
        self.updated: dict | None = None

    def require_authoring_contract(self):
        return {
            "locales": ["en"],
            "defaultLocale": "en",
            "enabled": {"collections": ["pages"], "globals": []},
            "authoring": {
                "collections": {"pages": [
                    {"name": "title", "type": "text", "required": True},
                    {"name": "slug", "type": "text", "required": True},
                    {"name": "summary", "type": "textarea"},
                ]},
                "globals": {},
            },
        }

    def read(self, collection, *, identifier, identifier_kind, draft, locale):
        return {
            "id": 2, "sourceId": "pages:about", "slug": "about", "title": "About",
            "_status": "draft", "_helloadaRevision": REVISION,
        }

    def update(self, collection, document_id, data, *, expected_hash, locale):
        assert expected_hash == REVISION
        self.updated = {"collection": collection, "id": document_id, "data": data, "locale": locale}
        return {
            "id": 2, "sourceId": "pages:about", "slug": "about",
            "title": data.get("title", "About"), "_status": "draft",
            "_helloadaRevision": "sha256:" + "b" * 64,
        }


def _job(memory: Memory) -> int:
    conversation = memory.create_conversation(title="about")
    return memory.enqueue_chat_job(conversation, "write the page", [])


def _seed_plan(memory: Memory, job_id: int) -> None:
    memory.kv_set(f"chat_turn:{job_id}", {
        "_website_change_plan": {
            "content_effects": [{
                "kind": "collection", "operation": "update", "target": "pages",
                "collection": "pages", "global": "", "identifier": "2",
                "identifier_kind": "id", "fields": ["title"],
                "summary": "Set the About title.", "completed_fields": [],
            }],
            "source_brief": "",
        },
    })


def test_a_read_in_one_tool_call_is_visible_to_the_next_tool_call(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        job_id = _job(memory)
        _seed_plan(memory, job_id)
        payload = _Payload()
        base = {"config": {}, "memory": memory, "env": {}, "payload_gateway": payload}

        read = agent_tools.call_tool(
            memory, base, job_id, "read_payload_content",
            {"collection": "pages", "identifier": "2", "identifier_kind": "id", "draft": True},
        )
        assert "pages:about" in read

        # The plan validator needs the exact document read earlier in this turn.
        # A new TurnState per tool call must share that read cache.
        result = agent_tools.call_tool(
            memory, base, job_id, "update_payload_draft",
            {"collection": "pages", "id": "2", "expected_hash": REVISION,
             "data": {"title": "Peter Abaji"}},
        )

        assert result.startswith("Payload draft updated")
        assert payload.updated == {
            "collection": "pages", "id": "2",
            "data": {"title": "Peter Abaji"}, "locale": "en",
        }
    finally:
        memory.close()
