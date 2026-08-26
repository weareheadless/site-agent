import datetime

from site_agent.core import memory_store
from site_agent.core.memory import Memory


def _observe(memory, source: str, text: str, days_ago: int = 0) -> int:
    ts = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    ).isoformat(timespec="seconds")
    with memory.conn:
        cur = memory.conn.execute(
            "INSERT INTO observations (ts, source, text, meta) VALUES (?, ?, ?, '{}')",
            (ts, source, text),
        )
    return cur.lastrowid


def test_embedding_is_local_deterministic_and_normalized(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        a = memory_store._local_embedding("the reef off Playa del Carmen at noon")
        b = memory_store._local_embedding("the reef off Playa del Carmen at noon")
        c = memory_store._local_embedding("something entirely different about taxes")
        assert a == b
        assert a != c
        assert len(a) == memory_store.EMBEDDING_DIMENSIONS == 384
        norm = sum(v * v for v in a) ** 0.5
        assert abs(norm - 1.0) < 1e-6
    finally:
        memory.close()


def test_reindex_indexes_new_observations_once(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        _observe(memory, "learning", "- Safety stories outnumber gear talk.")
        _observe(memory, "reddit/freediving", "New freediving technique post about no-limits.")
        _observe(memory, "self", "heartbeat")  # system noise: never indexed

        assert memory_store.reindex(memory) == 2
        assert memory_store.index_count(memory) == 2
        # Incremental: nothing new -> nothing added.
        assert memory_store.reindex(memory) == 0
        # A new observation indexes on the next pass.
        _observe(memory, "dream", "I dreamed the sea gave me a longer breath.")
        assert memory_store.reindex(memory) == 1
        assert memory_store.index_count(memory) == 3
    finally:
        memory.close()


def test_recall_by_meaning_ranks_relevant_memories(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        _observe(memory, "learning", "- Frenzel equalization builds slowly over weeks.")
        _observe(memory, "reddit/freediving", "Someone got no-limits depth nervous.")
        _observe(memory, "dream", "I kept rising too fast in a column of light.")
        # no reindex call yet: recall is lazy
        results = memory_store.recall_by_meaning(memory, "frenzel equalization", k=3)
        assert results, "recall should lazily index"
        assert results[0]["kind"] == "learning"
        assert "Frenzel" in results[0]["text"]
        assert all(r["score"] >= 0.0 for r in results)
    finally:
        memory.close()


def test_recall_kind_boost_prefers_identity_over_noise(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        for i in range(25):
            _observe(memory, "reddit/freediving", f"Gear sale roundup entry number {i} with fins and masks.")
        _observe(memory, "inner_voice", "The site keeps circling gear and never the people under the surface.",)
        results = memory_store.recall_by_meaning(memory, "site drifting from people", k=3)
        kinds = [r["kind"] for r in results]
        assert "inner_voice" in kinds
    finally:
        memory.close()


def test_recall_empty_query_returns_nothing(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        assert memory_store.recall_by_meaning(memory, "   ") == []
    finally:
        memory.close()


def test_fmt_recall_readable(tmp_path):
    results = [{"kind": "dream", "text": "a weight belt on the seabed", "ts": 1_600_000_000.0, "score": 0.5}]
    out = memory_store.fmt_recall(results)
    assert "[dream" in out and "weight belt" in out
    assert "(nothing in my memory matches that)" in memory_store.fmt_recall([])


def test_maintenance_cleanup_dedupes_and_caps(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        for i in range(8):
            _observe(memory, "reddit/freediving", f"Distinct observation about reefs number {i}.")
        _observe(memory, "dream", "A dream worth keeping after cap.")
        memory_store.reindex(memory)
        assert memory_store.index_count(memory) == 9
        # Inject a duplicate directly into the store (as an old pre-dedup install would have).
        row = memory.conn.execute("SELECT kind, text, ts, embedding FROM memories WHERE kind='dream'").fetchone()
        memory.conn.execute(
            "INSERT INTO memories (id, kind, text, ts, embedding) VALUES (?,?,?,?,?)",
            (99999, row["kind"], row["text"], row["ts"], row["embedding"]),
        )
        memory.conn.commit()

        result = memory_store.maintenance_cleanup(memory, {"maintenance": {"semantic_max_rows_by_kind": {"observations": 3}}})
        assert result["duplicates_removed"] == 1
        assert result["over_limit_removed"] == 5  # 8 obs capped to 3
        assert result["rows_after"] == 4  # 3 obs + 1 dream
        kinds = {r["kind"] for r in memory.conn.execute("SELECT kind FROM memories")}
        assert {"observations", "dream"} == kinds
    finally:
        memory.close()