import sqlite3

import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.memory import MIGRATIONS, Memory, SCHEMA_VERSION


def _run_kwargs():
    return {
        "run_id": "design-run-1",
        "mode": "production_candidate",
        "status": "created",
        "intake_json": {"business": {"name": "North Star"}},
        "intake_hash": "a" * 64,
        "base_sha": "b" * 40,
        "publishable": True,
        "candidate_ref": "refs/ada-design/design-run-1",
    }


def test_design_run_round_trips_events_and_survives_reopen(tmp_path):
    path = tmp_path / "memory.db"
    memory = Memory(path)
    run = memory.create_design_run(**_run_kwargs())

    assert run["run_id"] == "design-run-1"
    assert run["intake_json"]["business"]["name"] == "North Star"
    event_id = memory.add_design_run_event(
        "design-run-1",
        "planning",
        "Building the site strategy.",
        {"api_key": "must-not-persist", "run_id": "design-run-1"},
    )
    assert event_id > 0
    assert memory.list_design_run_events("design-run-1")[0]["detail"]["api_key"] == "[REDACTED]"
    memory.close()

    reopened = Memory(path)
    stored = reopened.get_design_run("design-run-1")
    assert stored["status"] == "created"
    assert stored["publishable"] is True
    assert reopened.list_design_run_events("design-run-1")[0]["stage"] == "planning"
    reopened.close()


def test_design_run_transition_matrix_is_guarded(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.create_design_run(**_run_kwargs())

    memory.transition_design_run("design-run-1", "assessing_intake")
    memory.transition_design_run("design-run-1", "planning")
    with pytest.raises(ContractError, match="cannot transition"):
        memory.transition_design_run("design-run-1", "ready_for_review")

    memory.transition_design_run("design-run-1", "failed", error="quality gate failed")
    stored = memory.get_design_run("design-run-1")
    assert stored["status"] == "failed"
    assert stored["error"] == "quality gate failed"
    memory.close()


def test_design_migration_from_schema_21_preserves_existing_data(tmp_path):
    path = tmp_path / "schema-21.db"
    conn = sqlite3.connect(path)
    for version in range(1, 22):
        with conn:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
    conn.execute("INSERT INTO kv (key, value) VALUES ('kept', 'yes')")
    conn.commit()
    conn.close()

    memory = Memory(path)
    assert SCHEMA_VERSION >= 22
    assert memory.kv_get("kept") == "yes"
    assert memory.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='design_runs'"
    ).fetchone()
    memory.close()


def test_design_run_persists_operation_relationship_and_artifact_identity(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    parent = memory.create_design_run(**_run_kwargs())
    memory.update_design_run(parent["run_id"], candidate_sha="b" * 40)
    child = memory.create_design_run(
        run_id="design-run-1-refined",
        mode="local_experiment",
        status="created",
        intake_json=parent["intake_json"],
        intake_hash=parent["intake_hash"],
        base_sha="c" * 40,
        publishable=False,
        candidate_ref="refs/ada-design-lab/design-run-1-refined",
        parent_run_id=parent["run_id"],
        operation_kind="visual_refinement",
        source_candidate_sha="b" * 40,
    )

    assert child["parent_run_id"] == parent["run_id"]
    assert child["operation_kind"] == "visual_refinement"
    assert child["source_candidate_sha"] == "b" * 40

    updated = memory.update_design_run(
        child["run_id"],
        transcript_path="artifacts/transcript.jsonl",
        opencode_session_id="session-2",
        visual_critique_hash="d" * 64,
    )
    assert updated["transcript_path"] == "artifacts/transcript.jsonl"
    assert updated["opencode_session_id"] == "session-2"
    assert updated["visual_critique_hash"] == "d" * 64
    memory.close()


def test_design_phase_artifacts_are_durable_and_completed_work_is_not_restarted(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.create_design_run(**_run_kwargs())

    claimed = memory.claim_design_phase(
        "design-run-1",
        "copy",
        variant_key="primary",
        base_sha="b" * 40,
        context_snapshot_hash="c" * 64,
        input_hashes=["d" * 64],
        provider_id="openrouter",
        model="copy-model",
        session_id="copy-session",
    )
    assert claimed["status"] == "running"
    assert claimed["claimed"] is True
    completed = memory.complete_design_phase(
        claimed["id"],
        {"headline": "Into the dark"},
        prompt_tokens=10,
        completion_tokens=20,
    )
    assert completed["status"] == "completed"
    assert completed["payload"] == {"headline": "Into the dark"}

    reclaimed = memory.claim_design_phase(
        "design-run-1",
        "copy",
        variant_key="primary",
        base_sha="b" * 40,
        context_snapshot_hash="c" * 64,
        input_hashes=["d" * 64],
    )
    assert reclaimed["id"] == completed["id"]
    assert reclaimed["claimed"] is False
    assert len(memory.list_design_phase_artifacts("design-run-1", phase="copy")) == 1

    memory.close()


def test_design_phase_artifact_allows_one_failed_retry_but_then_stops(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.create_design_run(**_run_kwargs())

    first = memory.claim_design_phase("design-run-1", "concept", variant_key="a", base_sha="b" * 40)
    memory.fail_design_phase(first["id"], error_code="provider_timeout", error_detail="timed out")
    second = memory.claim_design_phase("design-run-1", "concept", variant_key="a", base_sha="b" * 40)
    assert second["attempt"] == 2
    memory.fail_design_phase(second["id"], error_code="provider_timeout")

    with pytest.raises(ContractError, match="exhausted"):
        memory.claim_design_phase("design-run-1", "concept", variant_key="a", base_sha="b" * 40)
    memory.close()
