"""Ada's monthly SEO research and strategy loop.

Ada chooses the business question, focus market, seeds, and a verified competitor
when the available evidence supports one. CrawlSEO executes the bounded provider
batch; this module only requests it, interprets the cached result, and creates
owner-reviewable work.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..application.actions import OwnerActionService
from ..config import validate_research_config
from ..core.contracts import (
    ActionPriority,
    ActionRequirement,
    Artifact,
    ArtifactKind,
    OwnerAction,
)
from ..core.llm import extract_json
from . import article as brain_article


class SeoPlanningError(RuntimeError):
    """Ada cannot safely create a paid research brief from available context."""


PACKAGE_VERSION = "standard-v1"
TERMINAL_REPORT_STATUSES = {"completed", "partial", "failed"}


def _research_config(config: Mapping[str, Any]) -> dict[str, Any]:
    seo = config.get("seo") or {}
    research = seo.get("research") or {}
    if not isinstance(research, dict):
        raise SeoPlanningError("seo.research must be an object")
    validate_research_config(dict(config))
    return research


def previous_period(config: Mapping[str, Any], now: datetime.datetime | None = None) -> str:
    research = _research_config(config)
    timezone = ZoneInfo(str(research.get("timezone") or "UTC"))
    local_now = now.astimezone(timezone) if now is not None else datetime.datetime.now(timezone)
    first = local_now.date().replace(day=1)
    previous = first - datetime.timedelta(days=1)
    return previous.strftime("%Y-%m")


def _markets(research: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for language in research.get("languages") or []:
        if not isinstance(language, Mapping):
            continue
        code = str(language.get("code") or "").strip().lower()
        for market in language.get("markets") or []:
            country = str(market).strip().upper()
            if code and country:
                result.append({"language": code, "country": country, "primary": bool(language.get("primary"))})
    return result


def choose_focus_market(memory: Any, config: Mapping[str, Any]) -> dict[str, str]:
    research = _research_config(config)
    markets = _markets(research)
    if not markets:
        raise SeoPlanningError("no SEO language-markets are configured")
    previous = memory.kv_get("seo_focus_market") or {}
    previous_key = f"{previous.get('language')}:{previous.get('country')}" if isinstance(previous, Mapping) else ""
    now = datetime.datetime.now(datetime.timezone.utc)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, market in enumerate(markets):
        rows = memory.list_seo_seeds(market["language"], market["country"], limit=1000)
        researched = [row.get("last_researched_ts") for row in rows if row.get("last_researched_ts")]
        oldest = min(researched) if researched else ""
        score = 0.0
        if market["primary"]:
            score += 3.0
        if not rows:
            score += 2.0
        if previous_key == f"{market['language']}:{market['country']}" and len(markets) > 1:
            score -= 2.0
        try:
            researched_at = datetime.datetime.fromisoformat(oldest).astimezone(datetime.timezone.utc)
            age_score = min(365.0, max(0.0, (now - researched_at).total_seconds() / 86_400.0)) / 365.0
        except (TypeError, ValueError, OverflowError):
            age_score = 0.0
        scored.append((score + age_score, -index, market))
    scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
    selected = scored[0][2]
    memory.kv_set("seo_focus_market", selected)
    return {"language": selected["language"], "country": selected["country"]}


def _normalize_seed(value: str) -> str:
    return " ".join(value.lower().split()).strip()


def _near_duplicate(seed: str, selected: list[str]) -> bool:
    normalized = _normalize_seed(seed)
    if not normalized or normalized in {_normalize_seed(item) for item in selected}:
        return True
    words = set(normalized.split())
    for item in selected:
        other = set(_normalize_seed(item).split())
        if words and other:
            overlap = len(words & other) / max(len(words | other), 1)
            if overlap >= 0.8:
                return True
    return False


def _candidate_seeds(memory: Any, config: Mapping[str, Any], market: Mapping[str, str]) -> list[dict[str, str]]:
    research = _research_config(config)
    language = market["language"]
    country = market["country"]
    candidates: list[dict[str, str]] = []

    def add(value: Any, source: str, rationale: str, cluster: str = "") -> None:
        if not isinstance(value, str):
            return
        seed = " ".join(value.split()).strip()
        if len(seed) < 3 or len(seed) > 120 or _near_duplicate(seed, [item["seed"] for item in candidates]):
            return
        candidates.append({"seed": seed, "source": source, "rationale": rationale, "cluster": cluster or seed})

    for topic in research.get("anchor_topics") or []:
        add(topic, "business", "Configured anchor topic for the customer strategy", "business")
    for service in research.get("priority_services") or []:
        add(service, "service", "Configured priority service", "service")

    gsc = memory.latest_snapshot("gsc") or {}
    gsc_data = gsc.get("data") if isinstance(gsc, Mapping) else {}
    for row in (gsc_data.get("top_queries") if isinstance(gsc_data, Mapping) else []) or []:
        if isinstance(row, Mapping):
            add(row.get("query"), "gsc", "Existing Search Console demand for this site", "gsc")

    for keyword in (config.get("sources") or {}).get("keywords") or []:
        add(keyword, "audience", "Configured audience monitoring topic", "audience")

    for theme in memory.kv_get("themes", []) or []:
        add(theme, "learning", "A recurring audience theme Ada has learned", "learning")

    for row in memory.list_seo_seeds(language, country, limit=1000):
        freshness = str(row.get("freshness") or "new")
        if freshness in {"aging", "stale", "new"}:
            add(row.get("seed"), "history", "Historical seed retained for deliberate refresh", row.get("cluster", ""))
    return candidates


def select_seeds(memory: Any, config: Mapping[str, Any], market: Mapping[str, str]) -> list[dict[str, str]]:
    candidates = _candidate_seeds(memory, config, market)
    historical = {
        _normalize_seed(row["seed"])
        for row in memory.list_seo_seeds(market["language"], market["country"], limit=1000)
        if row.get("seed")
    }
    strategic = [item for item in candidates if item["source"] in {"business", "service"}]
    expansion = [item for item in candidates if item["source"] not in {"business", "service", "history"} and _normalize_seed(item["seed"]) not in historical]
    adaptive = [item for item in candidates if item["source"] in {"gsc", "learning", "audience"}]
    selected: list[dict[str, str]] = []

    def take(pool: list[dict[str, str]], slot_type: str) -> None:
        for candidate in pool:
            if _near_duplicate(candidate["seed"], [item["seed"] for item in selected]):
                continue
            selected.append({**candidate, "slot_type": slot_type})
            return

    for _ in range(2):
        take(strategic, "strategic")
    for _ in range(2):
        take(expansion, "expansion")
    take(adaptive, "adaptive")

    # A sparse customer config is a missing business-input problem, not a reason
    # to spend a paid task on generic fallback keywords.
    if len(selected) != 5:
        raise SeoPlanningError("Ada needs five distinct, justified SEO seeds before requesting research")
    return selected


def _domain(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or port or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or "." not in hostname or hostname in {"localhost", "example.com"}:
        return None
    return hostname


def _tokens(values: Any) -> set[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {
        token
        for value in values
        for token in re.findall(r"[a-z0-9]{4,}", str(value).lower())
        if token not in {"with", "from", "your", "this", "that", "guide", "service"}
    }


def _competitor_candidates(memory: Any, config: Mapping[str, Any], market: Mapping[str, str]) -> list[dict[str, Any]]:
    research = _research_config(config)
    descriptors = _tokens(
        [
            *(research.get("priority_services") or []),
            *(research.get("anchor_topics") or []),
            str((config.get("persona") or {}).get("audience") or ""),
        ]
    )
    own_domain = _domain(((config.get("seo") or {}).get("site_url") or ""))
    candidates: list[dict[str, Any]] = []

    def add(item: Any, source: str) -> None:
        if isinstance(item, str):
            item = {"domain": item}
        if not isinstance(item, Mapping):
            return
        domain = _domain(item.get("domain") or item.get("url"))
        if not domain or domain == own_domain or domain.removeprefix("www.") == (own_domain or "").removeprefix("www."):
            return
        markets = {str(value).upper() for value in item.get("markets") or []}
        if markets and market["country"].upper() not in markets:
            return
        descriptors_found = _tokens(
            [
                item.get("category"),
                item.get("category_match"),
                *((item.get("services") or []) if isinstance(item.get("services"), list) else [item.get("services")]),
                *((item.get("topics") or []) if isinstance(item.get("topics"), list) else [item.get("topics")]),
                *((item.get("evidence") or []) if isinstance(item.get("evidence"), list) else [item.get("evidence")]),
            ]
        )
        overlap = len(descriptors & descriptors_found)
        verified = bool(item.get("verified") or item.get("category_verified") or item.get("category_match") is True)
        score = (3 if markets else 1) + min(overlap, 3) * 2 + (2 if verified else 0)
        # A domain is not a competitor merely because it was mentioned. Require
        # either explicit category verification or meaningful service overlap.
        if score < 5 or (overlap == 0 and not verified):
            return
        candidates.append({
            "domain": domain,
            "source": source,
            "score": score,
            "market_match": bool(markets),
            "overlap": sorted(descriptors & descriptors_found)[:8],
        })

    for item in research.get("competitors") or []:
        add(item, "config.competitors")
    for item in research.get("competitor_candidates") or []:
        add(item, "config.competitor_candidates")
    raw_memory_candidates = memory.kv_get("seo_competitor_candidates", [])
    for item in raw_memory_candidates if isinstance(raw_memory_candidates, list) else []:
        add(item, "memory.seo_competitor_candidates")
    for source in ("gsc", "ga4", "crawl"):
        snapshot = memory.latest_snapshot(source) or {}
        data = snapshot.get("data") if isinstance(snapshot, Mapping) else {}
        if not isinstance(data, Mapping):
            continue
        for key in ("competitor_candidates", "competitors"):
            for item in data.get(key) or []:
                add(item, f"snapshot.{source}.{key}")

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        current = unique.get(candidate["domain"])
        if current is None or candidate["score"] > current["score"]:
            unique[candidate["domain"]] = candidate
    return sorted(unique.values(), key=lambda item: (-item["score"], item["domain"]))


def _competitor(
    memory: Any,
    config: Mapping[str, Any],
    market: Mapping[str, str],
    llm: Any | None = None,
) -> tuple[str | None, str]:
    candidates = _competitor_candidates(memory, config, market)
    if not candidates:
        return None, "Ada could not verify an in-category competitor from available customer context; competitor research was skipped."

    selected = candidates[0]
    if llm is not None and len(candidates) > 1:
        prompt = [
            {
                "role": "system",
                "content": (
                    "Select the strongest genuine SEO competitor from the supplied candidates. "
                    "Do not invent a domain and return null if none is clearly relevant. JSON only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "focus_market": market,
                    "business_services": (_research_config(config).get("priority_services") or [])[:8],
                    "candidates": candidates[:12],
                }, ensure_ascii=False, default=str)[:9000],
            },
        ]
        try:
            decoded = extract_json(llm.chat(prompt, json_mode=True, temperature=0.0))
            requested = _domain(decoded.get("domain")) if isinstance(decoded, Mapping) else None
            by_domain = {item["domain"]: item for item in candidates}
            if requested in by_domain:
                selected = by_domain[requested]
        except Exception:  # noqa: BLE001 — deterministic evidence ranking remains safe
            pass
    overlap = ", ".join(selected["overlap"]) or "verified category context"
    return selected["domain"], f"Ada selected {selected['domain']} from {selected['source']} for {market['language']}-{market['country']} using {overlap}."


def build_research_brief(
    memory: Any,
    config: Mapping[str, Any],
    period: str,
    llm: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    research = _research_config(config)
    market = choose_focus_market(memory, config)
    selections = select_seeds(memory, config, market)
    competitor, competitor_rationale = _competitor(memory, config, market, llm)
    persona = config.get("persona") or {}
    audience = str(persona.get("audience") or "").strip()
    if not audience:
        raise SeoPlanningError("Ada needs an audience description before requesting SEO research")
    goals = [str(item).strip() for item in research.get("business_goals") or [] if str(item).strip()]
    services = [str(item).strip() for item in research.get("priority_services") or [] if str(item).strip()]
    if not goals:
        goals = [f"Grow qualified organic reach for {audience}"]
    if not services:
        services = [str(item["seed"]) for item in selections[:2]]
    brief = {
        "period": period,
        "focus_market": market,
        "business_goal": goals[0],
        "audience": [audience],
        "priority_services": services,
        "keyword_seeds": [item["seed"] for item in selections],
        "competitor": competitor,
        "research_questions": [
            "Which search opportunities can support the current business goal?",
            "What should Ada write next for this market and audience?",
            "Which existing pages or technical issues limit qualified organic growth?",
        ],
        "selection_rationale": {
            "market": f"Selected {market['language']}-{market['country']} from customer priorities, freshness, and available first-party signals.",
            "seeds": [item["rationale"] for item in selections],
            "competitor": competitor_rationale,
        },
        "package": PACKAGE_VERSION,
    }
    return brief, selections


def _news_material(memory: Any, limit: int = 20) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in memory.recent_observations(limit=limit):
        source = str(row.get("source") or "")
        if source in {"self", "inner_voice", "dream", "awaken", "identity_shift"}:
            continue
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        result.append({
            "source": source,
            "text": text[:700],
            "url": str((row.get("meta") or {}).get("link") or ""),
            "observed_at": str(row.get("ts") or ""),
        })
    return result


def _strategy_prompt(material: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are Ada, the business-aware SEO strategist for this specific website. "
                "Use only the supplied evidence. Connect search demand, audience needs, "
                "current news, and business goals. Do not invent metrics or source URLs. "
                "Prefer a timely useful article when news genuinely supports it."
            ),
        },
        {
            "role": "user",
            "content": (
                "Create a monthly SEO strategy from this material. Return JSON only with "
                "keys summary, initiatives, and article. initiatives may contain at most 5 "
                "items. Each initiative needs kind, title, action, hypothesis, why, "
                "evidence (short paths or task IDs), expected (object), priority, language, "
                "and market. article needs title, angle, why, primary_keyword, language, "
                "market, and source_urls (copied URLs only).\n\n"
                + json.dumps(material, ensure_ascii=False, default=str)[:40_000]
            ),
        },
    ]


def _blocked_strategy(reason: str) -> dict[str, Any]:
    """Represent a report that is useful for inspection but not actionable."""

    return {
        "status": "blocked",
        "blocked_reason": reason[:1000],
        "summary": "Ada could not prepare recommendations from this report.",
        "initiatives": [],
        "article": {},
    }


def _normalized_strategy(raw: str, report: Mapping[str, Any], brief: Mapping[str, Any]) -> dict[str, Any]:
    decoded = extract_json(raw)
    if not isinstance(decoded, Mapping):
        raise SeoPlanningError("Ada's strategy response was not a valid object")
    initiatives = decoded.get("initiatives")
    if not isinstance(initiatives, list):
        raise SeoPlanningError("Ada's strategy response did not include initiatives")
    normalized: list[dict[str, Any]] = []
    for item in initiatives[:5]:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        action = str(item.get("action") or "").strip()
        if not title or not action:
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        expected = item.get("expected") if isinstance(item.get("expected"), Mapping) else {}
        normalized.append({
            "kind": str(item.get("kind") or "content").strip().lower()[:40],
            "title": title[:300],
            "action": action[:1200],
            "hypothesis": str(item.get("hypothesis") or "").strip()[:2000],
            "why": str(item.get("why") or "").strip()[:2000],
            "evidence": [str(value)[:300] for value in evidence[:8]],
            "expected": dict(expected),
            "priority": str(item.get("priority") or "normal").strip().lower(),
            "language": str(item.get("language") or brief["focus_market"]["language"]).strip().lower(),
            "market": str(item.get("market") or brief["focus_market"]["country"]).strip().upper(),
        })
    if not normalized:
        raise SeoPlanningError("Ada's strategy response contained no valid initiatives")
    article = decoded.get("article") if isinstance(decoded.get("article"), Mapping) else {}
    article_data = dict(article)
    for field_name, max_chars in (("title", 300), ("angle", 1000), ("why", 1000), ("primary_keyword", 200)):
        article_data[field_name] = str(article_data.get(field_name) or "").strip()[:max_chars]
    article_data["source_urls"] = [str(url) for url in article_data.get("source_urls") or [] if str(url).startswith(("http://", "https://"))][:8]
    if not article_data.get("title"):
        raise SeoPlanningError("Ada's strategy response did not include an article proposal")
    return {"status": "ready", "summary": str(decoded.get("summary") or "").strip()[:4000] or "Ada prepared a strategy from the available evidence.", "initiatives": normalized, "article": article_data}


def _language_supported(config: Mapping[str, Any], language: str) -> bool:
    existing = {
        str(locale).strip().lower()
        for locale in (((config.get("seo") or {}).get("research") or {}).get("existing_locales") or [])
        if str(locale).strip()
    }
    normalized = language.strip().lower()
    base = normalized.split("-", 1)[0]
    return normalized in existing or base in {locale.split("-", 1)[0] for locale in existing}


def _apply_language_boundary(
    strategy: dict[str, Any],
    config: Mapping[str, Any],
    brief: Mapping[str, Any],
) -> dict[str, Any]:
    focus = brief["focus_market"]
    focus_language = str(focus["language"])
    focus_market = str(focus["country"])
    initiatives = list(strategy.get("initiatives") or [])
    for initiative in initiatives:
        language = str(initiative.get("language") or focus_language).strip().lower()
        if _language_supported(config, language):
            continue
        initiative["kind"] = "localization"
        initiative["language"] = language
        initiative["market"] = str(initiative.get("market") or focus_market).upper()
        initiative["action"] = (
            f"Prepare a localization proposal for the {language} locale before creating or publishing content: "
            "define the URL prefix, navigation, canonicals, hreflang, sitemap, and editorial review."
        )
        initiative["why"] = "The selected language is not currently published by the site, so website structure needs owner review first."
        initiative["evidence"] = [*list(initiative.get("evidence") or []), "config.seo.research.existing_locales"][:8]

    article = dict(strategy.get("article") or {})
    article_language = str(article.get("language") or focus_language).strip().lower()
    article["language"] = article_language
    article["market"] = str(article.get("market") or focus_market).upper()
    article["unsupported_language"] = not _language_supported(config, article_language)
    if article["unsupported_language"] and not any(item.get("kind") == "localization" for item in initiatives):
        initiatives.append({
            "kind": "localization",
            "title": f"Prepare the {article_language} SEO locale proposal",
            "action": (
                f"Define the {article_language} locale URL prefix, navigation, canonicals, hreflang, sitemap, "
                "and editorial review before drafting localized pages."
            ),
            "hypothesis": "A reviewed locale structure is safer than creating duplicate or orphaned localized pages.",
            "why": "The selected article language is not currently published by the site.",
            "evidence": ["brief.focus_market", "config.seo.research.existing_locales"],
            "expected": {"metric": "approved localization plan"},
            "priority": "normal",
            "language": article_language,
            "market": article["market"],
        })
    strategy["initiatives"] = initiatives[:5]
    strategy["article"] = article
    return strategy


def _render_report(
    brief: Mapping[str, Any],
    report: Mapping[str, Any],
    strategy: Mapping[str, Any],
    news: list[Mapping[str, Any]] | None = None,
) -> str:
    freshness = report.get("freshness") if isinstance(report.get("freshness"), Mapping) else {}
    lines = [
        f"# Monthly SEO report: {brief['period']}",
        "",
        f"Focus market: {brief['focus_market']['language']}-{brief['focus_market']['country']}",
        f"Business goal: {brief['business_goal']}",
        "",
        "## What Ada found",
        str(strategy.get("summary") or "No summary was returned."),
        "",
        "## Data health",
        f"DataForSEO tasks: {freshness.get('dataforseo', {}).get('completed_count', 0)}/{freshness.get('dataforseo', {}).get('task_count', 0)} completed.",
    ]
    first_party = freshness.get("first_party", {}) if isinstance(freshness, Mapping) else {}
    for source in ("gsc", "ga4", "crawl"):
        state = first_party.get(source, {}) if isinstance(first_party, Mapping) else {}
        lines.append(f"- {source.upper()}: {state.get('status', 'unknown')}")
    competitor_state = freshness.get("competitor", {}) if isinstance(freshness, Mapping) else {}
    if isinstance(competitor_state, Mapping):
        if competitor_state.get("status") == "selected":
            lines.append(f"- COMPETITOR: {competitor_state.get('domain', 'selected')}")
        else:
            lines.append(f"- COMPETITOR: not selected ({competitor_state.get('reason', 'insufficient evidence')})")
    history = report.get("history") if isinstance(report.get("history"), Mapping) else {}
    windows = history.get("windows") if isinstance(history, Mapping) else {}
    lines.extend(["", "## Historical context", f"Six-month GSC history: {windows.get('history_state', 'unknown')}."])
    for month in (history.get("gsc_months") if isinstance(history, Mapping) else []) or []:
        lines.append(
            f"- {month.get('month')}: {month.get('clicks', 0)} clicks, {month.get('impressions', 0)} impressions"
            + ("" if month.get("available") else " (no stored data)")
        )
    if news:
        lines.extend(["", "## Current audience and news"])
        for item in news[:8]:
            url = f" ({item.get('url')})" if item.get("url") else ""
            lines.append(f"- {item.get('text', '')}{url}")
    if strategy.get("status") == "blocked":
        lines.extend([
            "",
            "## Ada's preparation status",
            "Recommendations were not prepared.",
            str(strategy.get("blocked_reason") or "The strategy planner is unavailable."),
        ])
        return "\n".join(lines)[:30_000]
    lines.extend(["", "## What Ada suggests next"])
    for index, initiative in enumerate(strategy.get("initiatives") or [], 1):
        evidence = ", ".join(str(value) for value in initiative.get("evidence") or []) or "not specified"
        lines.extend([
            f"{index}. **{initiative['title']}**: {initiative['action']}",
            f"   Why: {initiative.get('why') or initiative.get('hypothesis') or 'See linked evidence.'}",
            f"   Evidence: {evidence}",
        ])
    if strategy["article"].get("unsupported_language"):
        lines.extend([
            "",
            "## Article opportunity",
            f"Localization proposal required before drafting **{strategy['article'].get('title', 'the selected article')}**.",
        ])
    else:
        lines.extend(["", "## Article Ada prepared", f"**{strategy['article'].get('title', 'Article draft')}**", str(strategy["article"].get("why") or "")])
    return "\n".join(lines)[:30_000]


def _initiative_action(
    context: Mapping[str, Any],
    cycle_id: int,
    initiative: Mapping[str, Any],
    draft_id: int | None = None,
    site_change: bool = False,
) -> OwnerAction:
    title = str(initiative["title"])
    action = str(initiative["action"])
    source = "seo-strategy:" + hashlib.sha256(f"{cycle_id}:{title}:{action}".encode()).hexdigest()[:20]
    priority = str(initiative.get("priority") or "normal").lower()
    resolved_priority = ActionPriority.URGENT if priority == "urgent" else ActionPriority.OPTIONAL if priority == "optional" else ActionPriority.NORMAL
    return OwnerAction(
        capability_id="review.site_change" if site_change else "content.suggestion",
        provider_id="site-agent",
        title=title,
        summary=action,
        action_label="Review website change" if site_change else "Review Ada's SEO proposal",
        priority=resolved_priority,
        requirement=ActionRequirement.OWNER_DECISION,
        source_ref=source,
        dedupe_key=source,
        draft_id=draft_id,
        payload={
            "source": "monthly_seo_strategy",
            "cycle_id": cycle_id,
            "kind": initiative.get("kind", "content"),
            "hypothesis": initiative.get("hypothesis", ""),
            "why": initiative.get("why", ""),
            "evidence": initiative.get("evidence", []),
            "expected": initiative.get("expected", {}),
            "language": initiative.get("language"),
            "market": initiative.get("market"),
            "effect": "site_mutation" if site_change else "proposal",
        },
    )


_SITE_CHANGE_KINDS = {
    "site_change",
    "technical",
    "technical_repair",
    "internal_linking",
    "title_change",
    "meta_change",
    "conversion_page",
    "localization",
    "website",
}


def _is_site_change(initiative: Mapping[str, Any]) -> bool:
    return str(initiative.get("kind") or "").strip().lower() in _SITE_CHANGE_KINDS


def _context_action(memory: Any, period: str, message: str) -> None:
    source_ref = f"seo-research-context:{period}"
    OwnerActionService(memory).create(
        OwnerAction(
            capability_id="seo.research.context",
            provider_id="site-agent",
            title="Complete Ada's SEO research context",
            summary=message[:1000],
            action_label="Add SEO context",
            priority=ActionPriority.NORMAL,
            requirement=ActionRequirement.OWNER_INFORMATION,
            source_ref=source_ref,
            dedupe_key=source_ref,
            payload={
                "source": "monthly_seo_research",
                "period": period,
                "missing_context": message[:1000],
            },
        ),
        reuse_terminal=True,
    )


def _process_report(context: dict[str, Any], request: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    memory = context["memory"]
    report_id = str(request.get("report_id") or "")
    report = payload.get("report")
    brief = request.get("brief")
    if not report_id or not isinstance(report, Mapping) or not isinstance(brief, Mapping):
        raise SeoPlanningError("CrawlSEO returned an incomplete research report")
    existing_cycle = memory.get_strategy_cycle(report_id)
    if existing_cycle is not None and existing_cycle.get("status") == "completed":
        memory.update_seo_research_request(
            request["id"],
            status=str(payload.get("status") or "completed").lower(),
            completed_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        )
        return

    if existing_cycle is not None:
        saved = existing_cycle.get("report_json") if isinstance(existing_cycle.get("report_json"), Mapping) else {}
        saved_brief = saved.get("brief")
        saved_report = saved.get("report")
        saved_strategy = saved.get("strategy")
        if not isinstance(saved_brief, Mapping) or not isinstance(saved_report, Mapping) or not isinstance(saved_strategy, Mapping):
            raise SeoPlanningError("stored SEO strategy cycle is incomplete")
        brief = saved_brief
        report = saved_report
        strategy = dict(saved_strategy)
        cycle = existing_cycle
    else:
        material = {
            "brief": brief,
            "research_report": report,
            "recent_news": _news_material(memory),
            "themes": memory.kv_get("themes", []),
            "recent_decisions": memory.recent_decisions(limit=10),
            "active_initiatives": memory.list_strategy_initiatives(limit=30),
        }
        llm = context.get("llm")
        if llm is None:
            strategy = _blocked_strategy("Ada's strategy planner is unavailable; no recommendation was invented.")
        else:
            try:
                raw = llm.chat(_strategy_prompt(material), json_mode=True, temperature=0.4)
                strategy = _normalized_strategy(raw, report, brief)
            except Exception as exc:  # noqa: BLE001 — preserve the evidence and expose the blocked planner boundary
                strategy = _blocked_strategy(f"Ada's strategy planner failed: {str(exc)[:700]}")
        strategy = _apply_language_boundary(strategy, context["config"], brief)

        report_hash = hashlib.sha256(json.dumps(report, sort_keys=True, default=str).encode()).hexdigest()
        report_body = _render_report(brief, report, strategy, _news_material(memory))
        report_artifact = memory.create_artifact(
            Artifact(
                kind=ArtifactKind.SEO_REPORT,
                title=f"Monthly SEO report {brief['period']}",
                summary=str(strategy.get("summary") or "Monthly SEO evidence report")[:500],
                renderer="seo_report",
                capability_id="seo.report.read",
                provider_id="site-agent",
                content_hash="sha256:" + hashlib.sha256(report_body.encode()).hexdigest(),
                preview_data={
                    "body": report_body,
                    "period": brief["period"],
                    "report_id": report_id,
                    "report_hash": report_hash,
                },
            )
        )
        report_draft_id = memory.save_draft(
            title=f"Monthly SEO report {brief['period']}",
            body=report_body,
            kind="report",
            meta={
                "period": brief["period"],
                "report_id": report_id,
                "report_hash": report_hash,
                "artifact_id": report_artifact.artifact_id,
                "focus_market": brief["focus_market"],
            },
        )
        cycle = memory.create_strategy_cycle(
            report_id,
            str(brief["period"]),
            report_hash,
            {"brief": brief, "report": report, "strategy": strategy, "recent_news": _news_material(memory)},
            summary=str(strategy.get("summary") or ""),
            report_draft_id=report_draft_id,
            report_artifact_id=report_artifact.artifact_id,
        )
    completed_seeds = {
        _normalize_seed(str((task.get("input") or {}).get("seed") or ""))
        for task in (report.get("dataforseo") or [])
        if isinstance(task, Mapping)
        and task.get("kind") == "keyword_seed"
        and task.get("status") == "completed"
        and isinstance(task.get("input"), Mapping)
    }
    for selection in memory.list_seo_seed_selections(int(request["id"])):
        if _normalize_seed(str(selection.get("seed") or "")) in completed_seeds:
            memory.mark_seo_seed_researched(
                int(selection["seed_id"]),
                report_id,
                freshness="current" if str(payload.get("status") or "").lower() == "completed" else "aging",
            )
    action_service: OwnerActionService = context.get("owner_action_service") or OwnerActionService(memory)
    article_draft_id: int | None = None
    article_title = str((strategy.get("article") or {}).get("title") or "").strip()
    existing_titles = {str(d.get("title") or "").strip().lower() for d in memory.list_drafts(limit=200) if d.get("status") in {"pending", "approved"}}
    if article_title and not strategy["article"].get("unsupported_language") and article_title.lower() not in existing_titles:
        try:
            article_draft_id = brain_article.draft_article_for_strategy(
                context,
                {
                    **dict(strategy["article"]),
                    "research_report_id": report_id,
                    "strategy_cycle_id": cycle["id"],
                },
                report,
            )
        except Exception as exc:  # noqa: BLE001 — the evidence report remains useful without an LLM draft
            memory.record_action("seo_strategy", f"article draft skipped for report {report_id}: {str(exc)[:300]}")

    existing_initiatives = {
        str(row.get("title") or "").strip().lower(): row
        for row in memory.list_strategy_initiatives(cycle["id"])
    }
    for initiative in strategy.get("initiatives") or []:
        if not isinstance(initiative, Mapping):
            continue
        initiative_key = str(initiative.get("title") or "").strip().lower()
        existing_initiative = existing_initiatives.get(initiative_key)
        if existing_initiative is not None:
            continue
        draft_id = article_draft_id if initiative.get("kind") == "content" and article_draft_id is not None else None
        # A strategy record is evidence-backed advice, not an implementation
        # candidate. Until Ada has prepared and validated a concrete Payload or
        # design candidate, it must remain a proposal with no mutation approval.
        site_change = False
        action = action_service.create(
            _initiative_action(context, cycle["id"], initiative, draft_id, site_change),
            reuse_terminal=True,
        )
        artifact_id = None
        approval_id = None
        if _is_site_change(initiative):
            memory.record_action(
                "seo_strategy",
                f"initiative '{initiative.get('title', 'untitled')}' remains a proposal until Ada prepares a validated implementation candidate",
            )
        if existing_initiative is not None:
            memory.update_strategy_initiative(
                existing_initiative["id"],
                owner_action_id=action.id,
                artifact_id=artifact_id,
                approval_id=approval_id,
                draft_id=draft_id,
            )
        else:
            memory.create_strategy_initiative(
                cycle["id"],
                kind=str(initiative.get("kind") or "content"),
                title=str(initiative["title"]),
                summary=str(initiative["action"]),
                hypothesis=str(initiative.get("hypothesis") or ""),
                rationale=str(initiative.get("why") or ""),
                evidence=list(initiative.get("evidence") or []),
                expected=dict(initiative.get("expected") or {}),
                language=str(initiative.get("language") or brief["focus_market"]["language"]),
                market=str(initiative.get("market") or brief["focus_market"]["country"]),
                priority=str(initiative.get("priority") or "normal"),
                owner_action_id=action.id,
                artifact_id=artifact_id,
                approval_id=approval_id,
                draft_id=draft_id,
            )
        existing_initiatives[initiative_key] = {"artifact_id": artifact_id}
    report_status = str(payload.get("status") or "completed").lower()
    if report_status not in {"completed", "partial"}:
        report_status = "completed"
    memory.update_seo_research_request(
        request["id"],
        status=report_status,
        completed_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    )
    memory.update_strategy_cycle(cycle["id"], status="completed")
    memory.record_action("seo_strategy", f"report {report_id}: cycle #{cycle['id']}, {len(strategy.get('initiatives') or [])} initiative(s)")


def run(context: dict[str, Any]) -> None:
    config = context["config"]
    research = _research_config(config)
    memory = context["memory"]
    if not research.get("enabled", False):
        return
    service = context.get("crawlseo_service")
    if service is None:
        memory.record_action("seo_research", "skipped: CrawlSEO provider is unavailable")
        return
    period = previous_period(config)
    request = memory.get_seo_research_request(period, PACKAGE_VERSION)
    if request is None:
        try:
            brief, selections = build_research_brief(memory, config, period, context.get("llm"))
            key = f"seo:{period}:{PACKAGE_VERSION}"
            try:
                request = memory.create_seo_research_request(period, PACKAGE_VERSION, key, brief)
            except sqlite3.IntegrityError:
                request = memory.get_seo_research_request(period, PACKAGE_VERSION)
            if request is None:
                raise SeoPlanningError("SEO research request could not be persisted")
            for ordinal, selection in enumerate(selections, 1):
                seed_row = memory.upsert_seo_seed(
                    _normalize_seed(selection["seed"]),
                    brief["focus_market"]["language"],
                    brief["focus_market"]["country"],
                    cluster=selection.get("cluster", ""),
                    objective=brief["business_goal"],
                    priority="high" if selection["slot_type"] == "strategic" else "normal",
                )
                memory.create_seo_seed_selection(
                    request["id"], seed_row["id"], ordinal, selection["slot_type"], selection["rationale"]
                )
        except SeoPlanningError as exc:
            _context_action(memory, period, str(exc))
            memory.record_action("seo_research", f"not requested for {period}: {str(exc)[:500]}")
            return
        except Exception as exc:  # noqa: BLE001 — scheduler must continue and owner gets a concrete action
            message = str(exc)[:500]
            memory.record_action("seo_research", f"not requested for {period}: {message}")
            return

    if request and not request.get("report_id"):
        brief = request.get("brief")
        if not isinstance(brief, Mapping):
            memory.update_seo_research_request(request["id"], status="failed", error="stored SEO brief is invalid")
            _context_action(memory, period, "The stored SEO brief is invalid and must be rebuilt")
            return
        key = str(request.get("idempotency_key") or f"seo:{period}:{PACKAGE_VERSION}")
        try:
            response = service.request_research_report(dict(brief), key)
            report_id = str(response.get("report_id") or "")
            if not report_id:
                raise SeoPlanningError("CrawlSEO did not return a research report ID")
            request = memory.update_seo_research_request(
                request["id"], report_id=report_id, status=str(response.get("status") or "requested"), requested_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            )
            memory.record_action("seo_research", f"requested {period} report {report_id} for {brief['focus_market']['language']}-{brief['focus_market']['country']}")
        except SeoPlanningError as exc:
            memory.update_seo_research_request(request["id"], status="failed", error=str(exc)[:500])
            _context_action(memory, period, str(exc))
            memory.record_action("seo_research", f"not requested for {period}: {str(exc)[:500]}")
            return
        except Exception as exc:  # noqa: BLE001 — scheduler must continue and owner gets a concrete action
            message = str(exc)[:500]
            memory.update_seo_research_request(request["id"], status="failed", error=message)
            memory.record_action("seo_research", f"not requested for {period}: {message}")
            return

    if not request or not request.get("report_id"):
        return
    report_id = str(request["report_id"])
    status = service.research_report_status(report_id)
    status_value = str(status.get("status") or "").lower()
    memory.update_seo_research_request(request["id"], status=status_value or "waiting")
    if status_value not in {"completed", "partial"}:
        if status_value in TERMINAL_REPORT_STATUSES:
            memory.update_seo_research_request(request["id"], status=status_value, error=str(status.get("error_code") or "research failed"))
        return
    payload = service.research_report(report_id)
    _process_report(context, request, payload)


__all__ = [
    "SeoPlanningError",
    "build_research_brief",
    "choose_focus_market",
    "previous_period",
    "run",
    "select_seeds",
]
