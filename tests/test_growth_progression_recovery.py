"""Scheduler-level capacity is waiting work, not a failed preparation effect."""

from contextlib import closing
from types import SimpleNamespace

import pytest

from site_agent.application import growth_workflow as workflow
from site_agent.core.growth_contracts import GrowthPolicy
from site_agent.core.memory import Memory


@pytest.fixture(autouse=True)
def journal_provider(monkeypatch):
    """Provider boundary only; the real workflow still requires its checkpoint."""
    from site_agent.application import growth_delivery
    recorded = []
    monkeypatch.setattr(growth_delivery, "journal", lambda ctx: SimpleNamespace(
        issue=lambda initiative: recorded.append(initiative["id"])))
    return recorded


def saved_run(memory, opportunities, *, key="scheduled-assessment"):
    config = {"growth": {"timezone": "UTC", "max_active_candidates": 1},
              "site": {"website_present": True, "public_url": "https://example.test"}}
    goal = workflow.ensure_default_goal(memory)
    policy = GrowthPolicy.from_config(config)
    run = memory.create_growth_run(run_id=key, run_key=key, trigger="weekly",
        goal_revision=goal["revision"], timezone="UTC", phase="preparing", status="pending",
        policy=policy.to_dict(), origin_revision=policy.origin_revision, phase_version=2)
    material = {"inventory": [], "sources": [{"id": "inventory", "sourceRef": "inventory", "state": "ready"}]}
    artifact_id, _, _ = workflow._persist_evidence_artifact(memory, run=run, goal=goal,
        policy=policy, sources=material["sources"], material=material)
    memory.update_growth_run(run["run_id"], detail={"evidenceArtifactId": artifact_id,
        "articleResearch": {"status": "not_due"},
        "material": material,
        "assessment": {"summary": "Saved assessment", "opportunities": opportunities}})
    return {"config": config, "memory": memory}, run


def opportunity(title, kind="payload_content", document="1"):
    return {"title": title, "kind": kind, "scope": "Bounded improvement", "why": "Observed evidence",
            "evidence": ["inventory"], "requiredSources": ["inventory"],
            "collection": "pages", "documentId": document}


def test_requested_check_wakes_existing_scheduler_without_duplicate_runs(tmp_path):
    import datetime

    with closing(Memory(tmp_path / "memory.db")) as memory:
        context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
        future = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600
        memory.kv_set("next_run:growth_pending", future)
        first = workflow.queue_growth_check(context)
        wake = memory.kv_get("next_run:growth_pending")
        assert wake < future
        second = workflow.queue_growth_check(context)
        assert second["run_id"] == first["run_id"]
        assert len(memory.list_growth_runs()) == 1
        assert memory.kv_get("next_run:growth_pending") == wake
        memory.update_growth_run(first["run_id"], status="complete", phase="complete")
        memory.kv_set("next_run:growth_pending", future)
        completed = workflow.queue_growth_check(context)
        assert completed["status"] == "complete"
        assert memory.kv_get("next_run:growth_pending") == future


def ready_candidate(memory, initiative, *args):
    memory.transition_strategy_initiative(initiative["id"], "validating")
    return memory.transition_strategy_initiative(initiative["id"], "ready_for_review")


def test_capacity_wait_has_runnable_due_time_then_resumes_saved_assessment(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("First"), opportunity("Next", document="2")])
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "prepare_payload_candidate", lambda ctx, row, *args: ready_candidate(memory, row))
        first = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")
        assert first["status"] == "pending"
        assert first["phase"] == "preparing"
        assert first["next_due_ts"]
        assert first["detail"]["blocks"] == []
        assert first["detail"]["waitingForCapacity"] == ["Next"]
        assert len(memory.list_strategy_initiatives()) == 1
        memory.transition_strategy_initiative(first["detail"]["candidateIds"][0], "rejected")
        memory.update_growth_run(run["run_id"], next_due_ts="2000-01-01T00:00:00+00:00")
        monkeypatch.setattr(workflow, "_collect_cycle_evidence", lambda *args: (_ for _ in ()).throw(AssertionError("must not recollect")))
        monkeypatch.setattr(growth_candidates, "reconcile_source_candidates", lambda ctx: None)
        monkeypatch.setattr(workflow, "_reconcile_article_research", lambda ctx: None)
        workflow.run_pending_growth(context)
        final = memory.get_growth_run(run["run_id"])
        assert final["status"] == "complete"
        assert "waitingForCapacity" not in final["detail"]
        assert len(memory.list_strategy_initiatives()) == 2
        assert memory.list_strategy_initiatives()[-1]["state"] == "ready_for_review"


def test_queued_source_work_consumes_capacity_before_another_payload_candidate(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("Source", "code"), opportunity("Payload")])
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "queue_source_candidate", lambda *args: 99)
        monkeypatch.setattr(growth_candidates, "prepare_payload_candidate", lambda *args: (_ for _ in ()).throw(AssertionError("capacity exceeded")))
        result = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")
        assert result["status"] == "pending"
        assert result["detail"]["blocks"] == []
        assert result["detail"]["waitingForCapacity"] == ["Payload"]
        assert len(memory.list_strategy_initiatives()) == 1


def test_owner_question_is_not_blocked_by_candidate_capacity(tmp_path, monkeypatch, journal_provider):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("Page"), opportunity("Confirm hours", "owner_information")])
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "prepare_payload_candidate", lambda ctx, row, *args: ready_candidate(memory, row))
        result = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")
        assert result["status"] == "complete"
        question = memory.list_strategy_initiatives()[-1]
        assert question["state"] == "waiting_for_owner"
        assert memory.get_owner_action(question["owner_action_id"]).source_ref == f"growth-initiative:{question['id']}"
        assert journal_provider == [question["id"]]


