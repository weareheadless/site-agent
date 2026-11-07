from __future__ import annotations

from site_agent.application import agent_tools
from site_agent.core.memory import Memory

REVISION = "sha256:" + "a" * 64


class _GlobalPayload:
    def __init__(self) -> None:
        self.updated: dict | None = None

    def require_authoring_contract(self):
        return {
            "locales": ["en"],
            "defaultLocale": "en",
            "enabled": {"collections": [], "globals": ["navigation"]},
            "authoring": {
                "collections": {},
                "globals": {"navigation": [{"name": "items", "type": "array"}]},
            },
        }

    def read_global(self, global_name, *, draft, locale):
        return {"id": 1, "items": [], "_helloadaRevision": REVISION}

    def update_global(self, global_name, data, *, expected_hash, locale):
        assert expected_hash == REVISION
        self.updated = {"global": global_name, "data": data, "locale": locale}
        return {
            "id": 1, "items": data["items"],
            "_helloadaRevision": "sha256:" + "b" * 64,
        }


def test_a_global_read_in_one_tool_call_is_visible_to_the_next_call(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        conversation = memory.create_conversation(title="nav")
        job_id = memory.enqueue_chat_job(conversation, "add the menu link", [])
        memory.kv_set(f"chat_turn:{job_id}", {
            "_website_change_plan": {
                "content_effects": [{
                    "kind": "global", "operation": "update", "target": "navigation",
                    "collection": "", "global": "navigation", "identifier": "navigation",
                    "identifier_kind": "global", "fields": ["items"],
                    "summary": "Add the About link.", "completed_fields": [],
                }],
                "source_brief": "",
            },
        })
        payload = _GlobalPayload()
        base = {"config": {}, "memory": memory, "env": {}, "payload_gateway": payload}

        read = agent_tools.call_tool(
            memory, base, job_id, "read_payload_global", {"global": "navigation", "draft": True},
        )
        assert "items" in read

        items = [{"key": "primary.about", "label": "About", "href": "/about"}]
        result = agent_tools.call_tool(
            memory, base, job_id, "update_payload_global",
            {"global": "navigation", "expected_hash": REVISION, "data": {"items": items}},
        )

        assert result.startswith("Payload global draft updated")
        assert payload.updated == {"global": "navigation", "data": {"items": items}, "locale": "en"}
    finally:
        memory.close()
