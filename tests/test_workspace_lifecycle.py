from __future__ import annotations

import pytest

from site_agent.application.workspace import BridgeError, ChatService
from site_agent.core.memory import Memory


def test_history_exposes_one_current_owner_update(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        first = memory.save_draft("First update", "diff", kind="merge", meta={"head_sha": "a" * 40})
        second = memory.save_draft("Current update", "diff", kind="merge", meta={"head_sha": "b" * 40})
        service = ChatService(memory, object())

        history = service.history()

        assert history["current_update"]["id"] == second
        assert history["current_update"]["title"] == "Current update"
        assert history["current_update"]["pending_count"] == 2
        assert {draft["id"] for draft in history["drafts"]} >= {first, second}
    finally:
        memory.close()


def test_stale_owner_update_cannot_be_approved(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        first = memory.save_draft("Old update", "diff", kind="merge")
        memory.save_draft("Current update", "diff", kind="merge")
        service = ChatService(memory, object())

        with pytest.raises(BridgeError, match="current website update"):
            service.approve_draft(first)
    finally:
        memory.close()
