"""reflect.py — periodic self-reflection on her own voice.

The light port of Ada's personality-evolution loop: instead of silently
rewriting herself, she proposes voice adjustments and the owner approves
them (a draft of kind 'reflection'). Approved notes are merged into the
persona prompt at runtime.
"""

from __future__ import annotations

import json
from typing import Any

from ..brain.prompts import memory_context


def _prompt(persona: str, outputs: str, context_block: str) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nYou are reviewing your own recent work. Reflect: is your voice "
        "consistent? Are you repeating yourself? Are you serving this site's "
        "audience or drifting? Be honest and specific."
    )
    user = (
        f"Your recent writing:\n{outputs}\n\n"
        f"Recent context:\n{context_block}\n\n"
        "Reply with JSON only: {\"voice_notes\": [\"max 4 concrete voice/content rules for yourself\"], "
        "\"avoid\": [\"max 3 things to stop doing\"]}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def approved_notes(memory: Any) -> dict[str, list[str]]:
    return memory.kv_get("persona_notes", {"voice_notes": [], "avoid": []})


def reflect(context: dict[str, Any]) -> int:
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot reflect")

    persona = context.get("persona_prompt") or ""
    drafts = [
        d for d in memory.list_drafts(limit=20)
        if d["kind"] in ("article", "report", "reflection", "summary")
    ][:6]
    outputs = "\n\n---\n\n".join(
        f"[{d['kind']}] {d['title']}\n{d['body'][:1500]}" for d in drafts
    ) or "(no output yet)"

    raw = llm.chat(_prompt(persona, outputs, memory_context(memory)), json_mode=True, temperature=0.5)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"reflection returned invalid JSON: {raw[:200]}")

    proposal = {
        "voice_notes": [str(x) for x in (parsed.get("voice_notes") or [])][:4],
        "avoid": [str(x) for x in (parsed.get("avoid") or [])][:3],
    }
    draft_id = memory.save_draft(
        title="Self-reflection: proposed voice adjustments",
        body=json.dumps(proposal, indent=2),
        kind="reflection",
        meta=proposal,
    )
    memory.record_action("reflect", f"proposal draft #{draft_id}")
    return draft_id


def effective_persona(config: dict[str, Any], memory: Any) -> str:
    """Persona prompt plus owner-approved reflection notes."""
    from ..brain.prompts import persona_prompt

    base = persona_prompt(config)
    notes = approved_notes(memory)
    extras = [str(n) for n in (notes.get("voice_notes") or []) if n]
    avoid = [str(n) for n in (notes.get("avoid") or []) if n]
    lines = []
    if extras:
        lines += ["", "Voice notes you gave yourself and the owner approved:", *[f"- {n}" for n in extras]]
    if avoid:
        lines += ["", "Stop doing:", *[f"- {n}" for n in avoid]]
    return base + "\n".join(lines)


def approve_reflection(memory: Any, draft_id: int) -> bool:
    drafts = {d["id"]: d for d in memory.list_drafts()}
    draft = drafts.get(draft_id)
    if not draft or draft["kind"] != "reflection" or draft["status"] == "approved":
        return False
    try:
        proposal = json.loads(draft["body"])
    except json.JSONDecodeError:
        return False
    current = approved_notes(memory)
    merged = {
        "voice_notes": list(dict.fromkeys([*proposal.get("voice_notes", []), *current.get("voice_notes", [])]))[:8],
        "avoid": list(dict.fromkeys([*proposal.get("avoid", []), *current.get("avoid", [])]))[:6],
    }
    memory.kv_set("persona_notes", merged)
    memory.update_draft_status(draft_id, "approved")
    memory.record_action("persona_update", f"notes merged from draft #{draft_id}")
    return True
