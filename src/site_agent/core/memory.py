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
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import (
    ActionState,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    ContractError,
    OwnerAction,
    ProviderReceipt,
    validate_action_transition,
    validate_approval_transition,
)

SCHEMA_VERSION = 11

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
    10: [
        """CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision INTEGER NOT NULL DEFAULT 1,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            renderer TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            source_action_id INTEGER,
            content_hash TEXT NOT NULL,
            preview_data TEXT NOT NULL DEFAULT '{}',
            created_ts TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS owner_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capability_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            action_label TEXT NOT NULL,
            priority TEXT NOT NULL,
            requirement TEXT NOT NULL,
            state TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            snoozed_until TEXT,
            conversation_id INTEGER,
            artifact_id INTEGER,
            approval_id INTEGER,
            draft_id INTEGER,
            payload_version INTEGER NOT NULL DEFAULT 1,
            payload TEXT NOT NULL DEFAULT '{}'
        )""",
        """CREATE TABLE IF NOT EXISTS approval_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id INTEGER NOT NULL,
            artifact_hash TEXT NOT NULL,
            effect_class TEXT NOT NULL,
            owner_action_label TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            action_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            decided_ts TEXT,
            owner_feedback TEXT,
            execution_job_id INTEGER,
            provider_receipt_id INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS provider_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            action_id INTEGER,
            approval_id INTEGER,
            idempotency_key TEXT NOT NULL,
            external_object_id TEXT,
            external_url TEXT,
            status TEXT NOT NULL,
            safe_message TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_owner_actions_state_priority ON owner_actions (state, priority, id)",
        "CREATE INDEX IF NOT EXISTS idx_owner_actions_refs ON owner_actions (conversation_id, artifact_id, approval_id, draft_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_actions_active_dedupe ON owner_actions (dedupe_key) WHERE state NOT IN ('completed', 'dismissed', 'stale')",
        "CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests (status, id)",
        "CREATE INDEX IF NOT EXISTS idx_approval_requests_refs ON approval_requests (artifact_id, action_id, provider_id)",
        "CREATE INDEX IF NOT EXISTS idx_provider_receipts_refs ON provider_receipts (provider_id, approval_id, action_id)",
    ],
    11: [
        "ALTER TABLE conversations ADD COLUMN deleted_ts TEXT",
        "CREATE INDEX IF NOT EXISTS idx_conversations_visibility ON conversations (deleted_ts, archived_ts, id)",
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
    def create_owner_action(self, action: OwnerAction) -> OwnerAction:
        if action.id is not None:
            raise ContractError("new owner action must not already have an id")
        record = action.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO owner_actions "
                "(capability_id, provider_id, title, summary, action_label, priority, requirement, state, "
                "source_ref, dedupe_key, created_ts, updated_ts, snoozed_until, conversation_id, artifact_id, "
                "approval_id, draft_id, payload_version, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["capability_id"], record["provider_id"], record["title"], record["summary"],
                    record["action_label"], record["priority"], record["requirement"], record["state"],
                    record["source_ref"], record["dedupe_key"], record["created_ts"], record["updated_ts"],
                    record["snoozed_until"], record["conversation_id"], record["artifact_id"],
                    record["approval_id"], record["draft_id"], record["payload_version"], record["payload"],
                ),
            )
        return replace(action, id=cur.lastrowid)

    @_locked
    def get_owner_action(self, action_id: int) -> OwnerAction | None:
        row = self.conn.execute("SELECT * FROM owner_actions WHERE id = ?", (action_id,)).fetchone()
        return OwnerAction.from_record(dict(row)) if row else None

    @_locked
    def find_owner_action(self, dedupe_key: str, include_terminal: bool = False) -> OwnerAction | None:
        query = "SELECT * FROM owner_actions WHERE dedupe_key = ?"
        if not include_terminal:
            query += " AND state NOT IN ('completed', 'dismissed', 'stale')"
        query += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(query, (dedupe_key,)).fetchone()
        return OwnerAction.from_record(dict(row)) if row else None

    @_locked
    def list_owner_actions(self, states: list[str] | tuple[str, ...] | None = None, limit: int = 100) -> list[OwnerAction]:
        query = "SELECT * FROM owner_actions"
        params: list[Any] = []
        if states:
            values = [ActionState(state).value for state in states]
            query += " WHERE state IN (" + ",".join("?" for _ in values) + ")"
            params.extend(values)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [OwnerAction.from_record(dict(row)) for row in self.conn.execute(query, params)]

    @_locked
    def transition_owner_action(
        self,
        action_id: int,
        state: ActionState | str,
        *,
        snoozed_until: str | None = None,
    ) -> OwnerAction | None:
        row = self.conn.execute("SELECT * FROM owner_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            return None
        current = OwnerAction.from_record(dict(row))
        try:
            target = ActionState(state)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid owner action state: {state}") from exc
        validate_action_transition(current.state, target)
        if target == ActionState.SNOOZED and not snoozed_until:
            raise ContractError("snoozed actions require snoozed_until")
        next_snoozed_until = snoozed_until if target == ActionState.SNOOZED else None
        updated_ts = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE owner_actions SET state = ?, snoozed_until = ?, updated_ts = ? WHERE id = ?",
                (target.value, next_snoozed_until, updated_ts, action_id),
            )
        return replace(current, state=target, snoozed_until=next_snoozed_until, updated_ts=updated_ts)

    @_locked
    def link_owner_action(
        self,
        action_id: int | None,
        *,
        conversation_id: int | None = None,
        artifact_id: int | None = None,
        approval_id: int | None = None,
        draft_id: int | None = None,
    ) -> OwnerAction:
        if action_id is None:
            raise ContractError("owner action id is required")
        action = self.get_owner_action(action_id)
        if action is None:
            raise KeyError(f"no such owner action: {action_id}")
        fields: list[str] = []
        values: list[Any] = []
        for name, value in (
            ("conversation_id", conversation_id),
            ("artifact_id", artifact_id),
            ("approval_id", approval_id),
            ("draft_id", draft_id),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                values.append(value)
        if not fields:
            return action
        updated_ts = _now()
        fields.append("updated_ts = ?")
        values.extend((updated_ts, action_id))
        with self.conn:
            self.conn.execute(
                f"UPDATE owner_actions SET {', '.join(fields)} WHERE id = ?", values
            )
        return replace(
            action,
            conversation_id=conversation_id if conversation_id is not None else action.conversation_id,
            artifact_id=artifact_id if artifact_id is not None else action.artifact_id,
            approval_id=approval_id if approval_id is not None else action.approval_id,
            draft_id=draft_id if draft_id is not None else action.draft_id,
            updated_ts=updated_ts,
        )

    @_locked
    def create_artifact(self, artifact: Artifact) -> Artifact:
        if artifact.artifact_id is not None:
            raise ContractError("new artifact must not already have an id")
        record = artifact.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO artifacts "
                "(revision, kind, title, summary, renderer, capability_id, provider_id, source_action_id, content_hash, preview_data, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["revision"], record["kind"], record["title"], record["summary"], record["renderer"],
                    record["capability_id"], record["provider_id"], record["source_action_id"],
                    record["content_hash"], record["preview_data"], record["created_ts"],
                ),
            )
        return replace(artifact, artifact_id=cur.lastrowid)

    @_locked
    def get_artifact(self, artifact_id: int) -> Artifact | None:
        row = self.conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return Artifact.from_record(dict(row)) if row else None

    @_locked
    def create_approval_request(self, approval: ApprovalRequest) -> ApprovalRequest:
        if approval.approval_id is not None:
            raise ContractError("new approval request must not already have an id")
        record = approval.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO approval_requests "
                "(artifact_id, artifact_hash, effect_class, owner_action_label, provider_id, action_id, status, created_ts, updated_ts, decided_ts, owner_feedback, execution_job_id, provider_receipt_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["artifact_id"], record["artifact_hash"], record["effect_class"], record["owner_action_label"],
                    record["provider_id"], record["action_id"], record["status"], record["created_ts"],
                    record["updated_ts"], record["decided_ts"], record["owner_feedback"],
                    record["execution_job_id"], record["provider_receipt_id"],
                ),
            )
        return replace(approval, approval_id=cur.lastrowid)

    @_locked
    def get_approval_request(self, approval_id: int) -> ApprovalRequest | None:
        row = self.conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        return ApprovalRequest.from_record(dict(row)) if row else None

    @_locked
    def list_approval_requests(
        self,
        status: ApprovalStatus | str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        query = "SELECT * FROM approval_requests"
        params: list[Any] = []
        if status is not None:
            value = status.value if isinstance(status, ApprovalStatus) else ApprovalStatus(status).value
            query += " WHERE status = ?"
            params.append(value)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [ApprovalRequest.from_record(dict(row)) for row in self.conn.execute(query, params)]

    @_locked
    def transition_approval_request(
        self,
        approval_id: int,
        status: ApprovalStatus | str,
        *,
        owner_feedback: str | None = None,
    ) -> ApprovalRequest | None:
        row = self.conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        current = ApprovalRequest.from_record(dict(row))
        try:
            target = ApprovalStatus(status)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid approval status: {status}") from exc
        validate_approval_transition(current.status, target)
        updated_ts = _now()
        decided_ts = updated_ts if target != ApprovalStatus.PENDING else current.decided_ts
        feedback = current.owner_feedback if owner_feedback is None else owner_feedback.strip()[:1000]
        with self.conn:
            self.conn.execute(
                "UPDATE approval_requests SET status = ?, updated_ts = ?, decided_ts = ?, owner_feedback = ? WHERE id = ?",
                (target.value, updated_ts, decided_ts, feedback, approval_id),
            )
        return replace(current, status=target, updated_ts=updated_ts, decided_ts=decided_ts, owner_feedback=feedback)

    @_locked
    def create_provider_receipt(self, receipt: ProviderReceipt) -> ProviderReceipt:
        if receipt.receipt_id is not None:
            raise ContractError("new provider receipt must not already have an id")
        record = receipt.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO provider_receipts "
                "(provider_id, capability_id, action_id, approval_id, idempotency_key, external_object_id, external_url, status, safe_message, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["provider_id"], record["capability_id"], record["action_id"], record["approval_id"],
                    record["idempotency_key"], record["external_object_id"], record["external_url"],
                    record["status"], record["safe_message"], record["created_ts"], record["updated_ts"],
                ),
            )
        return replace(receipt, receipt_id=cur.lastrowid)

    @_locked
    def get_provider_receipt(self, receipt_id: int) -> ProviderReceipt | None:
        row = self.conn.execute("SELECT * FROM provider_receipts WHERE id = ?", (receipt_id,)).fetchone()
        return ProviderReceipt.from_record(dict(row)) if row else None

    @_locked
    def get_provider_receipt_by_idempotency_key(self, idempotency_key: str) -> ProviderReceipt | None:
        row = self.conn.execute(
            "SELECT * FROM provider_receipts WHERE idempotency_key = ? ORDER BY id DESC LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        return ProviderReceipt.from_record(dict(row)) if row else None

    @_locked
    def link_approval_request(
        self,
        approval_id: int,
        *,
        provider_receipt_id: int | None = None,
        execution_job_id: int | None = None,
    ) -> ApprovalRequest:
        approval = self.get_approval_request(approval_id)
        if approval is None:
            raise KeyError(f"no such approval: {approval_id}")
        fields: list[str] = []
        values: list[Any] = []
        if provider_receipt_id is not None:
            fields.append("provider_receipt_id = ?")
            values.append(provider_receipt_id)
        if execution_job_id is not None:
            fields.append("execution_job_id = ?")
            values.append(execution_job_id)
        if not fields:
            return approval
        fields.append("updated_ts = ?")
        values.extend((_now(), approval_id))
        with self.conn:
            self.conn.execute(f"UPDATE approval_requests SET {', '.join(fields)} WHERE id = ?", values)
        return self.get_approval_request(approval_id)

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
        clauses = ["deleted_ts IS NULL"]
        if not include_archived:
            clauses.append("archived_ts IS NULL")
        query += " WHERE " + " AND ".join(clauses)
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
    def archive_conversation(self, conversation_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE conversations SET archived_ts = ? WHERE id = ? AND deleted_ts IS NULL AND archived_ts IS NULL",
                (_now(), conversation_id),
            )
        return cur.rowcount == 1

    @_locked
    def restore_conversation(self, conversation_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE conversations SET archived_ts = NULL WHERE id = ? AND deleted_ts IS NULL AND archived_ts IS NOT NULL",
                (conversation_id,),
            )
        return cur.rowcount == 1

    @_locked
    def delete_conversation_content(self, conversation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, deleted_ts FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            return None
        if row["deleted_ts"]:
            return {
                "conversation_id": conversation_id,
                "deleted_ts": row["deleted_ts"],
                "already_deleted": True,
                "job_ids": [],
            }
        active = [
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM chat_jobs WHERE conversation_id = ? AND status IN ('queued', 'running')",
                (conversation_id,),
            )
        ]
        if active:
            return {"conversation_id": conversation_id, "blocked_job_ids": active}
        deleted_ts = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE chat_jobs SET message = '', message_id = NULL, steps = '[]', result = NULL, error = NULL, "
                "claimed_by = NULL, heartbeat_ts = NULL, updated_ts = ? WHERE conversation_id = ?",
                (deleted_ts, conversation_id),
            )
            self.conn.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
            self.conn.execute(
                "UPDATE conversations SET title = 'Deleted conversation', archived_ts = ?, deleted_ts = ? WHERE id = ?",
                (deleted_ts, deleted_ts, conversation_id),
            )
        return {
            "conversation_id": conversation_id,
            "deleted_ts": deleted_ts,
            "already_deleted": False,
            "job_ids": [],
        }

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
