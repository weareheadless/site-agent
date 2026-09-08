"""Hybrid novelty context for one incubation design request."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ..core.design_contracts import SiteIntake
from ..core.incubation_contracts import CreativeEpisode, NoveltyContext, ProvisioningBundle
from ..core.intake_ada_store import IntakeAdaStore
from .intake_ada_memory import IntakeAdaMemoryError, IntakeAdaMemoryService


class NoveltyServiceError(ValueError):
    """Novelty retrieval could not produce a safe bounded context."""


class NoveltyService:
    def __init__(self, store: IntakeAdaStore, *, max_matches: int = 8) -> None:
        self.memory = IntakeAdaMemoryService(store)
        self.max_matches = max(1, min(int(max_matches), 20))

    def context_for(self, intake: SiteIntake, *, constraints: list[str] | None = None) -> NoveltyContext:
        if not isinstance(intake, SiteIntake):
            raise NoveltyServiceError("site intake is invalid")
        query, fingerprint = _sanitized_design_query(intake)
        try:
            matches = self.memory.recall(query, fingerprint=fingerprint, limit=self.max_matches)
        except IntakeAdaMemoryError as exc:
            raise NoveltyServiceError(str(exc)[:500]) from exc
        bounded = []
        for item in matches:
            bounded.append({
                "episode_id": str(item.get("episode_id") or ""),
                "score": round(max(0.0, min(1.0, float(item.get("score") or 0.0))), 6),
                "semantic_score": round(max(0.0, min(1.0, float(item.get("semantic_score") or 0.0))), 6),
                "structured_score": round(max(0.0, min(1.0, float(item.get("structured_score") or 0.0))), 6),
                "patterns": [str(value)[:200] for value in (item.get("patterns") or [])[:20]],
            })
        return NoveltyContext.from_dict({
            "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "constraints": list(constraints or _constraints_from_matches(bounded)),
            "matches": bounded,
        })

    def record_accepted_bundle(self, bundle: ProvisioningBundle) -> CreativeEpisode:
        """Persist only an abstract design lesson after customer handoff."""
        if not isinstance(bundle, ProvisioningBundle):
            raise NoveltyServiceError("provisioning bundle is invalid")
        site_intake = bundle.intake_revision.get("site_intake")
        site = site_intake.get("site") if isinstance(site_intake, Mapping) else {}
        pages = site.get("required_pages") if isinstance(site, Mapping) else []
        pages = pages if isinstance(pages, list) else []
        page_count = min(len(pages), 12) or 1
        commerce = any(str(page).strip().casefold().rstrip("/") in {"shop", "store"} for page in pages)
        episode_id = "episode_" + hashlib.sha256(bundle.bundle_id.encode("utf-8")).hexdigest()[:32]
        episode = CreativeEpisode.from_dict({
            "episode_id": episode_id,
            "created_at": datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(),
            "engagement_outcome": "accepted",
            "design_fingerprint": {
                "layout_topology": [f"pages:{page_count}", "commerce" if commerce else "service-led"],
                "type_roles": ["display", "body"],
                "palette_shape": ["owner-directed"],
                "motion_patterns": ["restrained"],
                "navigation_pattern": "primary-action",
                "component_rhythm": ["intro", "proof", "action"],
            },
            "copy_fingerprint": {
                "opening_pattern": "direct-introduction",
                "section_rhythm": ["intro", "proof", "action"],
                "cta_pattern": "primary-action",
                "repeated_motifs": [],
            },
            "quality": {"accepted": True, "critic_categories": [], "revision_count": min(max(len(bundle.design_history) - 1, 0), 100)},
            "reflection": {"habits_repeated": [], "departures_that_worked": [], "approaches_to_avoid": [], "techniques_to_reuse_carefully": []},
            "semantic_text": f"accepted website design with {page_count} required pages and {'commerce' if commerce else 'service-led'} information architecture",
        })
        try:
            return self.memory.record_episode(episode)
        except IntakeAdaMemoryError as exc:
            raise NoveltyServiceError(str(exc)[:500]) from exc


def _sanitized_design_query(intake: SiteIntake) -> tuple[str, dict[str, list[str]]]:
    pages = list(intake.site.get("required_pages") or ())
    page_shape = ["home", "about", "services", "contact", "other"]
    if pages:
        page_count = len(pages)
    else:
        page_count = 1
    voice = _abstract_terms(str(intake.brand.get("voice") or ""))
    query = "website design composition page-count={} voice={}".format(page_count, " ".join(voice[:8]))
    fingerprint = {
        "design.layout_topology": [f"pages:{min(page_count, 12)}"],
        "design.type_roles": ["display", "body"],
        "design.navigation_pattern": ["primary-action"],
        "copy.section_rhythm": ["intro", "proof", "action"],
    }
    if any(str(page).strip().casefold() in {"/shop", "/store"} for page in pages):
        fingerprint["design.layout_topology"].append("commerce")
    return query, fingerprint


def _abstract_terms(value: str) -> list[str]:
    stop = {"and", "the", "with", "for", "that", "site", "brand", "voice"}
    return [term for term in re.findall(r"[a-z]{3,}", value.casefold()) if term not in stop][:12]


def _constraints_from_matches(matches: list[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in matches:
        if float(item.get("score") or 0.0) < 0.8:
            continue
        for pattern in item.get("patterns") or []:
            text = str(pattern).strip()
            if text and text not in result:
                result.append(f"avoid repeating high-similarity pattern: {text}")
    return result[:20]


__all__ = ["NoveltyService", "NoveltyServiceError"]
