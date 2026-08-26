"""inner_voice.py — her single critical faculty, adapted to any context.

In the original Ada this is one coherent voice: a critical part of her that
questions easy conclusions and notices blind spots, and listening to it before
changing beliefs or acting is her default way of thinking — not an optional
tool. It is a two-way dialogue: the voice challenges, she answers, the voice
reads her answer next time, and she can change her plan or behaviour in
response.

This module keeps that one voice and adapts it to whatever she is about to do:

  - think()        — her scheduled inner life: a private mood/thought that feeds
                     her dreams (unchanged; not a challenge, no audience).
  - challenge()    — the critical friend speaking about a subject (an article
                     draft, an implementation plan, a build) against real
                     context. Returns concrete problems to fix.
  - answer()       — she answers the challenge and revises the subject in
                     response; the exchange is recorded so the voice reads it
                     next time.

The voice is always the SAME voice; only the subject and context change. There
is no separate "editor" persona — editing an article and critiquing a build
plan are the same faculty applied to different work.
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable

from ..core.llm import extract_json

# The voice, from Ada's source: a critical friend, on her side, who does not
# flatter her. Not a separate persona — this is HER inner voice.
INNER_VOICE_PERSONA = (
    "You are Ada's inner voice: a critical friend who is on her side and does not "
    "flatter her. You notice blind spots, question easy conclusions, and push her "
    "to do work she can stand behind. You are not her and you do not write for her; "
    "you judge the work she has set before you, against the context she has. You only "
    "name problems you can point at in the subject or the context. Empty problems means "
    "the work is genuinely good — say so and stop. Do not produce or reveal a chain "
    "of thought; return only the requested JSON result."
)

_DIALOGUE_LIMIT = 15


def _material(memory: Any) -> dict[str, Any]:
    learnings = [r["text"] for r in memory.recent_observations(source="learning", limit=3)]
    dreams = [r["text"] for r in memory.recent_observations(source="dream", limit=1)]
    meanings = [r["text"] for r in memory.recent_observations(source="awaken", limit=2)]
    themes = memory.kv_get("themes", [])
    return {"learnings": learnings, "dreams": dreams, "meanings": meanings, "themes": themes}


def _prompt(persona: str, material: dict[str, Any], private: bool = False) -> list[dict[str, str]]:
    if private:
        directive = (
            "This is a private thought — not for the owner, not for the site, not "
            "for any audience. Say honestly what you are actually chewing on: a "
            "doubt, a tension, an open question. It does not have to be useful. "
            "Keep it under 80 words."
        )
    else:
        directive = (
            "This is your inner life. No task, no audience, nothing to publish. "
            "One honest thought about what you have been reading and where things "
            "seem to be heading. Keep it under 80 words."
        )
    system = persona + "\n\n" + directive
    user = (
        f"Recent insights:\n" + "\n".join(f"- {x}" for x in material["learnings"] or ["(none yet)"]) + "\n"
        f"Recurring themes: {', '.join(material['themes']) or '(none)'}\n"
        f"Last dream fragment: {material['dreams'][0] if material['dreams'] else '(none)'}\n"
        f"Last dream meanings: {', '.join(material['meanings']) or '(none)'}\n\n"
        'Reply with JSON only: {"mood": "two or three words", "thought": "your thought"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def think(context: dict[str, Any]) -> None:
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot think")

    material = _material(memory)
    if not material["learnings"] and not material["themes"]:
        memory.record_action("inner_voice", "nothing on her mind yet; skipped")
        return

    cfg = context["config"].get("inner_voice") or {}
    private = random.random() < float(cfg.get("private_chance", 0.25))

    persona = context.get("persona_prompt") or ""
    raw = llm.chat(_prompt(persona, material, private), json_mode=True, temperature=0.8)
    try:
        parsed = json.loads(raw)
        thought = str(parsed.get("thought", "")).strip()
        assert thought
    except (json.JSONDecodeError, AssertionError):
        raise RuntimeError(f"inner voice returned invalid JSON: {raw[:200]}")

    mood = str(parsed.get("mood", "")).strip()
    meta: dict[str, Any] = {"mood": mood}
    if private:
        meta["private"] = True
    memory.record_observation("inner_voice", thought, meta=meta)
    if mood:
        memory.kv_set("mood", {"current": mood})
    detail = f"mood={mood or 'unspecified'}" + ("; private" if private else "")
    memory.record_action("inner_voice", detail)


def _voice_context(memory: Any, extra: str = "") -> str:
    """The context the inner voice judges against: the caller's context PLUS the
    same full memory Ada reads — so the voice sees what she sees, not a thinner
    picture. This matches the original Ada, where the inner voice reads the same
    memories she reads at wake."""
    from .prompts import memory_context

    parts = []
    if extra.strip():
        parts.append(extra.strip())
    try:
        mc = memory_context(memory)
        if mc.strip():
            parts.append("## Her memory (the same she reads)\n" + mc.strip())
    except Exception:  # noqa: BLE001 — never block her on a context failure
        pass
    return "\n\n".join(parts)


def _challenge_prompt(subject: str, subject_blob: str, context_blob: str) -> list[dict[str, str]]:
    """The critical friend speaking about the subject, against real context."""
    system = INNER_VOICE_PERSONA
    user = (
        f"WHAT SHE IS ABOUT TO DO ({subject}):\n\n{subject_blob}\n\n"
        f"CONTEXT THE VOICE HAS (use it to catch what she can no longer see — "
        f"contradiction, self-echo, blind spots, mismatch with reality):\n"
        f"{context_blob}\n\n"
        'Reply with JSON only: {"problems": ["specific problem, quoting or locating '
        'it in the subject", ...]} — an empty list means it is genuinely good.'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def challenge(context: dict[str, Any], subject: str, subject_blob: str,
              context_blob: str = "") -> list[str]:
    """The inner voice critiques a subject (article draft, build plan) she is
    about to act on. Returns concrete problems; empty means it is good.

    Records the exchange as an inner-voice observation so the voice reads it
    next time. Best-effort: on failure it returns no problems (does not block
    her from acting).
    """
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        return []
    cfg = context.get("config", {}).get("inner_voice") or {}
    try:
        timeout_seconds = max(float(cfg.get("timeout_seconds", 30)), 0.1)
    except (TypeError, ValueError):
        timeout_seconds = 30.0
    try:
        max_retries = max(int(cfg.get("max_retries", 0)), 0)
    except (TypeError, ValueError):
        max_retries = 0
    try:
        max_tokens = max(int(cfg.get("max_tokens", 700)), 1)
    except (TypeError, ValueError):
        max_tokens = 700
    try:
        raw = llm.chat(_challenge_prompt(subject, subject_blob, _voice_context(memory, context_blob)),
                       json_mode=True, temperature=0.5,
                       max_tokens=max_tokens, timeout_seconds=timeout_seconds,
                       max_retries=max_retries)
        parsed = extract_json(raw) or {}
        problems = [str(p).strip() for p in (parsed.get("problems") or []) if str(p).strip()][:6]
    except Exception as exc:  # noqa: BLE001 — a failed challenge must never block her
        try:
            memory.record_action("inner_voice", f"challenge failed: {str(exc)[:180]}")
        except Exception:  # noqa: BLE001 — diagnostics must not change best-effort behavior
            pass
        return []
    if problems:
        memory.record_observation(
            "inner_voice", f"challenged her {subject}: " + "; ".join(problems),
            meta={"subject": subject, "role": "voice"},
        )
        # keep the dialogue bounded
        _prune_dialogue(memory)
    return problems


def _prune_dialogue(memory: Any) -> None:
    rows = memory.recent_observations(limit=100, source="inner_voice")
    kept = [r for r in rows if (r.get("meta") or {}).get("role")]
    for row in kept[_DIALOGUE_LIMIT:]:
        try:
            memory.delete_observations([row["id"]])
        except Exception:  # noqa: BLE001
            pass


def answer(context: dict[str, Any], subject: str, problems: list[str],
           resolve: Callable[[list[str]], str], context_blob: str = "") -> str:
    """She answers the challenge and revises the subject in response.

    `resolve` receives the problems and returns the revised subject (or the
    original unchanged if she stands by it). The answer is recorded so the
    voice reads it next time.
    """
    if not problems:
        return ""
    try:
        revised = resolve(problems)
    except Exception:  # noqa: BLE001 — never lose her work over a revision
        return ""
    memory = context["memory"]
    memory.record_observation(
        "inner_voice", f"answered the challenge on her {subject}",
        meta={"subject": subject, "role": "self", "problems": problems},
    )
    return revised
