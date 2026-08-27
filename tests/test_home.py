import datetime

from site_agent.application.actions import OwnerActionService
from site_agent.application.home import HomeService
from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction
from site_agent.core.memory import Memory


def _action(source_ref: str, *, priority=ActionPriority.NORMAL, requirement=ActionRequirement.OWNER_DECISION):
    return OwnerAction(
        capability_id="site.change.propose",
        provider_id="site-agent",
        title=source_ref,
        summary="A short owner-facing summary.",
        action_label="Review change",
        priority=priority,
        requirement=requirement,
        source_ref=source_ref,
        dedupe_key=source_ref,
    )


def test_owner_action_service_deduplicates_and_transitions(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = OwnerActionService(memory)
    first = service.create(_action("test:one"))
    duplicate = service.create(_action("test:one", priority=ActionPriority.URGENT))
    assert duplicate.id == first.id
    started = service.start(first.id, conversation_id=memory.create_conversation("Focused"))
    assert started.state.value == "started"
    assert started.conversation_id is not None
    completed = service.complete(first.id)
    assert completed.state.value == "completed"
    memory.close()


def test_home_composes_owner_actions_and_compatibility_views(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    urgent = memory.create_owner_action(_action("test:urgent", priority=ActionPriority.URGENT))
    memory.create_owner_action(_action("test:suggestion", requirement=ActionRequirement.SUGGESTION, priority=ActionPriority.OPTIONAL))
    draft_id = memory.save_draft("Journal page", "prepared", kind="merge")
    report_id = memory.save_draft("Weekly report", "internal summary", kind="report")
    memory.kv_set(
        "strategist_cards",
        {"cards": [{"title": "Write about calm breathing", "action": "Ask Ada to draft it", "why": "People are asking."}]},
    )
    conversation_id = memory.create_conversation("Background work")
    memory.enqueue_chat_job(conversation_id, "prepare background work")

    result = HomeService(memory).snapshot()
    assert result.needs_you[0].id == urgent.id
    assert any(action.draft_id == draft_id for action in result.needs_you)
    assert all(action.draft_id != report_id for action in result.needs_you)
    assert {action.requirement.value for action in result.suggestions} == {"suggestion"}
    assert result.handling.active_count == 1
    assert result.to_dict()["everything_is_handled"] is False
    memory.close()


def test_home_hides_future_snoozed_and_terminal_actions(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    snoozed = memory.create_owner_action(_action("test:snoozed", priority=ActionPriority.URGENT))
    memory.transition_owner_action(snoozed.id, "snoozed", snoozed_until=future)
    completed = memory.create_owner_action(_action("test:completed"))
    memory.transition_owner_action(completed.id, "completed")
    result = HomeService(memory).snapshot()
    assert all(action.source_ref not in {"test:snoozed", "test:completed"} for action in result.needs_you)
    memory.close()


def test_home_includes_visible_inner_life_and_keeps_private_thoughts_out(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.record_observation("inner_voice", "A visible thought about the tide of the site.", meta={"mood": "quietly alert"})
    memory.record_observation("inner_voice", "A private thought that must not leave memory.", meta={"mood": "hollow", "private": True})
    memory.record_observation("dream", "I followed a red buoy into a field of light.", meta={"lure": "the ocean"})
    memory.record_observation("awaken", "The thread worth carrying is patience before motion.")
    memory.kv_set("mood", {"current": "hollow"})
    memory.kv_set("themes", ["patience", "depth"])
    memory.record_action("digest", "2 new reading notes")
    memory.record_action("job_error", "dream: transient provider failure")

    inner_life = HomeService(memory).snapshot().to_dict()["inner_life"]

    assert inner_life["thought"]["text"] == "A visible thought about the tide of the site."
    assert "private thought" not in inner_life["thought"]["text"]
    assert inner_life["dream"]["text"].startswith("I followed a red buoy")
    assert inner_life["awakening"]["text"].startswith("The thread worth carrying")
    assert inner_life["mood"] == ""  # the current mood came from the private row
    assert inner_life["themes"] == ["patience", "depth"]
    assert inner_life["activity"]["text"] == "digest - 2 new reading notes"
    memory.close()


def test_home_exposes_a_bounded_self_understanding_summary(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.kv_set(
        "inner_self",
        {
            "self_description": "I keep returning to unfinished questions.",
            "persistent_tendencies": ["I distrust easy closure."],
            "open_questions": ["What deserves to remain unresolved?"],
            "updated_ts": "2026-08-27T20:00:00+00:00",
        },
    )
    memory.record_observation(
        "identity_shift",
        "Ada revised how she understands herself: I keep returning to unfinished questions.",
        meta={"evidence_ids": [1]},
    )

    self_view = HomeService(memory).snapshot().to_dict()["inner_life"]["self_understanding"]

    assert self_view["description"] == "I keep returning to unfinished questions."
    assert self_view["open_questions"] == ["What deserves to remain unresolved?"]
    assert "unfinished questions" in self_view["last_shift"]
    memory.close()


def test_owner_action_service_snoozes_for_seven_days(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = OwnerActionService(memory)
    action = service.create(_action("test:snooze"))
    before = datetime.datetime.now(datetime.timezone.utc)
    snoozed = service.snooze_for(action.id)
    deadline = datetime.datetime.fromisoformat(snoozed.snoozed_until)
    assert datetime.timedelta(days=6, hours=23) < deadline - before < datetime.timedelta(days=7, minutes=1)
    assert HomeService(memory).snapshot().needs_you == ()
    memory.close()
