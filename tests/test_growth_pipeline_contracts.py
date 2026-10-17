import pytest

from site_agent.application.growth_budget import reserve_paid_research
from site_agent.application.growth_workflow import run_growth_reconciler
from site_agent.core.memory import Memory


def test_noop_growth_preparation_is_not_a_technical_failure(monkeypatch):
    from site_agent.application.growth_candidates import prepare_payload_candidate
    from site_agent.brain.growth import UnsupportedGrowthPreparation

    class Payload:
        def require_growth_contract(self):
            return None

        def require_authoring_contract(self):
            return {}

        def authoring_fields(self, *_args, **_kwargs):
            return ["title"]

        def read(self, *_args, **_kwargs):
            return {"id": "page-1", "title": "Already correct"}

        def apply_growth_candidate(self, *_args, **_kwargs):
            raise AssertionError("a no-op must never be written")

    monkeypatch.setattr(
        "site_agent.application.growth_candidates.brain_growth.prepare",
        lambda *_args, **_kwargs: {"title": "Already correct"},
    )
    context = {"memory": object(), "payload_gateway": Payload()}
    opportunity = {"collection": "pages", "documentId": "page-1", "title": "Improve title"}
    initiative = {"id": 1, "validation": {}}
    inventory = [{"collection": "pages", "document": {"id": "page-1"}, "route": "/"}]

    with pytest.raises(UnsupportedGrowthPreparation, match="already present") as error:
        prepare_payload_candidate(context, initiative, opportunity, inventory, {})

    assert error.value.code == "no_actionable_change"




def test_historical_noop_block_is_reclassified_without_touching_candidate_content(tmp_path):
    from site_agent.application.growth_workflow import (
        has_recoverable_historical_noop,
        reconcile_historical_noop_initiatives,
    )

    memory = Memory(tmp_path / "memory.db")
    cycle = memory.create_strategy_cycle("report-noop", "2026-10", "hash-noop", {})
    safe_id = memory.create_strategy_initiative(
        cycle["id"], kind="payload_content", title="Already correct", summary="No edit is needed.",
        state="blocked", last_error="Ada proposed no actual change", validation={"status": "blocked"},
    )
    unsafe_id = memory.create_strategy_initiative(
        cycle["id"], kind="payload_content", title="Candidate exists", summary="Must not be hidden.",
        state="blocked", last_error="Ada proposed no actual change", candidate_hash="candidate-hash",
        validation={"status": "blocked"},
    )

    assert has_recoverable_historical_noop(memory)
    assert reconcile_historical_noop_initiatives(memory) == 1
    rows = {row["id"]: row for row in memory.list_strategy_initiatives(limit=None)}
    assert rows[safe_id]["state"] == "deferred"
    assert rows[safe_id]["validation"]["errorCode"] == "no_actionable_change"
    assert "nothing to approve" in rows[safe_id]["validation"]["reason"]
    assert rows[safe_id]["last_error"] == rows[safe_id]["validation"]["reason"]
    assert rows[unsafe_id]["state"] == "blocked"
    assert not has_recoverable_historical_noop(memory)
    assert reconcile_historical_noop_initiatives(memory) == 0
    memory.close()

