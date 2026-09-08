"""strategist.py — ranked suggestions from real signals, feeding the report.

Combines GA4 + GSC snapshots and her article history into up to three
concrete next moves. These are the "cards" the weekly report presents;
they are not a separate dashboard.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..application.actions import OwnerActionService
from ..core.contracts import ActionPriority, ActionRequirement, OwnerAction
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
    active_initiatives = [
        initiative
        for initiative in memory.list_strategy_initiatives(limit=100)
        if initiative.get("state") not in {"declined", "completed"}
    ]
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
        "active_monthly_initiatives": active_initiatives[:12],
    }


def _prompt(persona: str, material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nYou are reviewing this site's numbers to pick the highest-value next "
        "moves. Be concrete and honest; if the data is thin, say what you'd do "
        "anyway and why. No vanity suggestions. A next move may also be something "
        "you have been carrying — a learnings thread or a dream that kept meaning "
        "something — if it genuinely serves the site. Monthly SEO initiatives below "
        "are the durable strategy; monitor them and suggest follow-ups rather than "
        "inventing a competing paid research plan."
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


def _card_text(card: dict[str, Any], key: str, *, required: bool, max_chars: int) -> str | None:
    value = card.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if required and not value:
        return None
    return value[:max_chars] if value else ""


def _normalize_cards(raw: str) -> list[dict[str, str]]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"strategist returned invalid JSON: {raw[:200]}") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("cards"), list):
        raise RuntimeError(f"strategist returned invalid cards: {raw[:200]}")

    cards: list[dict[str, str]] = []
    for candidate in decoded["cards"]:
        if not isinstance(candidate, dict):
            continue
        title = _card_text(candidate, "title", required=True, max_chars=200)
        action = _card_text(candidate, "action", required=True, max_chars=500)
        why = _card_text(candidate, "why", required=False, max_chars=500)
        origin = _card_text(candidate, "from", required=False, max_chars=120)
        if title is None or action is None or why is None or origin is None:
            continue
        cards.append({"title": title, "action": action, "why": why, "from": origin})
        if len(cards) == 3:
            break
    if not cards:
        raise RuntimeError(f"strategist returned no valid cards: {raw[:200]}")
    return cards


def _card_action(card: dict[str, str], action_service: OwnerActionService) -> OwnerAction:
    title = card["title"]
    action = card["action"]
    source_ref = "strategist:" + hashlib.sha256(f"{title}\0{action}".encode()).hexdigest()[:16]
    return action_service.create(
        OwnerAction(
            capability_id="content.suggestion",
            provider_id="site-agent",
            title=title,
            summary=action,
            action_label="Ask Ada to help",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref=source_ref,
            dedupe_key=source_ref,
            payload={"why": card["why"], "from": card["from"], "source": "strategist_cards"},
        ),
        reuse_terminal=True,
    )


def run(context: dict[str, Any]) -> int:
    memory: Any = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot strategize")
    material = gather(memory)
    persona = context.get("persona_prompt") or ""
    raw = llm.chat(_prompt(persona, material), json_mode=True, temperature=0.5)
    cards = _normalize_cards(raw)

    action_service = context.get("owner_action_service") or OwnerActionService(memory)
    for card in cards:
        _card_action(card, action_service)

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
