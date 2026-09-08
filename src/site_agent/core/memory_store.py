"""memory_store.py — her semantic memory store.

Direct port of Ada (anticapitalist-bot)'s memory_store.py + local embedding
machinery. The idea is identical: instead of stuffing all memories into the
context window (where they rot), episodic memories are indexed here with
deterministic local vectors and retrieved ON DEMAND by meaning.

Recall embeds a query, scores every memory by cosine similarity (plus a light
recency boost so fresh + relevant surface together), and returns the top
matches. Nothing is lost to a fade — everything is kept; only what enters the
window is selective.

Embeddings are LOCAL and DETERMINISTIC (hashed word + bigram features into a
384-dim signed vector, stdlib only). No model endpoint, no API key, no extra
dependency — so indexing and recall work offline and vectorize identically to
Ada for the same text.

For site-agent the rows live in the instance memory.db `memories` table
(observation id as the stable primary key); indexing is incremental from a kv
watermark, so it stays cheap. Recall is lazy: calling recall first indexes any
new observations.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import re
import time
from typing import Any

# number of features that exist in the vector space — must stay fixed: it defines
# the stored vectors. (Same as Ada: 384.)
EMBEDDING_DIMENSIONS = 384

# Recall tuning — identical to Ada. recency_weight controls how much "recent"
# competes with "relevant"; halflife_days controls how fast the recency boost
# decays (a memory a halflife old contributes half).
RECENCY_WEIGHT = 0.15
HALFLIFE_DAYS = 7.0

# Per-kind multiplier on the cosine score, so high-value memory kinds
# (learnings, inner voice, self-notes, identity shifts) aren't drowned out by noisy bulk.
KIND_WEIGHT: dict[str, float] = {
    "inner_voice": 1.1,
    "awaken": 1.1,
    "learning": 1.1,
    "dream": 1.05,
    "identity_shift": 1.1,
    "self": 1.0,
    "archive": 1.0,
    "observations": 1.0,
}

# Default per-kind caps for maintenance_cleanup (config overridable).
DEFAULT_LIMITS: dict[str, int] = {
    "observations": 500,
    "learning": 500,
    "self": 100,
    "inner_voice": 300,
    "dream": 100,
    "identity_shift": 100,
    "awaken": 100,
    "archive": 200,
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9_@#'-]+", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().casefold().split())


def _embedding_features(text: str) -> list[tuple[str, float]]:
    tokens = [item.lower() for item in _TOKEN_PATTERN.findall(text or "")]
    features: list[tuple[str, float]] = [(f"w:{token}", 1.0) for token in tokens]
    features.extend(
        (f"b:{left}:{right}", 0.6)
        for left, right in zip(tokens, tokens[1:])
    )
    return features


def _local_embedding(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for feature, weight in _embedding_features(text[:8000]):
        digest = hashlib.sha256(feature.encode("utf-8", "ignore")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def embed_text(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """Return the stable local embedding used by both customer and Intake memory."""
    return _local_embedding(text, dimensions)


def _to_epoch(ts_text: Any) -> float:
    try:
        dt = datetime.datetime.fromisoformat(str(ts_text).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _source_to_kind(source: str) -> str:
    if source in ("learning", "inner_voice", "dream", "awaken", "identity_shift", "self", "archive"):
        return source
    return "observations"


def _is_heartbeat(row: dict[str, Any]) -> bool:
    return row.get("source") == "self" and _normalize(row.get("text", "")) == "heartbeat"


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compare two embeddings without exposing a persistence implementation."""
    return _cosine(a, b)


def reindex(memory: Any, batch_size: int = 100) -> int:
    """Index any observations not already in the store. Returns how many were added.

    Incremental from the kv watermark; cheap when nothing is new. Episodic items
    are deduped by the stable observation id AND by normalized text, so
    re-reading the same world content across cycles doesn't bloat the store.
    """
    until = int(memory.kv_get("memory_index_until_id", 0) or 0)
    rows = [
        dict(r)
        for r in memory.conn.execute(
            "SELECT id, ts, source, text FROM observations WHERE id > ? ORDER BY id ASC",
            (until,),
        )
    ]
    rows = [r for r in rows if not _is_heartbeat(r) and str(r["text"] or "").strip()]
    if not rows:
        return 0

    existing_norm = {_normalize(r["text"]) for r in memory.conn.execute("SELECT text FROM memories")}
    to_embed: list[dict[str, Any]] = []
    for row in rows:
        norm = _normalize(row["text"])
        if norm in existing_norm:
            continue
        existing_norm.add(norm)
        to_embed.append(row)
    if not to_embed:
        memory.kv_set("memory_index_until_id", max(r["id"] for r in rows))
        return 0

    added = 0
    last_success_id = 0
    for i in range(0, len(to_embed), batch_size):
        batch = to_embed[i : i + batch_size]
        try:
            vecs = [_local_embedding(r["text"]) for r in batch]
        except Exception:  # noqa: BLE001 — never let indexing break a job
            break
        try:
            for row, vec in zip(batch, vecs):
                memory.conn.execute(
                    "INSERT OR REPLACE INTO memories (id, kind, text, ts, embedding) VALUES (?,?,?,?,?)",
                    (
                        row["id"],
                        _source_to_kind(row["source"]),
                        row["text"],
                        _to_epoch(row.get("ts", "")),
                        json.dumps(vec),
                    ),
                )
            memory.conn.commit()
        except Exception:  # noqa: BLE001
            break
        added += len(batch)
        last_success_id = max(r["id"] for r in batch)

    if last_success_id:
        memory.kv_set("memory_index_until_id", last_success_id)
    return added


