"""Scheduler-level capacity is waiting work, not a failed preparation effect."""

from contextlib import closing
import hashlib
import json
from types import SimpleNamespace

import pytest

from site_agent.application import growth_workflow as workflow
from site_agent.core.growth_contracts import GrowthPolicy
from site_agent.core.memory import Memory


def test_ready_source_refs_include_both_identifiers_but_never_unready_records():
    required = {"crawlseo:health"}
    ready = workflow._ready_source_refs([{"id": "crawlseo_health", "sourceRef": "crawlseo:health", "state": "ready"}])
    missing = workflow._ready_source_refs([{"id": "crawlseo_health", "sourceRef": "crawlseo:health", "state": "missing"}])
    assert required - ready == set()
    assert required - missing == required


@pytest.fixture(autouse=True)
def journal_provider(monkeypatch):
    """Provider boundary only; the real workflow still requires its checkpoint."""
    from site_agent.application import growth_delivery
    recorded = []
    monkeypatch.setattr(growth_delivery, "journal", lambda ctx: SimpleNamespace(
        issue=lambda initiative: recorded.append(initiative["id"])))
    return recorded


def saved_run(memory, opportunities, *, key="scheduled-assessment", material=None):
    config = {"growth": {"timezone": "UTC", "max_active_candidates": 1},
              "site": {"website_present": True, "public_url": "https://example.test"}}
    goal = workflow.ensure_default_goal(memory)
    policy = GrowthPolicy.from_config(config)
    run = memory.create_growth_run(run_id=key, run_key=key, trigger="weekly",
        goal_revision=goal["revision"], timezone="UTC", phase="preparing", status="pending",
        policy=policy.to_dict(), origin_revision=policy.origin_revision, phase_version=2)
    material = material if material is not None else {
        "inventory": [], "sources": [{"id": "inventory", "sourceRef": "inventory", "state": "ready"}]
    }
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


