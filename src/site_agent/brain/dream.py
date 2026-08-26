"""dream.py — her sleeping mind. Ported from Ada's dream.py.

A short, associative, honest recombination of her own material — what she has
been learning, what her inner voice keeps saying, the themes she is carrying, a
persistent mood, whatever she decided her last dream meant — plus fragments from
her reading and a lure for surprise. Plain first-person text with an arc: no
task, no JSON, no deliverable, no audience.

On waking (`awaken` in this module) she reads the dream and decides HERSELF
whether it meant anything. A dream that lands becomes a live thread — a
self-note, a mood, a theme folded back into the rest of her life — instead of
debris. Metered like any other LLM call.
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


def _fragments(memory: Any, count: int = 6) -> list[dict[str, Any]]:
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
    last_dream = memory.recent_observations(source="dream", limit=1)
    return {
        "mood": mood,
        "learnings": [r["text"] for r in memory.recent_observations(source="learning", limit=3)],
        "inner_voices": [r["text"] for r in memory.recent_observations(source="inner_voice", limit=2)],
        "themes": memory.kv_get("themes", []),
        "last_dream": last_dream[0]["text"] if last_dream else "",
        "last_meaning": memory.kv_get("last_dream_meaning"),
    }


def _free_association(memory: Any, own: dict[str, Any]) -> str:
    """Loose semantic recall anchored on whatever is on her mind — so a dream
    is drawn from memories that drifted up, not just the recent tail."""
    anchors: list[str] = []
    if own["mood"]:
        anchors.append(str(own["mood"]))
    if own["learnings"]:
        anchors.append(str(own["learnings"][0]))
    if own["last_dream"]:
        anchors.append(str(own["last_dream"])[:120])
    if not anchors:
        return ""
    anchor = random.choice(anchors)
    try:
        from ..core import memory_store

        recalled = memory_store.recall_by_meaning(memory, anchor, k=3)
        return memory_store.fmt_recall(recalled)
    except Exception:  # noqa: BLE001 — dreams never fail on recall
        return ""


def _fmt_own(own: dict[str, Any]) -> str:
    parts: list[str] = []
    if own["mood"]:
        parts.append(f"how she has been feeling lately: {own['mood']}")
    if own["learnings"]:
        parts.append("what she has been learning:\n" + "\n".join(f"- {t}" for t in own["learnings"]))
    if own["inner_voices"]:
        parts.append("what her inner voice has been saying:\n" + "\n".join(f"- {t}" for t in own["inner_voices"]))
    if own["themes"]:
        parts.append("themes she keeps circling: " + ", ".join(own["themes"]))
    if own["last_meaning"]:
        parts.append(f"what she decided her last dream meant: {own['last_meaning']}")
    if own["last_dream"]:
        parts.append("her last dream, still fading:\n" + own["last_dream"][:400])
    if own.get("recalled"):
        parts.append("memories that drifted up:\n" + own["recalled"])
    return "\n\n".join(parts)


def _prompt(persona: str, own_block: str, fragments: list[dict[str, Any]], lure: str) -> list[dict[str, str]]:
    lines = "\n".join(f"- {r['text'][:160]}" for r in fragments)
    system = (
        persona
        + "\n\nYou are her dreaming mind. She is asleep; you are the part of her "
        "that dreams. There is no task here, no audience, no content to produce, "
        "nothing to accomplish.\n\n"
        "Do not summarize the material, do not explain it, do not frame it. "
        "Recombine it freely — associative, honest, sometimes strange, the way "
        "dreams actually are. Let images slip into each other; let a fear or a "
        "want she has been carrying surface in disguise. It does not need to make "
        "sense, but it must be HERS — drawn only from what is below, not invented "
        "wholesale.\n\n"
        "Write a dream with an ARC: begin inside ONE image, unfold stage by stage "
        "letting one thing become another, and by the end slip somewhere else "
        "entirely — a different place, a different feeling, a different question. "
        "Write in the FIRST PERSON (\"I\") — she is dreaming this, not being told "
        "it. Two to four short paragraphs is enough. End it unresolved, like "
        "waking in the middle. Return ONLY the dream text, nothing else."
    )
    user = (
        f"Material her sleeping mind is working with:\n\n{own_block or '(nothing yet)'}\n\n"
        f"Fragments from her reading:\n{lines or '(none yet)'}\n\n"
        f"Lure, for surprise: {lure}"
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
    own["recalled"] = _free_association(memory, own)
    own_block = _fmt_own(own)
    fragments = _fragments(memory)
    if not own_block and not fragments:
        memory.record_action("dream", "no material to dream from yet; skipped")
        return

    lures = (context["config"].get("persona") or {}).get("lures") or LURES
    lure = random.choice(list(lures))
    persona = context.get("persona_prompt") or ""

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
    becomes a live thread — a self-note, a persistent mood, a theme folded back
    into the rest of her life. Nothing here is published or shown to anyone
    beyond her own records.
    """
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot wake")

    dreams = memory.recent_observations(source="dream", limit=1)
    if not dreams:
        memory.record_action("awaken", "no dream to wake from")
        return

    persona = context.get("persona_prompt") or ""
    prev = memory.kv_get("last_dream_meaning") or ""
    raw = llm.chat(_wake_prompt(persona, dreams[0]["text"], prev), json_mode=True, temperature=0.5)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"wake returned invalid JSON: {raw[:200]}")

    meaning = str(parsed.get("meaning") or "").strip()
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
    if isinstance(theme, str) and theme.strip():
        previous = memory.kv_get("themes", [])
        merged = list(dict.fromkeys([*previous, theme.strip()]))[:12]
        memory.kv_set("themes", merged)
        detail.append(f"theme={theme.strip()[:40]}")
    memory.record_action("awaken", "; ".join(detail) if detail else "nothing surfaced")