import pytest

from site_agent.application.growth import growth_snapshot, owner_queue
from site_agent.application.growth_workflow import _crawlseo_dataset_source, queue_growth_check, run_growth_cycle, run_growth_reconciler, run_pending_growth
from site_agent.core.contracts import ContractError
from site_agent.core.jobs import register_builtin
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler
import datetime


def test_manual_growth_refresh_uses_crawlseo_authority_run_after_cutover(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    config = {"growth": {"timezone": "UTC"}, "providers": {"crawlseo": {
        "enabled": True, "connector_url": "https://crawlseo.test/api/connector/v1",
        "research_authority": "crawlseo",
    }}}
    run = queue_growth_check({"memory": memory, "config": config})
    assert run["trigger"] == "crawlseo_action"
    assert run["status"] == "pending"
    assert not [row for row in memory.list_growth_runs(limit=None) if row["trigger"] == "owner_review"]
    with pytest.raises(RuntimeError, match="Local Growth discovery is disabled"):
        run_growth_cycle({"memory": memory, "config": config}, trigger="weekly")
    memory.close()


def test_monthly_crawlseo_material_completes_without_local_paid_research(monkeypatch, tmp_path):
    import site_agent.application.growth_workflow as workflow

    memory = Memory(tmp_path / "crawlseo-monthly-material.db")
    context = {"memory": memory, "config": {"growth": {"timezone": "UTC"}}}
    monkeypatch.setattr(workflow, "_collect_cycle_evidence", lambda *_args: {
        "authority": "crawlseo", "actions": [{"id": "remote-action-1"}], "sources": [],
    })
    monkeypatch.setattr(workflow, "_persist_evidence_artifact", lambda *_args, **_kwargs: ("artifact-1", "sha256:" + "a" * 64, {}))
    monkeypatch.setattr(workflow, "_run_monthly_research", lambda *_args: pytest.fail("must not start local paid research"))

    result = run_growth_cycle(context, trigger="monthly")

    assert result["status"] == "complete", result
    assert result["detail"]["remoteActions"] == [{"id": "remote-action-1"}]
    assert result["detail"]["note"].startswith("Recommendations and owner decisions are synchronized from CrawlSEO")
    memory.close()

def test_owner_queue_indexes_decisions_and_excludes_opportunities_and_history():
    tasks = [
        {"id": "decision:normal", "focus": "needs_you", "priority": "normal", "updatedAt": "2026-10-15T09:00:00Z"},
        {"id": "decision:urgent", "focus": "needs_you", "priority": "urgent", "updatedAt": "2026-10-01T09:00:00Z"},
        {"id": "idea:1", "focus": "opportunity", "priority": "urgent"},
        {"id": "working:1", "focus": "preparing", "kind": "article", "updatedAt": "2026-10-15T10:00:00Z"},
        {"id": "schedule:weekly", "focus": "planned", "nextRun": "2026-10-20T09:00:00Z"},
        {"id": "result:1", "focus": "completed", "state": "published", "kind": "payload_content", "updatedAt": "2026-10-14T09:00:00Z"},
        {"id": "article:published", "focus": "completed", "state": "published", "kind": "article", "updatedAt": "2026-10-15T11:00:00Z"},
        {"id": "article:approved", "focus": "completed", "state": "approved", "kind": "article", "updatedAt": "2026-10-15T12:00:00Z"},
        {"id": "failure:1", "focus": "paused", "executionIssue": True, "updatedAt": "2026-10-15T08:00:00Z"},
    ]

    agenda = owner_queue(tasks)
    assert {key: value for key, value in agenda.items() if key != "progression"} == {
        "featuredDecisionId": "decision:urgent",
        "additionalDecisionIds": ["decision:normal"],
        "decisionCount": 2,
        "activeTaskId": "working:1",
        "nextScheduledId": "schedule:weekly",
        "recentResultId": "article:published",
        "recentResultIds": ["article:published", "result:1"],
        "attentionTaskId": "failure:1",
    }
    assert agenda["progression"]["state"] == "ready_for_review"
    assert agenda["progression"]["primaryTaskId"] == "decision:urgent"
    assert agenda["progression"]["serviceIssueTaskId"] == "failure:1"


def test_owner_queue_caps_secondary_decisions_without_losing_the_real_count():
    tasks = [{"id": f"decision:{n}", "focus": "needs_you"} for n in range(5)]
    agenda = owner_queue(tasks)
    assert agenda["featuredDecisionId"] == "decision:0"
    assert agenda["additionalDecisionIds"] == ["decision:1", "decision:2", "decision:3"]
    assert agenda["decisionCount"] == 5



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
    assert snapshot["ownerTimezone"] == "America/Cancun"
    assert snapshot["growthContractVersion"] == "owner-decisions-v1"
    assert snapshot["ownerQueueContractVersion"] == "owner-queue-progression-v1"
    assert snapshot["ownerQueue"]["decisionCount"] == 0
    assert snapshot["ownerQueue"]["progression"]["state"] == "not_started"
    assert "work" not in snapshot
    assert all("nextRun" in row for row in snapshot["activities"])
    assert all(row.get("lastError") is None for row in snapshot["tasks"])
    assert snapshot["evidence"]["artifactId"] is not None
    assert snapshot["evidence"]["sources"]
    memory.close()


def test_crawlseo_dataset_sources_use_real_observation_times_not_fetch_times():
    now = datetime.datetime(2026, 10, 24, 21, 0, tzinfo=datetime.timezone.utc)
    config = {"growth": {"freshness_hours": {"inventory": 168, "dataforseo": 744}}}
    datasets = {
        "health": {"capturedAt": "2026-10-24T20:02:30Z", "errors": {}, "summary": {
            "status": "completed", "health_score": 91, "page_count": 24, "issue_count": 3,
            "finished_at": "2026-10-23T16:35:36.259Z"}, "issues": [{"severity": "warning"}]},
        "research": {"capturedAt": "2026-10-24T20:02:31Z", "errors": {}, "keywords": [
            {"keyword": "query one", "updatedAt": "2026-10-23T16:07:58.430Z"}]},
        "competition": {"capturedAt": "2026-10-24T20:02:31Z", "errors": {}, "serps": [
            {"query": "query one", "updatedAt": "2026-10-13T13:34:18.708Z"}]},
    }
    sources = {name: _crawlseo_dataset_source(name, value, config, now=now) for name, value in datasets.items()}
    assert {name: source["state"] for name, source in sources.items()} == {
        "health": "ready", "research": "ready", "competition": "ready"}
    assert sources["health"]["sourceRef"] == "crawlseo:health"
    assert sources["research"]["observedAt"] == "2026-10-23T16:07:58+00:00"
    assert sources["competition"]["observedAt"] == "2026-10-13T13:34:18+00:00"


def test_crawlseo_dataset_missing_failed_partial_and_stale_states_are_conservative():
    now = datetime.datetime(2026, 10, 24, 21, 0, tzinfo=datetime.timezone.utc)
    config = {"growth": {"freshness_hours": {"inventory": 168, "dataforseo": 744}}}
    missing = _crawlseo_dataset_source("research", {"capturedAt": now.isoformat(), "errors": {}, "keywords": []}, config, now=now)
    empty_completed = _crawlseo_dataset_source("research", {"capturedAt": now.isoformat(), "errors": {},
        "status": "completed", "reportId": "report-with-no-results", "updatedAt": now.isoformat(),
        "keywords": [], "domains": [], "backlinks": []}, config, now=now)
    failed_history_only = _crawlseo_dataset_source("research", {"capturedAt": now.isoformat(), "errors": {},
        "reports": [{"status": "failed", "updatedAt": "2026-10-24T20:00:00Z"}]}, config, now=now)
    completed_history_only = _crawlseo_dataset_source("research", {"capturedAt": now.isoformat(), "errors": {},
        "reports": [{"status": "completed", "updatedAt": "2026-10-24T20:00:00Z"}]}, config, now=now)
    failed = _crawlseo_dataset_source("health", {"errors": {"crawl": "offline"}}, config, now=now)
    partial = _crawlseo_dataset_source("research", {"errors": {"history": "timeout"}, "keywords": [
        {"keyword": "usable", "updatedAt": "2026-10-23T16:00:00Z"}]}, config, now=now)
    partial_row_missing_time = _crawlseo_dataset_source("competition", {"errors": {}, "serps": [
        {"query": "dated", "updatedAt": "2026-10-23T16:00:00Z"}, {"query": "undated"}]}, config, now=now)
    stale = _crawlseo_dataset_source("health", {"errors": {}, "summary": {
        "status": "completed", "finished_at": "2026-10-01T00:00:00Z"}}, config, now=now)
    fetch_time_only = _crawlseo_dataset_source("research", {"capturedAt": now.isoformat(), "errors": {},
        "keywords": [{"keyword": "no timestamp"}]}, config, now=now)
    mixed_age = _crawlseo_dataset_source("competition", {"capturedAt": now.isoformat(), "errors": {}, "serps": [
        {"query": "older row", "updatedAt": "2026-08-29T02:36:11Z"},
        {"query": "newer row", "updatedAt": "2026-10-23T13:34:18Z"}]}, config, now=now)
    mixed_research = _crawlseo_dataset_source("research", {"capturedAt": now.isoformat(), "errors": {}, "keywords": [
        {"keyword": "older result", "updatedAt": "2026-08-29T02:35:52Z"},
        {"keyword": "newer result", "updatedAt": "2026-10-23T16:07:58Z"}]}, config, now=now)
    historic_report_without_time = _crawlseo_dataset_source("research", {"errors": {}, "keywords": [
        {"keyword": "current result", "updatedAt": "2026-10-23T16:07:58Z"}], "reports": [{"id": "historic"}]}, config, now=now)
    future = _crawlseo_dataset_source("research", {"errors": {}, "keywords": [
        {"keyword": "future", "updatedAt": "2026-10-24T21:06:00Z"}]}, config, now=now)
    assert missing["state"] == "missing"
    assert empty_completed["state"] == "missing"
    assert failed_history_only["state"] == "missing"
    assert completed_history_only["state"] == "missing"
    assert failed["state"] == "failed"
    assert partial["state"] == "partial"
    assert partial_row_missing_time["state"] == "partial"
    assert stale["state"] == "stale"
    assert fetch_time_only["state"] == "uncertain"
    assert mixed_age["state"] == "stale"
    assert mixed_age["observedAt"] == "2026-08-29T02:36:11+00:00"
    assert mixed_research["state"] == "stale"
    assert mixed_research["observedAt"] == "2026-08-29T02:35:52+00:00"
    assert historic_report_without_time["state"] == "ready"
    assert future["state"] == "uncertain"


def test_growth_collection_binds_each_crawlseo_dataset_to_a_separate_source(tmp_path, monkeypatch):
    import site_agent.application.growth_evidence as evidence_module
    import site_agent.application.growth_workflow as workflow

    memory = Memory(tmp_path / "memory.db")
    config = {"growth": {"freshness_hours": {"inventory": 168, "dataforseo": 744}}}
    datasets = {
        "health": {"capturedAt": "2026-10-24T20:02:30Z", "errors": {}, "summary": {
            "status": "completed", "finished_at": "2026-10-24T19:00:00Z"}, "issues": []},
        "research": {"capturedAt": "2026-10-24T20:02:31Z", "errors": {}, "keywords": [
            {"keyword": "query one", "updatedAt": "2026-10-24T19:00:00Z"}]},
        "competition": {"capturedAt": "2026-10-24T20:02:31Z", "errors": {}, "serps": [
            {"query": "query one", "updatedAt": "2026-10-24T19:00:00Z"}]},
    }
    monkeypatch.setattr(workflow, "_inventory", lambda _context: [])
    monkeypatch.setattr(workflow, "_source_state", lambda *_args: [{"id": "dataforseo", "state": "missing",
        "reason": "No approved keyword seeds are recorded yet."}])
    monkeypatch.setattr(evidence_module, "growth_evidence", lambda _service, section: datasets[section])
    material = workflow._collect_cycle_evidence({"memory": memory, "config": config,
        "crawlseo_service": object()}, "owner_review", "test-run")
    source_by_ref = {row.get("sourceRef"): row for row in material["sources"]}
    for section in ("health", "research", "competition"):
        source_ref = f"crawlseo:{section}"
        assert source_ref in source_by_ref
        assert source_by_ref[source_ref]["state"] == "ready"
        assert material["datasets"][section]["sourceRef"] == source_ref
        assert material["datasets"][section]["observedAt"] == source_by_ref[source_ref]["observedAt"]
    assert source_by_ref["crawlseo:research"]["state"] == "ready"
    assert source_by_ref[None]["state"] == "missing"
    memory.close()


def test_owner_queue_uses_the_latest_assessment_not_a_newer_daily_evidence_refresh():
    tasks = [
        {"id": "work:article", "focus": "preparing", "kind": "article"},
        {"id": "schedule:weekly", "focus": "planned", "kind": "schedule", "nextRun": "2099-10-20T09:00:00Z"},
        {"id": "schedule:daily", "focus": "paused", "kind": "schedule", "executionIssue": True},
    ]
    runs = [{
        "trigger": "weekly",
        "status": "complete",
        "updated_ts": "2026-10-13T10:00:00Z",
        "detail": {"assessment": {"summary": "Reviewed the latest site evidence.", "unpreparedOpportunities": [{"title": "Finding"}]}},
    }, {
        "trigger": "daily",
        "status": "complete",
        "updated_ts": "2026-10-15T10:00:00Z",
        "detail": {"material": {"sources": []}},
    }]

    progression = owner_queue(tasks, runs)["progression"]

    assert progression["state"] == "service_issue"
    assert progression["primaryTaskId"] == "schedule:daily"
    assert progression["serviceIssueTaskId"] == "schedule:daily"
    assert progression["latestAssessmentAt"] == "2026-10-13T10:00:00Z"
    assert progression["latestAssessmentStatus"] == "complete"
    assert progression["latestAssessmentSummary"] == "Reviewed the latest site evidence."
    assert progression["deferredFindingCount"] == 1


def test_historical_unsupported_assessment_ideas_do_not_block_the_owner_progression():
    progression = owner_queue([], [{
        "trigger": "weekly",
        "status": "complete",
        "updated_ts": "2026-10-15T10:00:00Z",
        "detail": {"assessment": {
            "summary": "Ada reviewed the latest evidence.",
            "unpreparedOpportunities": [
                {"kind": "article", "title": "Old pseudo-task"},
                {"kind": "code", "title": "Unsupported frontend task"},
            ],
        }},
    }])["progression"]

    assert progression["state"] == "assessed"
    assert progression["deferredFindingCount"] == 0


def test_deferred_finding_explains_why_and_uses_the_real_next_weekly_schedule():
    progression = owner_queue([{
        "id": "schedule:growth_weekly",
        "kind": "schedule",
        "focus": "planned",
        "nextRun": "2026-10-19T14:30:00Z",
    }], [{
        "trigger": "weekly",
        "status": "complete",
        "updated_ts": "2026-10-12T14:30:00Z",
        "detail": {"assessment": {
            "summary": "Ada reviewed the latest evidence.",
            "unpreparedOpportunities": [{
                "kind": "payload_content",
                "title": "Add a new course page",
                "preparationNote": "This change needs a new route, which the current existing-document review cannot create.",
                "reassessWhen": "When the shared new-page route is available.",
            }],
        }},
    }])["progression"]

    assert progression["state"] == "deferred_findings"
    assert progression["deferredFindingTitle"] == "Add a new course page"
    assert "needs a new route" in progression["deferredFindingSummary"]
    assert progression["deferredReassessWhen"] == "When the shared new-page route is available."
    assert progression["nextAssessmentAt"] == "2026-10-19T14:30:00Z"


def test_expired_running_assessment_is_not_presented_as_active_ada_work():
    task = {
        "id": "assessment:stale",
        "kind": "assessment",
        "focus": "paused",
        "executionIssue": True,
    }
    progression = owner_queue([task], [{
        "run_id": "stale",
        "trigger": "owner_review",
        "status": "running",
        "updated_ts": "2026-10-15T10:00:00Z",
        "lease_until": "2000-01-01T00:00:00Z",
    }])["progression"]

    assert progression["state"] == "service_issue"
    assert progression["primaryTaskId"] == "assessment:stale"


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
        reservation_id="growth-budget-1",
        period="2026-10",
        idempotency_key="research:2026-10:one",
        amount_micros=250_000,
        cap_micros=500_000,
        operation="keyword_discovery",
    )
    assert reservation["reservation_id"] == repeat["reservation_id"] == "growth-budget-1"
    with pytest.raises(ContractError, match="idempotency key was reused for a different reservation"):
        memory.reserve_growth_budget(
            reservation_id="growth-budget-ignored",
            period="2026-10",
            idempotency_key="research:2026-10:one",
            amount_micros=250_000,
            cap_micros=500_000,
            operation="keyword_discovery",
        )
    memory.settle_growth_budget("growth-budget-1", status="uncertain", provider_task_id="task-1")
    memory.close()


