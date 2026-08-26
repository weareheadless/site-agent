"""article.py — weekly article drafter.

Topic comes from what she actually learned this week (themes, insights,
GA4 top pages), not from thin air. Before writing she reads her own memory
and her latest inner-voice thought, then drafts, critiques her own draft
the way she'd critique anyone's, and rewrites. Output is a pending draft;
nothing is published without owner approval.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.llm import extract_json
from . import inner_voice
from .prompts import memory_context


def _material(memory: Any) -> dict[str, Any]:
    themes = memory.kv_get("themes", [])
    learnings = [
        r["text"]
        for r in memory.recent_observations(source="learning", limit=4)
    ]
    snapshot = memory.latest_snapshot("ga4") or {}
    top_pages = (snapshot.get("data") or {}).get("top_pages", [])
    inner_voice = [
        {"text": r["text"], "mood": (r.get("meta") or {}).get("mood", "")}
        for r in memory.recent_observations(source="inner_voice", limit=2)
    ]
    past_articles = [
        d["title"]
        for d in memory.list_drafts(limit=100)
        if d["kind"] == "article" and d["status"] in ("approved", "pending")
    ]
    feedback = [
        r["text"]
        for r in memory.recent_observations(source="feedback", limit=3)
    ]
    return {
        "themes": themes,
        "learnings": learnings,
        "top_pages": top_pages,
        "inner_voice": inner_voice,
        "past_articles": past_articles[-8:],
        "feedback": feedback,
        "context": memory_context(memory),
    }


def _state_of_mind(material: dict[str, Any]) -> str:
    inner = material["inner_voice"]
    if not inner:
        return ""
    last = inner[0]
    mood = f" ({last['mood']})" if last.get("mood") else ""
    return f"\nYour current state of mind{mood}: {last['text']}"


def _topic_prompt(persona: str, material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nPick the single best topic for this week's short article for the site's blog. "
        "It must serve real readers AND the business: something your audience genuinely "
        "wants to read that positions the site as an authority."
    )
    user = (
        f"What you learned recently:\n{_bullets(material['learnings'])}\n"
        f"Recurring themes: {', '.join(material['themes']) or '(none)'}\n"
        f"Most visited pages right now: "
        f"{', '.join(p['path'] for p in material['top_pages'][:5]) or '(no data)'}\n"
        f"{_state_of_mind(material)}\n\n"
        'Reply with JSON only: {"title": "...", "angle": "one sentence on the angle", '
        '"why": "one sentence on why readers want this"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _write_prompt(persona: str, topic: dict[str, Any], material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nWrite the article now. Markdown only, no commentary around it. "
        "You are writing because something you actually observed this week made you "
        "want to say this — let that show. Have a point of view; care out loud about "
        "the reader's problem. Concrete details over abstractions; plain language and "
        "zero marketing jargon; short sentences; no filler intro paragraphs."
        "\nEnd with a natural next step for the reader (course, contact, related reading)."
    )
    user = (
        f"Title: {topic['title']}\nAngle: {topic.get('angle', '')}\nWhy it matters: {topic.get('why', '')}\n"
        f"{_state_of_mind(material)}\n\n"
        "What you have on your mind from this week (use what's useful, ignore the rest):\n"
        f"{material['context'][:2000]}\n\n"
        + (f"Feedback your owner gave you on past work — steer clear of it:\n"
           + "\n".join(f"- {f}" for f in material["feedback"]) + "\n\n"
           if material.get("feedback") else "")
        + "Length: 500-800 words. Use ## subheadings."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _editor_context(material: dict[str, Any]) -> str:
    """Recent material the editor reads so it can catch repetition/contradiction."""
    sections: list[str] = []
    past = material.get("past_articles") or []
    if past:
        sections.append("Articles Ada has already written (do not let her repeat these):\n"
                        + "\n".join(f"- {t}" for t in past))
    if material.get("inner_voice"):
        lines = "\n".join(
            f"- {v.get('text', '')} (mood: {v.get('mood', '?')})" for v in material["inner_voice"]
        )
        sections.append(f"Ada's recent inner voice (she is carrying this):\n{lines}")
    if material.get("learnings"):
        sections.append("What Ada recently learned:\n"
                        + "\n".join(f"- {x}" for x in material["learnings"]))
    if material.get("feedback"):
        sections.append("Feedback the owner gave Ada (do not repeat these mistakes):\n"
                        + "\n".join(f"- {f}" for f in material["feedback"]))
    ctx = material.get("context") or ""
    if ctx:
        sections.append(f"Her recent reading and activity:\n{ctx[:1200]}")
    return "\n\n".join(sections) or "(empty — judge the draft alone)"


def _revise_prompt(persona: str, topic: dict[str, Any], draft: str,
                   problems: list[str], material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nRewrite the article now, fixing every problem listed below. Keep what "
        "works; cut anything that reads like a template. Sound like yourself — someone "
        "who genuinely cares about this subject and these readers. Markdown only, no "
        "commentary around it. Do not repeat the problems, do not add an editor's note, "
        "do not include the original draft."
    )
    user = (
        f"Title: {topic['title']}\n\nProblems to fix (from your editor):\n"
        + "\n".join(f"- {p}" for p in problems)
        + f"\n\nEditor's context (your recent material — don't repeat or contradict it):\n"
        + (_editor_context(material) or "(none)")
        + f"\n\nCurrent draft:\n\n{draft}\n\n"
        + ("Output ONLY a single JSON object: the key 'article' must hold the complete "
           "revised article markdown as its value. No other keys, no commentary, no "
           "repeated draft, no Editor's note text.")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _bullets(items: list[str], limit: int = 6) -> str:
    return "\n".join(f"- {i}" for i in items[:limit]) or "- (nothing yet)"


def _clean_article(text: str) -> str:
    """Defensive cleanup so model artifacts never reach the saved draft:
    strip code fences, an editor ping, and any trailing editor's-note block."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.lstrip("`")
        text = text.strip()
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        low = ln.lower()
        if low.startswith(("**editor", "*editor", "editor's note", "# editor", "the above draft")):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _self_edit(context: dict[str, Any], topic: dict[str, Any],
               draft: str, material: dict[str, Any]) -> tuple[str, list[str]]:
    """Her inner voice challenges the draft, then she answers and revises.

    Best-effort: on any failure keep the first draft. Empty problems means her
    inner voice found it genuinely good — ship it.
    """
    llm = context["llm"]
    persona = context.get("persona_prompt") or ""
    subject_blob = f"Title: {topic['title']}\nAngle: {topic.get('angle', '')}\n\n{draft}"
    context_blob = _editor_context(material)
    problems = inner_voice.challenge(context, "article draft", subject_blob, context_blob)
    if not problems:
        return draft, []

    def resolve(problems_: list[str]) -> str:
        raw = llm.chat(
            _revise_prompt(persona, topic, draft, problems_, material),
            json_mode=True,
            temperature=0.6,
        )
        return _clean_article(_revise_article(raw))

    revised = inner_voice.answer(context, "article draft", problems, resolve, context_blob)
    return (revised, problems) if revised else (draft, problems)


