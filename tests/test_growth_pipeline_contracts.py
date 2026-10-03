from site_agent.application.growth_budget import reserve_paid_research
from site_agent.application.growth_workflow import run_growth_reconciler
from site_agent.core.memory import Memory


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
