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


def _material(memory: Any, research_report: dict[str, Any] | None = None) -> dict[str, Any]:
    article_research = (
        research_report
        if isinstance(research_report, dict) and "article_research_note" in research_report
        else {}
    )
    themes = memory.kv_get("themes", [])
    audience_needs = memory.kv_get("audience_needs", [])
    audience_questions = memory.kv_get("audience_questions", [])
    trends = memory.kv_get("trends", [])
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
    news = []
    for row in memory.recent_observations(limit=30):
        if row.get("source") in {"self", "inner_voice", "dream", "awaken", "identity_shift"}:
            continue
        link = str((row.get("meta") or {}).get("link") or "")
        if link.startswith(("http://", "https://")):
            news.append({
                "source": row.get("source", ""),
                "text": str(row.get("text") or "")[:700],
                "url": link,
                "observed_at": row.get("ts", ""),
            })
    research_signals = []
    try:
        research_signals = [
            {
                "kind": str(item.get("kind") or ""),
                "summary": str(item.get("summary") or "")[:700],
                "confidence": item.get("confidence"),
            }
            for item in memory.list_incubation_insights(limit=8)
            if str(item.get("summary") or "").strip()
        ]
    except Exception:  # noqa: BLE001 - article drafting remains useful without incubation tables
        research_signals = []
    return {
        "themes": themes,
        "audience_needs": audience_needs if isinstance(audience_needs, list) else [],
        "audience_questions": audience_questions if isinstance(audience_questions, list) else [],
        "trends": trends if isinstance(trends, list) else [],
        "learnings": learnings,
        "top_pages": top_pages,
        "inner_voice": inner_voice,
        "past_articles": past_articles[-8:],
        "feedback": feedback,
        "news": news[:12],
        "research_signals": research_signals,
        "seo_research": (research_report or {}) if not article_research else {},
        "article_research": article_research,
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
        + "\n\nPick the single best topic for this week's short article for the site's blog. Start with a "
        "real reader question or decision and its underlying constraint, not a keyword or a summary of your "
        "research. It must serve real readers AND the business: something your audience genuinely wants to read "
        "that positions the site as an authority. Search interest can inform the framing, but it must not replace "
        "the reader's need. State what this business can credibly clarify and flag technical distinctions that "
        "need evidence or owner review."
    )
    user = (
        f"What you learned recently:\n{_bullets(material['learnings'])}\n"
        f"Recurring themes: {', '.join(material['themes']) or '(none)'}\n"
        f"Audience needs Ada noticed: {', '.join(material.get('audience_needs', [])[:6]) or '(none)'}\n"
        f"Questions readers actually asked or tried to answer: "
        f"{'; '.join(material.get('audience_questions', [])[:6]) or '(none)'}\n"
        f"Emerging trends Ada noticed: {', '.join(material.get('trends', [])[:6]) or '(none)'}\n"
        f"Most visited pages right now: "
        f"{', '.join(p['path'] for p in material['top_pages'][:5]) or '(no data)'}\n"
        f"{_state_of_mind(material)}\n\n"
        'Reply with JSON only: {"title": "...", "angle": "one sentence on the angle", '
        '"why": "one sentence on why readers want this", "reader_question": "...", '
        '"reader_situation": "...", "reader_intent": "...", "business_relevance": "...", '
        '"market_context": "...", "expert_angle": "...", "expertise_basis": ["..."], '
        '"technical_watchouts": ["..."], '
        '"scope_boundaries": ["..."]}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _write_prompt(persona: str, topic: dict[str, Any], material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nWrite the article now. Markdown only, no commentary around it. "
        "You are answering a real reader question from the stated business's credible point of view, not "
        "writing a report about your research. Use research to ground the answer, but do not narrate the research "
        "process or turn a keyword into the premise. Something observed this week may give the article urgency, "
        "but the reader's decision remains the center. Have a point of view; care out loud about the reader's "
        "problem. Concrete details over abstractions; plain language and zero marketing jargon; short sentences; "
        "no filler intro paragraphs."
        "\nTechnical integrity rules: use the owner's confirmed knowledge and supplied evidence before general model "
        "knowledge. Do not invent procedures, diagnoses, standards, credentials, outcomes, or first-hand experience. "
        "Do not create a false opposition between two valid options just to make a stronger headline. If a term, "
        "claim, or distinction is marked uncertain or needs verification, qualify it, explain the relevant conditions, "
        "or leave it out rather than guessing. Respect the reader's vocabulary without silently treating it as the "
        "professional vocabulary."
        "\nEnd with a natural next step for the reader (course, contact, related reading)."
    )
    feedback_block = (
        "Feedback your owner gave you on past work — steer clear of it:\n"
        + "\n".join(f"- {item}" for item in material["feedback"])
        + "\n\n"
        if material.get("feedback") else ""
    )
    news_block = (
        "Fresh news and source material (use only if it genuinely helps; do not invent details):\n"
        + "\n".join(f"- {item.get('text', '')} ({item.get('url', '')})" for item in material.get("news", [])[:8])
        + "\n\n"
        if material.get("news") else ""
    )
    signal_block = (
        "Evidence-linked research signals (inferred, not owner-confirmed facts):\n"
        + "\n".join(
            f"- [{item.get('kind', 'signal')}] {item.get('summary', '')}"
            for item in material.get("research_signals", [])[:8]
        )
        + "\n\n"
        if material.get("research_signals") else ""
    )
    seo_block = (
        "SEO research evidence:\n" + json.dumps(material.get("seo_research") or {}, default=str)[:8000] + "\n\n"
        if material.get("seo_research") else ""
    )
    article_research = material.get("article_research")
    research_note_block = (
        "Editorial research note (support the original idea; do not optimize for density or replace its topic):\n"
        + json.dumps(article_research, default=str)[:8000]
        + "\n\n"
        if article_research else ""
    )
    target_language = topic.get("language") or "the site's configured language"
    target_market = topic.get("market") or "the site's configured market"
    base = (
        f"Title: {topic['title']}\nAngle: {topic.get('angle', '')}\nWhy it matters: {topic.get('why', '')}\n"
        f"Target language: {target_language}\n"
        f"Target market: {target_market}\n"
        f"Primary keyword: {topic.get('primary_keyword', '')}\n"
        "\nEditorial brief (the reader and the expert position come before SEO):\n"
        f"Reader question: {topic.get('reader_question', '')}\n"
        f"Reader situation and stakes: {topic.get('reader_situation', '')}\n"
        f"Reader intent or decision: {topic.get('reader_intent', '')}\n"
        f"Why this matters to the business: {topic.get('business_relevance', '')}\n"
        f"Market context and decision environment: {topic.get('market_context', '')}\n"
        f"Credible expert angle: {topic.get('expert_angle', '')}\n"
        f"Expertise basis: {json.dumps(topic.get('expertise_basis') or [], ensure_ascii=False, default=str)}\n"
        f"Technical watchouts: {json.dumps(topic.get('technical_watchouts') or [], ensure_ascii=False, default=str)}\n"
        f"Terminology notes: {json.dumps(topic.get('terminology_notes') or [], ensure_ascii=False, default=str)}\n"
        f"Technical claims to verify: {json.dumps(topic.get('technical_claims_to_verify') or [], ensure_ascii=False, default=str)}\n"
        f"Scope boundaries: {json.dumps(topic.get('scope_boundaries') or [], ensure_ascii=False, default=str)}\n"
        f"Misconceptions to avoid: {json.dumps(topic.get('misconceptions_to_avoid') or [], ensure_ascii=False, default=str)}\n"
        f"Question-to-research fit: {topic.get('question_fit', '')}\n"
        f"Search-demand interpretation: {topic.get('demand_interpretation', '')}\n"
        f"{_state_of_mind(material)}\n\n"
        "What you have on your mind from this week (use what's useful, ignore the rest):\n"
        f"{material['context'][:2000]}\n\n"
    )
    user = base + feedback_block + news_block + signal_block + seo_block + research_note_block + (
        "Write for the stated reader question, situation, and thesis. Use research terminology only when natural; "
        "translate between reader and professional vocabulary when needed, do not force the seed into the title "
        "or headings, and do not use keyword density targets.\n\n"
        if article_research else ""
    ) + (
        "Length: 500-800 words. Use ## subheadings. Do not repeat the article title as a heading; "
        "the site template renders it."
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


def _editorial_brief(topic: dict[str, Any]) -> dict[str, Any]:
    """Normalize the brief used by both legacy and research-led article paths.

    Older manually supplied briefs do not have the newer reader/expertise
    fields.  They remain draftable, but the writer gets an honest fallback
    rather than an empty-looking prompt; the paid research path validates these
    fields before it ever reaches here.
    """
    result = dict(topic)
    result["reader_question"] = str(
        result.get("reader_question") or result.get("why") or result.get("angle") or ""
    ).strip()
    result["reader_situation"] = str(
        result.get("reader_situation") or result.get("why") or ""
    ).strip()
    result["reader_intent"] = str(
        result.get("reader_intent") or result.get("reader_question") or ""
    ).strip()
    result["business_relevance"] = str(
        result.get("business_relevance") or result.get("why") or ""
    ).strip()
    result["market_context"] = str(result.get("market_context") or "").strip()
    result["expert_angle"] = str(
        result.get("expert_angle") or result.get("angle") or ""
    ).strip()
    for key in (
        "expertise_basis", "technical_watchouts", "scope_boundaries",
        "terminology_notes", "technical_claims_to_verify", "misconceptions_to_avoid",
    ):
        value = result.get(key)
        result[key] = value if isinstance(value, list) else []
    result["question_fit"] = str(result.get("question_fit") or "").strip()
    result["demand_interpretation"] = str(result.get("demand_interpretation") or "").strip()
    return result


def draft_article(
    context: dict[str, Any],
    article_brief: dict[str, Any] | None = None,
    research_report: dict[str, Any] | None = None,
) -> int:
    memory = context["memory"]
    llm = context.get("llm")
    persona = context.get("persona_prompt") or ""
    if llm is None:
        raise RuntimeError("llm client missing; cannot draft article")

    material = _material(memory, research_report)
    if not material["learnings"] and not material["themes"] and not article_brief:
        raise RuntimeError("nothing learned yet; run the digest/learning passes first")

    if article_brief is not None:
        topic = dict(article_brief)
        if not isinstance(topic.get("title"), str) or not topic["title"].strip():
            raise RuntimeError("strategy article brief has no title")
    else:
        topic_raw = llm.chat(_topic_prompt(persona, material), json_mode=True, temperature=0.7)
        try:
            topic = json.loads(topic_raw)
            assert isinstance(topic.get("title"), str) and topic["title"].strip()
        except (json.JSONDecodeError, AssertionError):
            raise RuntimeError(f"topic selection returned invalid JSON: {topic_raw[:200]}")
    topic = _editorial_brief(topic)

    body = _clean_article(llm.chat(_write_prompt(persona, topic, material), temperature=0.6))
    body, self_edit_problems = _self_edit(context, topic, body, material)

    meta = {"angle": topic.get("angle", ""), "why": topic.get("why", "")}
    meta["editorial_brief"] = {
        key: topic.get(key)
        for key in (
            "reader_question", "reader_situation", "reader_intent", "business_relevance", "market_context", "expert_angle",
            "expertise_basis", "technical_watchouts", "terminology_notes", "technical_claims_to_verify",
            "scope_boundaries", "misconceptions_to_avoid", "question_fit", "demand_interpretation",
        )
        if topic.get(key)
    }
    if article_brief is not None:
        meta["seo_strategy"] = {
            "research_report_id": topic.get("research_report_id", ""),
            "strategy_cycle_id": topic.get("strategy_cycle_id"),
            "primary_keyword": topic.get("primary_keyword", ""),
            "language": topic.get("language", ""),
            "market": topic.get("market", ""),
            "source_urls": topic.get("source_urls", []),
        }
    if topic.get("article_idea_id") is not None:
        meta["article_research"] = {
            "article_idea_id": topic.get("article_idea_id"),
            "keyword_research_run_id": topic.get("keyword_research_run_id"),
            "serp_research_run_id": topic.get("serp_research_run_id"),
            "research_decision": topic.get("research_decision", "keep"),
            "research_cost_micros": topic.get("research_cost_micros"),
            "origin": topic.get("origin", ""),
            "source_urls": topic.get("source_urls", []),
        }
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


def draft_article_for_strategy(
    context: dict[str, Any],
    article_brief: dict[str, Any],
    research_report: dict[str, Any],
) -> int:
    """Prepare one owner-reviewable article from a completed SEO strategy."""
    return draft_article(context, article_brief=article_brief, research_report=research_report)


def draft_article_for_idea(
    context: dict[str, Any],
    idea: dict[str, Any],
    research_note: dict[str, Any],
    related_keywords: list[Any] | None = None,
    serp_evidence: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
) -> int:
    """Draft once from the persisted audience hypothesis and compact research note."""
    decision = str(research_note.get("decision") or "keep")
    title = str(research_note.get("reframed_title") or idea.get("working_title") or "").strip()
    topic = {
        "title": title,
        "angle": str(research_note.get("reframed_thesis") or idea.get("thesis") or "").strip(),
        "why": str(idea.get("audience_need") or idea.get("why_now") or "").strip(),
        "reader_question": str(research_note.get("reader_question") or idea.get("reader_question") or "").strip(),
        "reader_situation": str(idea.get("reader_situation") or "").strip(),
        "reader_intent": str(idea.get("reader_intent") or "").strip(),
        "business_relevance": str(idea.get("business_relevance") or "").strip(),
        "market_context": str(research_note.get("market_context") or idea.get("market_context") or "").strip(),
        "expert_angle": str(research_note.get("expert_angle") or idea.get("expert_angle") or "").strip(),
        "expertise_basis": idea.get("expertise_basis") or [],
        "technical_watchouts": idea.get("technical_watchouts") or [],
        "terminology_notes": research_note.get("terminology_notes") or [],
        "technical_claims_to_verify": research_note.get("technical_claims_to_verify") or [],
        "scope_boundaries": research_note.get("scope_boundaries") or idea.get("scope_boundaries") or [],
        "misconceptions_to_avoid": research_note.get("misconceptions_to_avoid") or [],
        "question_fit": research_note.get("question_fit") or "",
        "demand_interpretation": research_note.get("demand_interpretation") or "",
        "language": idea.get("language", "en"),
        "market": idea.get("market", "US"),
        "source_urls": idea.get("source_urls", []),
        "article_idea_id": (lineage or {}).get("article_idea_id"),
        "keyword_research_run_id": (lineage or {}).get("keyword_research_run_id"),
        "serp_research_run_id": (lineage or {}).get("serp_research_run_id"),
        "research_decision": decision,
        "research_cost_micros": (lineage or {}).get("research_cost_micros"),
        "origin": idea.get("origin", ""),
        "primary_keyword": research_note.get("selected_query", ""),
    }
    if not title:
        raise RuntimeError("article idea has no working title")
    return draft_article(
        context,
        article_brief=topic,
        research_report={
            "article_research_note": research_note,
            "serp_evidence": serp_evidence or {},
            "related_keywords": (related_keywords or [])[:20],
        },
    )
