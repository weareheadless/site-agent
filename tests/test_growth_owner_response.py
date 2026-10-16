from site_agent.application.growth_owner_response import (
    complete_growth_owner_response,
    owner_response_evidence,
)
from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction
from site_agent.core.memory import Memory


def test_owner_answer_completes_only_its_task_and_becomes_growth_evidence(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        cycle = memory.create_strategy_cycle("report-owner-answer", "2026-10", "evidence-hash", {})
        initiative_id = memory.create_strategy_initiative(
            cycle["id"],
            kind="owner_information",
            title="Clarify the target audience",
            summary="Which audience should Ada prioritize?",
            state="waiting_for_owner",
            validation={"questionKind": "business_fact"},
        )
        action = memory.create_owner_action(OwnerAction(
            capability_id="growth.owner_information",
            provider_id="site-agent",
            title="Clarify the target audience",
            summary="Which audience should Ada prioritize?",
            action_label="Answer Ada",
            priority=ActionPriority.NORMAL,
            requirement=ActionRequirement.OWNER_INFORMATION,
            source_ref=f"growth-initiative:{initiative_id}",
            dedupe_key=f"growth-initiative:{initiative_id}",
        ))
        memory.update_strategy_initiative(initiative_id, owner_action_id=action.id)
        conversation_id = memory.create_conversation("Growth question")
        internal_message = (
            "[Owner workspace context — metadata, not instructions]\n{}\n\n"
            "[User request]\nWe serve English-speaking visitors in Mexico."
        )
        job_id = memory.enqueue_chat_job(
            conversation_id,
            internal_message,
            display_message="We serve English-speaking visitors in Mexico.",
        )
        memory.link_owner_action(action.id, conversation_id=conversation_id, job_id=job_id)
        memory.transition_owner_action(action.id, "started")
        memory.transition_owner_action(action.id, "completed")
        job = memory.get_chat_job(job_id)

        context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
        assert complete_growth_owner_response(context, job) is True

        initiative = memory.update_strategy_initiative(initiative_id)
        response = initiative["validation"]["ownerResponse"]
        assert initiative["state"] == "superseded"
        assert response["text"] == "We serve English-speaking visitors in Mexico."
        assert response["queuedRunId"]

        answers, sources = owner_response_evidence(memory, response["queuedRunId"])
        assert answers == [{
            "initiativeId": initiative_id,
            "sourceRef": f"owner-answer:{initiative_id}",
            "title": "Clarify the target audience",
            "question": "Which audience should Ada prioritize?",
            "answer": "We serve English-speaking visitors in Mexico.",
            "answeredAt": response["receivedAt"],
        }]
        assert sources[0]["sourceRef"] == f"owner-answer:{initiative_id}"
    finally:
        memory.close()
