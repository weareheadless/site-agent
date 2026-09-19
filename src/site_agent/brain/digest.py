"""digest.py — daily learning pass.

She reads what her senses gathered and distills it: what mattered today,
which themes are recurring. This is the light version of Ada's
wake->observe->consider loop, scoped to one job.
"""

from __future__ import annotations

import json
from typing import Any

LEARN_EXCLUDE_SOURCES = ("self", "learning")


def _prompt(persona: str, observations: list[dict[str, Any]]) -> list[dict[str, str]]:
    lines = []
    for row in observations:
        meta = row.get("meta") or {}
        link = f" ({meta['link']})" if meta.get("link") else ""
        lines.append(f"- [{row['source']}] {row['text']}{link}")
    system = (
        persona
        + "\n\nYou just finished your daily reading. Distill what actually matters "
        "for this website and its audience. Ignore fluff, memes and moderation posts."
    )
    user = (
        "Here is what you read today:\n"
        + "\n".join(lines)
        + "\n\nReply with JSON only: {\"learned\": [\"one insight per string, max 5\"], "
          "\"themes\": [\"recurring topics, max 6\"], "
          "\"audience_needs\": [\"needs expressed or evidenced by readers, max 5\"], "
          "\"trends\": [\"recurring or emerging signals, max 5\"]}. "
          "Keep needs and trends cautious and grounded in the reading; never invent demographics or demand."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def learn(context: dict[str, Any]) -> None:
    memory = context["memory"]
    llm = context.get("llm")
    last_id = int(memory.kv_get("learned_until_id", 0) or 0)
    rows = [
        r
        for r in memory.recent_observations(limit=60)
        if r["id"] > last_id and r["source"] not in LEARN_EXCLUDE_SOURCES
    ]
    if not rows:
        memory.record_action("learn", "nothing new to learn")
        return
    if llm is None:
        raise RuntimeError("llm client missing; cannot run learning pass")

    persona = context.get("persona_prompt") or ""
    raw = llm.chat(_prompt(persona, list(reversed(rows))), json_mode=True, temperature=0.4)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"learning pass returned invalid JSON: {raw[:200]}")

    learned = [str(x) for x in (parsed.get("learned") or [])][:5]
    themes = [str(x) for x in (parsed.get("themes") or [])][:6]
    audience_needs = [str(x) for x in (parsed.get("audience_needs") or [])][:5]
    trends = [str(x) for x in (parsed.get("trends") or [])][:5]
    body = "\n".join(f"- {item}" for item in learned) or "(nothing worth recording)"
    memory.record_observation(
        "learning",
        body,
        meta={
            "themes": themes,
            "audience_needs": audience_needs,
            "trends": trends,
            "from_id": min(r["id"] for r in rows),
            "to_id": max(r["id"] for r in rows),
        },
    )
    if themes:
        previous = memory.kv_get("themes", [])
        merged = list(dict.fromkeys([*themes, *previous]))[:12]
        memory.kv_set("themes", merged)
    for key, values, limit in (
        ("audience_needs", audience_needs, 12),
        ("trends", trends, 12),
    ):
        if values:
            previous = memory.kv_get(key, [])
            previous = previous if isinstance(previous, list) else []
            memory.kv_set(key, list(dict.fromkeys([*values, *previous]))[:limit])
    memory.kv_set("learned_until_id", max(r["id"] for r in rows))
    memory.record_action(
        "learn",
        f"{len(learned)} insights, {len(audience_needs)} audience needs, "
        f"{len(trends)} trends from {len(rows)} items",
    )