def test_failed_growth_run_replay_preserves_deferred_candidates_and_continues(tmp_path):
    from site_agent.application.growth_workflow import run_growth_cycle
    from site_agent.core.growth_contracts import GrowthPolicy

    memory = Memory(tmp_path / "memory.db")
    config = {"site": {"public_url": "https://example.test"}, "growth": {"timezone": "UTC"}}
    context = {"memory": memory, "config": config}
    evidence = run_growth_reconciler(context)
    goal = memory.latest_growth_goal()
    policy = GrowthPolicy.from_config(config)
    run_id = "growth-replay-deferred-candidate"
    source_ref = "payload:pages:1"
    deferred = {
        "kind": "payload_content",
        "title": "Improve the existing home page",
        "scope": "Clarify the existing home page.",
        "why": "The persisted assessment supports this change.",
        "evidence": [source_ref],
        "requiredSources": [],
        "collection": "pages",
        "documentId": "1",
    }
    owner_question = {
        "kind": "owner_information",
        "title": "Confirm the service duration",
        "scope": "Ada needs the owner's confirmed service duration.",
        "why": "The existing evidence does not state it.",
        "evidence": [source_ref],
        "requiredSources": [],
    }
    material = {
        "inventory": [{
            "collection": "pages",
            "document": {"id": "1", "sourceId": "page:home", "slug": "home"},
            "sourceRef": source_ref,
            "route": "/",
        }],
        "sources": [],
        "metrics": {},
        "datasets": {},
        "ownerResponses": [],
        "collectionErrors": {},
    }
    detail = {
        "evidenceArtifactId": evidence["detail"]["evidenceArtifactId"],
        "policy": policy.to_dict(),
        "material": material,
        "assessment": {
            "summary": "Replaying the assessment must preserve its prior disposition.",
            "opportunities": [deferred, owner_question],
        },
    }
    memory.create_growth_run(
        run_id=run_id,
        run_key=run_id,
        trigger="owner_review",
        goal_revision=goal["revision"],
        timezone="UTC",
        phase="preparing",
        status="failed",
        detail=detail,
        policy=policy.to_dict(),
        origin_revision=policy.origin_revision,
        phase_version=2,
    )
    cycle = memory.growth_strategy_cycle(run_id, detail["evidenceArtifactId"])
    reason = "No page change was needed in the previous preparation."
    reassess_when = "After the page content or supporting evidence changes."
    deferred_id = memory.create_strategy_initiative(
        cycle["id"],
        kind="payload_content",
        title=deferred["title"],
        summary=deferred["scope"],
        evidence=deferred["evidence"],
        expected={"opportunity": deferred},
        state="deferred",
        growth_run_id=run_id,
        goal_revision=goal["revision"],
        origin_revision=policy.origin_revision,
        validation={"status": "deferred", "reason": reason, "reassessWhen": reassess_when},
        last_error=reason,
    )

    class PayloadMustNotBeReopened:
        def require_growth_contract(self):
            raise AssertionError("a deferred candidate must not be prepared again in the same run")

    context["payload_gateway"] = PayloadMustNotBeReopened()
    result = run_growth_cycle(context, trigger="owner_review", run_id=run_id)

    assert result["status"] == "complete"
    saved = {row["id"]: row for row in memory.list_strategy_initiatives(limit=None)}
    assert saved[deferred_id]["state"] == "deferred"
    assert saved[deferred_id]["validation"]["reason"] == reason
    assert saved[deferred_id]["validation"]["reassessWhen"] == reassess_when
    assert saved[deferred_id]["owner_action_id"] is None
    assert len([row for row in saved.values() if row["kind"] == "owner_information"]) == 1
    memory.close()

def test_growth_candidate_lineage_and_lifecycle_are_persisted(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        cycle = memory.create_strategy_cycle("report-1", "2026-10", "hash", {})
        initiative_id = memory.create_strategy_initiative(
            cycle["id"],
            kind="content",
            title="A useful guide",
            summary="Prepare a grounded guide",
            state="preparing",
            growth_run_id="growth-1",
            goal_revision=0,
            origin_revision="origin-1",
            candidate_hash="candidate-1",
            review_package_hash="package-1",
            validation={"status": "passed"},
        )
        row = memory.list_strategy_initiatives(cycle["id"])[0]
        assert row["growth_run_id"] == "growth-1"
        assert row["validation"] == {"status": "passed"}
        memory.transition_strategy_initiative(initiative_id, "validating")
        memory.transition_strategy_initiative(initiative_id, "ready_for_review")
        memory.transition_strategy_initiative(initiative_id, "publishing")
        memory.transition_strategy_initiative(initiative_id, "verifying_live")
        memory.transition_strategy_initiative(initiative_id, "measuring")
        assert memory.list_strategy_initiatives(cycle["id"])[0]["state"] == "measuring"
    finally:
        memory.close()


def test_paid_research_reservation_is_recorded_on_request(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        request = memory.create_seo_research_request(
            "2026-10", "standard-v1", "seo:2026-10:standard-v1", {"focus_market": {"country": "MX"}}
        )
        reservation = reserve_paid_research(
            {"memory": memory, "config": {"growth": {"monthly_research_cap_micros": 500_000}}},
            idempotency_key=request["idempotency_key"],
            operation="seo_monthly_research",
        )
        updated = memory.update_seo_research_request(
            request["id"], budget_reservation_id=reservation["reservation_id"], status="budget_reserved"
        )
        assert updated["budget_reservation_id"] == reservation["reservation_id"]
    finally:
        memory.close()


def test_goal_revision_and_origin_create_a_new_reconciliation_run(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        config = {"site": {"public_url": "https://example.test"}, "growth": {"timezone": "UTC"}}
        first = run_growth_reconciler({"memory": memory, "config": config})
        memory.create_growth_goal({
            "goal_key": "bookings",
            "objective": "Bring qualified bookings",
            "metrics": ["qualified_events"],
            "confirmed_by": "owner",
            "confirmed_ts": "2026-10-03T00:00:00+00:00",
            "source": "owner_goal_change",
        })
        second = run_growth_reconciler({"memory": memory, "config": config})
        assert first["run_id"] != second["run_id"]
        assert len(memory.list_growth_runs()) == 2
    finally:
        memory.close()
