import datetime

from site_agent.brain.seo import (
    _process_report,
    _apply_language_boundary,
    build_research_brief,
    choose_focus_market,
    previous_period,
    select_seeds,
)
from site_agent.brain import seo_outcomes
from site_agent.core.contracts import ActionPriority, ActionRequirement, ActionState, OwnerAction
from site_agent.application.actions import OwnerActionService
from site_agent.application.approvals import ApprovalService
from site_agent.application.capabilities import CapabilityRegistry, default_capabilities
from site_agent.application.home import HomeService
from site_agent.core.memory import Memory


def _config():
    return {
        "persona": {"audience": "International buyers looking for careful advice"},
        "sources": {"keywords": ["practical buyer guide", "market comparison"]},
        "seo": {
            "research": {
                "enabled": True,
                "timezone": "Europe/Paris",
                "languages": [
                    {"code": "en", "markets": ["US", "GB"], "primary": True},
                    {"code": "fr", "markets": ["FR"]},
                ],
                "existing_locales": ["en"],
                "competitors": [{"domain": "competitor.example", "markets": ["US", "GB"], "services": ["Custom advisory"]}],
                "business_goals": ["Increase qualified consultations"],
                "priority_services": ["Custom advisory"],
                "anchor_topics": ["international buyer guide", "custom advisory service"],
            }
        },
    }


def test_previous_period_uses_customer_timezone_and_calendar_month():
    now = datetime.datetime(2026, 3, 1, 0, 30, tzinfo=datetime.timezone.utc)
    assert previous_period(_config(), now) == "2026-02"


