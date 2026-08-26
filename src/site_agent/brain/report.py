"""report.py — the weekly plain-language report (HERO feature).

One markdown artifact an owner will actually read: what happened on their
site, in human sentences. Saved as a draft so it goes through approval like
everything else she writes.
"""

from __future__ import annotations

import datetime
from typing import Any

from .prompts import memory_context, report_date_range


def _prompt(persona: str, start: str, end: str, context_block: str, strategist_cards: str = "") -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nWrite this site owner's weekly report. Plain language, no jargon, "
        "no flattery, no emoji spam. Short paragraphs. Be concrete with numbers. "
        "If something did badly, say so plainly and say what you plan to do about it."
    )
    cards_section = (
        f"\n\n{strategist_cards}\nWeave your top card into the suggestions section naturally.\n"
        if strategist_cards
        else ""
    )
    user = (
        f"Week covered: {start} to {end}.\n\n"
        "Here is everything you know from that week:\n\n"
        f"{context_block}\n{cards_section}\n\n"
        "Write a markdown report with exactly these sections:\n"
        "# This week on your site\n"
        "## What happened (traffic, plain sentences)\n"
        "## What I read and learned (from your niche's communities)\n"
        "## What I suggest next (max 3, most valuable first)\n"
        "Keep it under 350 words."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def weekly_report(context: dict[str, Any]) -> int:
    memory = context["memory"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("llm client missing; cannot write report")

    config = context["config"]
    start, end = report_date_range(memory)
    persona = context.get("persona_prompt") or ""
    context_block = memory_context(memory)
    from .strategist import cards_block

    raw = llm.chat(_prompt(persona, start, end, context_block, cards_block(memory)), temperature=0.5)
    title = f"Weekly report {start} → {end}"
    draft_id = memory.save_draft(
        title=title,
        body=raw,
        kind="report",
        meta={"week_start": start, "week_end": end},
    )
    memory.kv_set("last_report_ts", datetime.datetime.now(datetime.timezone.utc).isoformat())
    memory.record_action("report", f"draft #{draft_id}: {title}")
    del config
    return draft_id
