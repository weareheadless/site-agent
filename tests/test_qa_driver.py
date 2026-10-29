"""The driver must be proven against a real browser, not mocked.

These tests run Chromium against a tiny local fixture so the parts that can
silently rot -- selector waits, console capture, failed-request capture,
screenshots, evidence hashing -- are exercised for real.
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is an optional extra")

from site_agent.qa.driver import PlaywrightDriver
from site_agent.qa.evidence import build_bundle
from site_agent.qa.flow import Flow
from site_agent.qa.rubric import RuleJudge

PAGES = {
    "/ok": """<!doctype html><html><head><title>Intake</title></head><body>
        <h1>Tell Ada about the business</h1>
        <form id="composer"><textarea id="message"></textarea>
        <button id="send" type="submit">Send</button></form>
        <p id="composer-note"></p></body></html>""",
    "/console": """<!doctype html><html><body><h1>Broken</h1>
        <script>console.error("Uncaught TypeError: cannot read property")</script>
        </body></html>""",
    "/missing": """<!doctype html><html><body><h1>Something else entirely</h1></body></html>""",
    "/raw": """<!doctype html><html><body>
        <p>creative direction returned an invalid experience plan:
        brand_behavior_system.utility_behaviors[0].meaning is required</p>
        </body></html>""",
    "/slow": """<!doctype html><html><body><h1>Wait</h1>
        <script>setTimeout(() => {
            const el = document.createElement("p"); el.id = "late"; el.textContent = "ready";
            document.body.appendChild(el); }, 600);</script></body></html>""",
    "/chat": """<!doctype html><html><head><title>Ada</title></head><body data-phase="intake">
        <span id="chat-state">Ready</span>
        <section id="confirm-panel" hidden><h3 id="confirm-heading">Ready to build</h3></section>
        <div id="messages"></div>
        <form id="composer"><textarea id="message"></textarea>
        <button id="send" type="submit">Send</button></form>
        <p id="composer-note"></p>
        <button id="provision" type="button">Provision</button>
        <p id="provision-note"></p>
        <script>
          const QUESTIONS = [
            "What is the studio called?",
            "How much are the classes?",
            "Where can people find you?"
          ];
          const messages = document.querySelector("#messages");
          const note = document.querySelector("#composer-note");
          let turn = 0;
          function add(role, text) {
            const item = document.createElement("article");
            item.className = "message";
            item.dataset.role = role;
            item.textContent = text;
            messages.append(item);
          }
          add("assistant", "Tell me what this website needs to make clear.");
          document.querySelector("#composer").addEventListener("submit", (event) => {
            event.preventDefault();
            const box = document.querySelector("#message");
            add("user", box.value);
            box.value = "";
            document.querySelector("#chat-state").textContent = "Working";
            setTimeout(() => {
              turn += 1;
              if (turn > QUESTIONS.length) {
                add("assistant", "That is enough. Ready to build.");
                document.querySelector("#confirm-panel").hidden = false;
                document.body.dataset.phase = "ready";
              } else {
                add("assistant", QUESTIONS[turn - 1]);
              }
              document.querySelector("#chat-state").textContent = "Ready";
            }, 120);
          });
          document.querySelector("#provision").addEventListener("click", () => {
            if (!window.confirm("Provision this exact website candidate?")) return;
            document.querySelector("#provision-note").textContent = "The website is moving into management.";
          });
        </script></body></html>""",
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGES.get(self.path)
        if body is None:
            self.send_error(404)
            return
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def origin():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _flow(steps, tier="deterministic"):
    return Flow.from_dict({"id": "driver-check", "title": "Driver check", "tier": tier, "steps": steps})


def _driver(origin, tmp_path, **kwargs):
    return PlaywrightDriver(
        base_url=origin,
        artifacts_dir=tmp_path / "artifacts",
        timeout_ms=5_000,
        **kwargs,
    )


def test_clean_flow_passes_and_records_evidence(origin, tmp_path):
    flow = _flow(
        [
            {
                "id": "open",
                "action": "goto",
                "url": "/ok",
                "expect": [{"kind": "visible", "selector": "#composer"}],
            },
            {
                "id": "type",
                "action": "fill",
                "selector": "#message",
                "text": "a ceramics studio",
                "expect": [{"kind": "visible", "selector": "#send"}],
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    verdict = RuleJudge().review(result)
    assert result.status == "passed", result.error
    assert verdict.passed is True, verdict.reasons
    assert [step.id for step in result.steps] == ["open", "type"]
    assert all(step.screenshot for step in result.steps)
    assert result.observations.page_metrics["readyState"] == "complete"
    assert "Tell Ada" in result.observations.page_metrics["bodyText"]

    bundle = build_bundle(result, verdict=verdict, artifacts_dir=tmp_path / "artifacts")
    assert bundle["status"] == "passed"
    assert len(bundle["artifacts"]["files"]) == 2
    assert all(item["bytes"] > 0 for item in bundle["artifacts"]["files"])


def test_console_error_is_captured_and_blocks(origin, tmp_path):
    flow = _flow([{"id": "open", "action": "goto", "url": "/console"}])
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "passed"
    assert result.observations.console_errors
    assert "Uncaught TypeError" in result.observations.console_errors[0]["text"]
    verdict = RuleJudge().review(result)
    assert verdict.passed is False
    assert "browser.console" in verdict.failed_checks


def test_missing_element_fails_the_step_and_stops_the_flow(origin, tmp_path):
    flow = _flow(
        [
            {
                "id": "open",
                "action": "goto",
                "url": "/missing",
                "expect": [{"kind": "visible", "selector": "#composer", "timeout_ms": 400}],
            },
            {"id": "never", "action": "goto", "url": "/ok"},
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "failed"
    assert result.failed_step == "open"
    assert result.steps[1].status == "skipped"
    assert RuleJudge().review(result).passed is False


def test_raw_internal_error_text_blocks_a_failed_run(origin, tmp_path):
    flow = _flow(
        [
            {
                "id": "open",
                "action": "goto",
                "url": "/raw",
                "expect": [{"kind": "visible", "selector": "#composer", "timeout_ms": 400}],
            }
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    verdict = RuleJudge().review(result)
    assert "owner.error_text" in verdict.failed_checks


def test_polling_waits_for_content_that_appears_late(origin, tmp_path):
    flow = _flow(
        [
            {
                "id": "open",
                "action": "goto",
                "url": "/slow",
                "expect": [
                    {"kind": "visible", "selector": "#late", "timeout_ms": 4_000},
                    {"kind": "text", "selector": "#late", "text": "ready"},
                ],
            }
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "passed", result.steps[0].detail


def test_text_absence_expectation_catches_the_ui056_signature(origin, tmp_path):
    flow = _flow(
        [
            {
                "id": "open",
                "action": "goto",
                "url": "/raw",
                "expect": [
                    {"kind": "text_absent", "selector": "body", "text": "meaning is required", "timeout_ms": 300}
                ],
            }
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "failed"
    assert "text_absent" in result.steps[0].detail


def test_http_step_and_json_expectations_are_recorded(origin, tmp_path):
    flow = _flow(
        [
            {"id": "missing", "action": "http", "method": "GET", "path": "/nope"},
            {
                "id": "check",
                "action": "assert",
                "expect": [{"kind": "status", "step": "missing", "value": 404}],
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "passed", result.steps[-1].detail
    assert result.steps[0].http_status == 404


def test_http_expectation_failure_is_reported_with_the_observed_value(origin, tmp_path):
    flow = _flow(
        [
            {"id": "ok", "action": "http", "method": "GET", "path": "/ok"},
            {
                "id": "check",
                "action": "assert",
                "expect": [{"kind": "status", "step": "ok", "value": 201}],
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "failed"
    assert "http status 200" in result.steps[1].detail


def test_screenshots_can_be_disabled_for_cheap_runs(origin, tmp_path):
    flow = _flow([{"id": "open", "action": "goto", "url": "/ok"}])
    result = _driver(origin, tmp_path, screenshots=False).run(flow)
    assert result.steps[0].screenshot is None
    assert not any(Path(tmp_path / "artifacts").glob("*.png"))


def test_converse_answers_what_ada_actually_asked(origin, tmp_path):
    flow = _flow(
        [
            {"id": "open", "action": "goto", "url": "/chat"},
            {"id": "brief", "action": "fill", "selector": "#message", "text": "a ceramics studio"},
            {"id": "send", "action": "click", "selector": "#send"},
            {
                "id": "talk",
                "action": "converse",
                "reply_timeout_ms": 5_000,
                "until": [{"kind": "visible", "selector": "#confirm-panel", "timeout_ms": 500}],
                "persona": {
                    "max_turns": 8,
                    "fallback": "Yes, go ahead.",
                    "facts": [
                        {"when": ["called", "name"], "reply": "It is called Atelier Sete."},
                        {"when": ["how much", "classes", "price"], "reply": "The course is 240 euros."},
                        {"when": ["find you", "where"], "reply": "Rua da Boavista 112, Lisbon."},
                    ],
                },
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "passed", result.steps[-1].detail

    conversation = result.steps[-1]
    assert conversation.turns == 3
    answers = [turn["owner"] for turn in conversation.transcript]
    assert answers[0] == "It is called Atelier Sete."
    assert answers[1] == "The course is 240 euros."
    assert answers[2] == "Rua da Boavista 112, Lisbon."


def test_converse_fails_loudly_when_it_never_settles(origin, tmp_path):
    flow = _flow(
        [
            {"id": "open", "action": "goto", "url": "/chat"},
            {
                "id": "talk",
                "action": "converse",
                "reply_timeout_ms": 3_000,
                "until": [{"kind": "visible", "selector": "#never-appears", "timeout_ms": 200}],
                "persona": {
                    "max_turns": 2,
                    "fallback": "Yes, go ahead.",
                    "facts": [{"when": ["called"], "reply": "Atelier Sete."}],
                },
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "failed"
    assert "did not settle within 2 owner turns" in result.steps[-1].detail


def test_marks_measure_the_time_to_build(origin, tmp_path):
    flow = _flow(
        [
            {"id": "open", "action": "goto", "url": "/chat", "mark": "opened"},
            {
                "id": "brief",
                "action": "fill",
                "selector": "#message",
                "text": "a ceramics studio",
            },
            {"id": "send", "action": "click", "selector": "#send", "mark": "build_requested"},
            {
                "id": "wait",
                "action": "assert",
                "mark": "candidate_ready",
                "expect": [
                    {
                        "kind": "count",
                        "selector": "#messages article.message",
                        "op": "len_gte",
                        "value": 2,
                        "timeout_ms": 5_000,
                    }
                ],
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "passed", result.steps[-1].detail
    assert list(result.marks) == ["opened", "build_requested", "candidate_ready"]
    assert result.steps[3].mark == "candidate_ready"


def test_native_confirm_is_accepted_and_recorded(origin, tmp_path):
    flow = _flow(
        [
            {"id": "open", "action": "goto", "url": "/chat"},
            {
                "id": "provision",
                "action": "click",
                "selector": "#provision",
                "expect": [
                    {"kind": "text", "selector": "#provision-note", "text": "management"}
                ],
            },
        ]
    )
    result = _driver(origin, tmp_path).run(flow)
    assert result.status == "passed", result.steps[-1].detail
    assert result.observations.dialogs
    assert result.observations.dialogs[0]["message"].startswith("Provision this exact")
    assert result.observations.console_errors == []