def test_seed_selection_has_two_strategic_two_expansion_and_one_adaptive(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        memory.snapshot_metrics("gsc", {"top_queries": [{"query": "recent buyer questions"}]})
        selected = select_seeds(memory, _config(), {"language": "en", "country": "US"})
        assert [item["slot_type"] for item in selected] == [
            "strategic", "strategic", "expansion", "expansion", "adaptive"
        ]
        assert len({item["seed"].lower() for item in selected}) == 5
    finally:
        memory.close()


def test_brief_does_not_require_a_competitor(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        config = _config()
        config["seo"]["research"]["competitors"] = []
        memory.snapshot_metrics("gsc", {"top_queries": [{"query": "recent buyer questions"}]})
        brief, _ = build_research_brief(memory, config, "2026-02")
        assert brief["competitor"] is None
        assert "skipped" in brief["selection_rationale"]["competitor"]
    finally:
        memory.close()


def test_competitor_requires_market_and_category_evidence(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        config = _config()
        memory.snapshot_metrics("gsc", {"top_queries": [{"query": "recent buyer questions"}]})
        config["seo"]["research"]["competitors"] = [{
            "domain": "unrelated.example",
            "markets": ["US"],
            "services": ["Pet grooming"],
        }]
        brief, _ = build_research_brief(memory, config, "2026-02")
        assert brief["competitor"] is None

        config["seo"]["research"]["competitors"] = [{
            "domain": "relevant.example",
            "markets": ["US", "GB"],
            "services": ["Custom advisory"],
        }]
        brief, _ = build_research_brief(memory, config, "2026-02")
        assert brief["competitor"] == "relevant.example"
    finally:
        memory.close()


def test_competitor_discovery_only_allows_model_to_rank_known_candidates(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        config = _config()
        config["seo"]["research"]["competitors"] = [
            {"domain": "first.example", "markets": ["US", "GB"], "services": ["Custom advisory"]},
            {"domain": "second.example", "markets": ["US", "GB"], "services": ["Custom advisory", "international buyers"]},
        ]
        memory.snapshot_metrics("gsc", {"top_queries": [{"query": "recent buyer questions"}]})

        class RankingLlm:
            def chat(self, *_args, **_kwargs):
                return '{"domain":"second.example"}'

        brief, _ = build_research_brief(memory, config, "2026-02", RankingLlm())
        assert brief["competitor"] == "second.example"
    finally:
        memory.close()


def test_focus_market_rotates_when_another_market_has_no_history(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        memory.kv_set("seo_focus_market", {"language": "en", "country": "US"})
        selected = choose_focus_market(memory, _config())
        assert selected == {"language": "en", "country": "GB"}
    finally:
        memory.close()


def test_strategy_memory_preserves_cycle_initiative_decision_and_outcome(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        request = memory.create_seo_research_request(
            "2026-02", "standard-v1", "seo:2026-02:standard-v1", {"keyword_seeds": ["a"]}
        )
        assert request["brief"] == {"keyword_seeds": ["a"]}
        seed = memory.upsert_seo_seed("buyer guide", "en", "US", cluster="buyers")
        memory.create_seo_seed_selection(request["id"], seed["id"], 1, "strategic", "Business priority")
        cycle = memory.create_strategy_cycle("report-1", "2026-02", "hash", {"report": True})
        initiative = memory.create_strategy_initiative(
            cycle["id"],
            kind="content",
            title="Write the guide",
            summary="Prepare a useful guide",
            evidence=["dataforseo.keyword_seed"],
            expected={"metric": "clicks"},
        )
        memory.record_strategy_decision(initiative, "declined", "Not this quarter", "Focus shifted")
        outcome = memory.record_strategy_outcome(
            initiative, 90, {"clicks": 10}, {"clicks": 20}, "positive", "medium"
        )
        assert outcome > 0
        assert memory.get_strategy_cycle("report-1")["report_json"] == {"report": True}
        assert memory.list_strategy_initiatives(cycle["id"])[0]["evidence"] == ["dataforseo.keyword_seed"]
    finally:
        memory.close()


def test_unsupported_article_language_becomes_a_localization_proposal():
    strategy = {
        "summary": "summary",
        "initiatives": [{
            "kind": "content",
            "title": "French guide",
            "action": "Write it",
            "language": "fr",
            "market": "FR",
            "evidence": [],
        }],
        "article": {"title": "French guide", "language": "fr", "market": "FR"},
    }
    result = _apply_language_boundary(strategy, _config(), {"focus_market": {"language": "fr", "country": "FR"}})
    assert result["article"]["unsupported_language"] is True
    assert result["initiatives"][0]["kind"] == "localization"


def test_owner_action_round_trip_preserves_reference_columns(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        action = memory.create_owner_action(
            OwnerAction(
                capability_id="seo.test",
                provider_id="site-agent",
                title="Review",
                summary="Review the proposal",
                action_label="Review",
                priority=ActionPriority.NORMAL,
                requirement=ActionRequirement.OWNER_DECISION,
                source_ref="test:1",
                dedupe_key="test:1",
                state=ActionState.OPEN,
                artifact_id=4,
                job_id=5,
                approval_id=6,
                draft_id=7,
            )
        )
        loaded = memory.get_owner_action(action.id)
        assert loaded is not None
        assert (loaded.artifact_id, loaded.job_id, loaded.approval_id, loaded.draft_id) == (4, 5, 6, 7)
    finally:
        memory.close()


def test_outcome_job_waits_for_baseline_and_records_due_metric_change(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        baseline = memory.snapshot_metrics("gsc", {"current": {"clicks": 100}})
        del baseline
        cycle = memory.create_strategy_cycle("report-2", "2026-02", "hash", {})
        initiative_id = memory.create_strategy_initiative(
            cycle["id"],
            kind="content",
            title="Guide",
            summary="Write guide",
            expected={
                "implementation_baseline": {
                    "gsc": {"data": {"current": {"clicks": 100}}},
                    "ga4": {},
                }
            },
            review_30_ts="2020-01-01T00:00:00+00:00",
            state="approved",
        )
        memory.snapshot_metrics("gsc", {"current": {"clicks": 120}})
        assert seo_outcomes.run({"memory": memory}) == 1
        outcome = memory.get_strategy_outcome(initiative_id, 30)
        assert outcome is not None
        assert outcome["assessment"] == "positive"
    finally:
        memory.close()


def test_outcome_job_does_not_substitute_ga4_for_gsc_baseline(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        cycle = memory.create_strategy_cycle("report-3", "2026-02", "hash", {})
        initiative_id = memory.create_strategy_initiative(
            cycle["id"],
            kind="content",
            title="Search page",
            summary="Improve search page",
            expected={
                "implementation_baseline": {
                    "metric": "gsc.clicks",
                    "gsc": {"data": {"current": {"clicks": 10}}},
                    "ga4": {"data": {"current": {"sessions": 100}}},
                }
            },
            review_30_ts="2020-01-01T00:00:00+00:00",
            state="approved",
        )
        memory.snapshot_metrics("ga4", {"current": {"sessions": 999}})
        assert seo_outcomes.run({"memory": memory}) == 1
        outcome = memory.get_strategy_outcome(initiative_id, 30)
        assert outcome is not None
        assert outcome["assessment"] == "inconclusive"
        assert outcome["observed"]["metric"] == "gsc.clicks"
        assert outcome["observed"]["state"] == "missing"
    finally:
        memory.close()


def test_strategy_cycle_creates_report_artifact_without_fake_site_change_approval(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        request = memory.create_seo_research_request(
            "2026-02",
            "standard-v1",
            "seo:2026-02:standard-v1",
            {"period": "2026-02", "focus_market": {"language": "en", "country": "US"}, "business_goal": "Grow demand"},
        )
        request = memory.update_seo_research_request(request["id"], report_id="report-artifact-1")
        report = {
            "freshness": {"dataforseo": {"completed_count": 7, "task_count": 7}},
            "history": {"windows": {"history_state": "insufficient_history"}, "gsc_months": []},
            "dataforseo": [],
        }

        class StrategyLlm:
            def chat(self, *_args, **_kwargs):
                return (
                    '{"summary":"A focused opportunity", "initiatives":['
                    '{"kind":"technical","title":"Improve the homepage","action":"Clarify the homepage service paths",'
                    '"hypothesis":"Clearer paths improve qualified discovery","why":"The crawl shows weak structure",'
                    '"evidence":["first_party.crawl"],"expected":{"areas":["Homepage"]},"priority":"normal",'
                    '"language":"en","market":"US"}],'
                    '"article":{"title":"French article","angle":"A useful angle","why":"A reader need",'
                    '"primary_keyword":"guide","language":"fr","market":"FR","source_urls":[]}}'
                )

        actions = OwnerActionService(memory)
        approvals = ApprovalService(
            memory,
            actions=actions,
            capabilities=CapabilityRegistry(default_capabilities()),
        )
        _process_report(
            {
                "config": _config(),
                "memory": memory,
                "llm": StrategyLlm(),
                "owner_action_service": actions,
                "approval_service": approvals,
            },
            request,
            {"status": "completed", "report": report},
        )

        cycles = memory.conn.execute("SELECT * FROM strategy_cycles").fetchall()
        assert len(cycles) == 1
        assert cycles[0]["report_artifact_id"] is not None
        report_artifact = memory.get_artifact(cycles[0]["report_artifact_id"])
        assert report_artifact is not None
        assert report_artifact.kind.value == "seo_report"
        assert any(draft["kind"] == "report" for draft in memory.list_drafts(limit=20))
        initiatives = memory.list_strategy_initiatives(cycles[0]["id"])
        assert initiatives[0]["artifact_id"] is None
        assert initiatives[0]["approval_id"] is None
        assert len(memory.list_approval_requests(status="pending")) == 0
        actions = memory.list_owner_actions(states=("open",), limit=10)
        assert actions and actions[0].action_label == "Review Ada's SEO proposal"
        assert not any(action.title.startswith("Monthly SEO report") for action in HomeService(memory).snapshot(20, 20).needs_you)
    finally:
        memory.close()
