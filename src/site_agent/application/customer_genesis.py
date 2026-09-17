"""Provenance-aware customer-Ada genesis revisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.contracts import ContractError
from ..core.design_intake_contracts import DesignIntakeDraft, IntakeOrigin
from ..core.incubation_contracts import CustomerAdaGenesis, EvidenceOrigin, GenesisEvidence


class CustomerGenesisServiceError(ValueError):
    """A customer genesis proposal cannot be safely persisted."""


class CustomerGenesisService:
    """Build and persist immutable genesis revisions inside one incubation."""

    def __init__(self, memory) -> None:
        self.memory = memory

    def current(self) -> CustomerAdaGenesis:
        row = self.memory.get_customer_genesis_revision()
        return row["genesis"] if row else CustomerAdaGenesis.empty()

    def propose_from_session(self, session: Mapping[str, Any], *, updates: Mapping[str, Any] | None = None) -> CustomerAdaGenesis:
        try:
            draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
            intake = draft.to_site_intake()
        except (ContractError, TypeError, ValueError) as exc:
            raise CustomerGenesisServiceError(str(exc)[:500]) from exc
        current_row = self.memory.get_customer_genesis_revision()
        current = current_row["genesis"] if current_row else CustomerAdaGenesis.empty()
        next_revision = int(current_row["revision"]) + 1 if current_row else 1
        source_id = str(session.get("session_id") or "owner_intake").strip()
        business = intake.business
        audience = intake.audience
        brand = intake.brand
        source_rows = self.memory.list_research_sources(limit=500)
        candidate_feeds = [
            str(item.get("source_id"))
            for item in source_rows
            if item.get("trust_state") != "excluded" and not item.get("excluded")
        ]
        excluded_sources = [
            str(item.get("source_id"))
            for item in source_rows
            if item.get("trust_state") == "excluded" or item.get("excluded")
        ]
        asset_notes = _asset_visual_notes(session.get("assets") or ())
        sections = {
            "business_world": {
                **current.business_world,
                "purpose": business.get("offer_summary") or current.business_world.get("purpose", ""),
                "customer_promises": _merge(current.business_world.get("customer_promises"), business.get("primary_services")),
                "tensions": _merge(current.business_world.get("tensions"), intake.unknowns),
                "language": _merge(current.business_world.get("language"), brand.get("voice")),
            },
            "relationship": dict(current.relationship),
            "creative_identity": {
                **current.creative_identity,
                "principles": _merge(current.creative_identity.get("principles"), brand.get("voice")),
                "developing_tastes": _merge(current.creative_identity.get("developing_tastes"), asset_notes),
                "open_questions": _merge(current.creative_identity.get("open_questions"), intake.unknowns),
            },
            "research_identity": {
                **current.research_identity,
                "subjects": _merge(current.research_identity.get("subjects"), audience.get("primary")),
                "communities": _merge(current.research_identity.get("communities"), audience.get("secondary")),
                "candidate_feeds": _merge(current.research_identity.get("candidate_feeds"), candidate_feeds),
                "excluded_sources": _merge(current.research_identity.get("excluded_sources"), excluded_sources),
            },
        }
        if updates is not None:
            if not isinstance(updates, Mapping):
                raise CustomerGenesisServiceError("genesis updates must be an object")
            explicit = updates.get("genesis") if isinstance(updates.get("genesis"), Mapping) else updates
            if isinstance(explicit, Mapping):
                for section_name in sections:
                    section_updates = explicit.get(section_name)
                    if not isinstance(section_updates, Mapping):
                        continue
                    allowed = set(sections[section_name])
                    if set(section_updates) - allowed:
                        raise CustomerGenesisServiceError("genesis update contains unsupported fields")
                    for key, value in section_updates.items():
                        if key in {"purpose", "decision_style"}:
                            sections[section_name][key] = str(value or "").strip()
                        else:
                            sections[section_name][key] = _merge(sections[section_name].get(key), value)
        # These three genesis statements are projections of intake fields. Do
        # not turn bootstrap observations or Ada recommendations into owner
        # statements merely because a genesis revision was saved after a chat
        # turn. The latest projection replaces evidence for these paths; the
        # immutable genesis revision rows retain the historical trail.
        evidence_paths = {
            "business_world.purpose": "business.offer_summary",
            "research_identity.subjects": "audience.primary",
            "creative_identity.principles": "brand.voice",
        }
        evidence = [item for item in current.evidence if item.field_path not in evidence_paths]
        for path, intake_path in evidence_paths.items():
            provenance = draft.provenance.get(intake_path)
            if provenance is None:
                origin = EvidenceOrigin.OWNER_CORRECTION.value if updates and updates.get("correction") else EvidenceOrigin.OWNER_STATEMENT.value
                evidence_source = source_id
                confidence = 1.0
            elif provenance.origin == IntakeOrigin.CONFIRMED.value:
                origin = EvidenceOrigin.OWNER_STATEMENT.value
                evidence_source = f"message:{provenance.source_message_id}" if provenance.source_message_id else source_id
                confidence = 1.0
            elif provenance.origin == IntakeOrigin.ADVISED.value:
                origin = EvidenceOrigin.OWNER_ACCEPTANCE.value
                evidence_source = f"message:{provenance.source_message_id}" if provenance.source_message_id else source_id
                confidence = 0.9
            elif provenance.origin == IntakeOrigin.ASSUMED.value:
                origin = (
                    EvidenceOrigin.HOST_OBSERVATION.value
                    if provenance.source_message_id is None
                    else EvidenceOrigin.ADA_HYPOTHESIS.value
                )
                evidence_source = source_id if provenance.source_message_id is None else f"message:{provenance.source_message_id}"
                confidence = 0.2
            else:
                origin = EvidenceOrigin.ADA_REFLECTION.value
                evidence_source = f"message:{provenance.source_message_id}" if provenance.source_message_id else source_id
                confidence = 0.1
            evidence.append(GenesisEvidence(path, origin, evidence_source, confidence))
        for asset_id in _asset_ids(session.get("assets") or ()):
            evidence.append(GenesisEvidence(
                "creative_identity.developing_tastes",
                EvidenceOrigin.ASSET_ANALYSIS.value,
                f"asset:{asset_id}",
                0.6,
            ))
        return CustomerAdaGenesis(
            revision=next_revision,
            business_world=sections["business_world"],
            relationship=sections["relationship"],
            creative_identity=sections["creative_identity"],
            research_identity=sections["research_identity"],
            evidence=tuple(evidence[-200:]),
        )

    def save(self, genesis: CustomerAdaGenesis, *, source_kind: str = "genesis_update") -> dict[str, Any]:
        current_row = self.memory.get_customer_genesis_revision()
        expected_revision = int(current_row["revision"]) if current_row else 0
        try:
            return self.memory.save_customer_genesis_revision(
                genesis,
                source_kind=source_kind,
                expected_revision=expected_revision,
            )
        except (ContractError, ValueError) as exc:
            raise CustomerGenesisServiceError(str(exc)[:500]) from exc


def _asset_visual_notes(assets: Any) -> list[str]:
    """Turn uploaded-image analysis into bounded visual-taste notes for genesis."""
    if not isinstance(assets, (list, tuple)):
        return []
    notes: list[str] = []
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        analysis = asset.get("analysis") if isinstance(asset.get("analysis"), Mapping) else {}
        parts: list[str] = []
        description = str(analysis.get("description") or asset.get("description") or "").strip()
        if description:
            parts.append(description[:240])
        colors = analysis.get("dominant_colors") or asset.get("dominant_colors") or ()
        if colors:
            label = ", ".join(str(color)[:40] for color in list(colors)[:6])
            if label:
                parts.append(f"palette {label}")
        tags = analysis.get("tags") or asset.get("tags") or ()
        for tag in list(tags)[:5]:
            tag = str(tag).strip()[:60]
            if tag:
                parts.append(tag)
        ocr = str(analysis.get("ocr_text") or asset.get("ocr_text") or "").strip()[:160]
        if ocr:
            parts.append(f"texte visible: {ocr}")
        for note in parts:
            if note and note not in seen:
                seen.add(note)
                notes.append(note)
        if len(notes) >= 30:
            break
    return notes


def _asset_ids(assets: Any) -> list[str]:
    if not isinstance(assets, (list, tuple)):
        return []
    result: list[str] = []
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        value = asset.get("id")
        if value is None:
            value = asset.get("asset_id")
        if value is not None:
            result.append(str(value))
    return result[:50]


def _merge(existing: Any, incoming: Any, *, limit: int = 50) -> list[str]:
    def items(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    result: list[str] = []
    for item in items(existing) + items(incoming):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:500])
    return result[:limit]


__all__ = ["CustomerGenesisService", "CustomerGenesisServiceError"]
