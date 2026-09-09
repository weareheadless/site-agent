from pathlib import Path

from fastapi.testclient import TestClient

from site_agent.application.intake_lab import IntakeLabError
from site_agent.web.intake_lab import INTAKE_SESSION_COOKIE, create_app


class _Executor:
    running = True


class _Service:
    executor = _Executor()
    config = {"site": {"name": "North Star Studio"}}

    def retry_visual_review(self, run_id):
        raise IntakeLabError("review unavailable")

    def create_visual_refinement(self, run_id):
        raise IntakeLabError("refinement unavailable")

    def describe(self):
        return {
            "site_name": "North Star Studio",
            "implementation": {"provider": "entrim", "model": "deepseek-ai/DeepSeek-V4-Flash"},
            "visual_review": {"provider": "entrim", "model": "Qwen/Qwen3.8-27B"},
            "default_prompt": "Create the first website design.",
            "default_intake": {},
            "variants": ["candidate"],
            "viewports": [{"name": "desktop", "width": 1440, "height": 1000}],
            "publishing_enabled": False,
            "deprecated_routes": ["/api/runs"],
        }

    def list_runs(self, limit=50):
        return []

    def get_run(self, run_id):
        raise IntakeLabError("unknown run")

    def submit(self, prompt, intake):
        raise AssertionError("invalid request should not reach the service")

    def pages(self, run_id):
        return []

    def preview_identity(self, run_id, variant):
        raise IntakeLabError("unknown preview")


class _Intake:
    def __init__(self):
        self.calls = []

    def confirm(self, session_id, **kwargs):
        self.calls.append(("confirm", session_id, kwargs))
        return {
            "confirmed": True,
            "session": {
                "session_id": session_id,
                "status": "confirmed",
                "confirmed_revision_id": 7,
            },
        }

    def build(self, session_id, **kwargs):
        self.calls.append(("build", session_id, kwargs))
        return {
            "session": {"session_id": session_id, "status": "confirmed", "design_run_id": "intake-lab-" + "a" * 32},
            "run": {"run_id": "intake-lab-" + "a" * 32, "publishable": False},
        }

    def record_run_feedback(self, run_id, kind, *, notes=""):
        self.calls.append(("feedback", run_id, {"kind": kind, "notes": notes}))
        return {"session_id": "intake-" + "b" * 32, "status": "confirmed"}


class _IntakeService(_Service):
    def __init__(self):
        self.design_intake_service = _Intake()


class _IncubationService:
    def __init__(self):
        self.calls = []

    def get_record(self, incubation_id):
        return type("Record", (), {"incubation_id": incubation_id})()

    def technical_repair(self, incubation_id, run_id, *, owner_request=""):
        self.calls.append((incubation_id, run_id, owner_request))
        return {"run_id": "design-" + "a" * 32, "publishable": False}

    def retry_visual_review(self, incubation_id, run_id):
        self.calls.append(("visual", incubation_id, run_id))
        return {"run_id": run_id, "status": "ready_for_review"}


class _PagesService(_Service):
    run_id = "intake-lab-" + "a" * 32
    run = {
        "run_id": run_id,
        "mode": "local_experiment",
        "publishable": False,
        "base_sha": "b" * 40,
        "candidate_sha": "c" * 40,
    }

    def get_run(self, run_id):
        if run_id != self.run_id:
            raise IntakeLabError("unknown run")
        return self.run

    def pages(self, run_id):
        return ["index.html", "articles.html"]

    def preview_identity(self, run_id, variant):
        if variant != "candidate":
            raise IntakeLabError("unknown preview")
        return Path("/tmp/candidate"), self.run["candidate_sha"]

    def preview_profile(self, run_id):
        return "astro_react"


class _PageCache:
    def read_file(self, clone, sha, page, profile=None):
        return b"<html>page</html>" if page == "index.html" and sha == "c" * 40 else b""

    def clear(self):
        pass


