from __future__ import annotations

import pytest

from site_agent.brain import editor


CONTRACT = {
    "authoring": {"collections": {"pages": [
        {"name": "title", "type": "text", "required": True},
        {"name": "slug", "type": "text", "required": True},
        {"name": "summary", "type": "textarea"},
        {"name": "sections", "type": "array"},
        {"name": "seo", "type": "group"},
        {"name": "featuredImage", "type": "upload"},
    ]}},
}


def _state(effects):
    return {
        "_website_change_plan": {"content_effects": effects, "source_brief": "x"},
        "_payload_read_documents": {},
        "_payload_read_globals": {},
        "_authoring_contract": CONTRACT,
    }


def _page_effect(**overrides):
    effect = {
        "kind": "collection", "operation": "create", "target": "pages",
        "identifier": "about", "identifier_kind": "slug",
        "fields": ["title", "slug", "summary", "sections", "seo", "featuredImage"],
        "completed_fields": [],
    }
    effect.update(overrides)
    return effect


def test_a_page_may_be_created_with_the_fields_available_now():
    effect = _page_effect()
    state = _state([effect])

    matched = editor._plan_effect_for_tool(
        state, "create_payload_draft",
        {"collection": "pages", "data": {"title": "About", "slug": "about"}},
    )

    assert matched is effect


def test_a_field_outside_the_plan_is_still_refused():
    effect = _page_effect()
    state = _state([effect])

    with pytest.raises(ValueError, match="unexpected data fields: canonicalUrl"):
        editor._plan_effect_for_tool(
            state, "create_payload_draft",
            {"collection": "pages", "data": {"title": "About", "slug": "about", "canonicalUrl": "x"}},
        )


def test_the_plan_is_incomplete_until_every_planned_field_is_written():
    effect = _page_effect(completed_fields=["title", "slug"])
    state = _state([effect])

    assert editor._payload_plan_complete(state) is False

    effect["completed_fields"] = list(effect["fields"])
    assert editor._payload_plan_complete(state) is True


def test_a_second_call_can_complete_the_remaining_fields_of_the_same_page():
    effect = _page_effect(completed_fields=["title", "slug"], _document_id="41", _dispatched=True)
    state = _state([effect])
    state["_payload_read_documents"][("pages", "41")] = {
        "id": 41, "slug": "about", "_helloadaRevision": "sha256:" + "a" * 64,
    }

    matched = editor._plan_effect_for_tool(
        state, "update_payload_draft",
        {"collection": "pages", "id": "41", "expected_hash": "sha256:" + "a" * 64,
         "data": {"summary": "Meet Peter", "sections": []}},
    )

    assert matched is effect


def test_a_repeat_write_of_an_already_completed_field_is_refused():
    effect = _page_effect(completed_fields=["title", "slug"], _document_id="41", _dispatched=True)
    state = _state([effect])
    state["_payload_read_documents"][("pages", "41")] = {
        "id": 41, "slug": "about", "_helloadaRevision": "sha256:" + "a" * 64,
    }

    with pytest.raises(ValueError):
        editor._plan_effect_for_tool(
            state, "update_payload_draft",
            {"collection": "pages", "id": "41", "expected_hash": "sha256:" + "a" * 64,
             "data": {"title": "About again"}},
        )
