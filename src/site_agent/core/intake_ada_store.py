"""Private persistent store for the one cross-customer Intake Ada.

The store deliberately has no public SQLite connection.  Incubation content is
kept in its own database; this database contains only opaque registry metadata,
sanitized creative episodes, retrieval data, reflections, and receipts.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import ContractError, utc_now
from .design_contracts import canonical_hash, canonical_json
from .incubation_contracts import (
    CreativeEpisode,
    IncubationRecord,
    IncubationStatus,
    ProvisioningReceipt,
    validate_incubation_transition,
)
from .memory_store import cosine_similarity, embed_text


def _json(value: Any, name: str, maximum: int = 200_000) -> str:
    try:
        encoded = canonical_json(value)
    except Exception as exc:
        raise ContractError(f"{name} contains unsupported JSON values") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise ContractError(f"{name} exceeds {maximum} bytes")
    return encoded


def _incubation_id(value: Any) -> str:
    result = str(value or "").strip()
    if len(result) != 36 or not result.startswith("inc_") or any(char not in "inc_0123456789abcdef" for char in result):
        raise ContractError("incubation_id is invalid")
    return result


class IntakeAdaStore:
    """Typed SQLite adapter for Intake Ada's permanent state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS incubation_registry (
                    incubation_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    current_intake_revision INTEGER NOT NULL DEFAULT 0,
                    current_genesis_revision INTEGER NOT NULL DEFAULT 1,
                    accepted_candidate_sha TEXT,
                    accepted_run_id TEXT,
                    acceptance_manifest_id TEXT,
                    provisioning_request_id TEXT,
                    customer_instance_id TEXT,
                    workspace_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS incubation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incubation_id TEXT NOT NULL REFERENCES incubation_registry(incubation_id),
                    previous_status TEXT,
                    status TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incubation_registry_status ON incubation_registry(status, updated_at);
                CREATE TABLE IF NOT EXISTS creative_episodes (
                    episode_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    engagement_outcome TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    episode_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS creative_episode_vectors (
                    episode_id TEXT PRIMARY KEY REFERENCES creative_episodes(episode_id) ON DELETE CASCADE,
                    vector_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS creative_fingerprint_terms (
                    episode_id TEXT NOT NULL REFERENCES creative_episodes(episode_id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    term TEXT NOT NULL,
                    PRIMARY KEY (episode_id, category, term)
                );
                CREATE INDEX IF NOT EXISTS idx_episode_terms ON creative_fingerprint_terms(category, term);
                CREATE TABLE IF NOT EXISTS intake_self_reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id TEXT REFERENCES creative_episodes(episode_id),
                    reflection_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provisioning_receipts (
                    request_id TEXT PRIMARY KEY,
                    bundle_id TEXT NOT NULL UNIQUE,
                    incubation_id TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    bundle_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in self._conn.execute("PRAGMA table_info(incubation_registry)").fetchall()
            }
            if "accepted_run_id" not in columns:
                self._conn.execute("ALTER TABLE incubation_registry ADD COLUMN accepted_run_id TEXT")
            if "acceptance_manifest_id" not in columns:
                self._conn.execute("ALTER TABLE incubation_registry ADD COLUMN acceptance_manifest_id TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _record(self, row: sqlite3.Row | Mapping[str, Any]) -> IncubationRecord:
        return IncubationRecord.from_dict({
            "schema_version": 1,
            "incubation_id": row["incubation_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
            "current_intake_revision": row["current_intake_revision"],
            "current_genesis_revision": row["current_genesis_revision"],
            "accepted_candidate_sha": row["accepted_candidate_sha"],
            "accepted_run_id": row["accepted_run_id"],
            "acceptance_manifest_id": row["acceptance_manifest_id"],
            "provisioning_request_id": row["provisioning_request_id"],
            "customer_instance_id": row["customer_instance_id"],
            "workspace_path": row["workspace_path"],
        })

    def create_incubation(
        self,
        incubation_id: str,
        workspace_path: str | Path,
        *,
        expires_at: str | None = None,
    ) -> IncubationRecord:
        incubation_id = _incubation_id(incubation_id)
        workspace = Path(workspace_path).expanduser().resolve()
        if workspace == Path(workspace.anchor):
            raise ContractError("incubation workspace is too broad")
        now = utc_now()
        expires_at = expires_at or now
        record = IncubationRecord.from_dict({
            "incubation_id": incubation_id,
            "status": IncubationStatus.COLLECTING.value,
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "current_intake_revision": 0,
            "current_genesis_revision": 1,
            "workspace_path": str(workspace),
        })
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT status FROM incubation_registry WHERE incubation_id = ?",
                (record.incubation_id,),
            ).fetchone()
            if existing:
                if existing["status"] == IncubationStatus.PURGED.value:
                    raise ContractError("incubation identity was purged")
                raise ContractError("incubation already exists")
            try:
                self._conn.execute(
                    "INSERT INTO incubation_registry (incubation_id, status, created_at, updated_at, expires_at, workspace_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (record.incubation_id, record.status, record.created_at, record.updated_at, record.expires_at, str(workspace)),
                )
                self._conn.execute(
                    "INSERT INTO incubation_events (incubation_id, previous_status, status, event, created_at) VALUES (?, NULL, ?, 'created', ?)",
                    (record.incubation_id, record.status, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ContractError("incubation already exists") from exc
        return record

    def get_incubation(self, incubation_id: str, *, include_purged: bool = False) -> IncubationRecord | None:
        incubation_id = _incubation_id(incubation_id)
        with self._lock:
            query = "SELECT * FROM incubation_registry WHERE incubation_id = ?"
            params: list[Any] = [incubation_id]
            if not include_purged:
                query += " AND status != ?"
                params.append(IncubationStatus.PURGED.value)
            row = self._conn.execute(query, params).fetchone()
        return self._record(row) if row else None

    def list_incubations(
        self,
        *,
        statuses: Sequence[str] | None = None,
        limit: int = 100,
        include_purged: bool = False,
    ) -> list[IncubationRecord]:
        bounded = max(1, min(int(limit), 500))
        clauses: list[str] = [] if include_purged else ["status != ?"]
        params: list[Any] = []
        if not include_purged:
            params.append(IncubationStatus.PURGED.value)
        if statuses:
            normalized = [str(status).strip().lower() for status in statuses]
            if any(status not in {item.value for item in IncubationStatus} for status in normalized):
                raise ContractError("incubation status is invalid")
            clauses.append("status IN (" + ",".join("?" for _ in normalized) + ")")
            params.extend(normalized)
        query = "SELECT * FROM incubation_registry"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, incubation_id DESC LIMIT ?"
        params.append(bounded)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def transition_incubation(
        self,
        incubation_id: str,
        status: str,
        *,
        detail: Mapping[str, Any] | None = None,
        expected_status: str | None = None,
        accepted_candidate_sha: str | None = None,
        accepted_run_id: str | None = None,
        acceptance_manifest_id: str | None = None,
        provisioning_request_id: str | None = None,
        customer_instance_id: str | None = None,
    ) -> IncubationRecord:
        current = self.get_incubation(incubation_id)
        if current is None:
            raise ContractError("incubation was not found")
        target = str(status or "").strip().lower()
        if current.status == IncubationStatus.PURGED.value or target == IncubationStatus.PURGED.value:
            raise ContractError("purged incubations are not mutable")
        if current.status != target:
            validate_incubation_transition(current.status, target)
        if expected_status is not None and current.status != str(expected_status).strip().lower():
            raise ContractError("incubation status is stale")
        now = utc_now()
        candidate = current.accepted_candidate_sha if accepted_candidate_sha is None else str(accepted_candidate_sha or "").strip().lower() or None
        run_id = current.accepted_run_id if accepted_run_id is None else str(accepted_run_id or "").strip() or None
        manifest_id = current.acceptance_manifest_id if acceptance_manifest_id is None else str(acceptance_manifest_id or "").strip() or None
        request_id = current.provisioning_request_id if provisioning_request_id is None else str(provisioning_request_id or "").strip() or None
        customer_id = current.customer_instance_id if customer_instance_id is None else str(customer_instance_id or "").strip() or None
        detail_json = _json(dict(detail or {}), "incubation event detail", maximum=20_000)
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE incubation_registry SET status = ?, updated_at = ?, accepted_candidate_sha = ?, accepted_run_id = ?, acceptance_manifest_id = ?, provisioning_request_id = ?, customer_instance_id = ? WHERE incubation_id = ?",
                (target, now, candidate, run_id, manifest_id, request_id, customer_id, current.incubation_id),
            ).rowcount
            if updated != 1:
                raise ContractError("incubation status update was lost")
            self._conn.execute(
                "INSERT INTO incubation_events (incubation_id, previous_status, status, event, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (current.incubation_id, current.status, target, str((detail or {}).get("event") or target)[:100], detail_json, now),
            )
        return self.get_incubation(current.incubation_id)  # type: ignore[return-value]

    def mark_purged(
        self,
        incubation_id: str,
        *,
        expected_status: str | None = None,
        outcome: str = "pending",
        error: str | None = None,
    ) -> IncubationRecord:
        """Replace an incubation with a minimal, non-reopenable tombstone."""
        incubation_id = _incubation_id(incubation_id)
        safe_outcome = str(outcome or "pending").strip()[:40] or "pending"
        safe_error = str(error or "").strip()[:500]
        detail = {"outcome": safe_outcome}
        if safe_error:
            detail["error"] = safe_error
        detail_json = _json(detail, "purge detail", maximum=2_000)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM incubation_registry WHERE incubation_id = ?",
                (incubation_id,),
            ).fetchone()
            if row is None:
                raise ContractError("incubation was not found")
            if row["status"] == IncubationStatus.PURGED.value:
                return self._record(row)
            current = str(row["status"])
            if expected_status is not None and current != str(expected_status).strip().lower():
                raise ContractError("incubation status is stale")
            validate_incubation_transition(current, IncubationStatus.PURGED.value)
            now = utc_now()
            self._conn.execute("DELETE FROM incubation_events WHERE incubation_id = ?", (incubation_id,))
            updated = self._conn.execute(
                """
                UPDATE incubation_registry
                SET status = ?, updated_at = ?, expires_at = ?,
                    current_intake_revision = 0, current_genesis_revision = 1,
                    accepted_candidate_sha = NULL, provisioning_request_id = NULL,
                    customer_instance_id = NULL, workspace_path = ''
                WHERE incubation_id = ?
                """,
                (IncubationStatus.PURGED.value, now, now, incubation_id),
            ).rowcount
            if updated != 1:
                raise ContractError("incubation purge update was lost")
            self._conn.execute(
                """
                INSERT INTO incubation_events
                    (incubation_id, previous_status, status, event, detail_json, created_at)
                VALUES (?, ?, ?, 'purged', ?, ?)
                """,
                (incubation_id, current, IncubationStatus.PURGED.value, detail_json, now),
            )
            row = self._conn.execute(
                "SELECT * FROM incubation_registry WHERE incubation_id = ?",
                (incubation_id,),
            ).fetchone()
        return self._record(row)  # type: ignore[arg-type]

    def record_purge_result(
        self,
        incubation_id: str,
        *,
        outcome: str,
        error: str | None = None,
    ) -> IncubationRecord:
        """Persist bounded cleanup diagnostics without restoring customer data."""
        incubation_id = _incubation_id(incubation_id)
        safe_outcome = str(outcome or "unknown").strip()[:40] or "unknown"
        safe_error = str(error or "").strip()[:500]
        detail = {"outcome": safe_outcome}
        if safe_error:
            detail["error"] = safe_error
        detail_json = _json(detail, "purge detail", maximum=2_000)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM incubation_registry WHERE incubation_id = ?",
                (incubation_id,),
            ).fetchone()
            if row is None or row["status"] != IncubationStatus.PURGED.value:
                raise ContractError("purged incubation was not found")
            now = utc_now()
            event = self._conn.execute(
                "SELECT id FROM incubation_events WHERE incubation_id = ? ORDER BY id DESC LIMIT 1",
                (incubation_id,),
            ).fetchone()
            if event is None:
                self._conn.execute(
                    "INSERT INTO incubation_events (incubation_id, previous_status, status, event, detail_json, created_at) VALUES (?, NULL, ?, 'purged', ?, ?)",
                    (incubation_id, IncubationStatus.PURGED.value, detail_json, now),
                )
            else:
                self._conn.execute(
                    "UPDATE incubation_events SET detail_json = ? WHERE id = ?",
                    (detail_json, event["id"]),
                )
            self._conn.execute(
                "UPDATE incubation_registry SET updated_at = ?, workspace_path = '' WHERE incubation_id = ?",
                (now, incubation_id),
            )
            row = self._conn.execute(
                "SELECT * FROM incubation_registry WHERE incubation_id = ?",
                (incubation_id,),
            ).fetchone()
        return self._record(row)  # type: ignore[arg-type]

    def update_incubation_revisions(
        self,
        incubation_id: str,
        *,
        current_intake_revision: int | None = None,
        current_genesis_revision: int | None = None,
    ) -> IncubationRecord:
        """Update revision pointers without changing the lifecycle state."""
        current = self.get_incubation(incubation_id)
        if current is None:
            raise ContractError("incubation was not found")
        intake_revision = current.current_intake_revision if current_intake_revision is None else current_intake_revision
        genesis_revision = current.current_genesis_revision if current_genesis_revision is None else current_genesis_revision
        for name, value in (("current_intake_revision", intake_revision), ("current_genesis_revision", genesis_revision)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractError(f"{name} is invalid")
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE incubation_registry SET current_intake_revision = ?, current_genesis_revision = ?, updated_at = ? WHERE incubation_id = ?",
                (intake_revision, genesis_revision, now, current.incubation_id),
            )
        return self.get_incubation(current.incubation_id)  # type: ignore[return-value]

    def list_events(self, incubation_id: str, limit: int = 200, *, include_purged: bool = False) -> list[dict[str, Any]]:
        incubation_id = _incubation_id(incubation_id)
        if self.get_incubation(incubation_id, include_purged=include_purged) is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, incubation_id, previous_status, status, event, detail_json, created_at FROM incubation_events WHERE incubation_id = ? ORDER BY id ASC LIMIT ?",
                (incubation_id, max(1, min(int(limit), 500))),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["detail"] = {}
            result.append(item)
        return result

    def save_episode(self, episode: CreativeEpisode) -> CreativeEpisode:
        if not isinstance(episode, CreativeEpisode):
            raise ContractError("episode must be a CreativeEpisode")
        payload = episode.to_dict()
        content_hash = episode.content_hash
        vector = embed_text(episode.semantic_text)
        terms: list[tuple[str, str]] = []
        for category, values in episode.design_fingerprint.items():
            values = values if isinstance(values, list) else [values]
            terms.extend((f"design.{category}", str(value).casefold()) for value in values if str(value).strip())
        for category, values in episode.copy_fingerprint.items():
            values = values if isinstance(values, list) else [values]
            terms.extend((f"copy.{category}", str(value).casefold()) for value in values if str(value).strip())
        with self._lock, self._conn:
            existing = self._conn.execute("SELECT content_hash, episode_json FROM creative_episodes WHERE episode_id = ?", (episode.episode_id,)).fetchone()
            if existing:
                if existing["content_hash"] != content_hash:
                    raise ContractError("episode_id was already used for different content")
                return episode
            try:
                self._conn.execute(
                    "INSERT INTO creative_episodes (episode_id, created_at, engagement_outcome, content_hash, episode_json) VALUES (?, ?, ?, ?, ?)",
                    (episode.episode_id, episode.created_at, episode.engagement_outcome, content_hash, _json(payload, "creative episode")),
                )
            except sqlite3.IntegrityError as exc:
                raise ContractError("creative episode content already exists") from exc
            self._conn.execute(
                "INSERT INTO creative_episode_vectors (episode_id, vector_json) VALUES (?, ?)",
                (episode.episode_id, _json(vector, "creative episode vector", maximum=20_000)),
            )
            self._conn.executemany(
                "INSERT INTO creative_fingerprint_terms (episode_id, category, term) VALUES (?, ?, ?)",
                [(episode.episode_id, category, term[:200]) for category, term in terms],
            )
        return episode

    def get_episode(self, episode_id: str) -> CreativeEpisode | None:
        episode_id = str(episode_id or "").strip()
        if not episode_id:
            raise ContractError("episode_id is required")
        with self._lock:
            row = self._conn.execute("SELECT episode_json FROM creative_episodes WHERE episode_id = ?", (episode_id,)).fetchone()
        if not row:
            return None
        return CreativeEpisode.from_dict(json.loads(row["episode_json"]))

    def list_episodes(self, limit: int = 100) -> list[CreativeEpisode]:
        with self._lock:
            rows = self._conn.execute("SELECT episode_json FROM creative_episodes ORDER BY created_at DESC, episode_id DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
        return [CreativeEpisode.from_dict(json.loads(row["episode_json"])) for row in rows]

    def search_episodes(
        self,
        query: str,
        *,
        fingerprint: Mapping[str, Sequence[str]] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        qvec = embed_text(query)
        wanted: set[tuple[str, str]] = set()
        for category, values in (fingerprint or {}).items():
            wanted.update((str(category), str(value).casefold()) for value in values if str(value).strip())
        with self._lock:
            rows = self._conn.execute(
                "SELECT e.episode_id, e.episode_json, v.vector_json FROM creative_episodes e JOIN creative_episode_vectors v ON v.episode_id = e.episode_id"
            ).fetchall()
            term_rows = self._conn.execute("SELECT episode_id, category, term FROM creative_fingerprint_terms").fetchall()
        terms: dict[str, set[tuple[str, str]]] = {}
        for row in term_rows:
            terms.setdefault(row["episode_id"], set()).add((row["category"], row["term"]))
        result = []
        for row in rows:
            try:
                vector = json.loads(row["vector_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            semantic = max(0.0, cosine_similarity(qvec, vector))
            structured = (len(wanted & terms.get(row["episode_id"], set())) / len(wanted)) if wanted else 0.0
            score = min(1.0, semantic * 0.7 + structured * 0.3)
            result.append({"episode_id": row["episode_id"], "score": score, "semantic_score": semantic, "structured_score": structured, "patterns": sorted(term for category, term in terms.get(row["episode_id"], set()) if not wanted or (category, term) in wanted)[:20]})
        result.sort(key=lambda item: (item["score"], item["semantic_score"]), reverse=True)
        return result[: max(1, min(int(limit), 20))]

    def save_reflection(self, episode_id: str, reflection: Mapping[str, Any]) -> str:
        if self.get_episode(episode_id) is None:
            raise ContractError("reflection episode was not found")
        payload = copy.deepcopy(dict(reflection))
        content_hash = canonical_hash(payload)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO intake_self_reflections (episode_id, reflection_json, content_hash, created_at) VALUES (?, ?, ?, ?)",
                (episode_id, _json(payload, "Intake Ada reflection", maximum=50_000), content_hash, utc_now()),
            )
        return content_hash

    def save_receipt(self, receipt: ProvisioningReceipt, *, incubation_id: str | None = None) -> ProvisioningReceipt:
        if not isinstance(receipt, ProvisioningReceipt):
            raise ContractError("receipt must be a ProvisioningReceipt")
        safe_incubation_id = _incubation_id(incubation_id) if incubation_id else None
        payload = _json(receipt.to_dict(), "provisioning receipt", maximum=50_000)
        with self._lock, self._conn:
            existing = self._conn.execute("SELECT receipt_json FROM provisioning_receipts WHERE request_id = ?", (receipt.request_id,)).fetchone()
            if existing:
                return ProvisioningReceipt.from_dict(json.loads(existing["receipt_json"]))
            if safe_incubation_id is None:
                raise ContractError("incubation_id is required for a provisioning receipt")
            self._conn.execute(
                "INSERT INTO provisioning_receipts (request_id, bundle_id, incubation_id, receipt_json, bundle_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (receipt.request_id, receipt.bundle_id, safe_incubation_id, payload, receipt.bundle_hash, receipt.created_at),
            )
        return receipt

    def get_receipt(self, request_id: str) -> ProvisioningReceipt | None:
        with self._lock:
            row = self._conn.execute("SELECT receipt_json FROM provisioning_receipts WHERE request_id = ?", (str(request_id or "").strip(),)).fetchone()
        return ProvisioningReceipt.from_dict(json.loads(row["receipt_json"])) if row else None


__all__ = ["IntakeAdaStore"]
