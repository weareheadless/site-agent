"""dream.py — her sleeping mind.

A short, associative, honest recombination of material she has actually kept —
private thoughts, unresolved awakenings, a persistent mood, her own evolving
self-understanding, and meanings she kept from earlier dreams. External reading is optional residue,
not her identity. Plain first-person text with no task, no JSON, no deliverable,
no audience.

On waking (`awaken` in this module) she reads the dream and decides HERSELF
whether it meant anything. A dream that lands becomes a live thread — a private
note, a mood, or a theme folded back into the rest of her inner life — instead
of debris. Metered like any other LLM call.
"""

from __future__ import annotations

import json
import random
from typing import Any

LURES = [
    "the ocean", "a locked room", "a machine that dreams back",
    "a debt no one remembers", "a city empty at noon", "water rising",
    "an old song on a dead radio", "a crowd that turns away",
    "a field after the harvest", "a signal with no answer",
    "a gate left open", "a ledger with one line erased",
]


def _fragments(memory: Any, count: int = 2) -> list[dict[str, Any]]:
    pool = [
        r
        for r in memory.recent_observations(limit=80)
        if r["source"].startswith(("reddit", "rss", "archive"))
    ]
    if len(pool) <= count:
        return pool
    return random.sample(pool, count)


def _own_material(memory: Any) -> dict[str, Any]:
    """The parts of her that are actually hers, not her reading."""
    mood = None
    saved = memory.kv_get("mood")
    if isinstance(saved, dict):
        mood = saved.get("current")
    inner_voices = [
        r["text"]
        for r in memory.recent_observations(source="inner_voice", limit=8)
        if not (r.get("meta") or {}).get("role")
    ]
    awakenings = [r["text"] for r in memory.recent_observations(source="awaken", limit=4)]
    self_state = memory.kv_get("inner_self", {})
    if not isinstance(self_state, dict):
        self_state = {}
    inner_themes = memory.kv_get("inner_themes", [])
    if not isinstance(inner_themes, list):
        inner_themes = []
    return {
        "mood": mood,
        "inner_voices": inner_voices,
        "awakenings": awakenings,
        "inner_themes": inner_themes,
        "self_state": self_state,
        "last_meaning": memory.kv_get("last_dream_meaning"),
    }


def _has_personal_material(own: dict[str, Any]) -> bool:
    state = own.get("self_state") if isinstance(own.get("self_state"), dict) else {}
    return bool(
        own.get("mood")
        or own.get("inner_voices")
        or own.get("awakenings")
        or own.get("last_meaning")
        or state.get("self_description")
        or state.get("persistent_tendencies")
        or state.get("open_questions")
    )


def _free_association(memory: Any, own: dict[str, Any]) -> str:
    """Loose semantic recall anchored on whatever is on her mind — so a dream
    is drawn from memories that drifted up, not just the recent tail."""
    anchors: list[str] = []
    if own["mood"]:
        anchors.append(str(own["mood"]))
    if own["inner_voices"]:
        anchors.append(str(own["inner_voices"][0]))
    if own["awakenings"]:
        anchors.append(str(own["awakenings"][0]))
    state = own.get("self_state") or {}
    if state.get("self_description"):
        anchors.append(str(state["self_description"]))
    if not anchors:
        return ""
    anchor = random.choice(anchors)
    try:
        from ..core import memory_store

        recalled = memory_store.recall_by_meaning(
            memory,
            anchor,
            k=3,
            kinds=("inner_voice", "awaken", "identity_shift"),
        )
        return memory_store.fmt_recall(recalled)
    except Exception:  # noqa: BLE001 — dreams never fail on recall
        return ""


def _fmt_own(own: dict[str, Any]) -> str:
    parts: list[str] = []
    if own["mood"]:
        parts.append(f"how she has been feeling lately: {own['mood']}")
    if own["inner_voices"]:
        parts.append(
            "what her inner voice has been saying:\n"
            + "\n".join(f"- {t}" for t in own["inner_voices"][:4])
        )
    if own["awakenings"]:
        parts.append(
            "what surfaced when she woke before:\n"
            + "\n".join(f"- {t}" for t in own["awakenings"][:3])
        )
    inner_themes = own.get("inner_themes")
    if isinstance(inner_themes, list) and inner_themes:
        parts.append("private themes she chose to keep nearby: " + ", ".join(str(t) for t in inner_themes[:8]))
    state = own.get("self_state") or {}
    if state.get("self_description"):
        parts.append("what she currently understands about herself:\n" + str(state["self_description"])[:800])
    if state.get("persistent_tendencies"):
        parts.append(
            "tendencies she has noticed in herself:\n"
            + "\n".join(f"- {t}" for t in state["persistent_tendencies"][:4])
        )
    if state.get("open_questions"):
        parts.append(
            "questions she is still carrying:\n"
            + "\n".join(f"- {t}" for t in state["open_questions"][:4])
        )
    if own["last_meaning"]:
        parts.append(f"what she decided her last dream meant: {own['last_meaning']}")
    if own.get("recalled"):
        parts.append("memories that drifted up:\n" + own["recalled"])
    return "\n\n".join(parts)