def test_completed_run_duplicate_question_is_reconciled_without_restarting_work(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("Current question", "owner_information")])
        first = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")
        question = memory.list_strategy_initiatives()[0]
        cycle = memory.growth_strategy_cycle(run["run_id"], first["detail"]["evidenceArtifactId"])
        orphan_id = memory.create_strategy_initiative(cycle["id"], kind="owner_information",
            title="Older duplicate", summary="Retained facts", state="preparing", growth_run_id=run["run_id"],
            goal_revision=question["goal_revision"], origin_revision=question["origin_revision"])
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "reconcile_source_candidates", lambda ctx: None)
        monkeypatch.setattr(workflow, "_reconcile_article_research", lambda ctx: None)
        workflow.run_pending_growth(context)
        workflow.run_pending_growth(context)
        orphan = memory.update_strategy_initiative(orphan_id)
        assert orphan["state"] == "deferred"
        assert orphan["validation"]["relatedInitiativeId"] == question["id"]
        assert orphan["validation"]["reassessWhen"]
        assert len(memory.list_owner_actions(limit=None)) == 1
        assert memory.get_growth_run(run["run_id"])["status"] == "complete"


def test_question_reconciliation_does_not_touch_effects_or_inflight_run(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("Question", "owner_information")])
        workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")
        question = memory.list_strategy_initiatives()[0]
        cycle = memory.growth_strategy_cycle(run["run_id"], memory.get_growth_run(run["run_id"])["detail"]["evidenceArtifactId"])
        linked = memory.create_strategy_initiative(cycle["id"], kind="owner_information", title="Linked",
            summary="Existing action", state="preparing", growth_run_id=run["run_id"],
            goal_revision=question["goal_revision"], origin_revision=question["origin_revision"])
        memory.update_strategy_initiative(linked, owner_action_id=question["owner_action_id"])
        _, inflight = saved_run(memory, [], key="inflight")
        inflight_cycle = memory.growth_strategy_cycle(inflight["run_id"], memory.get_growth_run(inflight["run_id"])["detail"]["evidenceArtifactId"])
        inflight_id = memory.create_strategy_initiative(inflight_cycle["id"], kind="owner_information", title="In flight",
            summary="Not abandoned", state="preparing", growth_run_id=inflight["run_id"],
            goal_revision=question["goal_revision"], origin_revision=question["origin_revision"])
        memory.update_growth_run(inflight["run_id"], next_due_ts="2099-01-01T00:00:00+00:00")
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "reconcile_source_candidates", lambda ctx: None)
        monkeypatch.setattr(workflow, "_reconcile_article_research", lambda ctx: None)
        workflow.run_pending_growth(context)
        assert memory.update_strategy_initiative(linked)["state"] == "preparing"
        assert memory.update_strategy_initiative(inflight_id)["state"] == "preparing"


def test_capacity_wait_does_not_bypass_live_lease_or_future_due_time(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("Future")])
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "prepare_payload_candidate", lambda *args: (_ for _ in ()).throw(AssertionError("not runnable")))
        memory.update_growth_run(run["run_id"], next_due_ts="2099-01-01T00:00:00+00:00")
        assert workflow.run_growth_cycle(context, run_id=run["run_id"])["status"] == "pending"
        memory.update_growth_run(run["run_id"], next_due_ts=None)
        claimed = memory.claim_growth_run(run["run_id"], lease_owner="another-executor", lease_seconds=300)
        result = workflow.run_growth_cycle(context, run_id=run["run_id"])
        assert result["lease_owner"] == "another-executor"
        assert result["attempt"] == claimed["attempt"]
        assert memory.list_strategy_initiatives() == []


def test_owner_question_requires_journal_before_creating_action(tmp_path, monkeypatch):
    from site_agent.application import growth_delivery
    def unavailable(*args):
        raise growth_delivery.GrowthDeliveryError("Required checkpoint is unavailable")
    monkeypatch.setattr(growth_delivery, "journal", unavailable)
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [opportunity("Question", "owner_information")])
        result = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")
        assert result["status"] == "failed"
        assert result["phase"] == "preparing"
        assert result["detail"]["assessment"]["opportunities"]
        assert memory.list_owner_actions(limit=None) == []
        memory.update_growth_run(run["run_id"], next_due_ts="2000-01-01T00:00:00+00:00")
        recorded = []
        monkeypatch.setattr(growth_delivery, "journal", lambda ctx: SimpleNamespace(
            issue=lambda initiative: recorded.append(initiative["id"])))
        from site_agent.application import growth_candidates
        monkeypatch.setattr(growth_candidates, "reconcile_source_candidates", lambda ctx: None)
        monkeypatch.setattr(workflow, "_reconcile_article_research", lambda ctx: None)
        monkeypatch.setattr(workflow, "_collect_cycle_evidence", lambda *args: (_ for _ in ()).throw(AssertionError("must resume saved boundary")))
        workflow.run_pending_growth(context)
        assert memory.get_growth_run(run["run_id"])["status"] == "complete"
        assert len(memory.list_strategy_initiatives()) == 1
        assert len(memory.list_owner_actions(limit=None)) == 1
        assert recorded == [memory.list_strategy_initiatives()[0]["id"]]
