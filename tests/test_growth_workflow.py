from site_agent.application.growth import growth_snapshot
from site_agent.application.growth_workflow import run_growth_reconciler
from site_agent.core.jobs import register_builtin
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler


def test_new_site_goal_and_reconciliation_are_durable_and_idempotent(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    context = {
        "memory": memory,
        "config": {"growth": {"timezone": "America/Cancun"}},
        "crawlseo_service": None,
    }

    first = run_growth_reconciler(context)
    second = run_growth_reconciler(context)

    assert first["run_id"] == second["run_id"]
    assert first["status"] == "complete"
    assert memory.latest_growth_goal()["goal_key"] == "relevant_visitors"
    assert memory.latest_growth_goal()["objective"] == "Bring relevant visitors to my website"
    assert len(memory.list_growth_runs()) == 1

    snapshot = growth_snapshot(
        memory,
        context["config"],
        {"scheduler": type("SchedulerView", (), {"jobs": []})()},
    )
    assert snapshot["goal"]["revision"] == 1
    assert snapshot["work"]["state"] == "idle"
    assert snapshot["work"]["summaryKey"] == "backgroundIdle"
    assert snapshot["evidence"]["artifactId"] is not None
    assert snapshot["evidence"]["sources"]
    memory.close()


def test_growth_evidence_distinguishes_zero_stale_and_missing_sources(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        memory.snapshot_metrics("ga4", {"current": {"sessions": 0}})
        seed = memory.upsert_seo_seed("local service", "en", "US")
        memory.mark_seo_seed_researched(seed["id"], "report-1")
        context = {
            "memory": memory,
            "config": {
                "growth": {"timezone": "UTC", "freshness_hours": {"ga4": 168, "gsc": 168, "dataforseo": 168}},
                "ga": {"property_id": "123"},
                "seo": {"site_url": "https://example.test"},
            },
            "crawlseo_service": object(),
        }

        run = run_growth_reconciler(context)
        assert run["detail"]["evidenceArtifactId"]
        sources = {row["id"]: row for row in run["detail"]["sources"]}
        assert sources["ga4"]["state"] == "ready"
        assert sources["ga4"]["data"] == "available"
        assert sources["gsc"]["state"] == "missing"
        assert sources["dataforseo"]["state"] == "ready"
    finally:
        memory.close()


def test_growth_run_lease_and_budget_reservation_are_idempotent(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    goal = memory.create_growth_goal(
        {
            "goal_key": "relevant_visitors",
            "objective": "Bring relevant visitors to my website",
            "metrics": ["gsc_clicks"],
            "confirmed_by": "test",
            "confirmed_ts": "2026-10-02T00:00:00+00:00",
            "source": "test",
        }
    )
    memory.create_growth_run(
        run_id="growth-lease",
        run_key="growth-lease-key",
        trigger="test",
        goal_revision=goal["revision"],
        timezone="UTC",
        phase="collecting",
        status="pending",
    )
    claimed = memory.claim_growth_run("growth-lease", lease_owner="runner-a")
    assert claimed and claimed["status"] == "running"
    assert memory.claim_growth_run("growth-lease", lease_owner="runner-b") is None

    reservation = memory.reserve_growth_budget(
        reservation_id="growth-budget-1",
        period="2026-10",
        idempotency_key="research:2026-10:one",
        amount_micros=250_000,
        cap_micros=500_000,
        operation="keyword_discovery",
    )
    repeat = memory.reserve_growth_budget(
        reservation_id="growth-budget-ignored",
        period="2026-10",
        idempotency_key="research:2026-10:one",
        amount_micros=250_000,
        cap_micros=500_000,
        operation="keyword_discovery",
    )
    assert reservation["reservation_id"] == repeat["reservation_id"] == "growth-budget-1"
    memory.settle_growth_budget("growth-budget-1", status="uncertain", provider_task_id="task-1")
    memory.close()


def test_growth_scheduler_uses_tenant_timezone_and_registers_outcomes_independently(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(
        memory,
        lock_path=tmp_path / "scheduler.lock",
        timezone_name="Europe/Paris",
    )
    config = {
        "seo": {
            "enabled": True,
            "research": {"enabled": True, "timezone": "Europe/Paris"},
            "site_report": {"enabled": True},
            "article_research": {"enabled": True},
        }
    }
    context = {"memory": memory, "config": config, "crawlseo_service": object()}
    register_builtin(scheduler, config, context)
    names = {name for name, _spec, _fn in scheduler.jobs}

    assert "growth_reconciler" in names
    assert "seo_research_cycle" in names
    assert "seo_outcomes" in names
    assert scheduler.timezone_name == "Europe/Paris"
    memory.close()
