"""Audience-led article selection and its two-stage paid research reconciliation.

Ada generates 5-10 grounded candidate queries from context. CrawlSEO measures
the exact candidates, Ada keeps or reframes one, CrawlSEO captures one bounded
SERP for the selected query, then Ada drafts. Search volume and SERP framing are
evidence, never a verdict and never a reason to replace the audience need.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..config import primary_research_locale
from ..application.growth_budget import GrowthBudgetBlocked, mark_paid_research_uncertain, release_paid_research, reserve_paid_research, settle_paid_research
from ..core.llm import extract_json
from . import article as brain_article


_ORIGINS = {"news", "audience_concern", "learning", "community_question"}
_DECISIONS = {"keep", "reframe", "editorial_despite_low_demand"}


def _request_not_dispatched(exc: Exception) -> bool:
    """Recognise only the provider's explicit pre-dispatch/unavailable contract."""

    return "request is unavailable" in str(exc or "").lower()


def _settings(config: Mapping[str, Any]) -> dict[str, Any]:
    seo = config.get("seo") if isinstance(config, Mapping) else {}
    seo = seo if isinstance(seo, Mapping) else {}
    raw = seo.get("article_research") or {}
    settings = dict(raw) if isinstance(raw, Mapping) else {}
    # Follow the instance's primary research locale unless the pipeline is
    # overridden explicitly. This keeps the always-on article pipeline in the
    # site's own language instead of silently assuming English.
    if not str(settings.get("language") or "").strip() or not str(settings.get("market") or "").strip():
        derived_language, derived_market = primary_research_locale(dict(config))
        if derived_language and not str(settings.get("language") or "").strip():
            settings["language"] = derived_language
        if derived_market and not str(settings.get("market") or "").strip():
            settings["market"] = derived_market
    return settings


def _cycle_key(config: Mapping[str, Any], now: datetime.datetime | None = None) -> str:
    settings = _settings(config)
    timezone_name = str(settings.get("timezone") or "UTC")
    from zoneinfo import ZoneInfo

    local = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(ZoneInfo(timezone_name))
    iso = local.date().isocalendar()
    return f"article:{iso.year}-W{iso.week:02d}"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _news(memory: Any, limit: int = 12) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in memory.recent_observations(limit=30):
        source = str(item.get("source") or "")
        if source in {"self", "inner_voice", "dream", "awaken", "identity_shift"}:
            continue
        text = " ".join(str(item.get("text") or "").split())
        link = str((item.get("meta") or {}).get("link") or "")
        if text:
            rows.append({"source": source, "text": text[:700], "url": link[:1000], "observed_at": str(item.get("ts") or "")})
    return rows[:limit]


def _snapshot(memory: Any, source: str, limit: int = 3000) -> list[dict[str, Any]]:
    snapshot = memory.latest_snapshot(source)
    if not snapshot or not isinstance(snapshot.get("data"), Mapping):
        return []
    data = snapshot["data"]
    pages = data.get("top_pages") if isinstance(data.get("top_pages"), list) else []
    rows = []
    for page in pages[:8]:
        if not isinstance(page, Mapping):
            continue
        rows.append({
            "path": str(page.get("path") or ""),
            "queries": str(page.get("top_queries") or "")[:200],
            "clicks": page.get("clicks"),
            "impressions": page.get("impressions"),
        })
    return rows[:4]


