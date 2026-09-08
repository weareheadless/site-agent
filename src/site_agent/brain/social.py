"""Ada's grounded social-post planner.

This module chooses and writes the editorial brief. Cicero remains responsible
for media selection, visual rendering, and provider-specific work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..application.social_posts import SocialPostBrief, SocialPostError
from ..core.contracts import ArtifactKind
from ..core.llm import extract_json
from . import inner_voice
from .prompts import memory_context


class SocialPlanningError(RuntimeError):
    pass


def gather(memory: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    rows = memory.recent_observations(limit=80)
    usable = [
        row for row in rows
        if row.get("source") not in {"self", "inner_voice", "dream", "awaken", "identity_shift"}
        and str(row.get("text") or "").strip()
    ]
    sources: list[dict[str, str]] = []
    known_urls: set[str] = set()
    for row in usable:
        link = str((row.get("meta") or {}).get("link") or "").strip()
        if not link.startswith(("http://", "https://")) or link in known_urls:
            continue
        known_urls.add(link)
        title = " ".join(str(row.get("text") or "").split())[:300]
        sources.append({"title": title or "Source", "url": link})
    ga_snapshot = memory.latest_snapshot("ga4") or {}
    ga = ga_snapshot.get("data") if isinstance(ga_snapshot, Mapping) else {}
    ga = ga if isinstance(ga, Mapping) else {}
    social_artifacts = memory.list_artifacts(kind=ArtifactKind.SOCIAL_POST.value, limit=12)
    previous_posts = [
        {
            "title": artifact.title,
            "text": str(artifact.preview_data.get("text") or "")[:300],
            "format": artifact.preview_data.get("format", ""),
        }
        for artifact in social_artifacts
    ]
    decisions = []
    for approval in memory.list_approval_requests(limit=100):
        artifact = memory.get_artifact(approval.artifact_id)
        if artifact is not None and artifact.kind is ArtifactKind.SOCIAL_POST:
            decisions.append({"status": approval.status.value, "text": str(artifact.preview_data.get("text") or "")[:240]})
    persona = config.get("persona") or {}
    themes = memory.kv_get("themes", [])
    strategist_cards = memory.kv_get("strategist_cards")
    return {
        "observations": [
            {
                "source": row.get("source", ""),
                "text": str(row.get("text") or "")[:700],
                "link": (row.get("meta") or {}).get("link", ""),
            }
            for row in usable[:30]
        ],
        "sources": sources[:20],
        "known_source_urls": sorted(known_urls),
        "analytics": {
            "current_week": ga.get("current_week", {}),
            "top_pages": (ga.get("top_pages") if isinstance(ga.get("top_pages"), list) else [])[:8],
            "delta_pct": ga.get("delta_pct", {}),
        },
        "themes": themes[:12] if isinstance(themes, list) else [],
        "strategist_cards": (
            strategist_cards.get("cards", [])[:5]
            if isinstance(strategist_cards, Mapping) and isinstance(strategist_cards.get("cards"), list) else []
        ),
        "previous_social_posts": previous_posts,
        "social_decisions": decisions[:12],
        "audience": str(persona.get("audience") or ""),
        "taboo": persona.get("taboo") or [],
        "social_preferences": config.get("social") or {},
        "memory": memory_context(memory)[:5000],
    }


def _prompt(persona: str, material: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        persona
        + "\n\nYou are planning one grounded social post for the site's real audience. "
        "Choose a useful topic from the supplied observations, learning, site signals, "
        "or analytics. Never invent facts, statistics, experiences, live conditions, "
        "or source URLs. Do not repeat a recent social post. Avoid every taboo topic. "
        "The caption must stand on its own and the visual_message is the short message "
        "Cicero should express on the artwork."
    )
    user = (
        "Material available to Ada:\n"
        + json.dumps(material, ensure_ascii=False, default=str)[:12000]
        + "\n\nReply with JSON only, using exactly these keys:\n"
        '{"goal":"...","audience":"...","brief":"...","caption":"...",'
        '"visual_message":"...","format":"single|carousel|diaporama|video",'
        '"language":"en","media_names":[],"animated":false,'
        '"source_context":[{"title":"copied source title","url":"copied source URL"}],'
        '"constraints":{"avoid":["..."]}}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _known_source_check(brief: SocialPostBrief, material: dict[str, Any]) -> None:
    known = set(material.get("known_source_urls") or [])
    for source in brief.source_context:
        if source["url"] not in known:
            raise SocialPlanningError("planner returned a source URL not present in Ada's observations")


def plan(context: dict[str, Any]) -> SocialPostBrief:
    llm = context.get("llm")
    if llm is None:
        raise SocialPlanningError("llm client missing; cannot plan a social post")
    material = gather(context["memory"], context.get("config") or {})
    if not material["observations"] and not material["themes"] and not material["analytics"].get("top_pages"):
        raise SocialPlanningError("no credible material is available for a social post")
    raw = llm.chat(
        _prompt(context.get("persona_prompt") or "", material),
        json_mode=True,
        temperature=0.7,
    )
    decoded = extract_json(raw)
    if not isinstance(decoded, Mapping):
        raise SocialPlanningError("social planner returned invalid JSON")
    try:
        brief = SocialPostBrief.from_mapping(decoded)
    except SocialPostError as exc:
        raise SocialPlanningError(str(exc)) from exc
    _known_source_check(brief, material)
    social_config = (context.get("config") or {}).get("social") or {}
    default_format = social_config.get("default_format")
    if brief.format is None and default_format:
        if default_format not in {"single", "carousel", "diaporama", "video"}:
            raise SocialPlanningError("social.default_format is unsupported")
        brief = replace(brief, format=default_format)
    allowed_languages = {
        str(language).lower() for language in (social_config.get("languages") or []) if str(language).strip()
    }
    if allowed_languages and brief.language and brief.language.lower() not in allowed_languages:
        raise SocialPlanningError("planner selected a language outside social.languages")

    subject = json.dumps(brief.to_payload(), ensure_ascii=False, sort_keys=True)
    problems = inner_voice.challenge(
        context,
        "social post plan",
        subject,
        "Grounding material:\n" + json.dumps(material, ensure_ascii=False, default=str)[:5000],
    )
    if problems:
        raise SocialPlanningError("Ada's inner voice rejected the social plan: " + "; ".join(problems[:3]))
    return brief


def run(context: dict[str, Any]) -> Any:
    service = context.get("social_post_service")
    if service is None:
        raise SocialPlanningError("Cicero social provider is unavailable")
    brief = plan(context)
    result = service.prepare(brief)
    context["memory"].record_action(
        "social_post",
        f"prepared approval #{result.approval.approval_id} from Cicero post {result.provider_operation_id}",
    )
    return result


__all__ = ["SocialPlanningError", "gather", "plan", "run"]
