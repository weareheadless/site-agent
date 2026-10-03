from site_agent.core import memory as memory_module
from site_agent.core.jobs import _ga_snapshot, _seo_snapshot
from site_agent.core.memory import Memory


def test_successful_first_party_ingestion_has_one_authoritative_history(tmp_path, monkeypatch):
    from site_agent.senses import ga, seo
    class ContentOnlyPayload:
        def upsert_seo_record(self, *args, **kwargs):
            raise AssertionError("Analytics must not be copied into a second content database")
    monkeypatch.setattr(ga, "weekly_summary", lambda *_args, **_kwargs: {"current": {"sessions": 0}, "period_days": 7})
    monkeypatch.setattr(seo, "summary", lambda *_args, **_kwargs: {"current": {"clicks": 0}, "period_days": 7})
    memory = Memory(tmp_path / "tenant.db")
    context = {"memory": memory, "config": {"ga": {"enabled": True}, "seo": {"enabled": True}}, "payload_gateway": ContentOnlyPayload()}
    _ga_snapshot(context)
    _seo_snapshot(context)
    assert memory.latest_snapshot("ga4")["data"]["current"]["sessions"] == 0
    assert memory.latest_snapshot("gsc")["data"]["current"]["clicks"] == 0
    assert memory.latest_snapshot("gsc")["ts"]
    memory.close()


def test_v50_preserves_historical_report_and_initiative_links(tmp_path, monkeypatch):
    path = tmp_path / "tenant.db"
    with monkeypatch.context() as older:
        older.setattr(memory_module, "SCHEMA_VERSION", 49)
        memory = Memory(path)
        cycle = memory.create_strategy_cycle("real-report", "2026-09", "provider-hash", {})
        initiative = memory.create_strategy_initiative(cycle["id"], kind="article", title="Existing work", summary="Keep this work", state="identified")
        memory.close()
    migrated = Memory(path)
    assert migrated.get_schema_version() == 50
    assert migrated.list_strategy_initiatives()[0]["id"] == initiative
    assert migrated.list_strategy_initiatives()[0]["cycle_id"] == cycle["id"]
    assert migrated.get_strategy_cycle("real-report")["id"] == cycle["id"]
    assert not migrated.conn.execute("PRAGMA foreign_key_check").fetchall()
    migrated.close()


def test_due_work_is_filtered_before_the_limit(tmp_path):
    memory = Memory(tmp_path / "tenant.db")
    from site_agent.core.growth_contracts import GrowthGoalRevision
    goal = memory.create_growth_goal(GrowthGoalRevision.default().to_dict())
    for number in range(25):
        run = memory.create_growth_run(run_id=f"blocked-{number}", run_key=f"blocked-{number}", trigger="weekly",
            goal_revision=goal["revision"], timezone="UTC", phase="preparing", status="blocked", phase_version=2)
        memory.update_growth_run(run["run_id"], next_due_ts="2100-01-01T00:00:00+00:00")
    memory.create_growth_run(run_id="pending", run_key="pending", trigger="weekly", goal_revision=goal["revision"],
        timezone="UTC", phase="collecting", status="pending", phase_version=2)
    assert [row["run_id"] for row in memory.due_growth_runs(limit=1)] == ["pending"]
    memory.close()