def _idea_prompt(context: Mapping[str, Any]) -> list[dict[str, str]]:
    config = context["config"]
    memory = context["memory"]
    settings = _settings(config)
    prior = memory.article_research_context(limit=12)
    past = [
        {"title": str(row.get("title") or "")[:200], "status": row.get("status"), "updated_ts": row.get("updated_ts")}
        for row in memory.list_drafts(limit=100)
        if row.get("kind") == "article"
    ][-12:]
    audience = str((config.get("persona") or {}).get("audience") or "the site's audience")
    language = str(settings.get("language") or "en")
    market = str(settings.get("market") or "US")
    audience_questions = memory.kv_get("audience_questions", [])
    if not isinstance(audience_questions, list):
        audience_questions = []
    latest_insight = memory.latest_seo_insight() or {}
    payload = {
        "audience": audience,
        "target_language": language,
        "target_market": market,
        "audience_questions": [str(item)[:400] for item in audience_questions[:8]],
        "recent_reading": _news(memory),
        "themes": memory.kv_get("themes", [])[:8],
        "gsc_top_pages": _snapshot(memory, "gsc"),
        "ga4_top_pages": _snapshot(memory, "ga4"),
        # Ada's own most recent synthesis: the same view the owner sees.
        "seo_insight": {
            "headline": str(latest_insight.get("headline") or "")[:300],
            "next_action": str(latest_insight.get("next_action") or "")[:600],
            "focus_keyword": str(latest_insight.get("focus_keyword") or "")[:200],
            "opportunities": [
                str((item or {}).get("title") or "")[:200]
                for item in (latest_insight.get("opportunities") or [])
                if isinstance(item, Mapping)
            ][:4],
        }
        if latest_insight
        else {},
        "prior_paid_research_notes": prior,
        "previous_articles": past,
        "editorial_context": str(memory_context(memory))[:2500],
    }
    return [
        {
            "role": "system",
            "content": (
                str(context.get("persona_prompt") or "")
                + "\n\nChoose one audience-led article hypothesis. Start with a real reader question or decision, not a "
                "keyword and not a generic summary of the news. The idea must come from a real reader need, "
                "recent observation, learning, community question, or sourced news. Separate the surface request "
                "from the reader's situation, stakes, constraints, and desired outcome. Search demand is only a "
                "traffic signal: it may reveal a price-sensitive or anxious audience, but it must never replace "
                "the audience need or decide the angle by itself. Explain why the topic matters to this business "
                "and what the owner can credibly clarify. Analyze the supplied market context too: alternatives, "
                "price sensitivity, timing, regulation, competitive conventions, and the factors that change the "
                "reader's decision. If the market evidence is missing, name that gap instead of inferring it. Do not invent expertise; use supplied owner knowledge, "
                "approved evidence, or name the gap for owner review. When a seo_insight is supplied it is your own "
                "most recent synthesis for the owner: let it inform the choice, but do not simply restate it and do not "
                "let it override a concrete reader need. Avoid duplicates. Return JSON only. "
                "candidate_queries must be 5 to 10 concise Google queries that could surface local intent for this "
                "idea (include the relevant destination or market in queries where it matters). Each query must be "
                "one phrase: do not use semicolons, commas, pipes, or newline-separated alternatives. Make the "
                "queries reflect different ways a reader might express the same decision, including the reader's "
                "own vocabulary and the field's professional vocabulary when those differ. Include at least two "
                "short head terms of one to three words alongside the longer reader questions: very long natural-"
                "language phrases are often absent from keyword databases, and demand must be measurable rather "
                "than assumed."
            ),
        },
        {
            "role": "user",
            "content": (
                json.dumps(payload, ensure_ascii=False, default=str)[:18_000]
                + '\n\nReturn exactly: {"working_title":"...","audience_need":"...",'
                '"reader_question":"...","reader_situation":"...","reader_intent":"...",'
                '"business_relevance":"...","market_context":"...","expert_angle":"...",'
                '"expertise_basis":["owner knowledge, approved evidence, or a clearly named gap"],'
                '"technical_watchouts":["terms, claims, trade-offs, or distinctions requiring care"],'
                '"scope_boundaries":["what the article must not claim"],"thesis":"...",'
                '"why_now":"...","origin":"news|audience_concern|learning|community_question",'
                '"source_urls":["https://..."],"candidate_queries":["...","..."],"language":"...","market":"..."}'
            ),
        },
    ]


def memory_context(memory: Any) -> str:
    from .prompts import memory_context as prompt_memory_context

    return prompt_memory_context(memory)


def _single_seed(value: Any) -> str:
    normalized = " ".join(str(value or "").split())[:120]
    normalized = normalized.split(";", 1)[0].split("|", 1)[0]
    return normalized.lstrip("-*0123456789.) ").strip()


