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
    memory.kv_set(
        "strategist_cards",
        {"cards": [{"title": "Write about calm breathing", "action": "Ask Ada to draft it", "why": "People are asking."}]},
    )
    conversation_id = memory.create_conversation("Background work")
    memory.enqueue_chat_job(conversation_id, "prepare background work")

    result = HomeService(memory).snapshot()
    assert result.needs_you[0].id == urgent.id
    assert any(action.draft_id == draft_id for action in result.needs_you)
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
