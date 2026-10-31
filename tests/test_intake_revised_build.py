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


def test_live_build_is_not_duplicated_by_a_newer_confirmed_revision(tmp_path):
    """One conversation owns at most one live build; no duplicate provider spend."""
    memory = Memory(tmp_path / "intake.db")
    submissions = []

    class Lab:
        def submit(self, request, intake, **kwargs):
            submissions.append(kwargs)
            return memory.create_design_run(
                run_id=kwargs["run_id"], mode="production_candidate", status="building",
                intake_json=intake, intake_hash="c" * 64, base_sha="b" * 40,
                publishable=True, candidate_ref=f"refs/ada-design/{kwargs['run_id']}",
                intake_session_id=kwargs["intake_session_id"],
                intake_revision_id=kwargs["intake_revision_id"],
            )

        def get_run(self, run_id):
            return memory.get_design_run(run_id)

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=Lab())
    session = service.create_session()
    first = service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])["session"]
    started = service.build(session["session_id"], confirmed_revision=first["confirmed_revision_id"])
    assert started["run"]["status"] == "building"
    assert len(submissions) == 1

    # The owner re-confirms a newer brief while that build is still live.
    memory.update_design_intake_session(session["session_id"], status="ready_to_build")
    current = service.get_session(session["session_id"])
    newer = service.confirm(session["session_id"], revision=current["revision"],
                            draft_hash=current["draft_hash"], idempotency_key="confirm-during-build")["session"]
    assert newer["confirmed_revision_id"] != first["confirmed_revision_id"]

    again = service.build(session["session_id"], confirmed_revision=newer["confirmed_revision_id"])

    assert len(submissions) == 1, "a live build must not be duplicated"
    assert again["active_run_id"] == started["run"]["run_id"]
    assert again["build_pending"] is True
    memory.close()
def test_build_failure_evidence_keeps_the_error_not_the_warning_banner():
    from site_agent.hands.opencode_runner import summarize_build_failure

    raw = (
        "\x1b[33m▲\x1b[0m WARNING internal Durable Objects will not work locally\n\n"
        "src/app/(frontend)/page.tsx:12:3\n"
        "error TS2322: Type 'string' is not assignable to type 'never'.\n"
        "\x1b[2mmore trailing banner\x1b[0m\n"
    )
    summary = summarize_build_failure(raw)
    assert "error TS2322" in summary
    assert "\x1b[" not in summary
    assert "page.tsx:12:3" in summary


def test_build_heartbeat_reports_progress_while_one_turn_is_in_flight():
    import time

    from site_agent.hands.opencode_runner import _build_heartbeat

    beats = []
    with _build_heartbeat(beats.append, "still working", interval=15):
        time.sleep(0.05)
    assert beats == []
    with _build_heartbeat(beats.append, "still working", interval=15):
        pass
    assert beats == []


def test_a_candidate_waiting_for_repair_does_not_block_the_next_build(tmp_path):
    """`needs_repair` is finished work, not a live build.

    Counting it as live made the owner's next request a silent no-op: Ada
    replied that she was building while nothing was queued.
    """
    memory = Memory(tmp_path / "intake.db")
    submissions = []

    class Lab:
        def submit(self, request, intake, **kwargs):
            submissions.append(kwargs["run_id"])
            return memory.create_design_run(
                run_id=kwargs["run_id"], mode="production_candidate", status="needs_repair",
                intake_json=intake, intake_hash="c" * 64, base_sha="b" * 40,
                publishable=True, candidate_ref=f"refs/ada-design/{kwargs['run_id']}",
                intake_session_id=kwargs["intake_session_id"],
                intake_revision_id=kwargs["intake_revision_id"],
            )

        def get_run(self, run_id):
            return memory.get_design_run(run_id)

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=Lab())
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"],
    )["session"]
    service.build(session["session_id"], confirmed_revision=confirmed["confirmed_revision_id"])

    again = service.build(
        session["session_id"],
        confirmed_revision=confirmed["confirmed_revision_id"],
        force_new=True,
    )

    assert len(submissions) == 2, "a finished candidate must not block a new build"
    assert again["run"]["run_id"] == submissions[-1]
    memory.close()
