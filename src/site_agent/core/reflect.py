"""reflect.py — periodic self-reflection on her own voice.

The light port of Ada's personality-evolution loop: instead of silently
rewriting herself, she proposes voice adjustments and the owner approves
them (a draft of kind 'reflection'). Approved notes are merged into the
persona prompt at runtime.
"""

from __future__ import annotations

import json
import hashlib
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
    value = memory.kv_get("persona_notes", {"voice_notes": [], "avoid": []})
    return {
        "voice_notes": [str(item) for item in (value.get("voice_notes") or []) if str(item).strip()],
        "avoid": [str(item) for item in (value.get("avoid") or []) if str(item).strip()],
    }


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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
        "voice_notes": [str(x).strip() for x in (parsed.get("voice_notes") or []) if str(x).strip()][:4],
        "avoid": [str(x).strip() for x in (parsed.get("avoid") or []) if str(x).strip()][:3],
    }
    current = approved_notes(memory)
    review_package = {"kind": "ada_writing_guidance", "before": current, "after": proposal, "existingContentAffected": False}
    draft_id = memory.save_draft(
        title="Self-reflection: proposed voice adjustments",
        body=json.dumps(proposal, indent=2),
        kind="reflection",
        meta={"proposal": proposal, "base_hash": _digest(current), "review_package_hash": _digest(review_package)},
    )
    memory.record_action("reflect", f"proposal draft #{draft_id}")
    return draft_id


def effective_persona(config: dict[str, Any], memory: Any) -> str:
    """Persona prompt plus owner-approved reflection notes."""
    from ..brain.prompts import work_persona_prompt

    base = work_persona_prompt(config, memory)
    notes = approved_notes(memory)
    extras = [str(n) for n in (notes.get("voice_notes") or []) if n]
    avoid = [str(n) for n in (notes.get("avoid") or []) if n]
    lines = []
    if extras:
        lines += ["", "Voice notes you gave yourself and the owner approved:", *[f"- {n}" for n in extras]]
    if avoid:
        lines += ["", "Stop doing:", *[f"- {n}" for n in avoid]]
    return base + "\n".join(lines)


def approve_reflection(memory: Any, draft_id: int, review_package_hash: str) -> bool:
    drafts = {d["id"]: d for d in memory.list_drafts()}
    draft = drafts.get(draft_id)
    if not draft or draft["kind"] != "reflection" or draft["status"] != "pending":
        return False
    meta = draft.get("meta") if isinstance(draft.get("meta"), dict) else {}
    proposal = meta.get("proposal") if isinstance(meta.get("proposal"), dict) else None
    expected = str(meta.get("review_package_hash") or "")
    current = approved_notes(memory)
    package = {"kind": "ada_writing_guidance", "before": current, "after": proposal, "existingContentAffected": False}
    if not proposal or not expected or expected != review_package_hash or _digest(current) != meta.get("base_hash") or _digest(package) != expected:
        return False
    merged = {
        "voice_notes": list(dict.fromkeys([*proposal.get("voice_notes", []), *current.get("voice_notes", [])]))[:8],
        "avoid": list(dict.fromkeys([*proposal.get("avoid", []), *current.get("avoid", [])]))[:6],
    }
    memory.kv_set("persona_notes", merged)
    memory.update_draft_status(draft_id, "approved")
    memory.record_action("persona_update", f"notes merged from draft #{draft_id}")
    return True