def _candidate_queries(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else []
    queries = [query for query in (_single_seed(item) for item in raw) if query]
    if not 5 <= len(queries) <= 10:
        raise ValueError("article idea needs 5 to 10 candidate queries")
    lowered = [query.lower() for query in queries]
    if len(set(lowered)) != len(lowered):
        raise ValueError("article idea candidate queries must be unique")
    return queries


def _bounded_strings(value: Any, *, limit: int = 8, maximum: int = 500) -> list[str]:
    raw = value if isinstance(value, list) else []
    result: list[str] = []
    for item in raw[:limit]:
        text = " ".join(str(item or "").split())[:maximum]
        if text:
            result.append(text)
    return result


def _terminology_notes(value: Any) -> list[dict[str, str]]:
    """Keep terminology guidance structured without assuming a particular niche.

    The model may know that readers and practitioners use different words, but
    it must also say whether that distinction is owner-confirmed, sourced, or
    still uncertain.  Uncertain notes are useful guardrails, not facts.
    """
    raw = value if isinstance(value, list) else []
    result: list[dict[str, str]] = []
    for item in raw[:12]:
        if isinstance(item, Mapping):
            reader_term = " ".join(str(item.get("reader_term") or item.get("term") or "").split())[:120]
            preferred_term = " ".join(str(item.get("preferred_term") or item.get("professional_term") or "").split())[:160]
            distinction = " ".join(str(item.get("distinction") or item.get("guidance") or "").split())[:360]
            basis = " ".join(str(item.get("basis") or "uncertain").split())[:80]
        else:
            reader_term = " ".join(str(item or "").split())[:120]
            preferred_term = ""
            distinction = ""
            basis = "uncertain"
        if reader_term or preferred_term or distinction:
            result.append({
                "reader_term": reader_term,
                "preferred_term": preferred_term,
                "distinction": distinction,
                "basis": basis or "uncertain",
            })
    return result


def _validate_idea(raw: str, config: Mapping[str, Any]) -> dict[str, Any]:
    idea = extract_json(raw)
    if not isinstance(idea, Mapping):
        raise ValueError("article idea response was not an object")
    settings = _settings(config)
    result = {
        "working_title": str(idea.get("working_title") or "").strip()[:300],
        "audience_need": str(idea.get("audience_need") or "").strip()[:700],
        "reader_question": str(idea.get("reader_question") or "").strip()[:700],
        "reader_situation": str(idea.get("reader_situation") or "").strip()[:900],
        "reader_intent": str(idea.get("reader_intent") or "").strip()[:500],
        "business_relevance": str(idea.get("business_relevance") or "").strip()[:900],
        "market_context": str(idea.get("market_context") or "").strip()[:900],
        "expert_angle": str(idea.get("expert_angle") or "").strip()[:900],
        "expertise_basis": _bounded_strings(idea.get("expertise_basis"), limit=8, maximum=500),
        "technical_watchouts": _bounded_strings(idea.get("technical_watchouts"), limit=10, maximum=500),
        "scope_boundaries": _bounded_strings(idea.get("scope_boundaries"), limit=8, maximum=500),
        "thesis": str(idea.get("thesis") or "").strip()[:1200],
        "why_now": str(idea.get("why_now") or "").strip()[:700],
        "origin": str(idea.get("origin") or "").strip().lower(),
        "source_urls": [str(url).strip()[:1000] for url in (idea.get("source_urls") or []) if str(url).strip().startswith(("http://", "https://"))][:8],
        "candidate_queries": _candidate_queries(idea.get("candidate_queries")),
        "language": str(idea.get("language") or settings.get("language") or "en").strip().lower()[:16],
        "market": str(idea.get("market") or settings.get("market") or "US").strip().upper()[:2],
    }
    if (
        not result["working_title"]
        or not result["audience_need"]
        or not result["reader_question"]
        or not result["reader_situation"]
        or not result["reader_intent"]
        or not result["business_relevance"]
        or not result["market_context"]
        or not result["expert_angle"]
        or not result["expertise_basis"]
        or not result["thesis"]
        or not result["candidate_queries"]
    ):
        raise ValueError(
            "article idea needs a title, audience need, reader question and situation, reader intent, "
            "business relevance, market context, expert angle, expertise basis, thesis, and candidate queries"
        )
    if result["origin"] not in _ORIGINS:
        raise ValueError("article idea origin is not supported")
    time_sensitive = any(word in f"{result['why_now']} {result['thesis']}".lower() for word in ("today", "current", "this week", "now", "recent"))
    if time_sensitive and not result["source_urls"]:
        raise ValueError("time-sensitive article ideas require a source URL")
    configured_language = str(settings.get("language") or "en").lower().split("-", 1)[0]
    if result["language"].split("-", 1)[0] != configured_language:
        raise ValueError("article idea language is not supported by the configured publication locale")
    configured_market = str(settings.get("market") or "US").strip().upper()
    if result["market"] != configured_market:
        raise ValueError("article idea market is not supported by the configured research locale")
    return result


def _duplicate(idea: Mapping[str, Any], memory: Any) -> bool:
    title = str(idea.get("working_title") or "").strip().lower()
    thesis = str(idea.get("thesis") or "").strip().lower()
    for row in memory.list_article_ideas(limit=100):
        previous = row.get("idea_json") if isinstance(row.get("idea_json"), Mapping) else {}
        if title and title == str(previous.get("working_title") or "").strip().lower():
            return True
        if thesis and thesis == str(previous.get("thesis") or "").strip().lower():
            return True
    for row in memory.list_drafts(limit=100):
        if row.get("kind") == "article" and title == str(row.get("title") or "").strip().lower():
            return True
    return False


def _idea_summary(idea: Mapping[str, Any], *, limit: int = 1800) -> str:
    """Compose a bounded provider summary, most useful evidence first.

    The provider caps this field, so it is trimmed by priority rather than
    truncated mid-sentence: the reader question and thesis carry the meaning.
    """
    parts = (
        ("Reader question", idea.get("reader_question")),
        ("Thesis", idea.get("thesis")),
        ("Situation", idea.get("reader_situation")),
        ("Market context", idea.get("market_context")),
        ("Expert angle", idea.get("expert_angle")),
    )
    composed = ""
    for label, value in parts:
        chunk = " ".join(str(value or "").split())
        if not chunk:
            continue
        prefix = f"{composed} " if composed else ""
        room = limit - len(prefix) - len(label) - 2
        if room <= 40:
            break
        composed = f"{prefix}{label}: {chunk[:room]}".strip()
        if len(composed) >= limit:
            break
    return composed[:limit]


def _request_selected_idea(context: Mapping[str, Any], row: Mapping[str, Any], idea: Mapping[str, Any]) -> None:
    memory = context["memory"]
    service = context["crawlseo_service"]
    idempotency_key = f"article-research:{row['idea_hash']}:v1"
    reservation_id = str(row.get("keyword_budget_reservation_id") or "").strip()
    try:
        if reservation_id:
            reservation = memory.get_growth_budget_reservation(reservation_id)
            if reservation and str(reservation.get("status")) == "released":
                reservation_id = ""
            elif not reservation or str(reservation.get("status")) != "reserved":
                raise GrowthBudgetBlocked(f"article keyword research reservation {reservation_id} is not safely dispatchable; reconcile it first")
        if not reservation_id:
            reservation = reserve_paid_research(context, idempotency_key=idempotency_key, operation="article_keyword_overview", detail={"idea_id": row["id"], "cycle_key": row["cycle_key"]})
            reservation_id = str(reservation["reservation_id"])
            row = memory.update_article_idea(int(row["id"]), keyword_budget_reservation_id=reservation_id) or row
        response = service.request_article_keyword_research(
            idea_key=str(row["cycle_key"]),
            idea_summary=_idea_summary(idea),
            queries=list(idea.get("candidate_queries") or []),
            language=str(idea["language"]),
            country=str(idea["market"]),
            idempotency_key=idempotency_key,
        )
        run_id = str(response.get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError("CrawlSEO did not return an article research run ID")
        settle_paid_research(context, reservation_id, provider_task_id=run_id, detail={"provider_status": response.get("status") or "requested", "stage": "keyword_overview"})
        memory.update_article_idea(
            int(row["id"]),
            status="research_requested",
            research_run_id=run_id,
            error=None,
        )
        memory.record_action("article_research", f"idea #{row['id']}: requested one keyword overview run {run_id}")
    except GrowthBudgetBlocked as exc:
        memory.update_article_idea(int(row["id"]), status="blocked", error=str(exc)[:500])
        memory.record_action("article_research", f"idea #{row['id']}: blocked before paid request: {str(exc)[:300]}")
    except Exception as exc:  # noqa: BLE001 — an unknown paid outcome must not be retried blindly
        if reservation_id and _request_not_dispatched(exc):
            release_paid_research(context, reservation_id, reason=str(exc))
            memory.update_article_idea(int(row["id"]), status="selected", error=str(exc)[:500])
            memory.record_action("article_research", f"idea #{row['id']}: provider rejected the request before dispatch; safe retry is queued")
            return
        if reservation_id:
            mark_paid_research_uncertain(context, reservation_id, error=str(exc))
        memory.update_article_idea(
            int(row["id"]),
            status="uncertain",
            error=str(exc)[:500],
        )
        memory.record_action(
            "article_research",
            f"idea #{row['id']}: paid request outcome is uncertain and needs reconciliation: {str(exc)[:300]}",
        )


def _candidate_dict(parsed: Any) -> dict[str, Any]:
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _record_rejected_idea(
    memory: Any,
    cycle_key: str,
    raw: str | None,
    reason: str,
    parsed: Any = None,
) -> None:
    candidate = _candidate_dict(parsed)
    if not candidate and raw:
        try:
            candidate = _candidate_dict(extract_json(raw))
        except Exception:  # noqa: BLE001 - a malformed candidate is still recorded
            candidate = {}
    memory.record_rejected_article_idea(
        cycle_key=cycle_key,
        raw=raw or "",
        parsed=candidate,
        reason=reason,
    )


def select_and_request(context: dict[str, Any]) -> None:
    config = context["config"]
    memory = context["memory"]
    settings = _settings(config)
    if not settings.get("enabled", False):
        return
    cycle_key = _cycle_key(config)
    existing = memory.get_article_idea_by_cycle(cycle_key)
    if existing is not None:
        existing_idea = existing.get("idea_json")
        if (
            not existing.get("research_run_id")
            and existing.get("status") in {"selected", "failed"}
            and isinstance(existing_idea, Mapping)
        ):
            _request_selected_idea(context, existing, existing_idea)
        return
    llm = context.get("llm")
    service = context.get("crawlseo_service")
    if llm is None or service is None:
        memory.record_action("article_research", "skipped: LLM or CrawlSEO provider is unavailable")
        return
    raw_idea: str | None = None
    try:
        raw_idea = llm.chat(_idea_prompt(context), json_mode=True, temperature=0.7)
        idea = _validate_idea(raw_idea, config)
        if _duplicate(idea, memory):
            _record_rejected_idea(memory, cycle_key, raw_idea, "duplicate of existing editorial work", parsed=idea)
            memory.record_action("article_research", "article idea skipped: duplicate of existing editorial work")
            return
        idea_hash = _hash(idea)
        row = memory.create_article_idea(cycle_key, idea_hash, idea)
        _request_selected_idea(context, row, idea)
    except Exception as exc:  # noqa: BLE001 - rejection reasons are recorded, never lost
        _record_rejected_idea(memory, cycle_key, raw_idea, str(exc)[:400])
        row = memory.get_article_idea_by_cycle(cycle_key)
        if row is not None:
            memory.update_article_idea(row["id"], status="selected", error=str(exc)[:500])
        memory.record_action("article_research", f"idea selection/request failed: {str(exc)[:300]}")


def _research_note_prompt(idea: Mapping[str, Any], result: list[Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Interpret exact candidate search metrics for the already-selected article idea. Preserve the "
                "original reader question, situation, business relevance, market context, expert angle, and thesis. Search volume "
                "is context, never a verdict and never a reason to replace the topic. It can reveal a practical, "
                "price-sensitive, anxious, or comparison-led intent, but do not turn that signal into a claim about "
                "people's motives. Sparse or zero demand must not automatically reject an idea. Choose exactly one "
                "query for a single SERP snapshot: it should normally be one of the submitted candidates, but an "
                "explicitly editorial alternative is allowed when its reasoning explains why the submitted candidates "
                "miss the real need. Identify terminology differences, technical claims, false binaries, and scope "
                "boundaries that the writer must verify or qualify. Do not treat SERP wording as domain truth. Return "
                "JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Original idea:\n" + json.dumps(dict(idea), ensure_ascii=False, default=str)
                + "\n\nExact candidate metrics:\n" + json.dumps(result[:10], ensure_ascii=False, default=str)
                + '\n\nReturn exactly: {"original_thesis":"...","decision":"keep|reframe|editorial_despite_low_demand",'
                '"selected_query":"...","selected_from_query":"...","reader_language":["..."],'
                '"reader_question":"...","market_context":"...","question_fit":"...",'
                '"demand_interpretation":"...","related_questions":["..."],"useful_terms":["..."],'
                '"terminology_notes":[{"reader_term":"...","preferred_term":"...",'
                '"distinction":"...","basis":"owner|source|uncertain"}],'
                '"technical_claims_to_verify":["..."],"scope_boundaries":["..."],'
                '"misconceptions_to_avoid":["..."],"reframed_title":"...",'
                '"reframed_thesis":"...","expert_angle":"...","reasoning":"..."}'
            ),
        },
    ]


def _note(raw: str, idea: Mapping[str, Any]) -> dict[str, Any]:
    parsed = extract_json(raw)
    if not isinstance(parsed, Mapping):
        raise ValueError("article research note response was not an object")
    decision = str(parsed.get("decision") or "keep").strip().lower()
    if decision not in _DECISIONS:
        decision = "keep"
    candidates = [str(query) for query in (idea.get("candidate_queries") or [])]
    selected = str(parsed.get("selected_query") or "").strip()[:120]
    if not selected and candidates:
        selected = candidates[0]
    selected_from = str(parsed.get("selected_from_query") or "").strip()[:120]
    if not selected_from and selected in candidates:
        selected_from = selected
    candidate_lookup = {query.strip().lower(): query for query in candidates if query.strip()}
    selected_candidate = candidate_lookup.get(selected.lower())
    selected_from_candidate = candidate_lookup.get(selected_from.lower())
    if selected_candidate:
        selected = selected_candidate
        selected_from = selected_from_candidate or selected_candidate
    elif not selected:
        raise ValueError("article research note selected no query")
    elif not selected_from_candidate or not str(parsed.get("reasoning") or "").strip():
        raise ValueError(
            "article research note must select a submitted query or justify an editorial alternative with its source query"
        )
    return {
        "original_thesis": str(parsed.get("original_thesis") or idea.get("thesis") or "")[:1200],
        "decision": decision,
        "selected_query": selected,
        "selected_from_query": selected_from,
        "reader_question": str(parsed.get("reader_question") or idea.get("reader_question") or "")[:700],
        "market_context": str(parsed.get("market_context") or idea.get("market_context") or "")[:900],
        "question_fit": str(parsed.get("question_fit") or "")[:900],
        "demand_interpretation": str(parsed.get("demand_interpretation") or "")[:900],
        "reader_language": [str(item)[:160] for item in (parsed.get("reader_language") or [])][:8],
        "related_questions": [str(item)[:240] for item in (parsed.get("related_questions") or [])][:8],
        "useful_terms": [str(item)[:120] for item in (parsed.get("useful_terms") or [])][:12],
        "terminology_notes": _terminology_notes(parsed.get("terminology_notes")),
        "technical_claims_to_verify": _bounded_strings(parsed.get("technical_claims_to_verify"), limit=10, maximum=500),
        "scope_boundaries": _bounded_strings(
            parsed.get("scope_boundaries") or idea.get("scope_boundaries"), limit=8, maximum=500
        ),
        "misconceptions_to_avoid": _bounded_strings(parsed.get("misconceptions_to_avoid"), limit=8, maximum=500),
        "expert_angle": str(parsed.get("expert_angle") or idea.get("expert_angle") or "")[:900],
        "reframed_title": str(parsed.get("reframed_title") or idea.get("working_title") or "")[:300],
        "reframed_thesis": str(parsed.get("reframed_thesis") or idea.get("thesis") or "")[:1200],
        "reasoning": str(parsed.get("reasoning") or "")[:1600],
    }


def _empty_result_allowed(note: Mapping[str, Any]) -> bool:
    return (
        str(note.get("decision") or "").strip().lower() == "editorial_despite_low_demand"
        and bool(str(note.get("reasoning") or "").strip())
    )


def _volume(row: Any) -> int:
    if not isinstance(row, Mapping):
        return 0
    value = row.get("volume") if row.get("volume") is not None else row.get("search_volume")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _has_demand(result: list[Any]) -> bool:
    return any(_volume(row) > 0 for row in result)


def _serp_evidence(result: Any) -> dict[str, Any]:
    data = result if isinstance(result, Mapping) else {}
    return {
        "query": str(data.get("query") or "")[:120],
        "checked_at": str(data.get("checked_at") or "")[:80],
        "item_types": [str(item)[:50] for item in (data.get("item_types") or [])][:30],
        "organic": [
            {
                "rank": row.get("rank"),
                "domain": str(row.get("domain") or "")[:253],
                "title": str(row.get("title") or "")[:300],
                "url": str(row.get("url") or "")[:1000],
            }
            for row in (data.get("organic") or [])[:8]
            if isinstance(row, Mapping)
        ],
        "people_also_ask": [
            {"question": str(row.get("question") or "")[:300], "url": str(row.get("url") or "")[:1000]}
            for row in (data.get("peopleAlsoAsk") or [])[:6]
            if isinstance(row, Mapping)
        ],
        "related_searches": [str(item)[:200] for item in (data.get("relatedSearches") or [])][:8],
        "local_pack": [
            {"title": str(row.get("title") or "")[:300], "url": str(row.get("url") or "")[:1000], "rating": row.get("rating")}
            for row in (data.get("localPack") or [])[:4]
            if isinstance(row, Mapping)
        ],
    }


def _poll_run(service: Any, run_id: str) -> tuple[str, Any]:
    status = service.article_keyword_research_status(run_id)
    value = str(status.get("status") or "").lower()
    return value, status


def _draft_from_idea(context: dict[str, Any], idea: Mapping[str, Any]) -> int:
    idea_data = idea.get("idea_json") if isinstance(idea.get("idea_json"), Mapping) else {}
    note = idea.get("research_note_json") if isinstance(idea.get("research_note_json"), Mapping) else {}
    metrics = idea.get("research_result_json") if isinstance(idea.get("research_result_json"), list) else []
    return brain_article.draft_article_for_idea(
        context,
        idea_data,
        note,
        metrics,
        serp_evidence=note.get("serp_evidence"),
        lineage={
            "article_idea_id": idea["id"],
            "keyword_research_run_id": idea.get("research_run_id"),
            "serp_research_run_id": idea.get("serp_run_id"),
            "research_cost_micros": idea.get("research_cost_micros"),
        },
    )


def _reconcile_overview(context: dict[str, Any], idea: Mapping[str, Any], service: Any, llm: Any) -> None:
    memory = context["memory"]
    run_id = str(idea.get("research_run_id") or "")
    if not run_id:
        memory.update_article_idea(idea["id"], status="failed", error="missing keyword overview run ID")
        return
    value, status = _poll_run(service, run_id)
    if value in {"requested", "attempting"}:
        return
    if value in {"failed", "uncertain"}:
        memory.update_article_idea(
            idea["id"],
            status="failed",
            error=str(status.get("error_code") or value)[:500],
            research_cost_micros=status.get("cost_micros"),
        )
        memory.record_action("article_research", f"idea #{idea['id']}: no draft after {value} keyword overview")
        return
    if value != "completed":
        return
    payload = service.article_keyword_research(run_id)
    result = payload.get("result") if isinstance(payload.get("result"), list) else []
    idea_data = idea.get("idea_json") if isinstance(idea.get("idea_json"), Mapping) else {}
    existing_note = idea.get("research_note_json")
    note = existing_note if isinstance(existing_note, Mapping) and existing_note else _note(
        llm.chat(_research_note_prompt(idea_data, result), json_mode=True, temperature=0.2), idea_data
    )
    result_hash = _hash(result)
    provider_task_id = payload.get("provider_task_id") or status.get("provider_task_id")
    research_cost_micros = (
        payload.get("cost_micros")
        if payload.get("cost_micros") is not None
        else status.get("cost_micros")
    )
    if not _has_demand(result) and not _empty_result_allowed(note):
        memory.update_article_idea(
            idea["id"],
            status="held",
            research_result_hash=result_hash,
            research_result_json=result,
            provider_task_id=provider_task_id,
            research_cost_micros=research_cost_micros,
            research_note_json=note,
            error="exact candidate metrics show no demand; an explicit editorial_despite_low_demand reason is required",
        )
        memory.record_action(
            "article_research",
            f"idea #{idea['id']}: held because exact candidate metrics show no measurable demand",
        )
        return
    # Persist metrics and the note before the second paid request so a crash
    # between dispatch and local update is retried idempotently, never repeated.
    memory.update_article_idea(
        idea["id"],
        research_result_hash=result_hash,
        research_result_json=result,
        provider_task_id=provider_task_id,
        research_cost_micros=research_cost_micros,
        research_note_json=note,
        error=None,
    )
    selected_query = str(note.get("selected_query") or "").strip()
    if not selected_query:
        memory.update_article_idea(idea["id"], status="failed", error="research note selected no query")
        return
    serp_reservation_id = str(idea.get("serp_budget_reservation_id") or "").strip()
    try:
        serp_key = f"article-serp:{idea['idea_hash']}:{_hash(selected_query)}:v1"
        if serp_reservation_id:
            reservation = memory.get_growth_budget_reservation(serp_reservation_id)
            if reservation and str(reservation.get("status")) == "released":
                serp_reservation_id = ""
            elif not reservation or str(reservation.get("status")) != "reserved":
                raise GrowthBudgetBlocked(f"article SERP reservation {serp_reservation_id} is not safely dispatchable; reconcile it first")
        if not serp_reservation_id:
            reservation = reserve_paid_research(context, idempotency_key=serp_key, operation="article_serp_snapshot", detail={"idea_id": idea["id"], "query": selected_query})
            serp_reservation_id = str(reservation["reservation_id"])
            memory.update_article_idea(idea["id"], serp_budget_reservation_id=serp_reservation_id)
        response = service.request_article_serp_research(
            parent_run_id=run_id,
            keyword=selected_query,
            idempotency_key=serp_key,
        )
        serp_run_id = str(response.get("run_id") or "").strip()
        if not serp_run_id:
            raise RuntimeError("CrawlSEO did not return an article SERP run ID")
        settle_paid_research(context, serp_reservation_id, provider_task_id=serp_run_id, detail={"provider_status": response.get("status") or "requested", "stage": "serp_snapshot"})
        memory.update_article_idea(
            idea["id"],
            status="serp_requested",
            serp_run_id=serp_run_id,
            error=None,
        )
        memory.record_action(
            "article_research",
            f"idea #{idea['id']}: metrics saved; requested one SERP run {serp_run_id} for '{selected_query}'",
        )
    except GrowthBudgetBlocked as exc:
        memory.update_article_idea(idea["id"], status="blocked", error=str(exc)[:500])
        memory.record_action("article_research", f"idea #{idea['id']}: SERP blocked before paid request: {str(exc)[:300]}")
    except Exception as exc:  # noqa: BLE001 — the provider outcome is not safe to replay blindly
        if serp_reservation_id and _request_not_dispatched(exc):
            release_paid_research(context, serp_reservation_id, reason=str(exc))
            memory.update_article_idea(idea["id"], status="research_requested", error=str(exc)[:500])
            memory.record_action("article_research", f"idea #{idea['id']}: provider rejected the SERP request before dispatch; safe retry is queued")
            return
        if serp_reservation_id:
            mark_paid_research_uncertain(context, serp_reservation_id, error=str(exc))
        memory.update_article_idea(idea["id"], status="uncertain", error=str(exc)[:500])
        memory.record_action(
            "article_research",
            f"idea #{idea['id']}: SERP outcome is uncertain and needs reconciliation: {str(exc)[:300]}",
        )


def _reconcile_serp(context: dict[str, Any], idea: Mapping[str, Any], service: Any, llm: Any) -> None:
    memory = context["memory"]
    serp_run_id = str(idea.get("serp_run_id") or "")
    if not serp_run_id:
        memory.update_article_idea(idea["id"], status="failed", error="missing SERP run ID")
        return
    status = service.article_serp_research_status(serp_run_id)
    value = str(status.get("status") or "").lower()
    if value in {"requested", "attempting"}:
        return
    if value in {"failed", "uncertain"}:
        memory.update_article_idea(
            idea["id"],
            status="failed",
            error=str(status.get("error_code") or value)[:500],
            research_cost_micros=status.get("cost_micros"),
        )
        memory.record_action("article_research", f"idea #{idea['id']}: no draft after {value} SERP research")
        return
    if value != "completed":
        return
    payload = service.article_serp_research(serp_run_id)
    evidence = _serp_evidence(payload.get("result"))
    note = idea.get("research_note_json") if isinstance(idea.get("research_note_json"), Mapping) else {}
    note = {
        **note,
        "serp_evidence": evidence,
        "serp_receipt": {
            "run_id": serp_run_id,
            "provider_task_id": payload.get("provider_task_id") or status.get("provider_task_id"),
            "cost_micros": payload.get("cost_micros")
            if payload.get("cost_micros") is not None
            else status.get("cost_micros"),
            "checked_at": evidence.get("checked_at"),
        },
    }
    memory.update_article_idea(
        idea["id"],
        status="researched",
        research_note_json=note,
        researched_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        error=None,
    )
    memory.record_action(
        "article_research",
        f"idea #{idea['id']}: SERP evidence saved; drafting",
    )
    draft_id = _draft_from_idea(context, memory.get_article_idea(idea["id"]))
    memory.update_article_idea(
        idea["id"],
        status="drafted",
        draft_id=draft_id,
        drafted_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    )
    memory.record_action("article_research", f"idea #{idea['id']}: note and SERP evidence saved; draft #{draft_id} created")


def _research_complete(idea: Mapping[str, Any]) -> bool:
    note = idea.get("research_note_json") if isinstance(idea.get("research_note_json"), Mapping) else {}
    has_metrics = isinstance(idea.get("research_result_json"), list) and bool(idea.get("research_result_json"))
    has_serp = bool(note.get("serp_evidence") or note.get("serp_receipt"))
    return bool(idea.get("serp_run_id")) and has_metrics and has_serp


def _reconcile_local_draft(context: dict[str, Any], idea: Mapping[str, Any], memory: Any) -> None:
    if not _research_complete(idea):
        # A researched row without a completed SERP (or a legacy empty-result
        # hold) must never auto-draft. Keep it visibly held for the owner.
        memory.update_article_idea(
            idea["id"],
            status="held",
            error="article research is incomplete: a completed SERP and an explicit editorial_despite_low_demand reason are required",
        )
        return
    try:
        draft_id = _draft_from_idea(context, idea)
    except Exception as exc:  # noqa: BLE001 - local drafting is retryable without another paid request
        memory.update_article_idea(idea["id"], error=str(exc)[:500])
        memory.record_action("article_research", f"idea #{idea['id']}: local draft retry: {str(exc)[:300]}")
        return
    memory.update_article_idea(
        idea["id"],
        status="drafted",
        draft_id=draft_id,
        drafted_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    )
    memory.record_action("article_research", f"idea #{idea['id']}: draft #{draft_id} created")


def reconcile(context: dict[str, Any]) -> None:
    config = context["config"]
    memory = context["memory"]
    service = context.get("crawlseo_service")
    if not _settings(config).get("enabled", False) or service is None:
        return
    llm = context.get("llm")
    ideas: list[Mapping[str, Any]] = []
    # A provider run is never repeated, but local note/draft work may need a
    # retry after a process interruption. Keep serp_requested and researched
    # rows recoverable without issuing another paid request.
    for status in ("research_requested", "serp_requested", "researched"):
        ideas.extend(memory.list_article_ideas(status=status, limit=20))
    seen_ids: set[int] = set()
    for idea in ideas:
        if idea["id"] in seen_ids:
            continue
        seen_ids.add(idea["id"])
        if idea.get("draft_id"):
            if idea.get("status") != "drafted":
                memory.update_article_idea(idea["id"], status="drafted")
            continue
        if llm is None:
            continue
        try:
            if idea.get("status") == "research_requested":
                _reconcile_overview(context, idea, service, llm)
            elif idea.get("status") == "serp_requested":
                _reconcile_serp(context, idea, service, llm)
            elif idea.get("status") == "researched":
                _reconcile_local_draft(context, idea, memory)
        except Exception as exc:  # noqa: BLE001 - keep the paid runs and retry only local interpretation/drafting
            memory.update_article_idea(idea["id"], error=str(exc)[:500])
            memory.record_action("article_research", f"idea #{idea['id']}: reconciliation retry: {str(exc)[:300]}")


__all__ = ["reconcile", "select_and_request"]
