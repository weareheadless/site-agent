"""maintenance.py — memory hygiene and behavioral health. No audience, no ego.

Ports of Ada's compaction.py and observer.py:

  health_check   — read-only, ZERO tokens: scans her own ledger for context
                   rot and behavioral drift (repeated items, feed errors,
                   stale pending drafts, spend) and files findings.
  compact_memory — prevents context rot: old raw feed observations are
                   distilled into one archive entry via an LLM subagent, then
                   deleted raw. Identity material (learning, inner voice,
                   dreams, archives) is NEVER compacted.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from typing import Any

from .memory import Memory

_EXCLUDE_FROM_REPEAT_SCAN = ("self", "inner_voice", "dream", "awaken", "archive", "learning")


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().casefold().split())


def _cutoff_iso(days: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    ).isoformat(timespec="seconds")


def health_check(context: dict[str, Any]) -> list[str]:
    """Observer port — deterministic, zero-token behavioral ledger."""
    memory: Memory = context["memory"]
    findings: list[str] = []

    recent = [
        r
        for r in memory.recent_observations(limit=120)
        if not any(r["source"].startswith(p) or r["source"] == p for p in _EXCLUDE_FROM_REPEAT_SCAN)
    ]
    counts = Counter(_normalize(r["text"]) for r in recent if r["text"])
    repeated = [text for text, n in counts.most_common(3) if n > 1 and text]
    if repeated:
        findings.append(f"repeated observations captured {len(repeated)}x: possible dedupe leak")

    errors = [a for a in memory.recent_actions(limit=60) if a["kind"] == "job_error"]
    if len(errors) >= 5:
        findings.append(f"{len(errors)} job errors in the recent window; check feed/LLM health")

    pending = [d for d in memory.list_drafts(status="pending") if d["kind"] in ("report", "article")]
    stale = [d for d in pending if (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(d["created_ts"].replace("Z", "+00:00"))).days >= 21]
    if stale:
        findings.append(f"{len(stale)} draft(s) awaiting owner review for 21+ days")

    seen = memory.kv_get("seen_items", {})
    if isinstance(seen, dict) and len(seen) > 5000:
        findings.append(f"seen_items index at {len(seen)} keys; compaction due")

    spend = memory.llm_spend(since_hours=24 * 7)
    if spend["cost_usd"] > 20:
        findings.append(f"7d LLM spend ${spend['cost_usd']:.2f} exceeds comfort threshold")

    summary = "; ".join(findings) if findings else "healthy"
    memory.kv_set("last_health", {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "findings": findings})
    memory.record_action("health", summary)
    return findings


def backup_data(context: dict[str, Any], keep: int = 5) -> str:
    """Consistent sqlite snapshot into data/backups/, newest `keep` retained."""
    memory: Memory = context["memory"]
    backups_dir = memory.path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = backups_dir / f"memory-{stamp}.db"
    dest_conn = __import__("sqlite3").connect(dest)
    with dest_conn:
        memory.conn.backup(dest_conn)
    dest_conn.close()
    existing = sorted(backups_dir.glob("memory-*.db"))
    for old in existing[:-keep]:
        old.unlink()
    memory.record_action("backup", f"{dest.name} (kept {min(len(existing), keep)})")
    return str(dest)


def compact_memory(context: dict[str, Any]) -> None:
    config = context["config"]
    memory: Memory = context["memory"]
    llm = context.get("llm")
    maintenance = config.get("maintenance") or {}
    retention_days = int(maintenance.get("observation_retention_days", 45))
    min_batch = int(maintenance.get("compact_min_batch", 20))
    if llm is None:
        raise RuntimeError("llm client missing; cannot compact safely")

    cutoff = _cutoff_iso(retention_days)
    candidates = memory.compact_candidates(before_ts=cutoff)
    if len(candidates) < min_batch:
        memory.record_action("compact", f"nothing to do ({len(candidates)} below batch {min_batch})")
        return

    lines = "\n".join(f"- [{r['source']}] {r['text'][:140]}" for r in candidates[:200])
    system = (
        "You are a precise archivist. Compress these old reading notes into at most "
        "five durable facts or patterns worth keeping long-term. Drop anything "
        "time-sensitive, repetitive or trivial."
    )
    user = f"Notes to compress ({len(candidates)} items):\n{lines}\n\nReply with JSON only: {{\"archive\": [\"max 5 bullets\"]}}"
    raw = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        json_mode=True,
        temperature=0.2,
    )
    try:
        archive = [str(x) for x in json.loads(raw).get("archive", [])][:5]
        assert archive
    except (json.JSONDecodeError, AssertionError):
        raise RuntimeError(f"compaction returned invalid JSON: {raw[:200]}")

    period_from = candidates[0]["ts"][:10]
    period_to = candidates[-1]["ts"][:10]
    body = "\n".join(f"- {x}" for x in archive)
    archive_id = memory.record_observation(
        "archive",
        body,
        meta={"compressed": len(candidates), "period": [period_from, period_to]},
    )
    deleted = memory.delete_observations([r["id"] for r in candidates])
    memory.record_action("compact", f"{deleted} raw -> archive #{archive_id} ({period_from}..{period_to})")

    if llm is not None:
        try:
            from .memory_store import maintenance_cleanup

            result = maintenance_cleanup(memory, config)
            if result["rows_after"] or result["duplicates_removed"]:
                memory.record_action(
                    "compact",
                    f"semantic index: {result['rows_after']} rows "
                    f"({result['duplicates_removed']} dupes, {result['over_limit_removed']} over cap)",
                )
        except Exception:  # noqa: BLE001
            pass
