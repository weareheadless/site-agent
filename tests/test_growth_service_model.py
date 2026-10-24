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


def test_assessment_requires_a_canonical_primary_area_and_distinct_secondary_areas():
    opportunity = {
        "kind": "code", "title": "Improve navigation", "why": "Visitors miss key pages", "scope": "Navigation",
        "evidence": ["crawl"], "requiredSources": ["crawl"], "primaryArea": "website_health",
        "secondaryAreas": ["content"],
    }

    class LLM:
        def __init__(self, item):
            self.item = item
            self.messages = None

        def chat(self, messages, **kwargs):
            self.messages = messages
            return json.dumps({"summary": "Assessed", "opportunities": [self.item]})

    llm = LLM(opportunity)
    result = assess({"llm": llm}, {"sources": [{"id": "crawl"}], "inventory": []})
    assert result["opportunities"][0]["primaryArea"] == "website_health"
    contract = llm.messages[0]["content"]
    assert "Every opportunity must include primaryArea" in contract
    assert "secondaryAreas is optional" in contract
    assert "required for every new coverage row" in contract
    assert "headline to 90 characters or fewer" in contract
    assert "problem and nextStep to 160 characters or fewer" in contract


def test_assessment_accepts_optional_bounded_owner_summary_on_evidenced_coverage():
    class LLM:
        def chat(self, *args, **kwargs):
            return json.dumps({"summary": "Reviewed the supplied evidence.", "opportunities": [], "coverage": [{
                "area": "content", "summary": "Canonical inventory was reviewed.", "evidence": ["inventory"],
                "limitations": ["Metadata only"], "ownerSummary": {
                    "headline": "Some entries lack destinations.",
                    "problem": "Visitors cannot open the matching details from this page.",
                    "nextStep": "Link each entry to its existing destination."}}]})
    result = assess({"llm": LLM()}, {"sources": [{"id": "inventory"}], "inventory": []})
    assert result["coverage"][0]["ownerSummary"]["nextStep"].startswith("Link each entry")


def test_assessment_keeps_legacy_owner_summary_storage_bounds_compatible():
    owner_summary = {"headline": "h" * 170, "problem": "p" * 480, "nextStep": "n" * 480}
    class LLM:
        def chat(self, *args, **kwargs):
            return json.dumps({"summary": "Reviewed the supplied evidence.", "opportunities": [], "coverage": [{
                "area": "content", "summary": "Canonical inventory was reviewed.", "evidence": ["inventory"],
                "limitations": [], "ownerSummary": owner_summary}]})
    result = assess({"llm": LLM()}, {"sources": [{"id": "inventory"}], "inventory": []})
    assert result["coverage"][0]["ownerSummary"] == owner_summary


@pytest.mark.parametrize("owner_summary", [
    {"headline": "Okay", "problem": "Only two keys"},
    {"headline": "x" * 181, "problem": "Problem", "nextStep": "Action"},
    {"headline": "Headline", "problem": " ", "nextStep": "Action"},
])
def test_assessment_rejects_malformed_or_unbounded_owner_summary(owner_summary):
    class LLM:
        def chat(self, *args, **kwargs):
            return json.dumps({"summary": "Reviewed the supplied evidence.", "opportunities": [], "coverage": [{
                "area": "content", "summary": "Canonical inventory was reviewed.", "evidence": ["inventory"],
                "limitations": [], "ownerSummary": owner_summary}]})
    with pytest.raises(ValueError, match="ownerSummary"):
        assess({"llm": LLM()}, {"sources": [{"id": "inventory"}], "inventory": []})


@pytest.mark.parametrize("area", [None, "not_a_product_area"])
def test_assessment_rejects_missing_or_unknown_primary_area(area):
    opportunity = {
        "kind": "code", "title": "Improve navigation", "why": "Visitors miss key pages", "scope": "Navigation",
        "evidence": ["crawl"], "requiredSources": ["crawl"],
    }
    if area is not None:
        opportunity["primaryArea"] = area

    class LLM:
        def chat(self, *args, **kwargs):
            return json.dumps({"summary": "Assessed", "opportunities": [opportunity]})

    with pytest.raises(ValueError, match="primary Growth area"):
        assess({"llm": LLM()}, {"sources": [{"id": "crawl"}], "inventory": []})