class _LifecycleExecutor:
    running = False

    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")
        self.running = True

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def join(self, timeout=None):
        self.calls.append(("join", timeout))


class _LifecycleService(_Service):
    def __init__(self):
        self.executor = _LifecycleExecutor()


class _ClearCache(_PageCache):
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


def test_intake_lab_shell_and_metadata_are_standalone(tmp_path):
    app = create_app(_Service(), workspace=tmp_path, preview_cache=None)
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        shell = client.get("/")
        metadata = client.get("/api/lab")

    assert shell.status_code == 200
    assert "Intake Lab" in shell.text
    assert "Research this brief" in shell.text
    assert "Provision customer Ada" in shell.text
    assert "conversation-first-theme" in shell.text
    assert 'id="background-trace"' in shell.text
    assert 'id="debug-toggle"' in shell.text
    assert 'id="debug-drawer"' in shell.text
    assert 'id="debug-drawer" class="rail" aria-label="Intake evidence and build controls" hidden' in shell.text
    assert 'id="send" class="button primary" type="submit" aria-label="Send message">Send</button>' in shell.text
    assert 'id="new-session" class="new-session" type="button"' in shell.text
    assert "--brand: #e75c48" in shell.text
    assert "/incubations" in shell.text
    assert "Original" not in shell.text
    assert 'sandbox="allow-scripts"' in shell.text
    assert "allow-same-origin" not in shell.text
    assert metadata.status_code == 200
    assert metadata.json()["publishing_enabled"] is False
    assert "/api/runs" in metadata.json()["deprecated_routes"]


def test_intake_lab_rejects_cross_origin_and_unknown_submission_fields(tmp_path):
    app = create_app(_Service(), workspace=tmp_path, preview_cache=None)
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        cross_origin = client.get("/api/lab", headers={"origin": "https://evil.example"})
        unknown_field = client.post("/api/runs", json={"prompt": "x", "intake": {}, "extra": True})

    assert cross_origin.status_code == 403
    assert unknown_field.status_code == 400


def test_intake_lab_confirms_before_submitting_a_separate_build_operation(tmp_path):
    service = _IntakeService()
    app = create_app(service, workspace=tmp_path, preview_cache=None)
    session_id = "intake-" + "b" * 32
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        confirmed = client.post(
            f"/api/intake-sessions/{session_id}/confirm",
            json={"revision": 3, "draft_hash": "a" * 64, "idempotency_key": "confirm-1"},
        )
        built = client.post(
            f"/api/intake-sessions/{session_id}/build",
            json={"confirmed_revision": 7, "idempotency_key": "build-1", "owner_request": "Build it."},
        )

    assert confirmed.status_code == 202
    assert built.status_code == 202
    assert [call[0] for call in service.design_intake_service.calls] == ["confirm", "build"]
    assert service.design_intake_service.calls[0][2]["idempotency_key"] == "confirm-1"
    assert service.design_intake_service.calls[1][2]["confirmed_revision"] == 7


def test_intake_lab_records_feedback_by_run_id(tmp_path):
    service = _IntakeService()
    app = create_app(service, workspace=tmp_path, preview_cache=None)
    run_id = "intake-lab-" + "a" * 32

    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.post(f"/api/runs/{run_id}/feedback", json={"kind": "fits", "notes": "Clear direction."})

    assert response.status_code == 200
    assert service.design_intake_service.calls == [
        ("feedback", run_id, {"kind": "fits", "notes": "Clear direction."}),
    ]


