"""memory.py — per-instance sqlite state for the agent.

One database per site instance, stored in the instance's data/ directory.
Schema is versioned via PRAGMA user_version; migrations run automatically on
open so upgrading the package never erases what she learned.
"""

from __future__ import annotations

import datetime
from functools import wraps
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 9

MIGRATIONS: dict[int, list[str]] = {
    1: [
        """CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations (ts)""",
        """CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'article',
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            meta TEXT NOT NULL DEFAULT '{}'
        )""",
        """CREATE TABLE IF NOT EXISTS metrics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            source TEXT NOT NULL,
            data TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS llm_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL
        )""",
    ],
    2: [
        "ALTER TABLE observations ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'",
    ],
    3: [
        """CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT 'New conversation'
        )""",
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            ts TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages (conversation_id, id)""",
        """CREATE TABLE IF NOT EXISTS publishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            commit_sha TEXT NOT NULL DEFAULT '',
            draft_id INTEGER
        )""",
    ],
    4: [
        """CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            ts REAL NOT NULL DEFAULT 0,
            embedding TEXT NOT NULL DEFAULT '[]'
        )""",
        """CREATE INDEX IF NOT EXISTS idx_memories_kind_ts ON memories (kind, ts)""",
    ],
    5: [
        "ALTER TABLE publishes ADD COLUMN reverted_ts TEXT",
    ],
    6: [
        """CREATE TABLE IF NOT EXISTS chat_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            steps TEXT NOT NULL DEFAULT '[]',
            result TEXT,
            error TEXT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            claimed_by TEXT,
            heartbeat_ts REAL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_chat_jobs_status ON chat_jobs (status, id)""",
    ],
    7: [
        "ALTER TABLE chat_jobs ADD COLUMN message_id INTEGER REFERENCES chat_messages(id)",
    ],
    8: [
        "ALTER TABLE publishes ADD COLUMN parent_sha TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE publishes ADD COLUMN actor TEXT NOT NULL DEFAULT 'ada'",
        "ALTER TABLE publishes ADD COLUMN version_type TEXT NOT NULL DEFAULT 'edit'",
    ],
    9: [
        "ALTER TABLE conversations ADD COLUMN archived_ts TEXT",
    ],
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _locked(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class Memory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current + 1, SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(version, [])
            with self.conn:
                for statement in statements:
                    self.conn.execute(statement)
                self.conn.execute(f"PRAGMA user_version = {version}")

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @_locked
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    @_locked
    def kv_set(self, key: str, value: Any) -> None:
        encoded = value if isinstance(value, str) else json.dumps(value)
        with self.conn:
            self.conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, encoded),
            )

    @_locked
    def record_observation(self, source: str, text: str, meta: dict[str, Any] | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO observations (ts, source, text, meta) VALUES (?, ?, ?, ?)",
                (_now(), source, text, json.dumps(meta or {})),
            )
        return cur.lastrowid

    @_locked
    def recent_observations(self, limit: int = 20, source: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM observations"
        params: list[Any] = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in self.conn.execute(query, params)]
        for row in rows:
            try:
                row["meta"] = json.loads(row.get("meta") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["meta"] = {}
        return rows

    @_locked
    def record_action(self, kind: str, detail: str = "") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO actions (ts, kind, detail) VALUES (?, ?, ?)",
                (_now(), kind, detail[:500]),
            )
        return cur.lastrowid

    @_locked
    def recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]

    @_locked
    def save_draft(
        self,
        title: str,
        body: str,
        kind: str = "article",
        meta: dict[str, Any] | None = None,
        draft_id: int | None = None,
    ) -> int:
        now = _now()
        with self.conn:
            if draft_id is None:
                cur = self.conn.execute(
                    "INSERT INTO drafts (created_ts, updated_ts, kind, title, body, status, meta) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (now, now, kind, title, body, json.dumps(meta or {})),
                )
                return cur.lastrowid
            self.conn.execute(
                "UPDATE drafts SET updated_ts = ?, title = ?, body = ?, meta = ? WHERE id = ?",
                (now, title, body, json.dumps(meta or {}), draft_id),
            )
            return draft_id

    @_locked
    def update_draft_status(self, draft_id: int, status: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE drafts SET status = ?, updated_ts = ? WHERE id = ?",
                (status, _now(), draft_id),
            )
        return cur.rowcount > 0

    @_locked
    def add_draft_feedback(self, draft_id: int, feedback: str) -> bool:
        """Attach the owner's rejection note to the draft's meta so the decision
        ledger can show the *reason* a proposal was declined. Structured data,
        not parsed from free text."""
        feedback = (feedback or "").strip()
        if not feedback:
            return False
        try:
            row = self.conn.execute("SELECT meta FROM drafts WHERE id = ?", (draft_id,)).fetchone()
            if row is None:
                return False
            meta = json.loads(row["meta"]) if row["meta"] else {}
            meta["feedback"] = feedback
            with self.conn:
                self.conn.execute(
                    "UPDATE drafts SET meta = ?, updated_ts = ? WHERE id = ?",
                    (json.dumps(meta), _now(), draft_id),
                )
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    @_locked
    def list_drafts(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM drafts"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in self.conn.execute(query, params)]
        for row in rows:
            try:
                row["meta"] = json.loads(row["meta"])
            except (json.JSONDecodeError, TypeError):
                pass
        return rows

    @_locked
    def recent_decisions(self, limit: int = 6) -> list[dict[str, Any]]:
        """Adjudicated drafts — declined or approved — newest first.

        The editor surfaces these decisions as context. They inform the model
        without permanently preventing the owner from revisiting earlier work.
        """
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT id, kind, status, title, meta, updated_ts FROM drafts "
                "WHERE status IN ('declined', 'approved') ORDER BY updated_ts DESC, id DESC LIMIT ?",
                (limit,),
            )
        ]
        for row in rows:
            try:
                row["meta"] = json.loads(row["meta"])
            except (json.JSONDecodeError, TypeError):
                row["meta"] = {}
        return rows

    @_locked
    def snapshot_metrics(self, source: str, data: dict[str, Any]) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO metrics_snapshots (ts, source, data) VALUES (?, ?, ?)",
                (_now(), source, json.dumps(data)),
            )
        return cur.lastrowid

    @_locked
    def latest_snapshot(self, source: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM metrics_snapshots WHERE source = ? ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["data"] = json.loads(out["data"])
        return out

    @_locked
    def log_llm_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO llm_costs (ts, model, prompt_tokens, completion_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (_now(), model, prompt_tokens, completion_tokens, cost_usd),
            )

    @_locked
    def compact_candidates(
        self,
        before_ts: str,
        prefixes: tuple[str, ...] = ("reddit", "rss"),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Raw feed observations old enough to compress into an archive."""
        query = (
            "SELECT * FROM observations WHERE ts < ? AND ("
            + " OR ".join("source LIKE ?" for _ in prefixes)
            + ") ORDER BY id ASC LIMIT ?"
        )
        params = [before_ts, *[f"{p}%" for p in prefixes], limit]
        return [dict(r) for r in self.conn.execute(query, params)]

    @_locked
    def delete_observations(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.conn:
            cur = self.conn.execute(f"DELETE FROM observations WHERE id IN ({placeholders})", ids)
        return cur.rowcount

    @_locked
    def create_conversation(self, title: str = "New conversation") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO conversations (created_ts, title) VALUES (?, ?)",
                (_now(), title[:120]),
            )
        return cur.lastrowid

    @_locked
    def list_conversations(self, limit: int = 50, include_archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM conversations"
        params: list[Any] = []
        if not include_archived:
            query += " WHERE archived_ts IS NULL"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(query, params)]

    @_locked
    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def archive_conversations(self, keep_id: int | None = None) -> int:
        """Hide old conversations without deleting their durable chat jobs."""
        clauses = [
            "archived_ts IS NULL",
            "id NOT IN (SELECT conversation_id FROM chat_jobs WHERE status IN ('queued', 'running'))",
        ]
        where_params: list[Any] = []
        if keep_id is not None:
            clauses.append("id != ?")
            where_params.append(keep_id)
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE conversations SET archived_ts = ? WHERE {' AND '.join(clauses)}",
                [_now(), *where_params],
            )
        return cur.rowcount

    @_locked
    def add_message(self, conversation_id: int, role: str, text: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO chat_messages (conversation_id, ts, role, text) VALUES (?, ?, ?, ?)",
                (conversation_id, _now(), role, text),
            )
        return cur.lastrowid

    @_locked
    def get_messages(self, conversation_id: int, limit: int = 200) -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT ts, role, text FROM chat_messages WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (conversation_id, limit),
            )
        ]
        return list(reversed(rows))

    @_locked
    def get_messages_before(self, conversation_id: int, message_id: int, limit: int = 8) -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT ts, role, text FROM chat_messages WHERE conversation_id = ? AND id < ? "
                "ORDER BY id DESC LIMIT ?",
                (conversation_id, message_id, limit),
            )
        ]
        return list(reversed(rows))

    @_locked
    def enqueue_chat_job(self, conversation_id: int, message: str) -> int:
        """Persist the user message and its job together."""
        now = _now()
        with self.conn:
            message_cur = self.conn.execute(
                "INSERT INTO chat_messages (conversation_id, ts, role, text) VALUES (?, ?, 'user', ?)",
                (conversation_id, now, message),
            )
            cur = self.conn.execute(
                "INSERT INTO chat_jobs "
                "(conversation_id, message, message_id, status, created_ts, updated_ts) "
                "VALUES (?, ?, ?, 'queued', ?, ?)",
                (conversation_id, message, message_cur.lastrowid, now, now),
            )
        return cur.lastrowid

    @_locked
    def claim_chat_job(self, worker: str) -> dict[str, Any] | None:
        """Claim the oldest queued job using a database-level write lock."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            running = self.conn.execute(
                "SELECT 1 FROM chat_jobs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            if running:
                self.conn.rollback()
                return None
            row = self.conn.execute(
                "SELECT * FROM chat_jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                self.conn.rollback()
                return None
            updated = self.conn.execute(
                "UPDATE chat_jobs SET status = 'running', claimed_by = ?, updated_ts = ? "
                "WHERE id = ? AND status = 'queued'",
                (worker, _now(), row["id"]),
            ).rowcount
            if updated != 1:
                self.conn.rollback()
                return None
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        out = dict(row)
        out["status"] = "running"
        out["claimed_by"] = worker
        return self._decode_chat_job(out)

    @_locked
    def append_chat_job_step(self, job_id: int, worker: str, step: str) -> None:
        row = self.conn.execute(
            "SELECT steps FROM chat_jobs WHERE id = ? AND claimed_by = ?",
            (job_id, worker),
        ).fetchone()
        if row is None:
            return
        steps = json.loads(row["steps"] or "[]")
        steps.append({"ts": _now(), "text": step})
        with self.conn:
            self.conn.execute(
                "UPDATE chat_jobs SET steps = ?, updated_ts = ? "
                "WHERE id = ? AND claimed_by = ?",
                (json.dumps(steps[-200:]), _now(), job_id, worker),
            )

    @_locked
    def complete_chat_job(self, job_id: int, worker: str, result: dict[str, Any]) -> bool:
        row = self.conn.execute(
            "SELECT conversation_id FROM chat_jobs "
            "WHERE id = ? AND status = 'running' AND claimed_by = ?",
            (job_id, worker),
        ).fetchone()
        if row is None:
            return False
        with self.conn:
            updated = self.conn.execute(
                "UPDATE chat_jobs SET status = 'done', result = ?, updated_ts = ?, "
                "claimed_by = NULL, heartbeat_ts = NULL WHERE id = ? AND claimed_by = ?",
                (json.dumps(result), _now(), job_id, worker),
            ).rowcount
            if updated == 1:
                self.conn.execute(
                    "INSERT INTO chat_messages (conversation_id, ts, role, text) VALUES (?, ?, 'assistant', ?)",
                    (row["conversation_id"], _now(), result.get("reply") or ""),
                )
        return updated == 1

    @_locked
    def fail_chat_job(self, job_id: int, worker: str, error: str) -> bool:
        with self.conn:
            updated = self.conn.execute(
                "UPDATE chat_jobs SET status = 'error', error = ?, updated_ts = ?, "
                "claimed_by = NULL, heartbeat_ts = NULL WHERE id = ? AND claimed_by = ?",
                (error[:500], _now(), job_id, worker),
            ).rowcount
        return updated == 1

    @_locked
    def interrupt_running_chat_jobs(self, error: str = "interrupted by server restart; retry this job") -> int:
        """Make abandoned work visible instead of replaying it automatically."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE chat_jobs SET status = 'error', error = ?, updated_ts = ?, "
                "claimed_by = NULL, heartbeat_ts = NULL WHERE status = 'running'",
                (error[:500], _now()),
            )
        return cur.rowcount

    @_locked
    def retry_chat_job(self, job_id: int) -> bool:
        """Explicitly requeue a failed or incomplete job."""
        row = self.conn.execute(
            "SELECT status, result FROM chat_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return False
        retryable = row["status"] == "error"
        if row["status"] == "done":
            try:
                result = json.loads(row["result"] or "{}")
            except (json.JSONDecodeError, TypeError):
                result = {}
            retryable = not result.get("changed") and not result.get("merge_draft_id")
        if not retryable:
            return False
        with self.conn:
            cur = self.conn.execute(
                "UPDATE chat_jobs SET status = 'queued', steps = '[]', result = NULL, error = NULL, "
                "claimed_by = NULL, heartbeat_ts = NULL, updated_ts = ? "
                "WHERE id = ? AND status IN ('error', 'done')",
                (_now(), job_id),
            )
        return cur.rowcount == 1

    @staticmethod
    def _decode_chat_job(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["steps"] = json.loads(out.get("steps") or "[]")
        if out.get("result"):
            try:
                out["result"] = json.loads(out["result"])
            except (json.JSONDecodeError, TypeError):
                out["result"] = None
        return out

    @_locked
    def get_chat_job(self, job_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM chat_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._decode_chat_job(dict(row))

    @_locked
    def list_active_chat_jobs(self, conversation_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM chat_jobs WHERE status IN ('queued', 'running')"
        params: list[Any] = []
        if conversation_id is not None:
            query += " AND conversation_id = ?"
            params.append(conversation_id)
        query += " ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, id ASC LIMIT ?"
        params.append(limit)
        return [self._decode_chat_job(dict(r)) for r in self.conn.execute(query, params)]

    @_locked
    def list_chat_jobs(self, conversation_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM chat_jobs WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        return [self._decode_chat_job(dict(r)) for r in rows]

    @_locked
    def log_publish(
        self,
        summary: str,
        path: str,
        commit_sha: str,
        draft_id: int | None = None,
        parent_sha: str = "",
        actor: str = "ada",
        version_type: str = "edit",
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO publishes "
                "(ts, summary, path, commit_sha, draft_id, parent_sha, actor, version_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_now(), summary[:160], path, commit_sha, draft_id, parent_sha[:100], actor[:30], version_type[:30]),
            )
        return cur.lastrowid

    @_locked
    def mark_publish_reverted(self, commit_sha: str | None = None, draft_id: int | None = None) -> int:
        """Tag publish rows as reverted so the UI stops offering a Revert button."""
        with self.conn:
            if commit_sha:
                cur = self.conn.execute(
                    "UPDATE publishes SET reverted_ts = ? WHERE commit_sha = ? AND reverted_ts IS NULL",
                    (_now(), commit_sha),
                )
                return cur.rowcount
            if draft_id is not None:
                cur = self.conn.execute(
                    "UPDATE publishes SET reverted_ts = ? WHERE draft_id = ? AND reverted_ts IS NULL",
                    (_now(), draft_id),
                )
                return cur.rowcount
            return 0

    @_locked
    def list_publishes(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM publishes ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]

    @_locked
    def llm_spend(self, since_hours: float = 24.0) -> dict[str, Any]:
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=since_hours)
        ).isoformat(timespec="seconds")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) AS pt, COALESCE(SUM(completion_tokens),0) AS ct, "
            "COALESCE(SUM(cost_usd),0) AS cost FROM llm_costs WHERE ts >= ?",
            (cutoff,),
        ).fetchone()
        return {"prompt_tokens": row["pt"], "completion_tokens": row["ct"], "cost_usd": round(row["cost"], 6)}
