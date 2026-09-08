"""Bounded research planning for one customer incubation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.design_intake_contracts import DesignIntakeDraft
from ..core.llm import extract_json


class IncubationResearchPlanningError(ValueError):
    """A research plan could not be produced within the planning contract."""


_COMMUNITY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,4})?$", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_FEED_URL = re.compile(r"^https?://[^\s@<>]{3,300}$", re.IGNORECASE)


@dataclass(frozen=True)
class IncubationResearchPlan:
    """Validated planner output; it contains candidates, not business facts."""

    intent: str
    owner_language: str
    subjects: tuple[str, ...]
    markets: tuple[str, ...]
    candidate_communities: tuple[dict[str, Any], ...] = ()
    candidate_feeds: tuple[dict[str, Any], ...] = ()
    query_terms_by_language: dict[str, tuple[str, ...]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "owner_language": self.owner_language,
            "subjects": list(self.subjects),
            "markets": list(self.markets),
            "candidate_communities": [dict(item) for item in self.candidate_communities],
            "candidate_feeds": [dict(item) for item in self.candidate_feeds],
            "query_terms_by_language": {
                key: list(value) for key, value in (self.query_terms_by_language or {}).items()
            },
        }


def base_plan(draft: DesignIntakeDraft, *, owner_language: str = "en") -> IncubationResearchPlan:
    """Derive a safe research intent without asking a model to invent context."""
    if not isinstance(draft, DesignIntakeDraft):
        raise IncubationResearchPlanningError("intake draft is invalid")
    language = _language(owner_language) or "en"
    offer = _value_text(draft, "business.offer_summary")
    services = _values(draft.value("business.primary_services"))
    audience = _value_text(draft, "audience.primary")
    location = _values(draft.owner_confirmed_value("business.location"))
    service_area = _values(draft.owner_confirmed_value("business.service_area"))
    subjects = _unique((*services, audience, offer), limit=8)
    markets = _unique((*location, *service_area), limit=4)
    intent = " ".join(_unique((*subjects, *markets), limit=16))[:2_000]
    terms = tuple(_unique(_TOKEN.findall(intent), limit=50))
    return IncubationResearchPlan(
        intent=intent,
        owner_language=language,
        subjects=subjects,
        markets=markets,
        query_terms_by_language={language: terms} if terms else {},
    )


class LLMIncubationResearchPlanner:
    """Ask the model only for bounded community candidates and query terms."""

    def __init__(self, llm: Any, config: Mapping[str, Any] | None = None) -> None:
        self.llm = llm
        limits = config if isinstance(config, Mapping) else {}
        self.max_communities = max(1, min(int(limits.get("max_sources_per_pass", 8)), 8))
        settings = config.get("planner") if isinstance(config, Mapping) else None
        self.config = dict(settings) if isinstance(settings, Mapping) else {}

    def plan(
        self,
        draft: DesignIntakeDraft,
        *,
        owner_language: str = "en",
        excluded_communities: tuple[str, ...] | list[str] = (),
    ) -> IncubationResearchPlan:
        result = base_plan(draft, owner_language=owner_language)
        if self.llm is None or not callable(getattr(self.llm, "chat", None)):
            raise IncubationResearchPlanningError("research planner is unavailable")
        excluded = {self._community_name(item).casefold() for item in excluded_communities}
        prompt = (
            "You are proposing bounded public research for a website intake. "
            "Return likely Reddit community names only; do not claim that a community "
            "exists, is active, or is relevant. Do not return URLs, user names, quotes, "
            "business facts, or recommendations. A candidate will be verified before it "
            "is read. Use the owner's language for query terms when possible and preserve "
            "the source language for any international terms.\n\n"
            "Return JSON with exactly these keys: "
            '{"candidate_communities":[{"name":"...","language":"en",'
            '"rationale":"..."}],"candidate_feeds":[{"url":"https://...","name":"...",'
            '"language":"en","rationale":"..."}],"query_terms_by_language":{"en":["..."]}}\n\n'
            "candidate_feeds are OPTIONAL public blog/category pages likely to publish "
            "RSS about the same subjects; the host verifies readability before reading "
            "them. Only http(s) URLs without query credentials are accepted.\n\n"
            f"Owner language: {result.owner_language}\n"
            f"Research intent: {result.intent}\n"
            f"Subjects: {list(result.subjects)}\n"
            f"Markets: {list(result.markets)}\n"
            f"Limits: propose at most {self.max_communities} communities, 3 feeds, "
            "and 50 terms; the host will verify every candidate before reading it.\n"
            f"Excluded community names: {sorted(item for item in excluded if item)}"
        )
        for _attempt in range(2):
            try:
                raw = self.llm.chat(
                    [{"role": "system", "content": prompt}],
                    model=str(self.config.get("model") or "") or None,
                    json_mode=True,
                    temperature=float(self.config.get("temperature", 0.1)),
                    max_tokens=int(self.config.get("max_tokens", 2000)),
                    timeout_seconds=float(self.config.get("timeout_seconds", 90)),
                    max_retries=int(self.config.get("max_retries", 0)),
                )
                decoded = extract_json(raw)
                if not isinstance(decoded, Mapping):
                    raise IncubationResearchPlanningError("research planner returned invalid JSON")
                break
            except Exception as exc:  # noqa: BLE001 - planner failure must not fail intake
                if _attempt == 1:
                    raise IncubationResearchPlanningError(str(exc)[:500]) from exc
        communities = self._communities(decoded.get("candidate_communities"), excluded, limit=self.max_communities)
        feeds = self._feeds(decoded.get("candidate_feeds"), limit=3)
        terms = self._terms(decoded.get("query_terms_by_language"), result.owner_language)
        return IncubationResearchPlan(
            intent=result.intent,
            owner_language=result.owner_language,
            subjects=result.subjects,
            markets=result.markets,
            candidate_communities=communities,
            candidate_feeds=feeds,
            query_terms_by_language=terms or result.query_terms_by_language or {},
        )

    @staticmethod
    def _community_name(value: Any) -> str:
        name = str(value or "").strip()
        if "://" in name:
            return ""
        name = re.sub(r"^/?r/", "", name, flags=re.IGNORECASE).strip("/")
        return name if _COMMUNITY_NAME.fullmatch(name) else ""

    @classmethod
    def _communities(
        cls,
        value: Any,
        excluded: set[str],
        *,
        limit: int = 8,
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, list):
            return ()
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in value[:limit]:
            if not isinstance(raw, Mapping):
                continue
            name = cls._community_name(raw.get("name"))
            key = name.casefold()
            if not name or key in seen or key in excluded:
                continue
            language = _language(raw.get("language")) or "en"
            rationale = _safe_text(raw.get("rationale"), 500)
            result.append({
                "name": name,
                "language": language,
                "rationale": rationale,
                "status": "candidate",
            })
            seen.add(key)
        return tuple(result)

    @classmethod
    def _feeds(
        cls,
        value: Any,
        *,
        limit: int = 3,
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, list):
            return ()
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in value[:limit]:
            if not isinstance(raw, Mapping):
                continue
            url = str(raw.get("url") or "").strip()[:300]
            if not _FEED_URL.fullmatch(url) or not _has_host(url) or url.casefold() in seen:
                continue
            seen.add(url.casefold())
            result.append({
                "url": url,
                "name": _safe_text(raw.get("name"), 160) or url,
                "language": _language(raw.get("language")) or "en",
                "rationale": _safe_text(raw.get("rationale"), 500),
                "status": "candidate",
            })
        return tuple(result)

    @staticmethod
    def _terms(value: Any, owner_language: str) -> dict[str, tuple[str, ...]]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, tuple[str, ...]] = {}
        for raw_language, raw_terms in list(value.items())[:20]:
            language = _language(raw_language)
            if not language or not isinstance(raw_terms, list):
                continue
            terms = tuple(_unique((_safe_text(item, 200) for item in raw_terms), limit=50))
            if terms:
                result[language] = terms
        return result


def _language(value: Any) -> str:
    language = str(value or "").strip().lower().replace("_", "-")
    return language if _LANGUAGE.fullmatch(language) else ""


def _has_host(url: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0]
    return "." in host or host.casefold() == "localhost"


def _safe_text(value: Any, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or "http://" in text.lower() or "https://" in text.lower() or "@" in text:
        return ""
    return " ".join(text.split())[:maximum]


def _value_text(draft: DesignIntakeDraft, path: str) -> str:
    value = draft.value(path)
    return _safe_text(value, 500)


def _values(value: Any) -> tuple[str, ...]:
    values = [value] if isinstance(value, str) else list(value or ()) if isinstance(value, (list, tuple, set)) else []
    return tuple(item for item in (_safe_text(value, 500) for value in values) if item)


def _unique(values: Any, *, limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = _safe_text(value, 500)
        if text and text.casefold() not in {item.casefold() for item in result}:
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


__all__ = [
    "IncubationResearchPlan",
    "IncubationResearchPlanningError",
    "LLMIncubationResearchPlanner",
    "base_plan",
]
