"""Deterministic tier, end to end: real app, real browser, no model.

This is the gate that can run on every change. It serves the actual Intake Lab
owner surface with a temporary store and drives it in Chromium, so a broken
selector, a JS error, a failed asset request or a shell that never boots fails
the build before it reaches a release.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is an optional extra")

from site_agent.application.incubations import IncubationApplicationService
from site_agent.config import load_intake_config
from site_agent.core.intake_ada_store import IntakeAdaStore
from site_agent.qa.driver import PlaywrightDriver
from site_agent.qa.evidence import build_bundle
from site_agent.qa.flow import load_flow
from site_agent.qa.rubric import RuleJudge
from site_agent.web.intake_lab import create_app

FLOW = Path(__file__).resolve().parents[1] / "flows" / "intake-surface.flow.yaml"


class _Lab:
    config = {"site": {"name": "Intake Lab"}}

    def describe(self):
        return {"site_name": "Intake Lab", "publishing_enabled": False}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def intake_lab(tmp_path):
    import uvicorn

    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(
        store, root=config["incubation"]["root"], config=config
    )
    app = create_app(_Lab(), workspace=tmp_path, incubation_service=service)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        service.close()
        store.close()
        pytest.fail("intake lab did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        service.close()
        store.close()


def test_intake_surface_flow_passes_against_the_real_app(intake_lab, tmp_path):
    flow = load_flow(FLOW)
    driver = PlaywrightDriver(
        base_url=intake_lab,
        artifacts_dir=tmp_path / "artifacts",
        timeout_ms=20_000,
    )
    result = driver.run(flow)
    verdict = RuleJudge().review(result)

    assert result.status == "passed", [step.detail for step in result.steps]
    assert verdict.passed is True, verdict.reasons

    bundle = build_bundle(result, verdict=verdict, artifacts_dir=tmp_path / "artifacts")
    assert bundle["schema"] == "site-agent.qa.evidence/1"
    assert bundle["flow"]["id"] == "intake-surface"
    assert bundle["flow"]["tier"] == "deterministic"
    assert bundle["steps"], "evidence must describe what happened"
    assert bundle["artifacts"]["files"], "screenshots must be retained as evidence"
    assert bundle["observations"]["console_errors"] == []
    assert bundle["observations"]["failed_requests"] == []
