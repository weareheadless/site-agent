from types import SimpleNamespace

from site_agent.application.workspace import ChatService, Journey
import site_agent.application.workspace as workspace_module
from site_agent.core.memory import Memory


class _Intake:
    def __init__(self, revision=4):
        self.revision = revision

    def status(self, _conversation_id):
        return {"confirmed": True, "confirmed_revision_id": self.revision, "session_id": "intake-a"}


def _service(memory, revision=4):
    tenant = SimpleNamespace(
        tenant_id="tenant-a", memory=memory, context={"llm": object(), "journey": Journey(False, False),
        "intake_coordinator": _Intake(revision)},
    )
    service = ChatService(memory=memory, llm=object())
    return service, tenant


def _run(memory, *, revision=4, status="building"):
    run = memory.create_design_run(run_id=f"run-{revision}", mode="production_candidate", status=status,
        intake_json={"business": {"name": "A"}}, intake_hash="a" * 64, base_sha="b" * 40,
        publishable=True, candidate_ref=f"refs/ada-design/run-{revision}", intake_session_id="intake-a",
        intake_revision_id=revision)
    memory.conn.execute("UPDATE design_runs SET created_ts=? WHERE run_id=?", ("2026-01-01T00:00:00+00:00", run["run_id"]))
    for stage in ("queued", "planning", "generating", "building"):
        memory.add_design_run_event(run["run_id"], stage, f"Reached {stage}")
    return run


def test_status_exposes_persisted_order_and_elapsed_time(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    _run(memory)
    service, tenant = _service(memory)
    class FixedDateTime(__import__("datetime").datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 0, 5, tzinfo=tz)
    monkeypatch.setattr(workspace_module.datetime, "datetime", FixedDateTime)
    build = service.status(tenant=tenant)["build"]
    assert [stage["key"] for stage in build["stages"]] == ["queued", "planning", "generating", "building", "validating", "rendering"]
    assert [stage["state"] for stage in build["stages"]] == ["done", "done", "done", "current", "pending", "pending"]
    assert build["elapsed_seconds"] == 300
    assert build["stage"] == "building"
    memory.close()


def test_status_is_null_without_run_or_for_superseded_revision(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service, tenant = _service(memory)
    assert service.status(tenant=tenant)["build"] is None
    _run(memory, revision=3)
    assert service.status(tenant=tenant)["build"] is None
    memory.close()


def test_failed_status_preserves_last_stage_and_error(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    run = _run(memory, status="failed")
    memory.conn.execute("UPDATE design_runs SET error=? WHERE run_id=?", ("build failed", run["run_id"]))
    memory.add_design_run_event(run["run_id"], "failed", "Needs attention")
    service, tenant = _service(memory)
    build = service.status(tenant=tenant)["build"]
    assert build["state"] == "failed"
    assert build["stage"] == "building"
    assert build["error"] == "build failed"
    assert [stage["key"] for stage in build["stages"]] == ["queued", "planning", "generating", "building", "validating", "rendering"]
    assert [stage["state"] for stage in build["stages"]] == ["done", "done", "done", "failed", "pending", "pending"]
    memory.close()


def test_ready_status_marks_pipeline_complete_without_terminal_rows(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    run = _run(memory, status="ready_for_review")
    memory.add_design_run_event(run["run_id"], "ready", "Ready to review")
    service, tenant = _service(memory)
    build = service.status(tenant=tenant)["build"]
    assert build["state"] == "ready"
    assert build["stage"] == "ready"
    assert [stage["key"] for stage in build["stages"]] == ["queued", "planning", "generating", "building", "validating", "rendering"]
    assert [stage["state"] for stage in build["stages"]] == ["done"] * 6
    memory.close()
