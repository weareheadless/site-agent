import json
from pathlib import Path

import pytest

from site_agent.qa.flow import Flow, FlowError, Expectation, Step, load_flow, load_flows


def _minimal(**overrides):
    raw = {
        "id": "demo",
        "title": "Demo",
        "tier": "deterministic",
        "steps": [{"id": "open", "action": "goto", "url": "/"}],
    }
    raw.update(overrides)
    return raw


def test_flow_round_trips_through_its_own_dict():
    flow = Flow.from_dict(_minimal())
    assert flow.id == "demo"
    assert flow.tier == "deterministic"
    assert flow.step_ids == ("open",)
    assert Flow.from_dict(flow.to_dict()) == flow


def test_unknown_action_fails_at_load_not_at_run():
    with pytest.raises(FlowError, match="unknown action"):
        Flow.from_dict(_minimal(steps=[{"id": "x", "action": "teleport"}]))


def test_unknown_expectation_fails_at_load():
    with pytest.raises(FlowError, match="unknown expectation"):
        Flow.from_dict(
            _minimal(steps=[{"id": "x", "action": "assert", "expect": [{"kind": "vibes"}]}])
        )


def test_assert_step_without_expectations_asserts_nothing_and_is_rejected():
    with pytest.raises(FlowError, match="asserts nothing"):
        Flow.from_dict(_minimal(steps=[{"id": "x", "action": "assert"}]))


def test_unknown_tier_is_rejected():
    with pytest.raises(FlowError, match="unknown tier"):
        Flow.from_dict(_minimal(tier="sometimes"))


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(FlowError, match="duplicate step id"):
        Flow.from_dict(
            _minimal(
                steps=[
                    {"id": "open", "action": "goto", "url": "/"},
                    {"id": "open", "action": "goto", "url": "/again"},
                ]
            )
        )


def test_expectation_referencing_an_unknown_http_step_is_rejected():
    with pytest.raises(FlowError, match="unknown http step"):
        Flow.from_dict(
            _minimal(
                steps=[
                    {
                        "id": "check",
                        "action": "assert",
                        "expect": [{"kind": "status", "step": "missing", "value": 200}],
                    }
                ]
            )
        )


def test_action_specific_fields_are_required():
    with pytest.raises(FlowError, match="needs a url"):
        Flow.from_dict(_minimal(steps=[{"id": "x", "action": "goto"}]))
    with pytest.raises(FlowError, match="needs a selector"):
        Flow.from_dict(_minimal(steps=[{"id": "x", "action": "click"}]))
    with pytest.raises(FlowError, match="needs a path"):
        Flow.from_dict(_minimal(steps=[{"id": "x", "action": "http"}]))


def test_shipped_flows_are_valid_and_declare_their_tier():
    root = Path(__file__).resolve().parents[1] / "flows"
    flows = load_flows(root)
    assert flows, "the repository should ship at least one flow"
    ids = {flow.id for flow in flows}
    assert "intake-surface" in ids
    assert "intake-to-preview" in ids
    by_id = {flow.id: flow for flow in flows}
    assert by_id["intake-surface"].tier == "deterministic"
    assert by_id["intake-to-preview"].tier == "live"
    # A live flow must say what it needs, so it can never run by accident.
    assert by_id["intake-to-preview"].requires


def test_shipped_gate_flow_asserts_browser_health():
    flow = load_flow(Path(__file__).resolve().parents[1] / "flows" / "intake-surface.flow.yaml")
    kinds = {expectation.kind for step in flow.steps for expectation in step.expect}
    assert {"console_clean", "network_clean", "no_page_errors"} <= kinds