@pytest.mark.parametrize("secondary", [["website_health"], ["not_a_product_area"]])
def test_assessment_rejects_invalid_secondary_areas(secondary):
    opportunity = {
        "kind": "code", "title": "Improve navigation", "why": "Visitors miss key pages", "scope": "Navigation",
        "evidence": ["crawl"], "requiredSources": ["crawl"], "primaryArea": "website_health",
        "secondaryAreas": secondary,
    }

    class LLM:
        def chat(self, *args, **kwargs):
            return json.dumps({"summary": "Assessed", "opportunities": [opportunity]})

    with pytest.raises(ValueError, match="secondary Growth area"):
        assess({"llm": LLM()}, {"sources": [{"id": "crawl"}], "inventory": []})


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
    model = project(sources=[{"id": "crawl:1", "state": "ready"}], runs=[{"updated_ts": "2026-10-21T05:00:00Z", "detail": {
        "assessmentCompletedAt": "2026-10-20T02:00:00Z",
        "material": {"sources": [{"id": "crawl:1", "state": "ready", "observedAt": "2026-10-20T01:00:00Z"}]},
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


def test_later_execution_update_does_not_replace_a_newer_assessment():
    def run(assessed, updated, summary):
        return {"updated_ts": updated, "detail": {"assessmentCompletedAt": assessed,
            "assessment": {"coverage": [{"area": "content", "summary": summary,
                "evidence": ["inventory"], "limitations": []}]}}}
    model = project(runs=[
        run("2026-10-19T01:00:00Z", "2026-10-21T12:00:00Z", "Old assessment"),
        run("2026-10-20T01:00:00Z", "2026-10-20T02:00:00Z", "New assessment"),
    ])
    assert model["areas"][0]["summary"] == "New assessment"


def test_unavailable_or_stale_evidence_is_not_presented_as_current_coverage():
    for source_state, expected in [("stale", "stale"), ("unauthorised", "unavailable")]:
        model = project(sources=[{"id": "gsc", "state": source_state}], runs=[{
            "detail": {"assessmentCompletedAt": "2026-10-20T01:00:00Z", "assessment": {
                "coverage": [{"area": "search_visibility", "summary": "Reviewed search",
                    "evidence": ["gsc"], "limitations": []}]}}}])
        area = next(row for row in model["areas"] if row["id"] == "search_visibility")
        assert area["evidenceState"] == expected
        assert area["state"] == expected


def test_coverage_without_assessment_completion_is_not_a_completed_check():
    model = project(runs=[{"updated_ts": "2026-10-21T00:00:00Z", "detail": {
        "assessment": {"coverage": [{"area": "content", "summary": "Not completed",
            "evidence": ["inventory"], "limitations": []}]}}}])
    assert model["areas"][0]["state"] == "not_assessed"
    assert model["areas"][0]["lastAssessedAt"] is None


def test_deferred_initiative_remains_explained_without_becoming_a_decision():
    model = project(initiatives=[{"id": 9, "state": "deferred", "title": "Improve a page",
        "expected": {"opportunity": {"primaryArea": "content"}}, "validation": {
            "reason": "Evidence is too limited", "reassessWhen": "After new search data arrives"}}])
    assert model["decisionIds"] == []
    work = model["work"][0]
    assert work["id"] == "initiative:9"
    assert work["state"] == "deferred"
    assert work["reassessWhen"] == "After new search data arrives"
    assert model["areas"][0]["deferredWorkIds"] == ["initiative:9"]


def test_capacity_wait_exposes_its_real_run_and_executor_not_an_invented_task():
    run = {"run_id": "weekly-1", "status": "pending", "next_due_ts": "2026-10-21T01:00:00Z",
        "detail": {"waitingForCapacity": ["Next article"], "assessment": {"opportunities": [
            {"title": "Next article", "primaryArea": "content"}]}}}
    model = project(runs=[run], reconciliation={"enabled": True, "nextRun": "2026-10-21T02:00:00Z"})
    assert model["areas"][0]["state"] == "waiting_for_capacity"
    assert model["areas"][0]["pendingRunIds"] == ["weekly-1"]
    assert model["preparation"][0]["executor"] == "growth_pending"
    assert model["preparation"][0]["nextReconciliationAt"] == "2026-10-21T02:00:00Z"
    assert model["work"] == []
    assert project(runs=[run])["preparation"][0]["executor"] is None


def test_findings_preserve_run_index_and_exact_initiative_linkage_without_title_join():
    opportunity = {"kind": "payload_content", "title": "Fix the home page", "why": "Visitors cannot find the route.",
        "hypothesis": "Clear links may help visitors continue.", "scope": "Add links to the two existing routes.",
        "primaryArea": "content", "secondaryAreas": ["search_visibility"], "evidence": ["inventory"],
        "requiredSources": ["inventory"], "collection": "pages", "documentId": "1"}
    run = {"run_id": "run-1", "status": "pending", "detail": {
        "assessmentCompletedAt": "2026-10-20T00:00:00Z",
        "candidateIds": [10],
        "assessment": {"opportunities": [opportunity]}}}
    blocker = {"id": 9, "kind": "code", "state": "preparing", "growth_run_id": "other-run"}
    same_run = {"id": 10, "kind": "payload_content", "state": "ready_for_review", "growth_run_id": "run-1",
        "expected": {"opportunity": dict(opportunity)}}
    model = project(runs=[run], initiatives=[blocker, same_run], max_active_candidates=1,
        sources=[{"id": "inventory", "state": "ready"}])
    content = next(row for row in model["areas"] if row["id"] == "content")
    finding = content["findings"][0]
    assert finding["id"] == "run-1:0"
    assert finding["runId"] == "run-1" and finding["opportunityIndex"] == 0
    assert finding["problem"] == opportunity["why"] and finding["nextStep"] == opportunity["scope"]
    assert finding["status"] == "ready_for_review"
    assert finding["initiativeId"] == 10
    assert finding["candidateId"] == 10
    assert finding["target"] == {"collection": "pages", "documentId": "1"}
    assert finding["waitingOnWorkIds"] == []
    # It remains cross-area work with the same lineage, rather than a second finding.
    search = next(row for row in model["areas"] if row["id"] == "search_visibility")
    assert search["findings"] == content["findings"]


def test_waiting_findings_only_join_unique_titles_and_report_current_external_capacity_work():
    first = {"kind": "code", "title": "Same title", "why": "Problem one", "scope": "Action one",
        "evidence": ["inventory"], "requiredSources": ["inventory"], "primaryArea": "website_health"}
    second = {**first, "why": "Problem two", "scope": "Action two"}
    run = {"run_id": "run-2", "status": "pending", "detail": {
        "assessmentCompletedAt": "2026-10-20T00:00:00Z", "waitingForCapacity": ["Same title"],
        "assessment": {"opportunities": [first, second]}}}
    model = project(runs=[run], initiatives=[
        {"id": 1, "kind": "code", "state": "preparing", "growth_run_id": "other"},
        {"id": 2, "kind": "payload_content", "state": "ready_for_review", "growth_run_id": "other"},
        {"id": 3, "kind": "code", "state": "preparing", "growth_run_id": "run-2"},
        {"id": 4, "kind": "owner_information", "state": "waiting_for_owner", "growth_run_id": "other"},
    ], sources=[{"id": "inventory", "state": "ready"}], max_active_candidates=2)
    findings = next(row for row in model["areas"] if row["id"] == "website_health")["findings"]
    assert [row["status"] for row in findings] == ["unknown", "unknown"]
    assert all(row["waitingOnWorkIds"] == [] for row in findings)

    candidate_opportunity = {"kind": "payload_content", "title": "Other finding", "why": "Other problem",
        "scope": "Other action", "evidence": ["inventory"], "requiredSources": ["inventory"],
        "primaryArea": "content"}
    unique = {**run, "run_id": "run-3", "detail": {**run["detail"], "candidateIds": [3], "queuedInitiativeIds": [5],
        "assessment": {"opportunities": [first, candidate_opportunity]}}}
    model = project(runs=[unique], initiatives=[
        {"id": 1, "kind": "code", "state": "preparing", "growth_run_id": "other"},
        {"id": 3, "kind": "payload_content", "state": "ready_for_review", "growth_run_id": "run-3",
            "expected": {"opportunity": candidate_opportunity}},
        {"id": 5, "kind": "code", "state": "validating", "growth_run_id": "run-3"},
        {"id": 4, "kind": "owner_information", "state": "waiting_for_owner", "growth_run_id": "other"},
    ], sources=[{"id": "inventory", "state": "ready"}], max_active_candidates=3)
    finding = next(row for row in model["areas"] if row["id"] == "website_health")["findings"][0]
    assert finding["status"] == "waiting_for_capacity"
    assert finding["waitingOnWorkIds"] == ["initiative:1", "initiative:3", "initiative:5"]
    assert finding["capacityState"] == "full"


def test_saved_wait_marker_does_not_claim_current_blockage_when_capacity_is_available():
    opportunity = {"kind": "code", "title": "One finding", "why": "A current issue.", "scope": "Fix it.",
        "evidence": ["inventory"], "requiredSources": ["inventory"], "primaryArea": "website_health"}
    run = {"run_id": "run-free", "status": "pending", "detail": {
        "assessmentCompletedAt": "2026-10-20T00:00:00Z", "waitingForCapacity": [opportunity["title"]],
        "assessment": {"opportunities": [opportunity]}}}
    model = project(runs=[run], initiatives=[
        {"id": 9, "kind": "code", "state": "preparing", "growth_run_id": "other"}],
        sources=[{"id": "inventory", "state": "ready"}], max_active_candidates=2)
    finding = next(row for row in model["areas"] if row["id"] == "website_health")["findings"][0]
    assert finding["status"] == "waiting_for_capacity"
    assert finding["capacityState"] == "available"
    assert finding["waitingOnWorkIds"] == []
    assert "currently available" in finding["statusReason"]


def test_owner_summary_is_optional_and_suppressed_when_coverage_evidence_is_stale_or_missing():
    coverage = {"area": "content", "summary": "Canonical content was reviewed.", "evidence": ["inventory"],
        "limitations": ["Metadata only"], "ownerSummary": {
            "headline": "The home page has unlabeled entries.",
            "problem": "Visitors cannot tell which existing page an entry opens.",
            "nextStep": "Link the entries to the matching existing pages."}}
    run = {"detail": {"assessmentCompletedAt": "2026-10-20T00:00:00Z", "material": {"sources": [
        {"id": "inventory", "sourceRef": "inventory", "state": "ready", "observedAt": "2026-10-20T00:00:00Z"}]},
        "assessment": {"coverage": [coverage]}}}
    area = project(runs=[run], sources=[{"id": "inventory", "state": "ready"}])["areas"][0]
    assert area["ownerSummary"] == coverage["ownerSummary"]
    stale = project(runs=[run], sources=[{"id": "inventory", "state": "stale"}])["areas"][0]
    assert "ownerSummary" not in stale
    missing = project(runs=[{**run, "detail": {**run["detail"], "material": {},
        "assessment": {"coverage": [coverage]}}}])["areas"][0]
    assert "ownerSummary" not in missing


def test_current_ready_source_does_not_refresh_an_old_findings_evidence_snapshot():
    opportunity = {"kind": "code", "title": "Old finding", "why": "Historical issue.", "scope": "Review it.",
        "evidence": ["gsc"], "requiredSources": ["gsc"], "primaryArea": "search_visibility"}
    run = {"run_id": "old-run", "status": "completed", "detail": {
        "assessmentCompletedAt": "2026-01-01T00:00:00Z", "material": {"sources": [
            {"id": "gsc", "state": "ready", "observedAt": "2026-01-01T00:00:00Z", "freshnessHours": 24}]},
        "assessment": {"opportunities": [opportunity]}}}
    finding = next(row for row in project(runs=[run], sources=[{"id": "gsc", "state": "ready"}])["areas"]
        if row["id"] == "search_visibility")["findings"][0]
    assert finding["evidenceState"] == "stale"


def test_missing_historical_evidence_cannot_imply_current_coverage():
    model = project(runs=[{"detail": {"assessmentCompletedAt": "2026-01-01T00:00:00Z",
        "assessment": {"coverage": [{"area": "content", "summary": "Old check",
            "evidence": ["ga4:old"], "limitations": []}]}}}])
    area = model["areas"][0]
    assert area["state"] == "unavailable"
    assert area["unresolvedEvidenceRefs"] == ["ga4:old"]
    assert area["limitations"]


def test_inventory_evidence_uses_its_capture_time_and_retains_scope():
    def model(captured):
        return project(runs=[{"detail": {"assessmentCompletedAt": "2026-10-20T00:00:00Z",
            "material": {"sources": [{"id": "inventory", "sourceRef": "canonical_payload_inventory",
                "state": "ready", "observedAt": captured}], "inventory": [{"sourceRef": "payload:pages:1"}]},
            "assessment": {"coverage": [{"area": "content", "summary": "Inventory check",
                "evidence": ["payload:pages:1"], "limitations": ["Metadata only"]}]}}}])["areas"][0]
    assert model("2026-10-20T00:00:00Z")["state"] == "assessed"
    assert model("2026-01-01T00:00:00Z")["state"] == "stale"


def test_speed_area_does_not_claim_core_web_vitals_monitoring():
    area = next(row for row in project()["areas"] if row["id"] == "speed_experience")
    assert area["capability"]["automatedMeasurement"] == "not_supported"
    assert area["state"] == "not_assessed"


def test_approval_or_published_label_does_not_manufacture_a_verified_result():
    model = project(tasks=[{"id": "initiative:1", "focus": "completed", "state": "published"}],
        initiatives=[{"id": 1, "state": "measuring", "published_revision": "payload:pages:1:revision",
            "validation": {"status": "passed"}}])
    assert model["recentResults"] == []


def test_source_health_receipt_without_technical_acceptance_is_not_a_result():
    task = {"id": "initiative:1", "focus": "completed", "state": "live"}
    initiative = {"id": 1, "published_revision": 'git:' + 'a' * 40,
        "validation": {"status": "passed", "liveVerification": {
            "verified": True, "commit": 'a' * 40, "releaseId": 'release-1'}}}
    assert project(tasks=[task], initiatives=[initiative])["recentResults"] == []


def test_verified_implementation_and_later_impact_are_separate_and_bounded():
    task = {"id": "initiative:1", "focus": "planned", "state": "measuring", "title": "Clearer title",
        "draftId": 5, "outcomes": [{"id": 3, "horizon_days": 30, "measured_ts": "2026-11-20",
            "baseline": {"value": 1, "metric": "gsc.clicks", "private": "not for overview"},
            "observed": {"value": 2, "metric": "gsc.clicks"}, "assessment": "positive", "confidence": "low"}]}
    initiative = {"id": 1, "state": "measuring", "published_revision": "payload:pages:1:revision",
        "review_90_ts": "2027-01-20T00:00:00Z", "validation": {"status": "passed",
            "liveVerification": {"status": "passed", "checks": [{"route": "/", "status": 200,
                "documentId": "1", "updatedAt": "revision", "verifiedAt": "2026-10-20T00:00:00Z"}]}}}
    result = project(tasks=[task], initiatives=[initiative])["recentResults"][0]
    assert result["state"] == "verified"
    assert result["impact"][0]["baseline"] == 1
    assert result["impact"][0]["observed"] == 2
    assert result["impact"][0]["causalAttribution"] is False
    assert "private" not in str(result)
    assert result["nextMeasurement"]["horizonDays"] == 90


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
