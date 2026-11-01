import json
from pathlib import Path

from site_agent.qa.driver import FlowResult, Observations, StepResult
from site_agent.qa.evidence import (
    EVIDENCE_SCHEMA,
    build_bundle,
    fingerprint,
    run_id,
    sha256_file,
    timings,
    write_bundle,
)
from site_agent.qa.flow import Flow
from site_agent.qa.rubric import Check, JudgeVerdict


def _flow():
    return Flow.from_dict(
        {
            "id": "demo-flow",
            "title": "Demo flow",
            "tier": "deterministic",
            "steps": [{"id": "open", "action": "goto", "url": "/"}],
        }
    )


def _result(status="failed", step_status="failed", detail="step open failed"):
    result = FlowResult(flow=_flow(), base_url="http://127.0.0.1:3012", status=status)
    result.steps = [StepResult(id="open", action="goto", status=step_status, detail=detail)]
    result.error = detail if status == "failed" else None
    return result


def _verdict(*failed):
    return JudgeVerdict(
        verdict="fail" if failed else "pass",
        checks=[Check(name, False, detail="x") for name in failed],
    )


def test_fingerprint_is_stable_for_the_same_failure():
    first = fingerprint(_result(), _verdict("browser.console"))
    second = fingerprint(_result(), _verdict("browser.console"))
    assert first == second
    assert len(first) == 16


def test_fingerprint_separates_different_failures():
    base = fingerprint(_result(), _verdict("browser.console"))
    other_step = _result(detail="step other failed")
    assert base != fingerprint(other_step, _verdict("browser.console"))
    assert base != fingerprint(_result(), _verdict("browser.requests"))


def test_fingerprint_ignores_generated_numbers_so_dedupe_survives_ids():
    a = fingerprint(_result(detail="run 1234 timed out"), None)
    b = fingerprint(_result(detail="run 9876 timed out"), None)
    assert a == b


def test_bundle_carries_schema_status_and_target(tmp_path):
    result = _result()
    (tmp_path / "00-open.png").write_bytes(b"png-bytes")
    result.artifacts = ["00-open.png"]
    bundle = build_bundle(
        result,
        verdict=_verdict("browser.console"),
        artifacts_dir=tmp_path,
        target={"sha": "abc123", "deployed_sha": "def456", "environment": "staging"},
    )
    assert bundle["schema"] == EVIDENCE_SCHEMA
    assert bundle["status"] == "failed"
    assert bundle["failed_step"] == "open"
    assert bundle["target"]["sha"] == "abc123"
    assert bundle["rubric"]["passed"] is False
    assert bundle["artifacts"]["files"] == [
        {"path": "00-open.png", "sha256": sha256_file(tmp_path / "00-open.png"), "bytes": 9}
    ]


def test_bundle_missing_artifacts_are_omitted_not_invented(tmp_path):
    result = _result()
    result.artifacts = ["never-written.png"]
    bundle = build_bundle(result, verdict=_verdict(), artifacts_dir=tmp_path)
    assert bundle["artifacts"]["files"] == []


def test_write_bundle_is_atomic_and_parses(tmp_path):
    bundle = build_bundle(_result(), verdict=_verdict(), artifacts_dir=tmp_path)
    target = tmp_path / "evidence" / "demo.json"
    path = write_bundle(bundle, target)
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == EVIDENCE_SCHEMA
    assert not (tmp_path / "evidence" / "demo.json.tmp").exists()


def test_observations_serialise_verbatim():
    result = _result()
    result.observations = Observations(
        console_errors=[{"step": "open", "text": "boom", "location": ""}],
        failed_requests=[{"step": "open", "url": "http://x/y.js", "method": "GET", "reason": "x"}],
        page_metrics={"readyState": "complete"},
    )
    bundle = build_bundle(result, verdict=_verdict(), artifacts_dir=Path("/tmp"))
    assert bundle["observations"]["console_errors"][0]["text"] == "boom"
    assert bundle["observations"]["page_metrics"]["readyState"] == "complete"


def test_run_id_is_filesystem_and_url_safe():
    value = run_id("Intake To: Preview", "2026-10-29T10:00:00Z")
    assert value == "intake-to-preview-2026-10-29t10-00-00z"
    assert " " not in value and ":" not in value


def test_timings_measure_each_stage_and_the_whole_run():
    result = _result(status="passed")
    result.marks = {
        "brief_ready": "2026-10-29T10:02:00Z",
        "build_requested": "2026-10-29T10:02:30Z",
        "candidate_ready": "2026-10-29T10:14:30Z",
        "site_live": "2026-10-29T10:15:00Z",
    }
    measured = timings(
        result,
        started_at="2026-10-29T10:00:00Z",
        finished_at="2026-10-29T10:15:00Z",
    )
    assert measured["durations_s"]["brief_ready"] == 120.0
    assert measured["durations_s"]["build_requested"] == 30.0
    assert measured["durations_s"]["candidate_ready"] == 720.0
    assert measured["durations_s"]["site_live"] == 30.0
    assert measured["total_s"] == 900.0


def test_timings_survive_a_run_with_no_marks():
    measured = timings(_result(), started_at=None, finished_at=None)
    assert measured["marks"] == {}
    assert measured["durations_s"] == {}
    assert measured["total_s"] is None


def test_bundle_carries_timings_and_incubation_id(tmp_path):
    result = _result(status="passed")
    result.marks = {"build_requested": "2026-10-29T10:02:30Z", "candidate_ready": "2026-10-29T10:14:30Z"}
    result.incubation_id = "intake-abc123"
    bundle = build_bundle(
        result,
        verdict=_verdict(),
        artifacts_dir=tmp_path,
        started_at="2026-10-29T10:00:00Z",
        finished_at="2026-10-29T10:15:00Z",
    )
    assert bundle["incubation_id"] == "intake-abc123"
    assert bundle["timings"]["durations_s"]["candidate_ready"] == 720.0
    assert bundle["timings"]["total_s"] == 900.0


def test_default_finished_at_is_used_for_total_time_and_models_are_retained(tmp_path):
    bundle = build_bundle(_result(), verdict=_verdict(), artifacts_dir=tmp_path,
                          started_at='2026-10-29T00:00:00Z',
                          target={'model': 'gpt-6-luna', 'provider': 'openai'})
    assert bundle['timings']['total_s'] is not None
    assert bundle['target']['model'] == 'gpt-6-luna'
    assert bundle['target']['provider'] == 'openai'
    assert run_id('demo') != run_id('demo'), 'two runs in one second must not overwrite evidence'
