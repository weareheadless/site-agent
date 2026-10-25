from types import SimpleNamespace

import pytest

from site_agent.application import growth_workflow
from site_agent.brain import article_research, growth, monthly_seo_report, seo, seo_insights, seo_outcomes
from site_agent.core.jobs import register_growth_jobs, register_jobs
from site_agent.core.memory import Memory
from site_agent.core.research_authority import PRODUCER_FREEZE_KEY, producer_frozen
from site_agent.core.scheduler import Scheduler


@pytest.mark.parametrize("hold", [{"active": True}, "invalid", {"active": "false"}])
def test_pending_connector_dispatch_stops_before_remote_effects_while_activation_is_unverified(tmp_path, hold):
    from site_agent.core.research_authority import CONNECTOR_DISPATCH_HOLD_KEY
    memory = Memory(tmp_path / "paused-connector.db")
    memory.kv_set(CONNECTOR_DISPATCH_HOLD_KEY, hold)
    config = {"providers": {"crawlseo": {"enabled": True, "research_authority": "crawlseo",
        "connector_url": "https://crawlseo.example/api/connector/v1"}}}
    try:
        with pytest.raises(RuntimeError, match="paused"):
            growth_workflow.run_pending_growth({"memory": memory, "config": config})
        assert memory.crawlseo_migration_snapshot()["executionBindings"]["total"] == 0
    finally:
        memory.close()


@pytest.mark.parametrize("state", [
    None, "bad-json-shape", {"active": "true"}, {"active": 1}, {"reason": "migration"},
])
def test_malformed_persisted_freeze_fails_closed(tmp_path, state):
    memory = Memory(tmp_path / "freeze.db")
    try:
        memory.kv_set(PRODUCER_FREEZE_KEY, state)
        assert producer_frozen(memory)
    finally:
        memory.close()


def test_frozen_local_registration_removes_growth_producers_but_keeps_email(tmp_path):
    memory = Memory(tmp_path / "frozen-registration.db")
    settings = {
        "instance_name": "test-tenant",
        "site": {"website_present": True, "payload": {"enabled": True}},
        "scheduler": {"enabled": True},
        "growth": {"enabled": True},
        "messages": {"email": {"enabled": True, "provisioning": {"auto": True}}},
        "seo": {"enabled": True, "provisioning": {"auto": True}},
    }
    memory.kv_set(PRODUCER_FREEZE_KEY, {"active": True, "reason": "crawlseo migration"})
    memory.kv_set("next_run:growth_pending", 1)
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock")
    try:
        assert register_growth_jobs(scheduler, settings, {"memory": memory, "config": settings})
        names = {name for name, _spec, _fn in scheduler.jobs}
        assert names == {"email_provisioning", "seo_provisioning", "growth_pending"}
        assert memory.kv_get("next_run:growth_pending") == 1
    finally:
        memory.close()


def test_frozen_registration_preserves_generic_learning_and_seo_provisioning(tmp_path):
    memory = Memory(tmp_path / "frozen-generic-jobs.db")
    memory.kv_set(PRODUCER_FREEZE_KEY, {"active": True})
    settings = {
        "scheduler": {"enabled": True, "learning_enabled": True},
        "sources": {"rss_feeds": [{"name": "Example", "url": "https://example.test/feed.xml"}]},
        "seo": {"enabled": True, "provisioning": {"auto": True}},
    }
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock")
    try:
        register_jobs(scheduler, settings, {"memory": memory, "config": settings, "llm": object()})
        names = {name for name, _spec, _fn in scheduler.jobs}
        assert {"digest", "learn", "seo_provisioning"}.issubset(names)
        assert "growth_reconciler" not in names
    finally:
        memory.close()


def test_frozen_growth_paths_and_brain_entrypoints_stop_before_provider_work(tmp_path):
    memory = Memory(tmp_path / "frozen-direct.db")
    calls = []

    class LLM:
        def chat(self, *args, **kwargs):
            calls.append("llm")
            raise AssertionError("frozen producer must not call the LLM")

    context = {"memory": memory, "config": {}, "llm": LLM(), "crawlseo_service": SimpleNamespace()}
    memory.kv_set(PRODUCER_FREEZE_KEY, {"active": True})
    try:
        for operation in (
            lambda: growth_workflow.run_growth_cycle(context, trigger="weekly"),
            lambda: growth_workflow.run_growth_reconciler(context),
            lambda: growth.assess(context, {}),
            lambda: seo.run(context),
            lambda: article_research.select_and_request(context),
            lambda: article_research.reconcile(context),
            lambda: monthly_seo_report.run(context),
            lambda: seo_outcomes.run(context),
            lambda: seo_insights.generate(context),
        ):
            with pytest.raises(RuntimeError, match="frozen"):
                operation()
        assert not calls
        assert memory.list_growth_runs(limit=None) == []
    finally:
        memory.close()


def test_frozen_pending_local_growth_does_not_resume_legacy_runs(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "frozen-pending.db")
    memory.kv_set(PRODUCER_FREEZE_KEY, {"active": True})
    for index in range(6):
        memory.create_growth_run(
            run_id=f"legacy-{index}", run_key=f"legacy-key-{index}", trigger="weekly",
            goal_revision=1, timezone="UTC", phase="preparing", status="pending",
        )
    monkeypatch.setattr(
        growth_workflow,
        "run_growth_cycle",
        lambda *_args, **_kwargs: pytest.fail("frozen local run was replayed"),
    )
    try:
        growth_workflow.run_pending_growth({"memory": memory, "config": {}})
        saved = memory.list_growth_runs(limit=None)
        assert len(saved) == 6
        assert all(row["status"] == "pending" for row in saved)
    finally:
        memory.close()


def test_frozen_pending_growth_still_runs_crawlseo_connector_reconciliation(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "frozen-crawlseo.db")
    memory.kv_set(PRODUCER_FREEZE_KEY, {"active": True})
    config = {"providers": {"crawlseo": {
        "enabled": True,
        "connector_url": "https://crawlseo.example/api/connector/v1",
        "research_authority": "crawlseo",
    }}}
    synced = []
    monkeypatch.setattr(growth_workflow, "_sync_crawlseo_actions", lambda _context: synced.append(True))
    try:
        growth_workflow.run_pending_growth({"memory": memory, "config": config})
        assert synced == [True]
    finally:
        memory.close()
