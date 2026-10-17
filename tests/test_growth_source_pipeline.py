from types import SimpleNamespace

import pytest

from site_agent.application.growth_candidates import (
    content_hash,
    queue_source_candidate,
    reconcile_source_candidates,
    restore_growth_source_revision,
)
from site_agent.application.growth_tasks import growth_tasks
from site_agent.core.memory import Memory
from site_agent.hands import opencode_runner


def _initiative(memory, *, state="preparing", validation=None, last_error=""):
    cycle = memory.create_strategy_cycle("growth-source-test", "2026-10-17", "evidence-hash", {})
    initiative_id = memory.create_strategy_initiative(
        cycle["id"], kind="code", title="Improve the public crawler path",
        summary="Update the source-controlled crawler behavior.",
        rationale="The current public response blocks discovery.", evidence=["source:crawl"],
        expected={"opportunity": {"kind": "code", "title": "Improve the public crawler path"}},
        state=state, growth_run_id="growth-run-source-test", goal_revision=1,
        validation=validation or {}, last_error=last_error,
    )
    return memory.update_strategy_initiative(initiative_id)


def test_internal_growth_source_job_is_durable_without_a_synthetic_chat_turn(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        job_id = memory.enqueue_growth_source_candidate_job(
            4, "growth-run-4", {"initiative_id": 4, "brief": "bounded source change"},
        )
        assert memory.enqueue_growth_source_candidate_job(
            4, "growth-run-4", {"initiative_id": 4, "brief": "bounded source change"},
        ) == job_id
        job = memory.get_chat_job(job_id)
        assert job["operation_kind"] == "growth_source_candidate"
        assert job["conversation_id"] is None
        assert job["message_id"] is None
        assert memory.conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE role = 'assistant'"
        ).fetchone()[0] == 0
    finally:
        memory.close()