def recall_by_meaning(
    memory: Any,
    query: str,
    k: int = 8,
    recency_weight: float | None = None,
    halflife_days: float | None = None,
    kinds: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Semantic recall: rank memories by meaning blended with recency.

    Lazy: indexes any new observations first. Returns top-k dicts of
    {kind, text, ts, score, age_days, cos}. Same scoring as Ada's recall.
    """
    query = (query or "").strip()
    if not query:
        return []
    reindex(memory)
    total = memory.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    if not total:
        return []
    if recency_weight is None:
        recency_weight = RECENCY_WEIGHT
    if halflife_days is None:
        halflife_days = HALFLIFE_DAYS

    qvec = _local_embedding(query)
    dim = len(qvec)
    sql = "SELECT kind, text, ts, embedding FROM memories"
    params: list[str] = []
    if kinds:
        sql += " WHERE kind IN (" + ",".join("?" for _ in kinds) + ")"
        params.extend(kinds)
    rows = memory.conn.execute(sql, params).fetchall()
    now = time.time()
    scored: list[dict[str, Any]] = []
    for kind, text, ts, emb_json in rows:
        try:
            vec = json.loads(emb_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if len(vec) != dim:
            continue  # stale-dim rows are skipped, not trusted
        cos = _cosine(qvec, vec)
        age_days = max(0.0, (now - ts) / 86400.0)
        recency = math.exp(-age_days / halflife_days)
        kind_w = KIND_WEIGHT.get(kind, 1.0)
        score = cos * kind_w + recency_weight * recency
        scored.append({"kind": kind, "text": text, "ts": ts, "score": score, "age_days": age_days, "cos": cos})

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]


def fmt_recall(results: list[dict[str, Any]]) -> str:
    """Format recall results for a prompt (same shape as Ada's)."""
    if not results:
        return "(nothing in my memory matches that)"
    lines = []
    for r in results:
        when = datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M")
        kind = r.get("kind", "?")
        lines.append(f"[{kind} · {when} · {r.get('score', 0.0):.2f}] {str(r.get('text', ''))[:400]}")
    return "\n".join(lines)


def index_count(memory: Any) -> int:
    return int(memory.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])


def maintenance_cleanup(memory: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bound the semantic index without touching her authoritative memory.

    The index is a retrieval cache, not the source of truth. Keeping bounded,
    recent rows prevents old observations from winning recall just because they
    accumulated more embeddings than useful memories. Exact duplicates are
    removed defensively. Same limits/by-kind behavior as Ada's cleanup.
    """
    section = (config or {}).get("maintenance") or {}
    limits: dict[str, int] = dict(DEFAULT_LIMITS)
    raw_limits = (section.get("semantic_max_rows_by_kind") or {} if isinstance(section, dict) else {})
    if isinstance(raw_limits, dict):
        for kind, value in raw_limits.items():
            try:
                limits[str(kind)] = max(1, int(value))
            except (TypeError, ValueError):
                continue

    rows = memory.conn.execute(
        "SELECT id, kind, text, ts FROM memories ORDER BY kind ASC, ts DESC, id DESC"
    ).fetchall()
    seen_text = set()
    kept_by_kind: dict[str, int] = {}
    removed_duplicates = 0
    removed_over_limit = 0
    for rid, kind, text, _ts in rows:
        normalized = _normalize(text)
        if normalized in seen_text:
            memory.conn.execute("DELETE FROM memories WHERE id=?", (rid,))
            removed_duplicates += 1
            continue
        seen_text.add(normalized)
        kept = kept_by_kind.get(kind, 0)
        if kept >= limits.get(kind, 500):
            memory.conn.execute("DELETE FROM memories WHERE id=?", (rid,))
            removed_over_limit += 1
            continue
        kept_by_kind[kind] = kept + 1
    memory.conn.commit()
    total = memory.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    result = {
        "rows_before": len(rows),
        "duplicates_removed": removed_duplicates,
        "over_limit_removed": removed_over_limit,
        "rows_after": int(total),
        "kept_by_kind": kept_by_kind,
        "limits": limits,
    }
    return result