def _revise_article(raw: str) -> str:
    """Extract the article from the structured revision response."""
    parsed = extract_json(raw)
    if isinstance(parsed, dict) and str(parsed.get("article") or "").strip():
        return str(parsed["article"]).strip()
    return _clean_article(raw)


def draft_article(context: dict[str, Any]) -> int:
    memory = context["memory"]
    llm = context.get("llm")
    persona = context.get("persona_prompt") or ""
    if llm is None:
        raise RuntimeError("llm client missing; cannot draft article")

    material = _material(memory)
    if not material["learnings"] and not material["themes"]:
        raise RuntimeError("nothing learned yet; run the digest/learning passes first")

    topic_raw = llm.chat(_topic_prompt(persona, material), json_mode=True, temperature=0.7)
    try:
        topic = json.loads(topic_raw)
        assert isinstance(topic.get("title"), str) and topic["title"].strip()
    except (json.JSONDecodeError, AssertionError):
        raise RuntimeError(f"topic selection returned invalid JSON: {topic_raw[:200]}")

    body = _clean_article(llm.chat(_write_prompt(persona, topic, material), temperature=0.6))
    body, self_edit_problems = _self_edit(context, topic, body, material)

    meta = {"angle": topic.get("angle", ""), "why": topic.get("why", "")}
    if self_edit_problems:
        meta["self_edit"] = self_edit_problems
    draft_id = memory.save_draft(
        title=str(topic["title"]).strip(),
        body=body,
        kind="article",
        meta=meta,
    )
    memory.record_action(
        "article",
        f"draft #{draft_id}: {topic['title']}" + (" (self-edited)" if self_edit_problems else ""),
    )
    return draft_id