def test_owner_review_contract_revision_queues_one_new_run_without_mutating_old_lineage_or_review(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
        monkeypatch.setattr(workflow, "_OWNER_REVIEW_ASSESSMENT_CONTRACT", "owner-summary-v0")
        old = workflow.queue_growth_check(context)
        old_detail = {"assessment": {"summary": "Original assessment", "opportunities": []},
            "assessmentCompletedAt": "2026-10-24T00:00:00Z", "material": {"sources": [{"id": "inventory"}]}}
        memory.update_growth_run(old["run_id"], status="complete", phase="complete", detail=old_detail)

        cycle = memory.create_strategy_cycle(old["run_id"], "2026-10", "sha256:test", {})
        initiative_id = memory.create_strategy_initiative(cycle["id"], kind="payload_content",
            title="Existing owner review", summary="Keep this exact candidate", state="ready_for_review",
            growth_run_id=old["run_id"], approval_id=917, expected={"opportunity": {"documentId": "1"}})
        initiative_before = next(row for row in memory.list_strategy_initiatives(limit=None)
            if row["id"] == initiative_id)

        monkeypatch.setattr(workflow, "_OWNER_REVIEW_ASSESSMENT_CONTRACT", "owner-summary-v1")
        fresh = workflow.queue_growth_check(context)
        repeated = workflow.queue_growth_check(context)

        assert fresh["run_id"] != old["run_id"]
        assert fresh["trigger"] == "owner_review"
        assert fresh["run_key"].endswith(":assessment-owner-summary-v1")
        assert repeated["run_id"] == fresh["run_id"]
        assert len(memory.list_growth_runs()) == 2
        assert memory.get_growth_run(old["run_id"])["detail"] == old_detail
        initiative_after = next(row for row in memory.list_strategy_initiatives(limit=None)
            if row["id"] == initiative_id)
        assert initiative_after["state"] == initiative_before["state"] == "ready_for_review"
        assert initiative_after["approval_id"] == initiative_before["approval_id"] == 917
        assert initiative_after["growth_run_id"] == old["run_id"]


def test_non_owner_review_queue_key_is_unchanged_by_summary_contract_revision(tmp_path):
    import datetime

    with closing(Memory(tmp_path / "memory.db")) as memory:
        context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
        run = workflow.queue_growth_check(context, trigger="weekly")
        assert run["trigger"] == "weekly"
        assert ":assessment-" not in run["run_key"]
        goal = workflow.ensure_default_goal(memory)
        policy = GrowthPolicy.from_config(context["config"])
        now = datetime.datetime.now(datetime.timezone.utc)
        previous_weekly_key = workflow._cycle_key(
            policy, goal["revision"], "weekly:" + now.date().isoformat(), now,
        )
        assert run["run_key"] == previous_weekly_key


def ready_candidate(memory, initiative, *args):
    memory.transition_strategy_initiative(initiative["id"], "validating")
    return memory.transition_strategy_initiative(initiative["id"], "ready_for_review")


def test_explicit_check_brings_forward_existing_retry_without_resetting_work(tmp_path):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
        first = workflow.queue_growth_check(context)
        saved = {"assessment": {"summary": "Persisted assessment"}, "blocks": [{"initiativeId": 7}]}
        memory.update_growth_run(first["run_id"], status="blocked", phase="preparing",
            detail=saved, next_due_ts="2099-01-01T00:00:00+00:00")
        memory.kv_set("next_run:growth_pending", 4070908800.0)
        requested = workflow.queue_growth_check(context)
        assert requested["run_id"] == first["run_id"]
        assert requested["status"] == "blocked"
        assert requested["detail"] == saved
        assert requested["phase"] == "preparing"
        assert [row["run_id"] for row in memory.due_growth_runs()] == [first["run_id"]]
        assert memory.kv_get("next_run:growth_pending") < 4070908800.0


@pytest.mark.parametrize("status", ["running", "complete", "cancelled", "blocked", "failed"])
def test_check_does_not_invent_retry_or_reclaim_execution(tmp_path, status):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
        first = workflow.queue_growth_check(context)
        memory.update_growth_run(first["run_id"], status=status, next_due_ts=None)
        memory.kv_set("next_run:growth_pending", 4070908800.0)
        result = workflow.queue_growth_check(context)
        assert result["status"] == status
        assert result["next_due_ts"] is None
        assert memory.kv_get("next_run:growth_pending") == 4070908800.0


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


@pytest.mark.parametrize(("source_state", "expected_run_state", "expected_candidate_state", "prepare_count"), [
    ("ready", "complete", "ready_for_review", 1),
    ("missing", "complete", "deferred", 0),
])
def test_required_source_ref_alias_is_ready_only_with_its_exact_ready_source_record(
    tmp_path, monkeypatch, source_state, expected_run_state, expected_candidate_state, prepare_count,
):
    with closing(Memory(tmp_path / f"{source_state}.db")) as memory:
        opportunity_row = {**opportunity("Use the current crawl"), "evidence": ["inventory"],
            "requiredSources": ["crawlseo:health"]}
        material = {"inventory": [], "sources": [
            {"id": "inventory", "sourceRef": "canonical_payload_inventory", "state": "ready",
                "observedAt": "2026-10-24T19:00:00Z"},
            {"id": "crawlseo_health", "sourceRef": "crawlseo:health", "state": source_state,
                "observedAt": "2026-10-24T19:00:00Z"},
        ], "metrics": {}, "datasets": {}, "ownerResponses": [], "collectionErrors": {}}
        context, run = saved_run(memory, [opportunity_row], key=f"required-source-{source_state}", material=material)
        from site_agent.application import growth_candidates
        preparations = []
        monkeypatch.setattr(growth_candidates, "prepare_payload_candidate",
            lambda ctx, row, *args: preparations.append(row["id"]) or ready_candidate(memory, row))

        result = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")

        initiative = memory.list_strategy_initiatives()[0]
        assert result["status"] == expected_run_state
        assert initiative["state"] == expected_candidate_state
        assert len(preparations) == prepare_count
        if source_state == "missing":
            assert "Required evidence is not ready: crawlseo:health" in initiative["last_error"]
            assert result["detail"]["assessment"]["unpreparedOpportunities"][0]["errorCode"] == "required_source_not_ready"


def test_missing_evidence_binding_resumes_saved_material_and_assessment(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [])
        original = memory.get_growth_run(run["run_id"])
        material = original["detail"]["material"]
        artifact_id = original["detail"]["evidenceArtifactId"]
        saved_assessment = {"summary": "Already assessed", "opportunities": []}
        memory.update_growth_run(run["run_id"], status="failed", phase="collecting", detail={
            "material": material,
            "assessment": saved_assessment,
            "assessmentCompletedAt": "2026-10-23T00:00:00Z",
            "articleResearch": {"status": "not_due"},
            "error": "'evidenceArtifactId'",
        })
        monkeypatch.setattr(workflow, "_collect_cycle_evidence", lambda *args: pytest.fail("must reuse collected material"))
        from site_agent.brain import growth as brain_growth
        monkeypatch.setattr(brain_growth, "assess", lambda *args: pytest.fail("must reuse saved assessment"))

        result = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="weekly")

        assert result["status"] == "complete"
        assert result["detail"]["assessment"] == saved_assessment
        assert result["detail"]["evidenceArtifactId"] == artifact_id
        evidence = memory.list_artifacts(kind="growth_evidence", limit=100)
        assert len(evidence) == 1


