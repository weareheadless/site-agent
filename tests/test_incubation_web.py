from pathlib import Path

from fastapi.testclient import TestClient

from site_agent.application.incubations import IncubationApplicationService, IncubationRuntime
from site_agent.config import load_intake_config
from site_agent.core.incubation_contracts import IncubationStatus
from site_agent.core.intake_ada_store import IntakeAdaStore
from site_agent.web.intake_lab import INTAKE_SESSION_COOKIE, create_app


class _Lab:
    config = {"site": {"name": "Intake Lab"}}

    def describe(self):
        return {"site_name": "Intake Lab", "publishing_enabled": False}


class _Media:
    def list(self, **kwargs):
        return []


def _service(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    return IncubationApplicationService(store, root=config["incubation"]["root"], config=config), store


def test_canonical_incubation_routes_create_and_project_scoped_state(tmp_path):
    service, store = _service(tmp_path)
    app = create_app(_Lab(), workspace=tmp_path, incubation_service=service)
    try:
        with TestClient(app, base_url="http://127.0.0.1:3012") as client:
            created = client.post("/api/incubations", json={})
            incubation_id = created.json()["incubation"]["incubation_id"]
            listed = client.get("/api/incubations")
            summary = client.get(f"/api/incubations/{incubation_id}")
            research = client.post(f"/api/incubations/{incubation_id}/research", json={})

        assert created.status_code == 201
        assert created.cookies.get(INTAKE_SESSION_COOKIE) == incubation_id
        assert listed.status_code == 200
        assert listed.json()["incubations"][0]["incubation_id"] == incubation_id
        assert summary.status_code == 200
        assert summary.cookies.get(INTAKE_SESSION_COOKIE) == incubation_id
        assert summary.json()["incubation"]["status"] == IncubationStatus.COLLECTING.value
        assert "workspace_path" not in summary.json()["incubation"]
        assert research.status_code == 202
        assert research.json()["status"] == "awaiting_source_approval"
    finally:
        service.close()
        store.close()


def test_default_incubation_is_reused_by_one_cookie_and_isolated_for_another(tmp_path):
    service, store = _service(tmp_path)
    app = create_app(_Lab(), workspace=tmp_path, incubation_service=service)
    try:
        with TestClient(app, base_url="http://127.0.0.1:3012") as first_browser:
            first = first_browser.get("/api/incubations/default")
            same_browser = first_browser.get("/api/incubations/default")

        with TestClient(app, base_url="http://127.0.0.1:3012") as second_browser:
            second = second_browser.get("/api/incubations/default")

        first_id = first.json()["incubation"]["incubation_id"]
        same_id = same_browser.json()["incubation"]["incubation_id"]
        second_id = second.json()["incubation"]["incubation_id"]
        assert first.status_code == 200
        assert same_browser.status_code == 200
        assert second.status_code == 200
        assert first.headers["cache-control"] == "private, no-store"
        assert first.headers["vary"] == "Cookie"
        assert first_id == same_id
        assert second_id != first_id
        assert first.cookies.get(INTAKE_SESSION_COOKIE) == first_id
        assert second.cookies.get(INTAKE_SESSION_COOKIE) == second_id
    finally:
        service.close()
        store.close()


def test_canonical_media_route_uses_the_selected_incubation(tmp_path):
    service, store = _service(tmp_path)
    try:
        record = service.create_incubation()
        service.attach_runtime(record.incubation_id, IncubationRuntime(media_service=_Media()))
        app = create_app(_Lab(), workspace=tmp_path, incubation_service=service, default_incubation_id=record.incubation_id)
        with TestClient(app, base_url="http://127.0.0.1:3012") as client:
            response = client.get(f"/api/incubations/{record.incubation_id}/media")

        assert response.status_code == 200
        assert response.json() == {"assets": []}
    finally:
        service.close()
        store.close()


def test_provisioning_response_does_not_expose_destination_paths(tmp_path):
    service, store = _service(tmp_path)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        conversation_id = scoped.memory.create_conversation("intake")
        from site_agent.core.design_intake_contracts import DesignIntakeDraft
        from site_agent.core.design_contracts import SiteIntake

        intake = SiteIntake.from_dict({
            "schema_version": 1,
            "business": {"name": "Fictional studio", "offer_summary": "A clear service", "primary_services": ["A clear service"], "location": "Local service area"},
            "audience": {"primary": "People evaluating the service"},
            "conversion": {"primary_action": "Get in touch", "not_available": True},
            "brand": {"voice": "Clear and warm"},
            "site": {"required_pages": ["index.html"]},
        })
        draft = DesignIntakeDraft.from_site_intake(intake)
        session_id = "intake-" + "a" * 32
        scoped.memory.create_design_intake_session(session_id, draft, conversation_id=conversation_id)
        session = scoped.memory.get_design_intake_session(session_id)
        service.confirm_intake(record.incubation_id, {"session_id": session_id, "revision": session["revision"], "draft_hash": session["draft_hash"]})
        service.transition(record.incubation_id, IncubationStatus.BUILDING.value)
        service.transition(record.incubation_id, IncubationStatus.READY_FOR_FEEDBACK.value)
        service.transition(record.incubation_id, IncubationStatus.ACCEPTED.value, accepted_candidate_sha="a" * 40)
        app = create_app(_Lab(), workspace=tmp_path, incubation_service=service, default_incubation_id=record.incubation_id)
        with TestClient(app, base_url="http://127.0.0.1:3012") as client:
            response = client.post(f"/api/incubations/{record.incubation_id}/provision", json={})
            activation = client.post(f"/api/incubations/{record.incubation_id}/activate", json={})

        assert response.status_code == 202
        assert "config_path" not in response.json()["receipt"]
        assert "database_path" not in response.json()["receipt"]
        assert activation.status_code == 202
        assert activation.json()["activation"]["activated"] is True
    finally:
        service.close()
        store.close()


def test_incubation_summary_exposes_deductions_and_infusion_runs(tmp_path):
    service, store = _service(tmp_path)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        scoped.memory.save_infusion_run(_infusion_run())
        summary = service.summary(record.incubation_id)
        assert summary["deductions"] == []
        assert summary["infusion_runs"][0]["run_id"].startswith("infusion_")
    finally:
        service.close()
        store.close()


def test_incubation_chat_jobs_and_deductions_are_diagnosable_over_http(tmp_path):
    service, store = _service(tmp_path)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        conversation_id = scoped.memory.create_conversation("intake")
        from site_agent.core.design_contracts import SiteIntake
        from site_agent.core.design_intake_contracts import DesignIntakeDraft

        intake = SiteIntake.from_dict({
            "schema_version": 1,
            "business": {"name": "Workspace", "offer_summary": "Vitrail", "primary_services": ["Vitrail"], "location": "Lyon"},
            "audience": {"primary": "Clients"},
            "conversion": {"primary_action": "Contacter", "not_available": True},
            "brand": {"voice": "Chaleureux"},
            "site": {"required_pages": ["index.html"]},
        })
        session_id = "intake-" + "a" * 32
        scoped.memory.create_design_intake_session(session_id, DesignIntakeDraft.from_site_intake(intake), conversation_id=conversation_id)
        scoped.memory.enqueue_design_intake_advice_job(
            conversation_id,
            "Bonjour",
            session_id=session_id,
            idempotency_key="msg-1",
        )
        app = create_app(_Lab(), workspace=tmp_path, incubation_service=service, default_incubation_id=record.incubation_id)
        with TestClient(app, base_url="http://127.0.0.1:3012") as client:
            jobs = client.get(f"/api/incubations/{record.incubation_id}/chat/jobs")
            deductions = client.get(f"/api/incubations/{record.incubation_id}/deductions")

        assert jobs.status_code == 200
        payload = jobs.json()
        assert payload["jobs"][0]["status"] == "queued"
        assert "age_seconds" in payload["jobs"][0]
        assert deductions.status_code == 200
        assert deductions.json() == {"deductions": [], "runs": []}
    finally:
        service.close()
        store.close()


def _infusion_run():
    from site_agent.core.incubation_contracts import InfusionRun

    now = "2026-09-04T00:00:00Z"
    return InfusionRun.from_dict({
        "run_id": "infusion_" + "1" * 32,
        "trigger": "idle",
        "mode": "native",
        "status": "pending",
        "budget_tokens": 1200,
        "snapshot_hash": "0" * 64,
        "session_id": f"intake-{'a' * 32}",
        "created_at": now,
        "updated_at": now,
    })
