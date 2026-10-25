from site_agent.core import memory as memory_module
from site_agent.core.jobs import _ga_snapshot, _seo_snapshot
from site_agent.core.memory import Memory


def test_successful_first_party_ingestion_has_one_authoritative_history(tmp_path, monkeypatch):
    from site_agent.senses import ga, seo
    class ContentOnlyPayload:
        def __getattr__(self, name):
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


def test_latest_schema_preserves_historical_report_and_initiative_links(tmp_path, monkeypatch):
    path = tmp_path / "tenant.db"
    with monkeypatch.context() as older:
        older.setattr(memory_module, "SCHEMA_VERSION", 49)
        memory = Memory(path)
        cycle = memory.create_strategy_cycle("real-report", "2026-09", "provider-hash", {})
        initiative = memory.create_strategy_initiative(cycle["id"], kind="article", title="Existing work", summary="Keep this work", state="identified")
        memory.close()
    migrated = Memory(path)
    assert migrated.get_schema_version() == memory_module.SCHEMA_VERSION
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


def test_crawlseo_owner_projection_keeps_only_current_links_and_exact_local_reviews():
    from types import SimpleNamespace
    from site_agent.application.growth import _crawlseo_visible_initiatives
    from site_agent.core.contracts import ApprovalStatus

    package_hash = "sha256:" + "a" * 64
    record = {"provider_id": "crawlseo", "payload": {"remoteActionId": "remote-1", "revision": 3}}
    class ProjectionMemory:
        def list_owner_actions(self, *, limit):
            assert limit is None
            return [SimpleNamespace(to_record=lambda: record)]
        def get_approval_request(self, approval_id):
            assert approval_id == 77
            return SimpleNamespace(status=ApprovalStatus.PENDING, artifact_hash=package_hash)

    initiatives = [
        {"id": 1, "expected": {"crawlseoActionId": "remote-1", "crawlseoRevision": 3}},
        {"id": 2, "expected": {"crawlseoActionId": "remote-1", "crawlseoRevision": 2}},
        {"id": 3, "kind": "payload_content", "draft_id": 10, "approval_id": 77,
            "review_package_hash": package_hash},
        {"id": 4, "kind": "payload_content", "title": "legacy unapproved recommendation"},
        {"id": 5, "kind": "owner_information"},
    ]
    drafts = [{"id": 10, "status": "pending", "meta": {"review_package_hash": package_hash}}]
    result = _crawlseo_visible_initiatives(ProjectionMemory(), initiatives, drafts)
    assert [row["id"] for row in result] == [1, 3, 5]


def test_crawlseo_authority_growth_snapshot_hides_legacy_recommendation_queue(tmp_path):
    from site_agent.application.growth import growth_snapshot
    from site_agent.core.contracts import ActionPriority, ActionRequirement, Artifact, ArtifactKind, OwnerAction

    memory = Memory(tmp_path / "crawlseo-owner-projection.db")
    cycle = memory.create_strategy_cycle("legacy", "2026-10", "legacy-hash", {})
    memory.create_strategy_initiative(cycle["id"], kind="article", title="Old SEO recommendation",
        summary="Legacy local recommendation", state="identified")
    memory.create_article_idea("old-idea", "old-idea-hash", {"working_title": "Legacy topic"})
    memory.create_owner_action(OwnerAction(capability_id="review.site_change", provider_id="site-agent",
        title="Old SEO proposal", summary="Legacy output", action_label="Review", priority=ActionPriority.NORMAL,
        requirement=ActionRequirement.OWNER_DECISION, source_ref="legacy-seo", dedupe_key="legacy-seo",
        payload={"source": "monthly_seo_strategy"}))
    memory.snapshot_metrics("gsc", {"legacy": True})
    memory.snapshot_metrics("ga4", {"legacy": True})
    memory.create_artifact(Artifact(kind=ArtifactKind.GROWTH_EVIDENCE, title="CrawlSEO evidence",
        summary="Saved authoritative source references.", renderer="growth_evidence",
        capability_id="growth.evidence.read", provider_id="crawlseo", content_hash="sha256:" + "b" * 64,
        preview_data={"manifest": {"sources": [{"id": "source-1", "sourceRef": "crawlseo:source-1",
            "state": "ready", "observedAt": "2026-10-01T00:00:00Z", "retrievedAt": "2026-10-02T00:00:00Z"}]}}))
    config = {"site": {"website_present": True}, "providers": {"crawlseo": {"enabled": True,
        "connector_url": "https://crawlseo.example/api/connector/v1", "research_authority": "crawlseo"}}}
    snapshot = growth_snapshot(memory, config, {})
    assert snapshot["tasks"] == []
    assert snapshot["activities"] == []
    assert snapshot["goal"] is None
    assert snapshot["sources"] == [{"id": "source-1", "provider": "crawlseo", "capability": "growth.evidence.read",
        "state": "ready", "sourceRef": "crawlseo:source-1", "observedAt": "2026-10-01T00:00:00Z",
        "retrievedAt": "2026-10-02T00:00:00Z"}]
    assert snapshot["keywords"] == []
    assert snapshot["articleIdeas"] == []
    memory.close()


def test_direct_legacy_research_entry_points_are_fenced_under_crawlseo_authority(tmp_path):
    import pytest
    from site_agent.application import growth_workflow
    from site_agent.brain import article_research, growth, monthly_seo_report, seo, seo_outcomes

    memory = Memory(tmp_path / "crawlseo-direct-producer-fences.db")
    config = {"providers": {"crawlseo": {"enabled": True, "connector_url": "https://crawlseo.example/api/connector/v1",
            "research_authority": "crawlseo"}},
        "seo": {"enabled": True, "research": {"enabled": True},
            "site_report": {"enabled": True}, "article_research": {"enabled": True}}}
    context = {"config": config, "memory": memory}

    with pytest.raises(RuntimeError, match="Local Growth assessment is disabled"):
        growth.assess(context, {})
    article_research.select_and_request(context)
    article_research.reconcile(context)
    seo.run(context)
    monthly_seo_report.run(context)
    assert seo_outcomes.run(context) == 0
    with pytest.raises(RuntimeError, match="Local monthly research is disabled"):
        growth_workflow._run_monthly_research(context, {})
    assert growth_workflow._queue_article_research(context)["state"] == "disabled"
    growth_workflow._reconcile_article_research(context)
    with pytest.raises(RuntimeError, match="Local Growth discovery is disabled"):
        growth_workflow.run_growth_cycle(context, trigger="weekly")

    details = [row["detail"] for row in memory.recent_actions(limit=50)]
    assert any("CrawlSEO owns article research" in detail for detail in details)
    assert any("CrawlSEO owns research" in detail for detail in details)
    assert any("CrawlSEO owns SEO reporting" in detail for detail in details)
    assert any("CrawlSEO owns SEO outcome analysis" in detail for detail in details)
    assert not memory.list_strategy_initiatives(limit=50)
    assert not memory.list_article_ideas(limit=50)
    memory.close()
