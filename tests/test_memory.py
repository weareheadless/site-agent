import pytest

from site_agent.core.memory import Memory, SCHEMA_VERSION


def test_fresh_db_creates_current_schema(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    version = mem.conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    tables = {
        r["name"]
        for r in mem.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"kv", "observations", "actions", "drafts", "metrics_snapshots", "llm_costs"} <= tables
    mem.close()


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


def test_observations_roundtrip_and_filter(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mem.record_observation("reddit", "freedivers talk about mouthfill")
    mem.record_observation("ga", "traffic up")
    recent = mem.recent_observations(source="reddit")
    assert len(recent) == 1
    assert "mouthfill" in recent[0]["text"]
    assert len(mem.recent_observations(limit=5)) == 2
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
