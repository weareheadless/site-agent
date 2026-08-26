"""strategist.py — ranked suggestions from real signals, feeding the report.

Combines GA4 + GSC snapshots and her article history into up to three
concrete next moves. These are the "cards" the weekly report presents;
they are not a separate dashboard.
"""

from __future__ import annotations

import json
from typing import Any

from .prompts import memory_context


def gather(memory: Any) -> dict[str, Any]:
    ga = (memory.latest_snapshot("ga4") or {}).get("data", {})
    gsc = (memory.latest_snapshot("gsc") or {}).get("data", {})
    articles = [d for d in memory.list_drafts(limit=100) if d["kind"] == "article"]
    published = [
        {"title": d["title"], "approved_on": d["updated_ts"][:10]}
        for d in articles
        if d["status"] == "approved"
    ]
    pending = [{"title": d["title"]} for d in articles if d["status"] == "pending"]
    search_queries = gsc.get("top_queries", [])
    if not search_queries:
        search_queries = ga.get("organic_queries", [])
    dreams = memory.recent_observations(source="dream", limit=1)
    self_notes = [r["text"] for r in memory.recent_observations(source="awaken", limit=2)]
    themes = memory.kv_get("themes", [])
    anchor = ""
    if themes and isinstance(themes, list) and themes:
        anchor = str(themes[0])
    elif search_queries:
        anchor = str(getattr(search_queries[0], "get", lambda *_a, **_k: "")("query", ""))
    recalled: list[dict[str, Any]] = []
    if anchor:
        try:
            from ..core import memory_store

            recalled = memory_store.recall_by_meaning(memory, anchor, k=4)
        except Exception:  # noqa: BLE001 — strategy must not fail on recall
            pass
    return {
        "traffic": ga,
        "search_queries": search_queries,
        "query_source": "gsc" if search_queries and gsc.get("top_queries") else ("ga4-gsc-link" if search_queries else "none"),
        "published_articles": published[:10],
        "pending_articles": pending,
        "themes": themes,
        "dream": dreams[0]["text"] if dreams else "",
        "dream_meaning": memory.kv_get("last_dream_meaning") or "",
        "inner_voice": [r["text"] for r in memory.recent_observations(source="inner_voice", limit=2)],
        "self_notes": self_notes,
        "recalled": recalled,
    }


def _prompt(persona: str, material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nYou are reviewing this site's numbers to pick the highest-value next "
        "moves. Be concrete and honest; if the data is thin, say what you'd do "
        "anyway and why. No vanity suggestions. A next move may also be something "
        "you have been carrying — a learnings thread or a dream that kept meaning "
        "something — if it genuinely serves the site."
    )
    carried: list[str] = []
    if material["dream"]:
        carried.append(f"your last dream: {material['dream'][:400]}")
    if material["dream_meaning"]:
        carried.append(f"what you decided it meant: {material['dream_meaning']}")
    if material["inner_voice"]:
        carried.append("your inner voice:\n" + "\n".join(f"- {t}" for t in material["inner_voice"]))
    if material["self_notes"]:
        carried.append("notes you left yourself:\n" + "\n".join(f"- {t}" for t in material["self_notes"]))
    if material.get("recalled"):
        try:
            from ..core import memory_store

            carried.append("what your memory surfaces about this:\n" + memory_store.fmt_recall(material["recalled"]))
        except Exception:  # noqa: BLE001
            pass
    carried_block = "\n".join(carried) if carried else ""
    user = (
        f"Signals:\n{json.dumps(material, default=str)[:2500]}\n\n"
        + (f"Carried into this — use what is useful, ignore the rest:\n{carried_block}\n\n" if carried_block else "")
        + 'Reply with JSON only: {"cards": [{"title": "...", "action": "one concrete step", '
        '"why": "the expected payoff", "from": "optional: which thread this came from '
        '(traffic, a learning, a dream, a mood)"}], max 3, best first}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def run(context: dict[str, Any]) -> int:
    memory: Any = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot strategize")
    material = gather(memory)
    persona = context.get("persona_prompt") or ""
    raw = llm.chat(_prompt(persona, material), json_mode=True, temperature=0.5)
    try:
        cards = [c for c in json.loads(raw).get("cards", []) if isinstance(c, dict)][:3]
        assert cards
    except (json.JSONDecodeError, AssertionError):
        raise RuntimeError(f"strategist returned invalid JSON: {raw[:200]}")

    memory.kv_set(
        "strategist_cards",
        {"generated_for_week_of": material["traffic"].get("period"), "cards": cards},
    )
    titles = "; ".join(str(c.get("title", ""))[:40] for c in cards)
    memory.record_action("strategy", f"{len(cards)} cards: {titles}")
    return len(cards)


def cards_block(memory: Any) -> str:
    """Rendered for inclusion in the weekly report prompt."""
    stored = memory.kv_get("strategist_cards") or {}
    cards = stored.get("cards") or []
    if not cards:
        return ""
    lines = []
    for c in cards:
        origin = f" (from: {c['from']})" if c.get("from") else ""
        lines.append(f"- {c.get('title', '?')}: {c.get('action', '')}{origin} ({c.get('why', '')})")
    return "Your prepared strategist cards (ranked):\n" + "\n".join(lines)