def test_flow_file_errors_are_explicit(tmp_path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(FlowError, match="cannot read flow"):
        load_flow(missing)
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(FlowError, match="cannot parse flow"):
        load_flow(broken)
    not_mapping = tmp_path / "list.yaml"
    not_mapping.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(FlowError, match="must be a mapping"):
        load_flow(not_mapping)


def test_expectation_defaults_are_conservative():
    expectation = Expectation.from_dict({"kind": "visible", "selector": "#x"}, "where")
    assert expectation.op == "eq"
    assert expectation.timeout_ms == 15_000


def test_step_defaults_to_capturing_a_screenshot():
    step = Step.from_dict({"id": "x", "action": "goto", "url": "/"}, "where")
    assert step.screenshot is True
    assert Step.from_dict(
        {"id": "x", "action": "goto", "url": "/", "screenshot": False}, "where"
    ).screenshot is False


def _converse(**overrides):
    raw = {
        "id": "talk",
        "action": "converse",
        "until": [{"kind": "visible", "selector": "#confirm-panel"}],
        "persona": {"brief": "You are Mariana, who runs a ceramics studio in Lisbon."},
    }
    raw.update(overrides)
    return _minimal(steps=[raw])


def test_converse_requires_an_end_condition():
    raw = _converse()
    del raw["steps"][0]["until"]
    with pytest.raises(FlowError, match="never ends"):
        Flow.from_dict(raw)


def test_converse_requires_a_persona_brief():
    raw = _converse()
    del raw["steps"][0]["persona"]
    with pytest.raises(FlowError, match="persona brief"):
        Flow.from_dict(raw)

    raw = _converse()
    raw["steps"][0]["persona"] = {"brief": "   "}
    with pytest.raises(FlowError, match="who this owner is"):
        Flow.from_dict(raw)


def test_persona_turn_limit_is_bounded():
    raw = _converse()
    raw["steps"][0]["persona"]["max_turns"] = 500
    with pytest.raises(FlowError, match="max_turns"):
        Flow.from_dict(raw)


def test_until_is_rejected_outside_a_conversation():
    raw = _minimal(
        steps=[
            {
                "id": "open",
                "action": "goto",
                "url": "/",
                "until": [{"kind": "visible", "selector": "#x"}],
            }
        ]
    )
    with pytest.raises(FlowError, match="only makes sense on a 'converse' step"):
        Flow.from_dict(raw)


def test_marks_must_be_stable_identifiers():
    with pytest.raises(FlowError, match="mark"):
        Flow.from_dict(
            _minimal(steps=[{"id": "open", "action": "goto", "url": "/", "mark": "Build Requested!"}])
        )
    flow = Flow.from_dict(
        _minimal(steps=[{"id": "open", "action": "goto", "url": "/", "mark": "build_requested"}])
    )
    assert flow.steps[0].mark == "build_requested"


def test_the_live_flow_gives_the_owner_a_brief_not_a_script():
    root = Path(__file__).resolve().parents[1] / "flows"
    flow = load_flow(root / "intake-to-preview.flow.yaml")
    converse = [step for step in flow.steps if step.action == "converse"]
    assert len(converse) == 1
    persona = converse[0].persona or {}
    brief = str(persona["brief"])
    assert len(brief) > 200, "the owner needs enough context to answer like a person"
    assert "facts" not in persona, "answers come from a model, not a lookup table"
    assert persona["max_turns"] >= 8
    assert converse[0].until

    marks = [step.mark for step in flow.steps if step.mark]
    assert "build_requested" in marks
    assert "candidate_ready" in marks
    assert "site_live" in marks
    assert marks.index("build_requested") < marks.index("candidate_ready")


def test_the_live_flow_aborts_when_the_build_reports_a_terminal_failure():
    root = Path(__file__).resolve().parents[1] / "flows"
    flow = load_flow(root / "intake-to-preview.flow.yaml")
    candidate = next(step for step in flow.steps if step.id == "candidate-in-review")
    assert candidate.abort, "waiting 30 minutes for a preview that will never render hides the cause"
    assert any(
        'blocked' in (expectation.selector or "") for expectation in candidate.abort
    )


def test_the_live_flow_provisions_like_production():
    root = Path(__file__).resolve().parents[1] / "flows"
    flow = load_flow(root / "intake-to-preview.flow.yaml")
    ids = flow.step_ids
    assert "provision-site" in ids
    assert ids.index("candidate-in-review") < ids.index("provision-site") < ids.index("site-live")