def test_intake_lab_default_starts_a_cookie_scoped_conversation(tmp_path):
    class _DefaultService(_Service):
        def create_incubation(self):
            return _IncubationRecord()

    class _IncubationRecord:
        incubation_id = "inc_7893a592e0ba456ab270d3e9bffd4c4d"

        def to_dict(self):
            return {"incubation_id": self.incubation_id, "status": "blocked"}

    app = create_app(_DefaultService(), workspace=tmp_path, preview_cache=None, incubation_service=_DefaultService())
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.get("/api/incubations/default")
    assert response.status_code == 200
    assert response.json()["incubation"]["incubation_id"] == "inc_7893a592e0ba456ab270d3e9bffd4c4d"
    assert response.cookies.get(INTAKE_SESSION_COOKIE) == "inc_7893a592e0ba456ab270d3e9bffd4c4d"


def test_intake_lab_preview_route_does_not_fall_back_to_a_production_run(tmp_path):
    app = create_app(_Service(), workspace=Path(tmp_path), preview_cache=None)
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.get("/api/runs/../production/preview/candidate/index.html")

    assert response.status_code == 404


def test_intake_lab_pages_report_rendered_variant_availability(tmp_path):
    service = _PagesService()
    app = create_app(service, workspace=tmp_path, preview_cache=_PageCache())
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.get(f"/api/runs/{service.run_id}/pages")

    assert response.status_code == 200
    assert response.json()["pages"] == [
        {"path": "index.html", "candidate": True},
        {"path": "articles.html", "candidate": False},
    ]


def test_intake_lab_rejects_original_preview_variant(tmp_path):
    service = _PagesService()
    app = create_app(service, workspace=tmp_path, preview_cache=_PageCache())
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.get(f"/api/runs/{service.run_id}/preview/original/index.html")

    assert response.status_code == 404


def test_intake_lab_visual_review_retry_is_loopback_only(tmp_path):
    app = create_app(_Service(), workspace=tmp_path, preview_cache=None)
    run_id = "intake-lab-" + "a" * 32
    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        cross_origin = client.post(
            f"/api/runs/{run_id}/visual-review",
            headers={"origin": "https://evil.example"},
        )
        unavailable = client.post(f"/api/runs/{run_id}/visual-review")
        refinement = client.post(f"/api/runs/{run_id}/visual-refinement")

    assert cross_origin.status_code == 403
    assert unavailable.status_code == 409
    assert refinement.status_code == 409


def test_intake_lab_accepts_an_explicit_scoped_technical_repair(tmp_path):
    incubation = _IncubationService()
    app = create_app(_Service(), workspace=tmp_path, preview_cache=None, incubation_service=incubation)
    incubation_id = "inc_7893a592e0ba456ab270d3e9bffd4c4d"
    run_id = "design-" + "b" * 32

    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.post(
            f"/api/incubations/{incubation_id}/runs/{run_id}/technical-repair",
            headers={"origin": "http://127.0.0.1:3012"},
            json={"owner_request": "Add a signature GSAP reveal."},
        )

    assert response.status_code == 202
    assert incubation.calls == [(incubation_id, run_id, "Add a signature GSAP reveal.")]


def test_intake_lab_accepts_a_scoped_visual_review_retry(tmp_path):
    incubation = _IncubationService()
    app = create_app(_Service(), workspace=tmp_path, preview_cache=None, incubation_service=incubation)
    incubation_id = "inc_7893a592e0ba456ab270d3e9bffd4c4d"
    run_id = "design-" + "b" * 32

    with TestClient(app, base_url="http://127.0.0.1:3012") as client:
        response = client.post(
            f"/api/incubations/{incubation_id}/runs/{run_id}/visual-review",
            headers={"origin": "http://127.0.0.1:3012"},
        )

    assert response.status_code == 202
    assert incubation.calls == [("visual", incubation_id, run_id)]


def test_intake_lab_lifespan_owns_worker_and_preview_cleanup(tmp_path):
    service = _LifecycleService()
    cache = _ClearCache()
    app = create_app(service, workspace=tmp_path, preview_cache=cache)

    with TestClient(app) as client:
        assert client.get("/healthz").json()["worker_running"] is True

    assert service.executor.calls == ["start", "stop", ("join", 10)]
    assert cache.cleared is True
