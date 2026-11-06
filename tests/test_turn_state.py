from __future__ import annotations

import pytest

from site_agent.brain.turn_state import PERSISTED, TurnState, clear_turn
from site_agent.core.memory import Memory


@pytest.fixture
def memory(tmp_path):
    store = Memory(tmp_path / "memory.db")
    try:
        yield store
    finally:
        store.close()


def test_a_durable_key_survives_a_new_state_object(memory):
    state = TurnState(memory, 41, {"config": {"site": {}}})
    state["_website_change_plan"] = {"source_brief": "add the footer"}

    restored = TurnState(memory, 41, {"config": {"site": {}}})

    assert restored["_website_change_plan"] == {"source_brief": "add the footer"}
    assert restored["config"] == {"site": {}}


def test_runtime_context_is_never_persisted(memory):
    state = TurnState(memory, 42, {"memory": memory, "config": {"secret": "x"}})
    state["config"] = {"secret": "y"}

    assert memory.kv_get("chat_turn:42", {}) == {}
    assert TurnState(memory, 42, {}) == {}


def test_setdefault_and_update_persist(memory):
    state = TurnState(memory, 43, {})
    state.setdefault("_payload_read_globals", {})["homepage"] = {"id": 1}
    state.update({"_completed_payload_effects": [{"kind": "collection"}]})

    restored = TurnState(memory, 43, {})
    assert restored["_payload_read_globals"] == {"homepage": {"id": 1}}
    assert restored["_completed_payload_effects"] == [{"kind": "collection"}]


def test_pop_and_clear_remove_persisted_values(memory):
    state = TurnState(memory, 44, {})
    state["_resolved_payload_locale"] = "en"
    assert state.pop("_resolved_payload_locale") == "en"
    assert TurnState(memory, 44, {}) == {}

    state["_website_change_plan_dispatched"] = True
    clear_turn(memory, 44)
    assert TurnState(memory, 44, {}) == {}


def test_every_persisted_key_is_a_private_context_name():
    assert all(name.startswith("_") for name in PERSISTED)