def test_growth_run_restart_reclaim_requires_the_exact_previous_lease(tmp_path):
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
        run_id="growth-interrupted",
        run_key="growth-interrupted-key",
        trigger="weekly",
        goal_revision=goal["revision"],
        timezone="UTC",
        phase="preparing",
        status="pending",
    )
    claimed = memory.claim_growth_run("growth-interrupted", lease_owner="old-worker")
    assert claimed is not None
    assert memory.claim_growth_run(
        "growth-interrupted", lease_owner="new-worker", reclaim_lease_owner="wrong-worker"
    ) is None
    unchanged = memory.get_growth_run("growth-interrupted")
    assert unchanged is not None
    assert unchanged["lease_owner"] == "old-worker"

    reclaimed = memory.claim_growth_run(
        "growth-interrupted", lease_owner="new-worker", reclaim_lease_owner="old-worker"
    )
    assert reclaimed is not None
    assert reclaimed["lease_owner"] == "new-worker"
    assert reclaimed["attempt"] == unchanged["attempt"] + 1
    with pytest.raises(ContractError, match="superseded or expired"):
        memory.update_growth_run("growth-interrupted", phase="complete", expected_lease="old-worker")
    memory.close()


def test_pending_growth_reclaims_only_a_side_effect_free_interrupted_preparation(tmp_path, monkeypatch):
    import site_agent.application.growth_workflow as workflow

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
        run_id="growth-orphan",
        run_key="growth-orphan-key",
        trigger="weekly",
        goal_revision=goal["revision"],
        timezone="UTC",
        phase="preparing",
        status="pending",
        detail={
            "material": {"inventory": []},
            "assessment": {"opportunities": []},
            "candidateIds": [],
        },
    )
    memory.claim_growth_run("growth-orphan", lease_owner="dead-worker")
    initiatives = [
        {
            "growth_run_id": "growth-orphan",
            "kind": "payload_content",
            "state": "preparing",
            "validation": {},
            "owner_action_id": None,
            "artifact_id": None,
            "approval_id": None,
            "draft_id": None,
            "receipt_id": None,
            "review_package_hash": None,
            "candidate_hash": None,
        },
        {
            "growth_run_id": "growth-orphan",
            "kind": "owner_information",
            "state": "waiting_for_owner",
            "validation": {},
            "owner_action_id": 22,
            "artifact_id": None,
            "approval_id": None,
            "draft_id": None,
            "receipt_id": None,
            "review_package_hash": None,
        },
    ]
    monkeypatch.setattr(memory, "list_strategy_initiatives", lambda **_kwargs: initiatives)
    calls = []
    monkeypatch.setattr(workflow, "run_growth_cycle", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(workflow, "_reconcile_article_research", lambda _context: None)

    run_pending_growth({"memory": memory}, recover_interrupted_runs=True)

    assert calls == [{
        "trigger": "weekly",
        "run_id": "growth-orphan",
        "resume_interrupted": True,
        "reclaim_lease_owner": "dead-worker",
    }]
    memory.close()


def test_pending_growth_stops_after_one_interrupted_recovery(tmp_path, monkeypatch):
    import site_agent.application.growth_workflow as workflow

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
        run_id="growth-twice-interrupted",
        run_key="growth-twice-interrupted-key",
        trigger="weekly",
        goal_revision=goal["revision"],
        timezone="UTC",
        phase="preparing",
        status="pending",
        detail={
            "material": {"inventory": []},
            "assessment": {"opportunities": []},
            "candidateIds": [],
            "recoveryEvents": [{"code": "growth_worker_restart_recovery"}],
        },
    )
    memory.claim_growth_run("growth-twice-interrupted", lease_owner="dead-worker")
    initiatives = [{
        "growth_run_id": "growth-twice-interrupted",
        "kind": "payload_content",
        "state": "preparing",
        "validation": {},
        "owner_action_id": None,
        "artifact_id": None,
        "approval_id": None,
        "draft_id": None,
        "receipt_id": None,
        "review_package_hash": None,
        "candidate_hash": None,
    }]
    monkeypatch.setattr(memory, "list_strategy_initiatives", lambda **_kwargs: initiatives)
    monkeypatch.setattr(workflow, "run_growth_cycle", lambda *_args, **_kwargs: pytest.fail("paid recovery must not repeat"))
    monkeypatch.setattr(workflow, "_reconcile_article_research", lambda _context: None)

    run_pending_growth({"memory": memory}, recover_interrupted_runs=True)

    run = memory.get_growth_run("growth-twice-interrupted")
    assert run["status"] == "blocked"
    assert run["lease_owner"] is None
    assert "avoid repeating paid work" in run["detail"]["error"]
    assert any(event["code"] == "growth_interrupted_run_stopped" for event in run["detail"]["recoveryEvents"])
    memory.close()


