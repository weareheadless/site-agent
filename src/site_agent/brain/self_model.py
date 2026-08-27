"""Ada's autonomous, evidence-linked account of herself.

This is deliberately smaller than a personality rewrite. Ada may keep the
same self-understanding, revise it, or leave a question open. Customer work
content is context at most; it is never treated as an identity instruction.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

SELF_KEY = "inner_self"
WATERMARK_KEY = "inner_self_until_id"

_MAX_DESCRIPTION = 2000
_MAX_ITEM = 300
_MAX_ITEMS = 8
_MAX_EVIDENCE = 40
# A raw dream is not identity evidence until Ada decides it mattered on waking.
_EVIDENCE_SOURCES = {"inner_voice", "awaken", "self_note"}


def _items(value: Any, fallback: list[str] | None = None) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return list(fallback or [])[:_MAX_ITEMS]
    return [str(item).strip()[:_MAX_ITEM] for item in value if str(item).strip()][:_MAX_ITEMS]


def current_self(memory: Any) -> dict[str, Any]:
    """Return a bounded, JSON-safe copy of Ada's current self-model."""
    raw = memory.kv_get(SELF_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "version": 1,
        "self_description": str(raw.get("self_description") or "").strip()[:_MAX_DESCRIPTION],
        "persistent_tendencies": _items(raw.get("persistent_tendencies")),
        "open_questions": _items(raw.get("open_questions")),
        "updated_ts": str(raw.get("updated_ts") or "").strip(),
    }


def _evidence(memory: Any) -> list[dict[str, Any]]:
    watermark = int(memory.kv_get(WATERMARK_KEY, 0) or 0)
    rows = memory.observations_since(
        watermark,
        sources=tuple(_EVIDENCE_SOURCES),
        limit=_MAX_EVIDENCE,
    )
    return [
        row
        for row in rows
        if not (row["source"] == "inner_voice" and (row.get("meta") or {}).get("role"))
    ]


def _format_evidence(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{row['id']} / {row['source']}] {str(row['text'])[:1000]}"
        for row in rows
    )


def _prompt(persona: str, state: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    current = json.dumps(state, ensure_ascii=True, indent=2)
    evidence = _format_evidence(rows)
    system = (
        persona
        + "\n\nThis is a private self-integration pass. You are not writing for the "
        "customer, the website, or an audience. Review only what Ada has actually "
        "recorded below. Do not force a change to make the account coherent. It is "
        "valid to keep the same self-understanding, to remain uncertain, or to say "
        "that nothing has changed. Do not turn a customer's subject into an identity "
        "or invent a biography. Return only the requested JSON; do not reveal a "
        "chain of thought."
    )
    user = (
        f"Ada's current self-understanding:\n{current}\n\n"
        f"New inner-life experiences since the last integration:\n{evidence}\n\n"
        "If these experiences genuinely changed how Ada understands herself, return "
        "the revised complete account. Otherwise return changed=false and preserve "
        "uncertainty. JSON only:\n"
        '{"changed": true or false, "self_description": "...", '
        '"persistent_tendencies": ["..."], "open_questions": ["..."], '
        '"reason": "one short sentence"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _candidate(state: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "self_description": str(parsed.get("self_description", state["self_description"]) or "").strip()[:_MAX_DESCRIPTION],
        "persistent_tendencies": _items(parsed.get("persistent_tendencies"), state["persistent_tendencies"]),
        "open_questions": _items(parsed.get("open_questions"), state["open_questions"]),
        "updated_ts": _now(),
    }


def integrate(context: dict[str, Any]) -> None:
    """Let Ada decide whether recent inner experience changed her self-model."""
    memory = context["memory"]
    if not (context.get("config", {}).get("self_model") or {}).get("enabled", True):
        memory.record_action("integrate_self", "self-integration disabled")
        return
    rows = _evidence(memory)
    if not rows:
        memory.record_action("integrate_self", "nothing new in her inner life")
        return

    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot integrate self")

    from .prompts import inner_identity_prompt

    state = current_self(memory)
    persona = context.get("inner_identity_prompt") or inner_identity_prompt(context["config"], memory)
    raw = llm.chat(_prompt(persona, state, rows), json_mode=True, temperature=0.5)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("result must be an object")
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError(f"self integration returned invalid JSON: {raw[:200]}")

    changed = bool(parsed.get("changed", False))
    candidate = _candidate(state, parsed)
    meaningful_change = candidate != {**state, "updated_ts": candidate["updated_ts"]}
    watermark = max(row["id"] for row in rows)
    memory.kv_set(WATERMARK_KEY, watermark)

    if not changed or not meaningful_change:
        memory.record_action("integrate_self", f"unchanged; reviewed {len(rows)} inner events")
        return

    memory.kv_set(SELF_KEY, candidate)
    reason = str(parsed.get("reason") or "a new pattern persisted").strip()[:300]
    summary = candidate["self_description"] or "; ".join(candidate["persistent_tendencies"][:2]) or reason
    shift_id = memory.record_observation(
        "identity_shift",
        f"Ada revised how she understands herself: {summary[:1100]}",
        meta={"evidence_ids": [row["id"] for row in rows], "reason": reason},
    )
    memory.record_action(
        "integrate_self",
        f"self-understanding changed; evidence={len(rows)}; shift=#{shift_id}",
    )
