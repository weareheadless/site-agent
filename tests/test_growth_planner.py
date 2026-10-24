import json

from site_agent.brain.growth import _response, assess


class RecordingLLM:
    def __init__(self):
        self.kwargs = None

    def chat(self, messages, **kwargs):
        self.kwargs = kwargs
        return json.dumps({"summary": "Grounded review.", "opportunities": []})


def test_structured_growth_plans_disable_hidden_reasoning():
    llm = RecordingLLM()

    result = _response(
        {"llm": llm},
        "summary: nonempty string; opportunities: array.",
        {"stage": "assess", "maxRecommendations": 3},
    )

    assert result["summary"] == "Grounded review."
    assert llm.kwargs == {
        "json_mode": True,
        "temperature": 0.2,
        "enable_thinking": False,
    }


class AssessmentLLM:
    def __init__(self, response):
        self.response = response

    def chat(self, *_args, **_kwargs):
        return json.dumps(self.response)


def _opportunity(kind="payload_content", title="Fix the service page summary"):
    return {
        "kind": kind, "primaryArea": "content", "title": title,
        "why": "The current service page omits a key detail visitors need.",
        "hypothesis": "Clearer information may help visitors decide whether to enquire.",
        "scope": "Update the summary on the existing service page only.",
        "evidence": ["inventory"], "requiredSources": ["inventory"],
        "collection": "pages", "documentId": "service",
    }


def _assessment_response(opportunities):
    return {"summary": "Reviewed this run's site evidence.", "opportunities": opportunities}


def test_assessment_defers_stale_finding_without_blocking_current_finding():
    material = {
        "maxRecommendations": 3,
        "sources": [{"id": "inventory", "state": "ready"}, {"id": "gsc", "state": "stale"}],
        "inventory": [{"collection": "pages", "document": {"id": "service"},
                       "sourceRef": "payload:pages:service"}],
    }
    finding = _opportunity()
    finding["requiredSources"] = ["gsc"]

    current = _opportunity(title="Current page summary")
    result = assess({"llm": AssessmentLLM(_assessment_response([current, finding]))}, material)

    assert "disposition" not in result["opportunities"][0]
    assert result["opportunities"][1]["disposition"] == "deferred"
    assert result["opportunities"][1]["errorCode"] == "required_evidence_not_current"


def test_assessment_defers_second_owner_question_instead_of_blocking_assessment():
    material = {
        "maxRecommendations": 3,
        "sources": [{"id": "inventory", "state": "ready"}],
        "inventory": [],
    }

    result = assess({"llm": AssessmentLLM(_assessment_response([
        _opportunity("owner_information", "Confirm service prices"),
        _opportunity("owner_information", "Confirm weekly availability"),
    ]))}, material)

    assert "disposition" not in result["opportunities"][0]
    assert result["opportunities"][1]["disposition"] == "deferred"
    assert result["opportunities"][1]["errorCode"] == "owner_question_already_open"


def test_deferred_owner_question_does_not_consume_the_single_question_slot():
    material = {
        "maxRecommendations": 3,
        "sources": [{"id": "inventory", "state": "ready"}, {"id": "business", "state": "stale"}],
        "inventory": [],
    }
    stale = _opportunity("owner_information", "Confirm pricing")
    stale["requiredSources"] = ["business"]
    current = _opportunity("owner_information", "Confirm availability")

    result = assess({"llm": AssessmentLLM(_assessment_response([stale, current]))}, material)

    assert result["opportunities"][0]["errorCode"] == "required_evidence_not_current"
    assert "disposition" not in result["opportunities"][1]


def test_assessment_defers_bad_citation_per_finding():
    material = {
        "maxRecommendations": 3,
        "sources": [{"id": "inventory", "state": "ready"}],
        "inventory": [{"collection": "pages", "document": {"id": "service"},
                       "sourceRef": "payload:pages:service"}],
    }
    bad = _opportunity(title="Unbound content claim")
    bad["evidence"] = ["old-run:gsc"]
    result = assess({"llm": AssessmentLLM(_assessment_response([
        _opportunity(title="Current page summary"), bad,
    ]))}, material)

    assert "disposition" not in result["opportunities"][0]
    assert result["opportunities"][1]["disposition"] == "deferred"
    assert result["opportunities"][1]["errorCode"] == "evidence_not_bound_to_assessment"