def test_pending_growth_replays_crawlseo_connector_reports(monkeypatch, tmp_path):
    import site_agent.application.growth_workflow as workflow
    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "crawlseo-hourly-replay.db")
    monkeypatch.setattr("site_agent.application.growth_candidates.reconcile_payload_growth_revisions", lambda *_args: None)
    monkeypatch.setattr("site_agent.application.growth_candidates.reconcile_source_candidates", lambda *_args: None)
    monkeypatch.setattr("site_agent.application.growth_delivery.reconcile_delivery", lambda *_args: None)
    monkeypatch.setattr(workflow, "reconcile_historical_noop_initiatives", lambda *_args: 0)
    monkeypatch.setattr(workflow, "_reconcile_orphan_owner_questions", lambda *_args: None)
    monkeypatch.setattr(workflow, "_reconcile_article_research", lambda *_args: None)
    monkeypatch.setattr(memory, "due_growth_runs", lambda **_kwargs: [])
    monkeypatch.setattr(memory, "list_growth_runs", lambda **_kwargs: [])
    calls = []
    monkeypatch.setattr(workflow, "_sync_crawlseo_actions", lambda _context: calls.append("sync"))
    context = {"memory": memory, "config": {"providers": {"crawlseo": {
        "enabled": True, "connector_url": "https://crawlseo.example/api/connector/v1",
        "research_authority": "crawlseo"}}}}

    workflow.run_pending_growth(context)

    assert calls == ["sync"]
    assert memory.kv_get("crawlseo_connector_sync_error") == {}
    memory.close()


