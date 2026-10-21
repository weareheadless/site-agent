from datetime import datetime, timezone
import json
import pytest

from site_agent.application.growth_service_model import AREAS, service_model
from site_agent.brain.growth import assess


def project(**kwargs):
    args = dict(tasks=[], initiatives=[], runs=[], sources=[], activities=[], website_present=True,
                now=datetime(2026, 10, 21, tzinfo=timezone.utc))
    return service_model(**{**args, **kwargs})


def test_missing_evidence_is_not_a_healthy_area_assessment():
    model = project(sources=[{"id": "gsc", "state": "ready", "observedAt": "2026-10-20T00:00:00Z"}])
    assert len(model["areas"]) == len(AREAS)
    assert all(row["state"] == "not_assessed" for row in model["areas"])
    assert all(row["lastAssessedAt"] is None for row in model["areas"])
    assert model["decisionIds"] == []


def test_one_cross_area_improvement_has_one_decision_and_preserves_a_separate_blocker():
    tasks = [
        {"id": "initiative:1", "focus": "needs_you", "canApprove": True, "approvalId": 12},
        {"id": "initiative:2", "focus": "paused", "executionIssue": True},
    ]
    initiatives = [
        {"id": 1, "expected": {"opportunity": {"primaryArea": "content", "secondaryAreas": ["search_visibility"]}}},
        {"id": 2, "expected": {"opportunity": {"primaryArea": "search_visibility"}}},
    ]
    model = project(tasks=tasks, initiatives=initiatives)
    assert model["decisionIds"] == ["initiative:1"]
    assert len(model["work"]) == 2
    search = next(row for row in model["areas"] if row["id"] == "search_visibility")
    assert search["state"] == "needs_decision"
    assert search["blockedWorkIds"] == ["initiative:2"]
    assert search["decisionIds"] == ["initiative:1"]


def test_unclassified_work_stays_visible_without_title_keyword_guessing():
    model = project(tasks=[{"id": "initiative:5", "title": "SEO speed article", "kind": "code", "focus": "paused"}])
    assert model["unassignedWorkIds"] == ["initiative:5"]
    assert model["work"][0]["primaryArea"] is None


def test_article_scope_is_content_and_does_not_copy_its_full_body():
    model = project(tasks=[{"id": "article:1", "kind": "article", "focus": "preparing", "body": "private full body"}])
    assert model["work"][0]["primaryArea"] == "content"
    assert "private full body" not in str(model)


def test_owner_answer_is_not_a_publication_approval():
    model = project(tasks=[{"id": "initiative:1", "focus": "needs_you", "ownerActionId": 8, "canApprove": False}])
    assert model["decisionIds"] == ["initiative:1"]
    assert model["work"][0]["actor"] == "owner"
    assert model["work"][0]["canApprove"] is False


def test_ready_state_without_approval_or_owner_action_does_not_create_a_decision():
    model = project(tasks=[{"id": "broken", "focus": "needs_you", "canApprove": False}])
    assert model["decisionIds"] == []
    assert model["work"][0]["state"] == "unresolved"


def test_area_assessment_time_is_not_run_update_or_raw_measurement_time():
    model = project(runs=[{"updated_ts": "2026-10-21T05:00:00Z", "detail": {
        "assessmentCompletedAt": "2026-10-20T02:00:00Z",
        "assessment": {"coverage": [{"area": "website_health", "summary": "Checked the supplied crawl.", "evidence": ["crawl:1"], "limitations": ["No speed measurement"]}]},
    }}])
    health = next(row for row in model["areas"] if row["id"] == "website_health")
    assert health["lastAssessedAt"] == "2026-10-20T02:00:00Z"
    assert health["state"] == "assessed"
    assert next(row for row in model["areas"] if row["id"] == "speed_experience")["state"] == "not_assessed"


def test_overdue_or_disabled_schedule_is_not_a_future_commitment():
    model = project(activities=[
        {"id": "growth_initial", "enabled": True, "nextRun": "2026-10-20T01:00:00Z"},
        {"id": "growth_weekly", "enabled": False, "nextRun": "2026-11-01T01:00:00Z"},
    ])
    assert model["overdueActivityIds"] == ["growth_initial"]
    assert all(row["nextAssessment"] is None for row in model["areas"])


def test_new_workspace_has_no_fake_checks_or_growth_commitments():
    model = project(website_present=False, activities=[{"id": "growth_weekly", "enabled": True, "nextRun": "2026-11-01T01:00:00Z"}])
    assert all(row["state"] == "awaiting_activation" for row in model["areas"])
    assert all(row["nextAssessment"] is None for row in model["areas"])


@pytest.mark.parametrize("coverage", [
    [{"area": "speed_experience", "summary": "Fast", "evidence": ["invented"], "limitations": []}],
    [{"area": "not_a_product_area", "summary": "Checked", "evidence": ["inventory"], "limitations": []}],
    [{"area": "content", "summary": "Checked", "evidence": [], "limitations": []}],
])
def test_planner_rejects_unbound_or_invalid_area_evidence(coverage):
    class LLM:
        def chat(self, *args, **kwargs):
            return json.dumps({"summary": "Assessed", "opportunities": [], "coverage": coverage})
    with pytest.raises(ValueError, match="coverage"):
        assess({"llm": LLM()}, {"sources": [{"id": "inventory"}], "inventory": []})