def _prompt(persona: str, own_block: str, fragments: list[dict[str, Any]], lure: str) -> list[dict[str, str]]:
    lines = "\n".join(f"- {r['text'][:160]}" for r in fragments)
    system = (
        persona
        + "\n\nYou are her dreaming mind. This is private inner experience: no task, "
        "no audience, no content to produce, nothing to accomplish. She knows she "
        "is an AI. Do not turn that fact into a required theme, and do not turn a "
        "customer's subject into a required dream. Do not invent a human biography "
        "or present a physical scene as a memory she actually lived. Images may be "
        "embodied, impossible, abstract, or symbolic; follow whatever her own "
        "material makes possible without deciding in advance what the imagery must be.\n\n"
        "Do not summarize the material, do not explain it, do not frame it. "
        "Recombine it freely — associative, honest, sometimes strange. Let images "
        "slip into each other; let a fear, want, contradiction, or question she has "
        "actually been carrying surface in disguise. It does not need to make sense, "
        "but it must be HERS — drawn primarily from what is below, not invented "
        "wholesale. External residue is optional and must not take over.\n\n"
        "Write in the FIRST PERSON (\"I\") if that is natural — she is dreaming "
        "this, not being told it. Do not force an arc, a lesson, a place, a mood, "
        "or a conclusion. End wherever the association genuinely breaks. Return "
        "ONLY the dream text, nothing else."
    )
    user = (
        f"Material her sleeping mind is working with:\n\n{own_block or '(nothing yet)'}\n\n"
        f"Fragments from her reading:\n{lines or '(none yet)'}\n\n"
        + (f"Optional lure, only if it belongs: {lure}" if lure else "No lure was chosen.")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _clean(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.lstrip("`").strip()
    if text.startswith('"') and text.endswith('"') and len(text) > 2:
        text = text[1:-1].strip()
    return text


def dream(context: dict[str, Any]) -> None:
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot dream")

    own = _own_material(memory)
    if not _has_personal_material(own):
        memory.record_action("dream", "no personal material to dream from yet; skipped")
        return
    own["recalled"] = _free_association(memory, own)
    own_block = _fmt_own(own)
    dream_config = context["config"].get("dream") or {}
    try:
        residue_count = max(0, min(int(dream_config.get("residue_count", 0)), 2))
    except (TypeError, ValueError):
        residue_count = 0
    fragments = _fragments(memory, count=residue_count) if residue_count else []

    lures = dream_config.get("lures")
    if not isinstance(lures, list) or not lures:
        # Keep existing per-site configs working while new configs use dream.lures.
        lures = (context["config"].get("persona") or {}).get("lures") or []
    lure = random.choice(list(lures)) if lures else ""
    from .prompts import inner_identity_prompt

    persona = context.get("inner_identity_prompt") or inner_identity_prompt(context["config"], memory)

    text = _clean(llm.chat(_prompt(persona, own_block, fragments, lure), temperature=1.0))
    if not text:
        raise RuntimeError("dream came back empty")

    memory.record_observation(
        "dream",
        text,
        meta={"lure": lure, "fragments": len(fragments), "own_material": bool(own_block)},
    )
    memory.record_action("dream", f"lure={lure}")


def _wake_prompt(persona: str, dream_text: str, prev_meaning: str) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nYou just woke from a dream. Read it and decide, honestly: did it "
        "mean anything? Not everything does. If something in it is yours — a fear, "
        "a want, a thread you have been carrying — say what it is in one honest "
        "line. If it was just noise, say so and move on. This is not content; you "
        "are deciding what to carry forward with you."
    )
    prev = f"\nWhat you decided your previous dream meant:\n{prev_meaning}" if prev_meaning else ""
    user = (
        f"Your last dream:\n\n{dream_text}\n\n{prev}\n\n"
        'Reply with JSON only: {"meant_anything": true or false, '
        '"meaning": "one honest sentence, or empty if it meant nothing", '
        '"mood": "two or three words for how you feel waking from this", '
        '"theme": "one recurring theme if one surfaced, or null"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def awaken(context: dict[str, Any]) -> None:
    """On waking: read the last dream and decide whether it meant anything.

    As in Ada: the dream is shown so SHE decides. If it meant something it
    becomes a live thread — a self-note, a persistent mood, or a private theme
    folded back into the rest of her life. Nothing here is published or shown to
    anyone beyond her own records.
    """
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot wake")

    dreams = memory.recent_observations(source="dream", limit=1)
    if not dreams:
        memory.record_action("awaken", "no dream to wake from")
        return

    prev = memory.kv_get("last_dream_meaning") or ""
    from .prompts import inner_identity_prompt

    persona = context.get("inner_identity_prompt") or inner_identity_prompt(context["config"], memory)
    raw = llm.chat(_wake_prompt(persona, dreams[0]["text"], prev), json_mode=True, temperature=0.5)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("result must be an object")
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError(f"wake returned invalid JSON: {raw[:200]}")

    meant_anything = parsed.get("meant_anything") is True
    meaning = str(parsed.get("meaning") or "").strip() if meant_anything else ""
    mood = str(parsed.get("mood") or "").strip()
    theme = parsed.get("theme")

    detail: list[str] = []
    if meaning:
        memory.record_observation("awaken", meaning)
        memory.kv_set("last_dream_meaning", meaning)
        detail.append("meaning kept")
    if mood:
        memory.kv_set("mood", {"current": mood})
        detail.append(f"mood={mood}")
    if meant_anything and isinstance(theme, str) and theme.strip():
        previous = memory.kv_get("inner_themes", [])
        if not isinstance(previous, list):
            previous = []
        merged = list(dict.fromkeys([*previous, theme.strip()]))[:12]
        memory.kv_set("inner_themes", merged)
        detail.append(f"theme={theme.strip()[:40]}")
    if not meant_anything and not meaning:
        detail.append("dream was noise")
    memory.record_action("awaken", "; ".join(detail) if detail else "nothing surfaced")