def test_pending_growth_skips_legacy_execution_recovery_in_crawlseo_authority(monkeypatch, tmp_path):
    import site_agent.application.growth_workflow as workflow
    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "crawlseo-no-legacy-executors.db")
    import site_agent.application.growth_candidates as candidates
    import site_agent.application.growth_delivery as delivery
    for module, name in (
        (candidates, "reconcile_payload_growth_revisions"),
        (candidates, "reconcile_source_candidates"),
        (delivery, "reconcile_delivery"),
    ):
        monkeypatch.setattr(module, name, lambda *_args, _name=name: pytest.fail(f"{_name} must be disabled under CrawlSEO authority"), raising=False)
    monkeypatch.setattr(workflow, "reconcile_historical_noop_initiatives", lambda *_args: pytest.fail("legacy initiative repair must be disabled"))
    monkeypatch.setattr(workflow, "_reconcile_orphan_owner_questions", lambda *_args: pytest.fail("legacy owner prompt repair must be disabled"))
    monkeypatch.setattr(workflow, "_reconcile_article_research", lambda *_args: pytest.fail("legacy paid article work must be disabled"))
    monkeypatch.setattr(memory, "due_growth_runs", lambda **_kwargs: [])
    monkeypatch.setattr(memory, "list_growth_runs", lambda **_kwargs: [])
    monkeypatch.setattr(workflow, "_sync_crawlseo_actions", lambda _context: None)
    workflow.run_pending_growth({"memory": memory, "config": {"providers": {"crawlseo": {
        "enabled": True, "connector_url": "https://crawlseo.example/api/connector/v1",
        "research_authority": "crawlseo"}}}})
    memory.close()