def test_artifact_persist_crash_reuses_collection_and_created_artifact(tmp_path, monkeypatch):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        config = {"growth": {"timezone": "UTC"}}
        context = {"memory": memory, "config": config}
        goal = workflow.ensure_default_goal(memory)
        policy = GrowthPolicy.from_config(config)
        run = memory.create_growth_run(
            run_id="evidence-persist-crash",
            run_key="evidence-persist-crash",
            trigger="owner_review",
            goal_revision=goal["revision"],
            timezone="UTC",
            phase="collecting",
            status="pending",
            policy=policy.to_dict(),
            origin_revision=policy.origin_revision,
            phase_version=2,
        )
        material = {
            "inventory": [],
            "sources": [{"id": "inventory", "sourceRef": "inventory", "state": "ready"}],
            "metrics": {},
            "datasets": {},
            "ownerResponses": [],
            "collectionErrors": [],
        }
        collection_calls = []
        assessment_calls = []
        monkeypatch.setattr(workflow, "_collect_cycle_evidence", lambda *args: collection_calls.append(1) or material)
        from site_agent.brain import growth as brain_growth
        monkeypatch.setattr(brain_growth, "assess", lambda *args: assessment_calls.append(1) or {
            "summary": "Recovered from saved evidence",
            "opportunities": [],
        })
        monkeypatch.setattr(workflow, "_queue_article_research", lambda *args: pytest.fail("must not dispatch paid research"))
        persist = workflow._persist_evidence_artifact
        persist_calls = []

        def create_then_interrupt(*args, **kwargs):
            result = persist(*args, **kwargs)
            persist_calls.append(1)
            if len(persist_calls) == 1:
                raise RuntimeError("simulated interruption after artifact creation")
            return result

        monkeypatch.setattr(workflow, "_persist_evidence_artifact", create_then_interrupt)
        failed = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="owner_review")

        assert failed["status"] == "failed"
        assert failed["detail"]["material"] == material
        assert "evidenceArtifactId" not in failed["detail"]
        artifact_id = memory.list_artifacts(kind="growth_evidence", limit=100)[0].artifact_id
        assert artifact_id is not None
        assert collection_calls == [1]
        assert assessment_calls == []

        memory.update_growth_run(run["run_id"], next_due_ts="2000-01-01T00:00:00+00:00")
        recovered = workflow.run_growth_cycle(context, run_id=run["run_id"], trigger="owner_review")

        assert recovered["status"] == "complete"
        assert recovered["detail"]["evidenceArtifactId"] == artifact_id
        assert collection_calls == [1]
        assert assessment_calls == [1]
        assert len(memory.list_artifacts(kind="growth_evidence", limit=100)) == 1


def test_evidence_artifact_reuse_rejects_different_material(tmp_path):
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [])
        detail = memory.get_growth_run(run["run_id"])["detail"]
        altered = {**detail["material"], "inventory": [{"sourceRef": "different"}]}
        with pytest.raises(ValueError, match="bound to different evidence"):
            workflow._persist_evidence_artifact(
                memory,
                run=run,
                goal=workflow.ensure_default_goal(memory),
                policy=GrowthPolicy.from_config(context["config"]),
                sources=detail["material"]["sources"],
                material=altered,
            )


def test_large_evidence_material_is_referenced_by_hash_and_reuses_exact_artifact(tmp_path):
    material = {
        "inventory": [{"sourceRef": "page:large", "description": "x" * 110_000}],
        "sources": [{"id": "inventory", "sourceRef": "inventory", "state": "ready"}],
    }
    with closing(Memory(tmp_path / "memory.db")) as memory:
        context, run = saved_run(memory, [], material=material)
        detail = memory.get_growth_run(run["run_id"])["detail"]
        artifact = memory.get_artifact(detail["evidenceArtifactId"])
        manifest = artifact.preview_data["manifest"]
        canonical_material = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        assert len(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) < 100_000
        assert "material" not in manifest
        assert manifest["materialHash"] == hashlib.sha256(canonical_material.encode("utf-8")).hexdigest()
        assert manifest["materialRef"] == f"growth-run:{run['run_id']}:material"
        assert manifest["sources"] == material["sources"]
        assert detail["material"] == material

        reused_id, reused_hash, reused_manifest = workflow._persist_evidence_artifact(
            memory,
            run=run,
            goal=workflow.ensure_default_goal(memory),
            policy=GrowthPolicy.from_config(context["config"]),
            sources=material["sources"],
            material=material,
        )
        assert reused_id == artifact.artifact_id
        assert reused_hash == artifact.content_hash
        assert reused_manifest == manifest


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
