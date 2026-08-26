"""Ada's planning pass for implementation work.

Ada owns the plan. Her inner voice is a separate critic that receives the plan
after this module produces it and returns only concrete problems.
"""

from __future__ import annotations

from typing import Any

from ..core.llm import extract_json
from .prompts import memory_context


def _context(memory: Any, extra: str) -> str:
    parts = [extra.strip()] if extra.strip() else []
    if memory is not None:
        try:
            remembered = memory_context(memory)
            if remembered.strip():
                parts.append("## Ada's memory\n" + remembered.strip())
        except Exception:  # noqa: BLE001 — missing memory must not block planning
            pass
    return "\n\n".join(parts)


def _draft_prompt(persona: str, request: str, context_blob: str) -> list[dict[str, str]]:
    system = persona + (
        "\n\nYou are Ada, making the implementation plan for this website request. "
        "Use the owner's intent, your memory, the brand, and the site reference. "
        "Decide what should change and why before an execution agent edits files. "
        "Be concrete about structure, imagery, surfaces, motion, mobile behavior, "
        "accessibility, and the one subject-specific signature gesture when relevant. "
        "For important images, choose an image treatment, depth cue, motion behavior, "
        "and mobile fallback using the actual image analysis when available. For a "
        "redesign or flatness/monochrome request, reject a token-only plan and require "
        "meaningful changes to structure, imagery, and surfaces/materials. For every "
        "substantial redesign, state the signature gesture's connection, trigger, "
        "transformation, mobile fallback, and reduced-motion fallback. Infer whether "
        "this is an evolution or a first-principles direction; for the latter, plan a "
        "new DOM/composition and CSS architecture rather than incremental overrides. "
        "Do not write code and do not ask a clarification unless the request is "
        "materially impossible to interpret. Keep the plan under 200 words. Reply "
        'with JSON only: {"plan":"..."}'
    )
    user = (
        f"OWNER REQUEST:\n{request}\n\n"
        f"CONTEXT (brand, site reality, and Ada's memory):\n{context_blob}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _revise_prompt(persona: str, request: str, plan: str,
                   problems: list[str], context_blob: str) -> list[dict[str, str]]:
    system = persona + (
        "\n\nYou are Ada revising your own implementation plan after your inner "
        "voice found concrete problems. Fix every valid problem while preserving "
        "the plan's intent. Do not write code. Keep the revised plan under 200 "
        "words and reply with JSON only: {\"plan\":\"...\"}"
    )
    user = (
        f"OWNER REQUEST:\n{request}\n\n"
        f"CONTEXT:\n{context_blob}\n\n"
        f"YOUR CURRENT PLAN:\n{plan}\n\n"
        "INNER-VOICE CRITICISM:\n" + "\n".join(f"- {problem}" for problem in problems)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _plan(raw: str) -> str:
    parsed = extract_json(raw) or {}
    return str(parsed.get("plan") or "").strip()


def draft(context: dict[str, Any], request: str, context_blob: str = "",
          persona: str = "") -> str:
    """Have Ada make an implementation plan. Best-effort fallback is the request."""
    llm = context.get("llm")
    if llm is None:
        return request
    try:
        raw = llm.chat(
            _draft_prompt(persona or context.get("persona_prompt") or "Ada", request,
                          _context(context.get("memory"), context_blob)),
            json_mode=True,
            temperature=0.4,
        )
        return _plan(raw) or request
    except Exception:  # noqa: BLE001 — planning failure must not block execution
        return request


def revise(context: dict[str, Any], request: str, plan: str, problems: list[str],
           context_blob: str = "", persona: str = "") -> str:
    """Have Ada revise her plan after criticism. Falls back to the current plan."""
    if not problems:
        return plan
    llm = context.get("llm")
    if llm is None:
        return plan
    try:
        raw = llm.chat(
            _revise_prompt(persona or context.get("persona_prompt") or "Ada", request,
                           plan, problems, _context(context.get("memory"), context_blob)),
            json_mode=True,
            temperature=0.4,
        )
        return _plan(raw) or plan
    except Exception:  # noqa: BLE001 — revision failure must not block execution
        return plan