def test_crawlseo_authority_quarantines_discovery_but_preserves_exact_legacy_work(monkeypatch, tmp_path):
    import site_agent.application.growth_workflow as workflow
    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "crawlseo-held-legacy-runs.db")
    memory.create_growth_run(run_id="legacy-weekly", run_key="legacy-weekly", trigger="weekly",
        goal_revision=1, timezone="UTC", phase="collecting", status="pending", policy={},
        origin_revision="origin-1", phase_version=1)
    memory.update_growth_run("legacy-weekly", next_due_ts="2000-01-01T00:00:00+00:00")
    memory.create_growth_run(run_id="legacy-candidate", run_key="legacy-candidate", trigger="weekly",
        goal_revision=1, timezone="UTC", phase="preparing", status="pending", policy={},
        origin_revision="origin-1", phase_version=1)
    cycle = memory.create_strategy_cycle("legacy-candidate-cycle", "2026-10", "saved-evidence", {})
    memory.create_strategy_initiative(cycle["id"], kind="payload_content", title="Exact pending candidate",
        summary="Preserve its existing owner decision.", state="ready_for_review", growth_run_id="legacy-candidate",
        approval_id=123, draft_id=456, candidate_hash="sha256:" + "a" * 64,
        review_package_hash="sha256:" + "b" * 64)
    monkeypatch.setattr(workflow, "_sync_crawlseo_actions", lambda _context: None)
    monkeypatch.setattr(workflow, "run_growth_cycle", lambda *_args, **_kwargs: pytest.fail("legacy run must remain history"))
    workflow.run_pending_growth({"memory": memory, "config": {"providers": {"crawlseo": {
        "enabled": True, "connector_url": "https://crawlseo.example/api/connector/v1",
        "research_authority": "crawlseo"}}}})
    retired = memory.get_growth_run("legacy-weekly")
    assert retired["status"] == "blocked"
    assert retired["next_due_ts"] is None
    assert retired["completed_ts"]
    assert retired["detail"]["recoveryEvents"][-1]["code"] == "legacy_discovery_quarantined_at_cutover"
    assert memory.get_growth_run("legacy-candidate")["status"] == "pending"
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


