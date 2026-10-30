"""A new confirmed brief must not be trapped in an older failed run."""

from site_agent.application.design_intake import DesignIntakeService
from site_agent.core.memory import Memory
from tests.test_design_intake import _intake


def test_new_confirmed_revision_starts_new_run_and_preserves_failed_history(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    calls = []

    class Lab:
        def submit(self, request, intake, **kwargs):
            calls.append(kwargs)
            return memory.create_design_run(
                run_id=kwargs["run_id"], mode="production_candidate", status="planning",
                intake_json=intake, intake_hash="c" * 64, base_sha="b" * 40,
                publishable=True, candidate_ref=f"refs/ada-design/{kwargs['run_id']}",
                intake_session_id=kwargs["intake_session_id"], intake_revision_id=kwargs["intake_revision_id"],
            )

        def get_run(self, run_id):
            return memory.get_design_run(run_id)

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=Lab())
    session = service.create_session()
    first = service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])["session"]
    old = memory.create_design_run(
        run_id="old-failed", mode="production_candidate", status="failed",
        intake_json=service.confirmed_intake(session["session_id"]).to_dict(),
        intake_hash="a" * 64, base_sha="b" * 40, publishable=True,
        candidate_ref="refs/ada-design/old-failed", intake_session_id=session["session_id"],
        intake_revision_id=first["confirmed_revision_id"],
    )
    # Reconfirmation persists a new immutable owner-approved revision, just as
    # the conversation did after the previous failed build.
    memory.update_design_intake_session(session["session_id"], status="ready_to_build", design_run_id=old["run_id"])
    current = service.get_session(session["session_id"])
    second = service.confirm(session["session_id"], revision=current["revision"], draft_hash=current["draft_hash"],
                             idempotency_key="confirm-revised")["session"]
    assert second["confirmed_revision_id"] != first["confirmed_revision_id"]
    result = service.build(session["session_id"], confirmed_revision=second["confirmed_revision_id"])
    assert result["run"]["run_id"] != old["run_id"]
    assert len(calls) == 1
    assert not calls[0].get("resume_run_id")
    assert calls[0]["intake_revision_id"] == second["confirmed_revision_id"]
    assert memory.get_design_run(old["run_id"]) == old
    duplicate = service.build(session["session_id"], confirmed_revision=second["confirmed_revision_id"])
    assert duplicate.get("idempotent") is True
    assert len(calls) == 1
    memory.close()
