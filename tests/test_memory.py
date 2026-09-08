import sqlite3

import pytest

from site_agent.core.contracts import (
    ActionPriority,
    ActionRequirement,
    ApprovalRequest,
    Artifact,
    ArtifactKind,
    EffectClass,
    OwnerAction,
    ProviderReceipt,
    ReceiptStatus,
)
from site_agent.core.memory import MIGRATIONS, Memory, SCHEMA_VERSION
from site_agent.core.media_contracts import MediaAsset, MediaKind, MediaStatus


def test_fresh_db_creates_current_schema(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    version = mem.conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    assert mem.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_provider_receipts_idempotency'"
    ).fetchone() is not None
    tables = {
        r["name"]
        for r in mem.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "kv", "observations", "actions", "drafts", "metrics_snapshots", "llm_costs",
        "owner_actions", "artifacts", "approval_requests", "provider_receipts",
        "seo_site_reports", "article_ideas",
    } <= tables
    mem.close()


def test_media_assets_and_chat_attachments_persist(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation()
    asset = MediaAsset(
        asset_id=0, status=MediaStatus.QUEUED, media_kind=MediaKind.IMAGE, source_kind="owner_upload",
        original_name="photo.jpg", content_type="image/jpeg", original_size=3, original_sha256="abc",
        storage_id="storage", original_key="media/storage/original/photo.jpg", created_ts="now", updated_ts="now",
    )
    asset_id = memory.create_media_asset(asset)
    assert memory.get_media_asset(asset_id).original_name == "photo.jpg"
    job_id = memory.enqueue_chat_job(
        conversation_id, "use this", [{"type": "media_asset", "asset_id": asset_id, "position": 0}]
    )
    assert job_id
    assert memory.get_messages(conversation_id)[0]["attachments"][0]["asset_id"] == asset_id
    claimed = memory.claim_media_asset("worker-1")
    assert claimed.status is MediaStatus.PROCESSING
    memory.close()


def test_migration_from_older_version_preserves_data(tmp_path):
    import sqlite3

    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO kv VALUES ('grudge', 'slow wifi')")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    mem = Memory(path)
    assert mem.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert mem.kv_get("grudge") == "slow wifi"
    assert mem.kv_get("missing", "fallback") == "fallback"
    mem.close()


def test_migration_34_separates_existing_derivatives_from_analysis_failure(tmp_path):
    path = tmp_path / "media-schema-33.db"
    conn = sqlite3.connect(path)
    for version in range(1, 34):
        with conn:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
    now = "2026-09-06T12:00:00+00:00"
    conn.executemany(
        "INSERT INTO media_assets (created_ts, updated_ts, status, media_kind, source_kind, original_name, "
        "content_type, original_size, original_sha256, storage_id, original_key, normalized_key, thumbnail_key, "
        "analysis_json, last_error) VALUES (?, ?, ?, 'image', 'owner_upload', ?, 'image/jpeg', 3, ?, ?, ?, ?, ?, ?, ?)",
        [
            (now, now, "failed", "vision-failed.jpg", "a" * 64, "vision-failed", "media/vision-failed/original.jpg",
             "media/vision-failed/normalized.webp", "media/vision-failed/thumbnail.webp", "{}", "vision provider failed"),
            (now, now, "ready", "analyzed.jpg", "b" * 64, "analyzed", "media/analyzed/original.jpg",
             "media/analyzed/normalized.webp", "media/analyzed/thumbnail.webp", '{"description":"ready"}', ""),
            (now, now, "failed", "missing.jpg", "c" * 64, "missing", "media/missing/original.jpg", "", "", "{}",
             "normalization failed"),
        ],
    )
    conn.execute("PRAGMA user_version = 33")
    conn.commit()
    conn.close()

    memory = Memory(path)

    failed_analysis = memory.get_media_asset(1)
    assert failed_analysis.status.value == "ready"
    assert failed_analysis.analysis_status.value == "failed"
    assert failed_analysis.analysis_error == "vision provider failed"

    analyzed = memory.get_media_asset(2)
    assert analyzed.status.value == "ready"
    assert analyzed.analysis_status.value == "ready"

    missing = memory.get_media_asset(3)
    assert missing.status.value == "failed"
    assert missing.analysis_status.value == "pending"
    memory.close()


def test_observations_roundtrip_and_filter(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mem.record_observation("reddit", "freedivers talk about mouthfill")
    mem.record_observation("ga", "traffic up")
    recent = mem.recent_observations(source="reddit")
    assert len(recent) == 1
    assert "mouthfill" in recent[0]["text"]
    assert len(mem.recent_observations(limit=5)) == 2
    mem.close()


def test_observations_since_returns_filtered_events_in_id_order(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    first = mem.record_observation("inner_voice", "first")
    mem.record_observation("reddit", "external")
    third = mem.record_observation("awaken", "third", meta={"kept": True})

    rows = mem.observations_since(first, sources=("inner_voice", "awaken"))

    assert [row["id"] for row in rows] == [third]
    assert rows[0]["meta"] == {"kept": True}
    mem.close()


def test_draft_lifecycle(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    did = mem.save_draft("Why depth feels calm", "body text", meta={"topic": "equalization"})
    drafts = mem.list_drafts(status="pending")
    assert len(drafts) == 1
    assert drafts[0]["meta"]["topic"] == "equalization"
    assert mem.update_draft_status(did, "approved")
    assert mem.list_drafts(status="pending") == []
    assert mem.list_drafts(status="approved")[0]["title"] == "Why depth feels calm"
    mem.close()


def test_recent_decisions_returns_adjudicated_with_ops(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    good = mem.save_draft("Approved redesign", "diff", kind="edit",
                          meta={"ops": [{"op": "edit", "path": "index.html", "find": "a", "replace": "b"}]})
    bad = mem.save_draft("Declined breath ring", "diff", kind="edit",
                         meta={"ops": [{"op": "edit", "path": "styles.css", "find": "c", "replace": "d"}]})
    mem.save_draft("Still pending", "diff", kind="edit",
                   meta={"ops": [{"op": "edit", "path": "keep.html", "find": "e", "replace": "f"}]})
    mem.update_draft_status(bad, "declined")
    mem.update_draft_status(good, "approved")

    decisions = mem.recent_decisions(limit=10)
    ids = {d["id"] for d in decisions}
    assert ids == {good, bad}
    by_id = {d["id"]: d for d in decisions}
    assert by_id[bad]["status"] == "declined"
    assert by_id[bad]["meta"]["ops"][0]["path"] == "styles.css"
    assert by_id[good]["status"] == "approved"
    mem.close()


def test_metrics_snapshots_latest_wins(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mem.snapshot_metrics("ga4", {"users": 100})
    mem.snapshot_metrics("ga4", {"users": 120})
    latest = mem.latest_snapshot("ga4")
    assert latest["data"]["users"] == 120
    assert mem.latest_snapshot("gsc") is None
    mem.close()


def test_migration_from_deployed_schema9_creates_owner_workflow_tables(tmp_path):
    path = tmp_path / "schema9.db"
    conn = sqlite3.connect(path)
    for version in range(1, 10):
        with conn:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
    conn.execute("INSERT INTO conversations (created_ts, title) VALUES ('2026-01-01T00:00:00+00:00', 'kept')")
    conn.commit()
    conn.close()

    memory = Memory(path)
    assert memory.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert memory.get_conversation(1)["title"] == "kept"
    assert memory.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='owner_actions'").fetchone()
    memory.close()


def test_migration_from_schema8_preserves_existing_records(tmp_path):
    path = tmp_path / "schema8.db"
    conn = sqlite3.connect(path)
    for version in range(1, 9):
        with conn:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
    conn.execute("INSERT INTO kv (key, value) VALUES ('owner_note', 'keep this')")
    conn.commit()
    conn.close()

    memory = Memory(path)
    assert memory.kv_get("owner_note") == "keep this"
    columns = {row["name"] for row in memory.conn.execute("PRAGMA table_info(conversations)")}
    assert {"archived_ts", "deleted_ts"} <= columns
    assert memory.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'").fetchone()
    memory.close()


def test_owner_workflow_records_round_trip_and_guard_transitions(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    action = memory.create_owner_action(
        OwnerAction(
            capability_id="content.article.prepare",
            provider_id="site-agent",
            title="Prepare an article",
            summary="Ada can prepare an article.",
            action_label="Ask Ada to prepare it",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref="test:article",
            dedupe_key="test:article",
            payload={"access_token": "do-not-store", "topic": "calm"},
        )
    )
    assert memory.get_owner_action(action.id).payload["access_token"] == "[REDACTED]"

    artifact = memory.create_artifact(
        Artifact(
            kind=ArtifactKind.ARTICLE,
            title="Prepared article",
            summary="An immutable prepared article.",
            renderer="article",
            capability_id="content.article.prepare",
            provider_id="site-agent",
            content_hash="sha256:abc",
            source_action_id=action.id,
            preview_data={"body": "hello", "secret": "hidden"},
        )
    )
    approval = memory.create_approval_request(
        ApprovalRequest(
            artifact_id=artifact.artifact_id,
            artifact_hash=artifact.content_hash,
            effect_class=EffectClass.PROPOSAL,
            owner_action_label="Keep this draft",
            provider_id="site-agent",
            action_id=action.id,
        )
    )
    receipt = memory.create_provider_receipt(
        ProviderReceipt(
            provider_id="site-agent",
            capability_id="content.article.prepare",
            idempotency_key="test-1",
            status=ReceiptStatus.SUCCESS,
            action_id=action.id,
            approval_id=approval.approval_id,
            safe_message="prepared",
        )
    )
    assert memory.get_artifact(artifact.artifact_id).preview_data["secret"] == "[REDACTED]"
    assert memory.get_approval_request(approval.approval_id).artifact_hash == "sha256:abc"
    assert memory.get_provider_receipt(receipt.receipt_id).status is ReceiptStatus.SUCCESS

    memory.transition_owner_action(action.id, "completed")
    with pytest.raises(ValueError, match="cannot transition"):
        memory.transition_owner_action(action.id, "open")
    memory.transition_approval_request(approval.approval_id, "approved")
    with pytest.raises(ValueError, match="cannot transition"):
        memory.transition_approval_request(approval.approval_id, "pending")
    memory.close()


def test_seo_report_and_article_idea_records_round_trip(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        report = memory.create_seo_site_report("2026-07")
        updated = memory.update_seo_site_report(
            report["id"],
            status="completed",
            evidence_hash="evidence-hash",
            evidence_json={"site": {"status": "ready"}},
            summary="Traffic was steady.",
            artifact_id=12,
        )
        assert updated["status"] == "completed"
        assert updated["evidence_json"]["site"]["status"] == "ready"
        assert memory.list_seo_site_reports()[0]["period"] == "2026-07"

        idea = memory.create_article_idea(
            "article:2026-W30",
            "idea-hash",
            {"working_title": "A useful guide", "thesis": "Help readers."},
        )
        idea = memory.update_article_idea(
            idea["id"],
            status="researched",
            research_run_id="run-1",
            serp_run_id="run-serp",
            research_note_json={"decision": "keep", "serp_evidence": {"organic": []}},
            research_result_json=[{"keyword": "useful guide", "search_volume": 20}],
            research_cost_micros=125000,
            draft_id=42,
        )
        assert idea["status"] == "researched"
        assert idea["serp_run_id"] == "run-serp"
        assert idea["research_note_json"] == {"decision": "keep", "serp_evidence": {"organic": []}}
        assert idea["research_result_json"] == [{"keyword": "useful guide", "search_volume": 20}]
        assert memory.get_article_idea_by_cycle("article:2026-W30")["research_run_id"] == "run-1"

        rejection_id = memory.record_rejected_article_idea(
            cycle_key="article:2026-W35",
            raw='{"working_title":"Rejected title"}',
            parsed={"working_title": "Rejected title"},
            reason="time-sensitive article ideas require a source URL",
        )
        assert rejection_id > 0
        rejections = memory.list_rejected_article_ideas()
        assert len(rejections) == 1
        assert rejections[0]["parsed_json"]["working_title"] == "Rejected title"
        assert rejections[0]["reason"] == "time-sensitive article ideas require a source URL"
        assert rejections[0]["cycle_key"] == "article:2026-W35"
        assert memory.get_article_idea_for_draft(42)["id"] == idea["id"]
    finally:
        memory.close()