def test_growth_scheduler_removes_duplicate_research_producers_under_crawlseo_authority(tmp_path):
    memory = Memory(tmp_path / "crawlseo-authority-scheduler.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="UTC")
    config = {
        "site": {"website_present": True, "payload": {"enabled": True}},
        "scheduler": {"enabled": True},
        "growth": {"enabled": True},
        "seo": {"enabled": True, "research": {"enabled": True}, "site_report": {"enabled": True},
            "article_research": {"enabled": True}},
        "providers": {"crawlseo": {"enabled": True, "connector_url": "https://crawlseo.example/api/connector/v1",
            "research_authority": "crawlseo"}},
    }
    register_builtin(scheduler, config, {"memory": memory, "config": config, "crawlseo_service": object(), "llm": object()})
    names = {name for name, _spec, _fn in scheduler.jobs}
    assert "growth_pending" in names
    assert not names.intersection({"growth_initial", "growth_daily", "growth_weekly", "growth_monthly"})
    assert "growth_article_sync" not in names
    assert not names.intersection({"seo_insight", "seo_outcomes", "seo_research_cycle", "seo_site_report_cycle",
        "article_research_cycle", "seo_provisioning"})
    assert "growth_reconciler" not in names
    memory.close()


def test_selected_crawlseo_authority_never_falls_back_when_connector_is_unconfigured(tmp_path):
    memory = Memory(tmp_path / "crawlseo-missing-connector.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="UTC")
    config = {
        "site": {"website_present": True, "payload": {"enabled": True}},
        "scheduler": {"enabled": True},
        "growth": {"enabled": True},
        "providers": {"crawlseo": {"research_authority": "crawlseo", "enabled": False}},
    }
    with pytest.raises(RuntimeError, match="authority is selected"):
        register_builtin(scheduler, config, {"memory": memory, "config": config, "llm": object()})
    assert not {name for name, _spec, _fn in scheduler.jobs}.intersection({
        "growth_initial", "growth_daily", "growth_weekly", "growth_monthly", "article_research_cycle",
    })
    memory.close()