def test_source_candidate_waits_for_owner_and_resumes_from_its_saved_brief(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    try:
        monkeypatch.setattr(opencode_runner, "builder_available", lambda _config: True)
        initiative = _initiative(memory)
        pending_draft = memory.save_draft("Existing owner change", "", kind="merge", meta={})
        job_id = queue_source_candidate(
            {"memory": memory, "config": {}, "tenant_id": "oceanicvibes"},
            initiative,
            {"title": initiative["title"], "why": initiative["rationale"],
             "scope": initiative["summary"], "evidence": ["source:crawl"]},
            {"evidenceHash": "sha256:evidence"},
        )
        assert job_id is None
        waiting = memory.update_strategy_initiative(initiative["id"])
        preparation = waiting["validation"]["preparation"]
        assert preparation["waitingForWebsiteDecision"] is True
        assert preparation["brief"]
        assert preparation["briefHash"] == content_hash(preparation["brief"])
        memory.update_draft_status(pending_draft, "discarded")
        reconcile_source_candidates({"memory": memory})
        updated = memory.update_strategy_initiative(initiative["id"])
        preparation = updated["validation"]["preparation"]
        assert preparation["jobId"]
        assert "waitingForWebsiteDecision" not in preparation
        job = memory.get_chat_job(preparation["jobId"])
        assert job["status"] == "queued"
        assert job["conversation_id"] is None
    finally:
        memory.close()


def test_growth_tasks_keep_internal_source_build_visible_after_assessment_ends(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        initiative = _initiative(memory)
        job_id = memory.enqueue_growth_source_candidate_job(
            initiative["id"], "growth-run-source-test", {"initiative_id": initiative["id"], "brief": "build"},
        )
        memory.update_strategy_initiative(initiative["id"], validation={"preparation": {
            "kind": "source_code", "jobId": job_id,
        }})
        current = memory.update_strategy_initiative(initiative["id"])
        tasks = growth_tasks(memory, [current], [], [], [], runs=[])
        task = next(row for row in tasks if row["id"] == f"initiative:{initiative['id']}")
        assert task["focus"] == "preparing"
        assert task["summaryKey"] == "sourceCandidatePreparing"
    finally:
        memory.close()


def test_growth_source_owner_decision_is_bound_to_exact_git_revision(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        initiative = _initiative(memory, state="ready_for_review")
        draft_id = memory.save_draft("Crawler improvement", "", kind="merge", meta={})
        memory.update_strategy_initiative(initiative["id"], draft_id=draft_id)
        candidate_sha = "a" * 40
        package_hash = "sha256:" + "b" * 64
        memory.record_strategy_decision_for_draft(
            draft_id, "approved", source_revision=candidate_sha,
            review_package_hash=package_hash,
        )
        row = memory.conn.execute(
            "SELECT decision, source_revision, review_package_hash FROM strategy_decisions WHERE initiative_id = ?",
            (initiative["id"],),
        ).fetchone()
        assert tuple(row) == ("approved", candidate_sha, package_hash)
    finally:
        memory.close()


def test_growth_source_decision_rejects_short_or_non_git_revision(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        initiative = _initiative(memory, state="ready_for_review")
        draft_id = memory.save_draft("Crawler improvement", "", kind="merge", meta={})
        memory.update_strategy_initiative(initiative["id"], draft_id=draft_id)
        with pytest.raises(ValueError, match="full Git SHA"):
            memory.record_strategy_decision_for_draft(draft_id, "approved", source_revision="abc123")
    finally:
        memory.close()


def test_source_builder_does_not_discard_an_existing_owner_merge(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        draft_id = memory.save_draft("Owner's pending website change", "", kind="merge", meta={})
        with pytest.raises(opencode_runner.RunnerError, match="already awaiting its owner decision"):
            opencode_runner.stage_merge_draft(
                {"memory": memory, "config": {"site": {}}},
                "new source change", {"changed_paths": []},
            )
        assert memory.get_draft(draft_id)["status"] == "pending"
    finally:
        memory.close()


def test_ready_growth_code_task_contains_the_exact_preview_and_git_sha(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        source = {
            "candidateSha": "c" * 40, "baseSha": "d" * 40,
            "changedPaths": ["src/routes/robots.ts"],
            "previewUrl": "https://preview.example.test/",
        }
        package = {"candidateType": "source_code", "source": source}
        package_hash = content_hash(package)
        meta = {
            "growth_package": package, "review_package_hash": package_hash,
            "head_sha": source["candidateSha"], "base_sha": source["baseSha"],
            "preview": {"status": "ready", "requires_build": False, "head_sha": source["candidateSha"]},
        }
        draft_id = 19
        initiative = {
            "id": 8, "kind": "code", "state": "ready_for_review", "title": "Improve crawl access",
            "summary": "The crawler path prevents indexing.", "rationale": "Verified crawl failure.",
            "draft_id": draft_id, "owner_action_id": None, "approval_id": 3,
            "review_package_hash": package_hash, "validation": {"status": "passed", "packageHash": package_hash,
                "checks": {"exactDraft": True, "publicRenderer": True, "approvalBoundary": True}},
        }
        draft = {"id": draft_id, "kind": "merge", "status": "pending", "title": "Improve crawl access", "meta": meta}

        class FakeMemory:
            def list_owner_actions(self, limit=None):
                return []

            def get_approval_request(self, approval_id):
                return SimpleNamespace(status=SimpleNamespace(value="pending"))

        task = next(row for row in growth_tasks(FakeMemory(), [initiative], [draft], [], []) if row["id"] == "initiative:8")
        assert task["canApprove"] is True
        assert task["reviewPackageHash"] == package_hash
        assert task["previewUrl"] == source["previewUrl"]
        assert task["review"]["source"]["candidateSha"] == source["candidateSha"]
        assert task["review"]["source"]["changedPaths"] == source["changedPaths"]
    finally:
        memory.close()


def test_growth_revision_job_remains_visible_as_active_work(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        conversation_id = memory.create_conversation("Growth revision")
        job_id = memory.enqueue_chat_job(
            conversation_id, "Revise this proposal", payload={
                "growth_task_revision": {"initiativeId": 8, "previousDraftId": 19},
            },
        )
        initiative = _initiative(memory, state="validating", validation={
            "preparation": {"kind": "source_code", "jobId": 5, "draftId": 19},
            "revision": {"chatJobId": job_id, "previousDraftId": 19},
        })
        task = next(row for row in growth_tasks(memory, [initiative], [], [], [], runs=[])
                    if row["id"] == f"initiative:{initiative['id']}")
        assert task["focus"] == "preparing"
        assert task["summaryKey"] == "sourceCandidatePreparing"
    finally:
        memory.close()


def test_failed_growth_revision_restores_the_exact_original_proposal(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        previous_hash = "sha256:" + "a" * 64
        previous_id = memory.save_draft(
            "Original proposal", "", kind="merge",
            meta={"review_package_hash": previous_hash, "growth_revision_pending": True},
        )
        validation = {
            "preparation": {"kind": "source_code", "jobId": 5, "draftId": previous_id},
            "revision": {
                "previousDraftId": previous_id,
                "previousReviewPackageHash": previous_hash,
                "previousValidation": {"status": "passed"},
            },
        }
        initiative = _initiative(memory, state="validating", validation=validation)
        assert restore_growth_source_revision(memory, initiative["id"], "preview failed") is True
        restored = memory.update_strategy_initiative(initiative["id"])
        draft = memory.get_draft(previous_id)
        assert restored["state"] == "ready_for_review"
        assert restored["draft_id"] == previous_id
        assert restored["validation"]["revisionFailure"] == "Ada could not prepare the requested revision. Your original proposal is still available to review."
        assert restored["validation"]["revisionError"] == "preview failed"
        assert draft["status"] == "pending"
        assert draft["meta"]["review_package_hash"] == previous_hash
        assert "growth_revision_pending" not in draft["meta"]
    finally:
        memory.close()
