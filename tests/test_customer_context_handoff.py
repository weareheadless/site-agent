import json
import subprocess
from pathlib import Path

import pytest

from site_agent.application.customer_context import CustomerContextService
from site_agent.application.incubations import (
    IncubationApplicationService,
    IncubationRuntime,
    IncubationServiceError,
)
from site_agent.application.provisioning import _copy_accepted_website, _verify_destination
from site_agent.config import load_intake_config
from site_agent.core.design_contracts import SiteIntake, canonical_json
from site_agent.core.design_intake_contracts import DesignIntakeDraft, IntakeSessionState
from site_agent.core.incubation_contracts import CustomerAdaGenesis
from site_agent.core.intake_ada_store import IntakeAdaStore
from site_agent.core.memory import Memory
from site_agent.core.media_contracts import MediaAsset, MediaKind, MediaStatus


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "Context Studio",
            "offer_summary": "A clear service",
            "primary_services": ["A clear service"],
            "location": "A defined service area",
        },
        "audience": {"primary": "People evaluating the service"},
        "conversion": {"primary_action": "Get in touch", "not_available": True},
        "brand": {"voice": "Clear and warm"},
        "site": {"required_pages": ["index.html"], "language": "en"},
    })


def _git_source(path: Path) -> str:
    path.mkdir(parents=True)
    (path / "index.html").write_text("<main>accepted</main>\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "index.html"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "accepted site"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_website_handoff_materializes_a_clean_exact_commit_from_a_worktree(tmp_path):
    repository = tmp_path / "repository"
    candidate_sha = _git_source(repository)
    source_worktree = tmp_path / "accepted-worktree"
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "--detach", str(source_worktree), candidate_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    (source_worktree / "uncommitted.txt").write_text("must not transfer\n", encoding="utf-8")
    destination = tmp_path / "customer-site"

    _copy_accepted_website(source_worktree, destination, candidate_sha)

    assert (destination / "index.html").read_text(encoding="utf-8") == "<main>accepted</main>\n"
    assert not (destination / "uncommitted.txt").exists()
    assert not subprocess.run(
        ["git", "-C", str(destination), "remote"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert not subprocess.run(
        ["git", "-C", str(destination), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_context_service_keeps_exact_lineage_and_bounded_views(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        memory.save_customer_genesis_revision(
            CustomerAdaGenesis.empty(),
            source_kind="genesis_created",
            expected_revision=0,
        )
        intake = _intake()
        session_id = "intake-" + "a" * 32
        conversation_id = memory.create_conversation("intake")
        memory.create_design_intake_session(session_id, DesignIntakeDraft.from_site_intake(intake), conversation_id=conversation_id)
        session = memory.get_design_intake_session(session_id)
        confirmed = memory.confirm_design_intake(
            session_id,
            revision=session["revision"],
            draft_hash=session["draft_hash"],
            site_intake_json=intake.to_dict(),
            summary_json={"accepted": True},
            idempotency_key="confirm-1",
            request_hash="1" * 64,
        )
        run = memory.create_design_run(
            run_id="design-" + "b" * 32,
            mode="local_experiment",
            status="ready_for_review",
            intake_json=intake.to_dict(),
            base_sha="0" * 40,
            candidate_ref="refs/ada-design-lab/test",
            intake_session_id=session_id,
            intake_revision_id=confirmed["confirmed_revision_id"],
        )
        run = memory.update_design_run(run["run_id"], candidate_sha="a" * 40)
        context, manifest = CustomerContextService(memory).snapshot_for_run("inc_" + "c" * 32, run)

        assert context.source_intake_revision_id == confirmed["confirmed_revision_id"]
        assert context.source_intake_hash == run["intake_hash"]
        assert context.business["name"] == "Context Studio"
        assert context.research_manifest is not None
        assert context.research_manifest.target_language == "en"
        assert manifest.context_hash == context.computed_hash
        assert manifest.research_manifest_hash == context.research_manifest.computed_hash
        service = CustomerContextService(memory)
        assert service.task_view("identity")["context"]["context_id"] == context.context_id
        article_view = service.task_view("article_research")
        assert "conversion" in article_view and "brand" in article_view and "site" in article_view
        assert "research_manifest" in article_view and "open_questions" in article_view
    finally:
        memory.close()


def test_context_service_uses_the_run_bound_asset_revision(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        memory.save_customer_genesis_revision(
            CustomerAdaGenesis.empty(),
            source_kind="genesis_created",
            expected_revision=0,
        )
        first_asset_id = memory.create_media_asset(MediaAsset(
            asset_id=0,
            status=MediaStatus.READY,
            media_kind=MediaKind.IMAGE,
            source_kind="owner_upload",
            original_name="first.webp",
            content_type="image/webp",
            original_size=4,
            original_sha256="a" * 64,
            storage_id="first",
            original_key="media/first/original.webp",
            normalized_key="media/first/normalized.webp",
            created_ts="now",
            updated_ts="now",
        ))
        second_asset_id = memory.create_media_asset(MediaAsset(
            asset_id=0,
            status=MediaStatus.READY,
            media_kind=MediaKind.IMAGE,
            source_kind="owner_upload",
            original_name="second.webp",
            content_type="image/webp",
            original_size=4,
            original_sha256="b" * 64,
            storage_id="second",
            original_key="media/second/original.webp",
            normalized_key="media/second/normalized.webp",
            created_ts="now",
            updated_ts="now",
        ))
        intake = SiteIntake.from_dict({
            **_intake().to_dict(),
            "assets": [{"id": str(first_asset_id), "usage": "website", "position": 0}],
        })
        session_id = "intake-" + "g" * 32
        conversation_id = memory.create_conversation("intake")
        memory.create_design_intake_session(
            session_id,
            DesignIntakeDraft.from_site_intake(intake),
            conversation_id=conversation_id,
        )
        session = memory.get_design_intake_session(session_id)
        confirmed = memory.confirm_design_intake(
            session_id,
            revision=session["revision"],
            draft_hash=session["draft_hash"],
            site_intake_json=intake.to_dict(),
            summary_json={"accepted": True},
            idempotency_key="confirm-assets",
            request_hash="2" * 64,
        )
        run = memory.create_design_run(
            run_id="design-" + "h" * 32,
            mode="local_experiment",
            status="ready_for_review",
            intake_json=intake.to_dict(),
            base_sha="0" * 40,
            candidate_ref="refs/ada-design-lab/assets",
            intake_session_id=session_id,
            intake_revision_id=confirmed["confirmed_revision_id"],
        )
        run = memory.update_design_run(run["run_id"], candidate_sha="a" * 40)

        # Mutating the live session creates a new collecting revision. It must
        # not change the accepted run's asset handoff.
        memory.replace_design_intake_assets(session_id, [{
            "asset_id": second_asset_id,
            "position": 0,
            "usage": "inspiration_only",
        }])

        context, _manifest = CustomerContextService(memory).snapshot_for_run(
            "inc_" + "h" * 32,
            run,
        )

        assert [item.asset_id for item in context.assets] == [first_asset_id]
        assert context.assets[0].content_hash == "a" * 64
    finally:
        memory.close()


def test_acceptance_provisions_context_intake_and_exact_website_commit(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    source = tmp_path / "source-site"
    candidate_sha = _git_source(source)

    class DesignSource:
        def clone_path_for_run(self, _run_id):
            return source

    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(
        store,
        root=config["incubation"]["root"],
        config=config,
        runtime_factory=lambda _scoped: IncubationRuntime(design_service=DesignSource()),
    )
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        session_id = "intake-" + "d" * 32
        conversation_id = scoped.memory.create_conversation("intake")
        scoped.memory.create_design_intake_session(session_id, DesignIntakeDraft.from_site_intake(_intake()), conversation_id=conversation_id)
        session = scoped.memory.get_design_intake_session(session_id)
        confirmed = service.confirm_intake(record.incubation_id, {
            "session_id": session_id,
            "revision": session["revision"],
            "draft_hash": session["draft_hash"],
        })
        confirmed_session = scoped.memory.get_design_intake_session(session_id)
        intake = _intake()
        run = scoped.memory.create_design_run(
            run_id="design-" + "e" * 32,
            mode="local_experiment",
            status="ready_for_review",
            intake_json=intake.to_dict(),
            base_sha="0" * 40,
            candidate_ref="refs/ada-design-lab/accepted",
            intake_session_id=session_id,
            intake_revision_id=confirmed["session"]["confirmed_revision_id"],
        )
        scoped.memory.update_design_run(
            run["run_id"],
            candidate_sha=candidate_sha,
            quality_report_json={"state": "passed", "checks": []},
        )
        scoped.memory.update_design_intake_session(session_id, design_run_id=run["run_id"])
        service.transition(record.incubation_id, "building")
        service.transition(record.incubation_id, "ready_for_feedback")

        accepted = service.accept(record.incubation_id, {"run_id": run["run_id"], "candidate_sha": candidate_sha})
        assert accepted["incubation"]["accepted_run_id"] == run["run_id"]
        assert accepted["incubation"]["acceptance_manifest_id"]
        stored_manifest = scoped.memory.get_acceptance_manifest(accepted["incubation"]["acceptance_manifest_id"])
        assert stored_manifest is not None
        assert "source_path" not in stored_manifest["manifest"].website_source

        result = service.provision(record.incubation_id, {})
        customer_root = Path(result["receipt"]["config_path"]).parent
        assert (customer_root / "site" / "index.html").read_text(encoding="utf-8") == "<main>accepted</main>\n"
        destination = Memory(result["receipt"]["database_path"])
        try:
            contexts = destination.list_customer_contexts(accepted_only=True)
            assert len(contexts) == 1
            assert destination.list_design_intake_sessions(limit=1)[0]["status"] == IntakeSessionState.CONFIRMED.value
            assert destination.kv_get("provisioning_website_commit") == candidate_sha
            assert destination.kv_get("provisioning_context_id") == contexts[0]["context"].context_id
            imported_manifest = destination.get_acceptance_manifest(accepted["incubation"]["acceptance_manifest_id"])
            assert imported_manifest is not None
            assert "source_path" not in imported_manifest["manifest"].website_source
        finally:
            destination.close()

        customer_db = Path(result["receipt"]["database_path"])
        tampered = Memory(customer_db)
        try:
            row = tampered.conn.execute(
                "SELECT context_id, revision, context_json FROM customer_context_revisions LIMIT 1"
            ).fetchone()
            payload = json.loads(row["context_json"])
            payload["business"]["name"] = "Tampered business"
            with tampered.conn:
                tampered.conn.execute(
                    "UPDATE customer_context_revisions SET context_json = ? WHERE context_id = ? AND revision = ?",
                    (canonical_json(payload), row["context_id"], row["revision"]),
                )
        finally:
            tampered.close()
        bundle = scoped.memory.get_provisioning_bundle(result["bundle_id"])["bundle"]
        assert not _verify_destination(
            customer_db,
            bundle,
            result["receipt"]["imported_counts"],
            customer_root / "site",
        )
    finally:
        service.close()
        store.close()


def test_provisioning_refuses_when_accepted_website_source_disappears(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    source = tmp_path / "source-site"
    candidate_sha = _git_source(source)

    class DisappearingDesignSource:
        calls = 0

        def clone_path_for_run(self, _run_id):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("accepted clone was removed")
            return source

    design_source = DisappearingDesignSource()
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(
        store,
        root=config["incubation"]["root"],
        config=config,
        runtime_factory=lambda _scoped: IncubationRuntime(design_service=design_source),
    )
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        session_id = "intake-" + "f" * 32
        conversation_id = scoped.memory.create_conversation("intake")
        scoped.memory.create_design_intake_session(
            session_id,
            DesignIntakeDraft.from_site_intake(_intake()),
            conversation_id=conversation_id,
        )
        session = scoped.memory.get_design_intake_session(session_id)
        confirmed = service.confirm_intake(record.incubation_id, {
            "session_id": session_id,
            "revision": session["revision"],
            "draft_hash": session["draft_hash"],
        })
        run = scoped.memory.create_design_run(
            run_id="design-" + "e" * 32,
            mode="local_experiment",
            status="ready_for_review",
            intake_json=_intake().to_dict(),
            base_sha="0" * 40,
            candidate_ref="refs/ada-design-lab/disappearing",
            intake_session_id=session_id,
            intake_revision_id=confirmed["session"]["confirmed_revision_id"],
        )
        scoped.memory.update_design_run(
            run["run_id"],
            candidate_sha=candidate_sha,
            quality_report_json={"state": "passed", "checks": []},
        )
        scoped.memory.update_design_intake_session(session_id, design_run_id=run["run_id"])
        service.transition(record.incubation_id, "building")
        service.transition(record.incubation_id, "ready_for_feedback")

        service.accept(record.incubation_id, {"run_id": run["run_id"], "candidate_sha": candidate_sha})

        with pytest.raises(IncubationServiceError, match="accepted website source is unavailable"):
            service.provision(record.incubation_id, {})

        current = service.get_record(record.incubation_id)
        assert current.status == "accepted"
        assert store.get_receipt(current.provisioning_request_id or "") is None
    finally:
        service.close()
        store.close()
