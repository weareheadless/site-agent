import json

from site_agent.qa.driver import FlowResult, Observations, StepResult
from site_agent.qa.flow import Flow
from site_agent.qa.rubric import ModelJudge, RuleJudge, review


def _flow(tier="deterministic"):
    return Flow.from_dict(
        {
            "id": "demo",
            "title": "Demo",
            "tier": tier,
            "steps": [{"id": "open", "action": "goto", "url": "/"}],
        }
    )


def _result(status="passed", detail="opened"):
    result = FlowResult(flow=_flow(), base_url="http://127.0.0.1:3012", status=status)
    result.steps = [StepResult(id="open", action="goto", status=status, detail=detail)]
    result.observations = Observations(page_metrics={"readyState": "complete"})
    return result


def _ids(verdict):
    return {check.id for check in verdict.checks if not check.ok}


def test_a_clean_run_passes():
    verdict = review(_result())
    assert verdict.verdict == "pass"
    assert verdict.passed is True
    assert verdict.reasons == []


def test_console_errors_block():
    result = _result()
    result.observations.console_errors = [{"step": "open", "text": "Uncaught TypeError", "location": ""}]
    verdict = review(result)
    assert verdict.verdict == "fail"
    assert "browser.console" in _ids(verdict)


def test_failed_requests_block_because_agents_md_says_they_are_failures():
    result = _result()
    result.observations.failed_requests = [
        {"step": "open", "url": "http://x/app.js", "method": "GET", "reason": "net::ERR_FAILED"}
    ]
    assert "browser.requests" in _ids(review(result))


def test_uncaught_page_errors_block():
    result = _result()
    result.observations.page_errors = [{"step": "open", "text": "ReferenceError: x is not defined"}]
    assert "browser.pageerror" in _ids(review(result))


def test_raw_contract_error_reaching_the_owner_blocks():
    result = _result(status="failed", detail="step open failed")
    result.observations.page_metrics["bodyText"] = (
        "creative direction returned an invalid experience plan: "
        "brand_behavior_system.utility_behaviors[0].meaning is required"
    )
    verdict = review(result)
    assert "owner.error_text" in _ids(verdict)
    assert "flow.steps" in _ids(verdict)


def test_harness_error_text_is_not_mistaken_for_owner_text():
    result = _result(status="failed", detail="DriverError: conversation did not settle")
    assert "owner.error_text" not in _ids(review(result))


def test_a_clean_failure_with_an_actionable_message_is_not_penalised():
    result = _result(status="failed", detail="step open failed")
    result.observations.page_metrics["bodyText"] = (
        "Ada could not finish the plan. Retry from the brief."
    )
    result.steps[0].status = "failed"
    verdict = review(result)
    assert "owner.error_text" not in _ids(verdict)


def test_broken_images_block():
    result = _result()
    result.observations.page_metrics["brokenImages"] = 2
    assert "page.images" in _ids(review(result))


def test_page_that_never_finishes_loading_blocks():
    result = _result()
    result.observations.page_metrics["readyState"] = "loading"
    assert "page.ready" in _ids(review(result))


def test_missing_metrics_are_advisory_not_blocking():
    result = _result()
    result.observations.page_metrics = {}
    verdict = review(result)
    assert verdict.passed is True
    assert any(check.id == "page.ready" and not check.blocking for check in verdict.checks)


def test_verdict_serialises_for_the_gate():
    payload = review(_result()).to_dict()
    assert payload["schema"]
    assert payload["passed"] is True
    assert payload["failed_checks"] == []
    json.dumps(payload)


def test_model_judge_is_advisory_and_parses_strict_json():
    def complete(prompt):
        assert "EVIDENCE" in prompt
        return '```json\n{"verdict": "fail", "findings": [{"severity": "blocking", "summary": "empty hero"}]}\n```'

    verdict = ModelJudge(complete).review(_result())
    assert verdict.verdict == "fail"
    assert verdict.findings[0]["summary"] == "empty hero"


def test_model_judge_degrades_to_needs_review_instead_of_guessing():
    assert ModelJudge(lambda prompt: "no idea, sorry").review(_result()).verdict == "needs_review"
    assert ModelJudge(lambda prompt: "```json\n{oops\n```").review(_result()).verdict == "needs_review"


def test_model_judge_failure_never_raises():
    def explode(prompt):
        raise RuntimeError("provider down")

    verdict = ModelJudge(explode).review(_result())
    assert verdict.verdict == "needs_review"
    assert "provider down" in verdict.reasons[0]


def test_rule_judge_ignores_the_model_entirely():
    assert RuleJudge().review(_result()).judge == "rule"
