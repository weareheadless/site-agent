"""Application service for durable conversational design intake."""

from __future__ import annotations

import copy
import hashlib
import re
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable

from ..brain.design_intake import (
    DesignIntakeAdvisor,
    DesignIntakeAdvisorError,
    LLMDesignIntakeAdvisor,
    UnavailableDesignIntakeAdvisor,
)
from ..brain.design_guidance import DesignSkillSet
from ..core.contracts import ContractError, safe_payload, utc_now
from ..core.design_contracts import DesignRunStatus, SiteIntake, canonical_hash, canonical_json
from ..core.design_intake_contracts import (
    DesignIntakeDraft,
    IntakeAssetBinding,
    IntakeAssetUsage,
    IntakeFieldProvenance,
    IntakeOrigin,
    IntakeSessionState,
    IntakeSummary,
    IntakeTurnResult,
    allowed_intake_field_paths,
    merge_intake_turn,
)
from .customer_genesis import CustomerGenesisService, CustomerGenesisServiceError
from .incubation_activity import IncubationActivityError, IncubationActivityService


class DesignIntakeServiceError(ValueError):
    """The conversational intake request cannot be safely completed."""


_CONNECTION_ISSUE = "Connection issue, try again."


_SESSION_ID = re.compile(r"^intake-[0-9a-f]{32}$")

# The builder's creative prompt is composed from the confirmed intake unless the
# owner supplied a real design request. Placeholders from older clients would
# otherwise reach the design pipeline.
_PLACEHOLDER_REQUESTS = frozenset({
    "",
    "Build the first visual website candidate from this confirmed conversation.",
    "Build the first visual website candidate from this confirmed intake.",
})

# A visual-review finding may ask for material the intake never supplied (e.g.
# photographs of a specific subject). Ada cannot fabricate it, so the intake
# turns those findings into a durable chat request for the owner. Kept
# conservative on purpose: only `imagery` findings whose wording calls for
# absent imagery are surfaced, never subjective composition feedback.
_ASSET_REQUEST_CATEGORIES = frozenset({"imagery"})
_ASSET_REQUEST_SIGNALS = (
    "no imagery",
    "no image",
    "no images",
    "no photos",
    "no photographs",
    "no photography",
    "add imagery",
    "add images",
    "add photos",
    "missing imagery",
    "missing images",
    "missing photos",
    "only photos of",
)


def asset_request_notes(critique: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Conservative extraction of owner-suppliable gaps from a visual critique.

    Returns the verbatim finding summaries (untrusted review evidence, bounded)
    that ask for imagery the intake did not provide. Never invents subjects.
    """
    if not isinstance(critique, Mapping):
        return ()
    findings = critique.get("findings")
    if not isinstance(findings, (list, tuple)):
        return ()
    notes: list[str] = []
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        category = str(finding.get("category") or "").strip().lower()
        if category not in _ASSET_REQUEST_CATEGORIES:
            continue
        summary = str(finding.get("summary") or "").strip()
        if not summary:
            continue
        haystack = " ".join(filter(None, (
            summary,
            str(finding.get("evidence") or ""),
            str(finding.get("note") or ""),
        ))).lower()
        if any(signal in haystack for signal in _ASSET_REQUEST_SIGNALS):
            if summary not in notes:
                notes.append(summary[:600])
    return tuple(notes[:3])


def _compose_creative_request(intake: SiteIntake) -> str:
    """Compose the creative direction the design builder receives.

    The confirmed intake already carries the brand, audience, conversion, and
    constraint fields the intake conversation collected. The OpenCode builder
    receives this as its creative prompt so the pipeline is driven by Ada's
    intake direction rather than a placeholder sentence.
    """
    brand = intake.brand or {}
    audience = intake.audience or {}
    business = intake.business or {}
    conversion = intake.conversion or {}
    name = str(business.get("name") or "the business").strip()
    offer = str(business.get("offer_summary") or "").strip()
    audience_primary = str(audience.get("primary") or "").strip()
    desired_impression = str(audience.get("desired_impression") or "").strip()
    vibe = str(brand.get("vibe") or "").strip()
    voice = str(brand.get("voice") or "").strip()
    colors = str(brand.get("colors") or "").strip()
    typography = str(brand.get("typography") or "").strip()
    visual_preferences = str(brand.get("visual_preferences") or "").strip()
    primary_action = str(conversion.get("primary_action") or "").strip()
    services = [
        str(item).strip()
        for item in (business.get("primary_services") or ())
        if isinstance(item, str) and str(item).strip()
    ]
    brief = f"Creative direction for {name}: {offer}."
    if audience_primary:
        brief += f" It is for {audience_primary}."
    if desired_impression:
        brief += f" The impression to leave is: {desired_impression}."
    if vibe:
        brief += f" The concept is {vibe}."
    if voice:
        brief += f" Voice: {voice}."
    if colors:
        brief += f" Palette: {colors}."
    if typography:
        brief += f" Typography: {typography}."
    if visual_preferences:
        brief += f" Visual treatment: {visual_preferences}."
    if services:
        brief += " Services: " + "; ".join(services) + "."
    if primary_action:
        brief += f" Primary conversion: {primary_action}."
    brief += (
        " Make it distinctive, high-end, and one of a kind, grounded in this business's own "
        "confirmed direction and supplied imagery. The installed design skills define the "
        "quality bar: satisfy them, do not approximate them."
    )
    return brief


def _message(value: Any) -> str:
    result = str(value or "").strip()
    if not result:
        raise DesignIntakeServiceError("message must not be empty")
    if len(result) > 20_000:
        raise DesignIntakeServiceError("message exceeds 20000 characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise DesignIntakeServiceError("message contains control characters")
    return result


def _optional_id(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DesignIntakeServiceError(f"{name} is invalid")
    return value


class DesignIntakeService:
    """Coordinate draft persistence, advisor turns, and explicit build handoff."""

    def __init__(
        self,
        memory,
        *,
        config: Mapping[str, Any] | None = None,
        llm: Any = None,
        default_intake: SiteIntake | None = None,
        design_service: Any = None,
        lab_service: Any = None,
        media_service: Any = None,
        media_url_prefix: str = "./api/intake/media",
        advisor: DesignIntakeAdvisor | None = None,
        skill_set: DesignSkillSet | None = None,
        activity_service: IncubationActivityService | None = None,
        genesis_service: CustomerGenesisService | None = None,
        on_revision_saved: Callable[[str, DesignIntakeDraft, Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
    ) -> None:
        if default_intake is not None and not isinstance(default_intake, SiteIntake):
            raise DesignIntakeServiceError("default_intake must be a validated SiteIntake")
        self.memory = memory
        self.config = dict(config or {})
        self.default_intake = default_intake
        self.design_service = design_service
        self.lab_service = lab_service
        self.media_service = media_service
        self.media_url_prefix = str(media_url_prefix or "./api/intake/media").rstrip("/")
        self.skill_set = skill_set
        self.activity_service = activity_service
        self.genesis_service = genesis_service
        self.on_revision_saved = on_revision_saved
        database_only = bool(
            (self.config.get("atelier_intake") or {}).get("database_only", False)
            if isinstance(self.config.get("atelier_intake"), Mapping)
            else False
        )
        self.database_only = database_only
        if advisor is not None:
            self.advisor = advisor
        elif llm is not None and getattr(llm, "api_key", True):
            try:
                self.advisor = LLMDesignIntakeAdvisor(
                    llm,
                    self.config.get("design_engine") or {},
                    skill_set=self.skill_set,
                )
            except DesignIntakeAdvisorError:
                self.advisor = UnavailableDesignIntakeAdvisor()
        else:
            self.advisor = UnavailableDesignIntakeAdvisor(database_only=database_only)

    def describe(self) -> dict[str, Any]:
        return {
            "available": True,
            "schema_version": 1,
            "states": [item.value for item in IntakeSessionState],
            "origins": [item.value for item in IntakeOrigin],
            "field_paths": list(allowed_intake_field_paths()),
            "default_ready": self._initial_draft().readiness == IntakeSessionState.READY_TO_BUILD.value,
            "publishing_enabled": False,
        }

    def _validate_session_id(self, session_id: Any) -> str:
        result = str(session_id or "").strip()
        if not _SESSION_ID.fullmatch(result):
            raise DesignIntakeServiceError("intake session was not found")
        return result

    def _initial_draft(self, draft: DesignIntakeDraft | None = None) -> DesignIntakeDraft:
        if draft is not None:
            return draft
        if self.default_intake is not None:
            return DesignIntakeDraft.from_site_intake(self.default_intake)
        return DesignIntakeDraft.empty()

    def create_session(
        self,
        *,
        conversation_id: int | None = None,
        draft: DesignIntakeDraft | None = None,
    ) -> dict[str, Any]:
        conversation_id = _optional_id(conversation_id, "conversation_id")
        if conversation_id is None:
            conversation_id = self.memory.create_conversation("Website design intake")
        if self.memory.get_conversation(conversation_id) is None:
            raise DesignIntakeServiceError("conversation was not found")
        existing = self.memory.find_design_intake_session_for_conversation(conversation_id)
        if existing is not None:
            return self.get_session(existing["session_id"])
        session_id = f"intake-{uuid.uuid4().hex}"
        try:
            self.memory.create_design_intake_session(
                session_id,
                self._initial_draft(draft),
                conversation_id=conversation_id,
            )
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        self._activity(
            category="conversation",
            kind="intake_session_created",
            state="completed",
            summary="Opened a private conversation for the customer incubation.",
            provenance="system",
            conversation_id=conversation_id,
            intake_session_id=session_id,
        )
        return self.get_session(session_id)

    def _activity(self, **kwargs: Any) -> None:
        if self.activity_service is None:
            return
        try:
            self.activity_service.record(**kwargs)
        except IncubationActivityError as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc

    def _row(self, session_id: str) -> dict[str, Any]:
        session = self.memory.get_design_intake_session(self._validate_session_id(session_id))
        if session is None:
            raise DesignIntakeServiceError("intake session was not found")
        return session

    def _asset_rows(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.memory.list_design_intake_assets(session_id)
        result = []
        for row in rows:
            item = dict(row)
            if self.media_service is not None:
                try:
                    asset = self.media_service.get(int(row["asset_id"]))
                    item.update(self.media_service.serialize(asset))
                except Exception:
                    item["available"] = False
            if str(item.get("usage") or "").strip().lower() == IntakeAssetUsage.UNDECIDED.value:
                item["usage"] = IntakeAssetUsage.WEBSITE.value
            asset_id = int(item["asset_id"])
            item["thumbnail_url"] = f"{self.media_url_prefix}/{asset_id}/thumbnail"
            item["preview_url"] = f"{self.media_url_prefix}/{asset_id}/preview"
            result.append(item)
        return result

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self._row(session_id)
        session_id = session["session_id"]
        draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
        session["draft"] = draft.to_dict()
        session["readiness"] = {
            "state": draft.readiness,
            "unresolved_core_paths": list(draft.unresolved_core_paths),
            "undecided_asset_ids": [item.asset_id for item in draft.undecided_assets],
            "assumptions": [item.to_dict() for item in draft.assumptions],
            "deferred": [item.to_dict() for item in draft.deferred],
            "contradictions": [item.to_dict() for item in draft.contradictions],
        }
        session["assets"] = self._asset_rows(session_id)
        session["revisions"] = self.memory.list_design_intake_revisions(session_id, limit=100)
        session["summary"] = IntakeSummary.from_draft(draft).to_dict()
        confirmed_revision = session.get("confirmed_revision")
        if confirmed_revision is not None:
            confirmed = next(
                (
                    item for item in reversed(session["revisions"])
                    if item.get("site_intake") and int(item.get("revision") or 0) == int(confirmed_revision)
                ),
                None,
            )
            if confirmed is not None:
                session["confirmed_revision_id"] = confirmed.get("id")
        session["feedback"] = self.memory.list_design_intake_feedback(session_id, limit=50)
        conversation_id = session.get("conversation_id")
        session["messages"] = self.memory.get_messages(conversation_id, limit=100) if conversation_id else []
        return session

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self.get_session(row["session_id"]) for row in self.memory.list_design_intake_sessions(limit)]

    def _normalize_asset_ids(self, values: Any) -> list[int]:
        if values is None:
            return []
        if not isinstance(values, list):
            raise DesignIntakeServiceError("attachments must be a list")
        result = []
        for raw in values[:20]:
            if isinstance(raw, Mapping):
                raw = raw.get("asset_id") or raw.get("id")
            if isinstance(raw, bool):
                raise DesignIntakeServiceError("attachment ID is invalid")
            try:
                asset_id = int(raw)
            except (TypeError, ValueError) as exc:
                raise DesignIntakeServiceError("attachment ID is invalid") from exc
            if asset_id < 1 or asset_id in result:
                raise DesignIntakeServiceError("attachments must contain unique positive IDs")
            result.append(asset_id)
        if len(values) > 20:
            raise DesignIntakeServiceError("choose up to 20 images")
        return result

    def _bind_assets(self, session_id: str, asset_ids: list[int]) -> list[dict[str, Any]]:
        current = self.memory.list_design_intake_assets(session_id)
        by_id = {int(row["asset_id"]): row for row in current}
        ordered: list[IntakeAssetBinding] = []
        for position, asset_id in enumerate(asset_ids):
            existing = by_id.get(asset_id)
            usage = str(existing.get("usage") if existing else IntakeAssetUsage.WEBSITE.value)
            if usage.strip().lower() == IntakeAssetUsage.UNDECIDED.value:
                usage = IntakeAssetUsage.WEBSITE.value
            aspects = existing.get("reference_aspects") if existing else []
            owner_note = str(existing.get("owner_note") or "") if existing else ""
            ordered.append(IntakeAssetBinding(
                asset_id=asset_id,
                position=position,
                usage=usage,
                reference_aspects=tuple(str(item) for item in (aspects or [])[:20]),
                owner_note=owner_note,
            ))
        try:
            return self.memory.replace_design_intake_assets(session_id, ordered)
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc

    def update_assets(self, session_id: str, assets: Any) -> dict[str, Any]:
        self._row(session_id)
        if not isinstance(assets, list) or len(assets) > 20:
            raise DesignIntakeServiceError("assets must contain at most 20 items")
        normalized: list[IntakeAssetBinding] = []
        for position, raw in enumerate(assets):
            if not isinstance(raw, Mapping):
                raise DesignIntakeServiceError("asset bindings must be objects")
            value = dict(raw)
            value["position"] = position
            try:
                normalized.append(IntakeAssetBinding.from_dict(value))
            except ContractError as exc:
                raise DesignIntakeServiceError(str(exc)[:500]) from exc
        try:
            self.memory.replace_design_intake_assets(session_id, normalized)
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        return self.get_session(session_id)

    def update_asset(self, session_id: str, asset_id: int, changes: Mapping[str, Any]) -> dict[str, Any]:
        self._row(session_id)
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id < 1:
            raise DesignIntakeServiceError("asset_id is invalid")
        if not isinstance(changes, Mapping):
            raise DesignIntakeServiceError("asset update must be an object")
        allowed = {"position", "usage", "reference_aspects", "owner_note"}
        unknown = set(changes) - allowed
        if unknown:
            raise DesignIntakeServiceError("asset update contains unsupported fields")
        current = [
            IntakeAssetBinding.from_dict({
                "asset_id": row["asset_id"],
                "position": row["position"],
                "usage": row["usage"],
                "reference_aspects": row.get("reference_aspects") or [],
                "owner_note": row.get("owner_note") or "",
            })
            for row in self.memory.list_design_intake_assets(session_id)
        ]
        target = next((item for item in current if item.asset_id == asset_id), None)
        if target is None:
            raise DesignIntakeServiceError("asset is not bound to this intake")
        updated = target.to_dict()
        for key in allowed:
            if key in changes:
                updated[key] = changes[key]
        replacement = IntakeAssetBinding.from_dict(updated)
        ordered = [item for item in current if item.asset_id != asset_id]
        ordered.insert(min(replacement.position, len(ordered)), replacement)
        return self.update_assets(session_id, [item.to_dict() for item in ordered])

    def remove_asset(self, session_id: str, asset_id: int) -> dict[str, Any]:
        self._row(session_id)
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id < 1:
            raise DesignIntakeServiceError("asset_id is invalid")
        current = self.memory.list_design_intake_assets(session_id)
        if not any(int(row["asset_id"]) == asset_id for row in current):
            raise DesignIntakeServiceError("asset is not bound to this intake")
        return self.update_assets(
            session_id,
            [
                {
                    "asset_id": row["asset_id"],
                    "position": position,
                    "usage": row["usage"],
                    "reference_aspects": row.get("reference_aspects") or [],
                    "owner_note": row.get("owner_note") or "",
                }
                for position, row in enumerate(current)
                if int(row["asset_id"]) != asset_id
            ],
        )

    def asset_thumbnail_url(self, session_id: str, asset_id: int) -> str:
        self._row(session_id)
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id < 1:
            raise DesignIntakeServiceError("asset_id is invalid")
        if not any(int(row["asset_id"]) == asset_id for row in self.memory.list_design_intake_assets(session_id)):
            raise DesignIntakeServiceError("asset is not bound to this intake")
        if self.media_service is None:
            raise DesignIntakeServiceError("image previews are unavailable")
        try:
            return self.media_service.preview_url(asset_id)
        except Exception as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc

    def send_message(
        self,
        session_id: str,
        message: str,
        *,
        attachments: Any = None,
        owner_context: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        session = self._row(session_id)
        message = _message(message)
        idempotency_key = self._operation_token(idempotency_key, "message")
        starts_new_revision = session.get("status") == IntakeSessionState.CONFIRMED.value
        asset_ids = self._normalize_asset_ids(attachments)
        if asset_ids:
            if self.media_service is None:
                raise DesignIntakeServiceError("image attachments are unavailable")
            try:
                self.media_service.resolve_attachments(asset_ids)
            except Exception as exc:
                raise DesignIntakeServiceError(str(exc)[:500]) from exc
            self._bind_assets(session["session_id"], asset_ids)
        attachment_rows = [{"asset_id": asset_id, "position": position} for position, asset_id in enumerate(asset_ids)]
        try:
            job_id = self.memory.enqueue_design_intake_advice_job(
                int(session["conversation_id"]), message,
                session_id=session["session_id"],
                attachments=attachment_rows,
                owner_context=self._owner_surface_context(owner_context),
                idempotency_key=idempotency_key,
            )
            job = self.memory.get_chat_job(job_id) or {}
            self.memory.update_design_intake_session(
                session["session_id"],
                latest_message_id=job.get("message_id"),
                latest_advice_job_id=job_id,
            )
            if starts_new_revision:
                # A post-confirmation owner turn starts a new draft revision
                # while retaining the frozen revision and its run as history.
                self.memory.update_design_intake_session(
                    session["session_id"],
                    status=IntakeSessionState.COLLECTING.value,
                    design_run_id=None,
                    build_started_ts=None,
                    build_error="",
                )
        except (ContractError, ValueError, KeyError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        return {
            "session_id": session["session_id"],
            "conversation_id": session["conversation_id"],
            "job_id": job_id,
            "message_id": job.get("message_id"),
            "idempotency_key": idempotency_key,
            "status": "queued",
        }

    @staticmethod
    def _operation_token(value: Any, prefix: str) -> str:
        result = str(value or "").strip()
        if not result:
            result = f"{prefix}-{uuid.uuid4().hex}"
        if len(result) > 160 or not re.fullmatch(r"[A-Za-z0-9._:-]+", result):
            raise DesignIntakeServiceError("idempotency_key is invalid")
        return result

    def _asset_context(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._asset_rows(session_id)
        if self.media_service is None or not isinstance(self.advisor, LLMDesignIntakeAdvisor):
            return rows
        # Asset pixels are analyzed by MediaWorker once and retained as durable
        # metadata. Never turn every conversational intake turn into another
        # multimodal request for the same selected files.
        for item in rows[:20]:
            try:
                asset = self.media_service.get(int(item["asset_id"]))
                analysis = asset.analysis if isinstance(asset.analysis, Mapping) else {}
                item.update({
                    "alt_text": str(analysis.get("alt_text") or "")[:500],
                    "dominant_colors": list(analysis.get("dominant_colors") or [])[:12],
                    "suggested_uses": list(analysis.get("suggested_uses") or [])[:8],
                    "quality_notes": list(analysis.get("quality_notes") or [])[:8],
                    "ocr_text": str(asset.ocr_text or "")[:2_000],
                })
            except Exception:
                continue
        return rows

    def handle_advice_job(self, context: Mapping[str, Any], job: Mapping[str, Any], progress=None) -> dict[str, Any]:
        """Run one claimed job and persist the resulting draft revision."""
        payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
        session_id = str(job.get("intake_session_id") or payload.get("session_id") or "").strip()
        session = self._row(session_id)
        if int(job.get("conversation_id") or 0) != int(session.get("conversation_id") or 0):
            raise DesignIntakeServiceError("intake job conversation does not match the session")
        source_message_id = _optional_id(job.get("message_id"), "message_id")
        if source_message_id is None:
            raise DesignIntakeServiceError("intake job is not bound to an owner message")
        message = _message(job.get("message"))
        history = self.memory.get_messages_before(int(session["conversation_id"]), source_message_id, limit=12)
        draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
        if progress:
            progress("intake / loading the working brief and recent conversation")
        asset_context = self._asset_context(session_id)
        if progress:
            if asset_context:
                progress(f"visual / reviewing {len(asset_context)} selected reference image(s)")
            else:
                progress("visual / no selected reference images to inspect")
            progress("intake / considering the next useful step")
            progress("intake / asking Ada for the next useful step")
        briefing = self._knowledge_briefing()
        preview_of_lab = isinstance(self.advisor, LLMDesignIntakeAdvisor)
        owner_context = payload.get("owner_context") if isinstance(payload.get("owner_context"), Mapping) else {}
        customer_view = self._customer_view_json(session, owner_context=owner_context) if preview_of_lab else ""
        owner_language = self._owner_language(owner_context)
        advise_kwargs: dict[str, Any] = {"assets": asset_context, "knowledge_briefing": briefing}
        if preview_of_lab:
            advise_kwargs["customer_view"] = customer_view
            advise_kwargs["owner_language"] = owner_language
        try:
            turn = self.advisor.advise(draft, history, message, **advise_kwargs)
        except DesignIntakeAdvisorError as exc:
            if not isinstance(self.advisor, LLMDesignIntakeAdvisor):
                raise
            if progress:
                progress("Ada's planning service was unavailable; no assistant reply was created")
            raise DesignIntakeServiceError(_CONNECTION_ISSUE) from exc
        advisor_call_count = int(getattr(self.advisor, "last_call_count", 0)) if isinstance(self.advisor, LLMDesignIntakeAdvisor) else 1
        updated = merge_intake_turn(draft, turn, source_message_id=source_message_id)
        if progress:
            progress("intake / validating the proposed intake turn")
        saved = self.memory.save_design_intake_revision(
            session_id,
            updated,
            source_kind="advisor_turn",
            source_message_id=source_message_id,
            expected_revision=int(session.get("revision") or 0),
        )
        saved = {**saved, "owner_language": owner_language}
        # Customer-Ada genesis is downstream of the first build-critical fact;
        # incomplete owner turns must still persist as ordinary intake turns.
        offer_summary = updated.value("business.offer_summary")
        if self.genesis_service is not None and isinstance(offer_summary, str) and offer_summary.strip():
            genesis_session = dict(session)
            genesis_session["draft"] = updated.to_dict()
            genesis_session["revision"] = saved.get("revision")
            try:
                genesis_session["assets"] = self._asset_rows(session_id)
            except Exception:
                genesis_session["assets"] = []
            try:
                genesis = self.genesis_service.propose_from_session(genesis_session)
                self.genesis_service.save(genesis, source_kind="intake_turn")
            except CustomerGenesisServiceError as exc:
                raise DesignIntakeServiceError(str(exc)[:500]) from exc
            self._activity(
                category="genesis",
                kind="genesis_revision_created",
                state="completed",
                summary="Updated customer-Ada's working direction from the latest intake turn.",
                provenance="model_inference",
                confidence=0.6,
                detail={"revision": genesis.revision, "status": "inferred"},
                conversation_id=int(session.get("conversation_id") or 0) or None,
                message_id=source_message_id,
                chat_job_id=int(job.get("id") or 0) or None,
                intake_session_id=session_id,
                intake_revision=int(saved.get("revision") or 0) or None,
                genesis_revision=genesis.revision,
            )
        if progress:
            progress("intake / saved the working brief and owner follow-up")
            progress(f"saved intake revision {saved.get('revision')}")
        self._activity(
            category="understanding",
            kind="intake_turn_completed",
            state="completed",
            summary="Updated the working brief from the owner's message and recorded the conversation progress.",
            provenance="model_inference",
            confidence=0.6,
            detail={
                "revision": int(saved.get("revision") or 0),
                "status": updated.readiness,
                "count": len(turn.creative_insights),
            },
            conversation_id=int(session.get("conversation_id") or 0) or None,
            message_id=source_message_id,
            chat_job_id=int(job.get("id") or 0) or None,
            intake_session_id=session_id,
            intake_revision=int(saved.get("revision") or 0) or None,
        )
        if turn.creative_insights:
            self._activity(
                category="design",
                kind="creative_implications_recorded",
                state="completed",
                summary="Recorded bounded creative implications separately from owner-confirmed intake facts.",
                provenance="model_inference",
                confidence=0.5,
                detail={"count": len(turn.creative_insights), "status": "inferred"},
                conversation_id=int(session.get("conversation_id") or 0) or None,
                message_id=source_message_id,
                chat_job_id=int(job.get("id") or 0) or None,
                intake_session_id=session_id,
                intake_revision=int(saved.get("revision") or 0) or None,
            )
            self._persist_creative_insights(
                turn.creative_insights,
                session,
                source_message_id,
                owner_language=owner_language,
            )
        research: Mapping[str, Any] | None = None
        if self.on_revision_saved is not None:
            try:
                candidate = self.on_revision_saved(session_id, updated, saved)
                if isinstance(candidate, Mapping):
                    research = candidate
            except Exception as exc:  # noqa: BLE001 - research must not strand intake
                research = {"status": "needs_attention", "error": type(exc).__name__}
                self._activity(
                    category="research",
                    kind="research_threshold",
                    state="needs_attention",
                    summary="Intake was saved, but automatic research could not be scheduled.",
                    provenance="host_validation",
                    detail={"error_code": type(exc).__name__, "status": "needs_attention"},
                    conversation_id=int(session.get("conversation_id") or 0) or None,
                    message_id=source_message_id,
                    chat_job_id=int(job.get("id") or 0) or None,
                    intake_session_id=session_id,
                    intake_revision=int(saved.get("revision") or 0) or None,
                )
        background = self._background_notes(asset_context, briefing, turn)
        if background:
            conversation_id = int(session.get("conversation_id") or 0) or None
            if conversation_id is not None:
                try:
                    self.memory.add_message(conversation_id, "system", background)
                except Exception:  # noqa: BLE001 - analysis sharing must never break a turn
                    pass
        return {
            "reply": turn.assistant_message,
            "changed": True,
            "operation_kind": "design_intake_advice",
            "intake_session_id": session_id,
            "intake_revision": saved.get("revision"),
            "intake_hash": saved.get("draft_hash"),
            "readiness": updated.readiness,
            "unresolved_core_paths": list(updated.unresolved_core_paths),
            "assumptions": [item.to_dict() for item in updated.assumptions],
            "deferred": [item.to_dict() for item in updated.deferred],
            "creative_insights": [item.to_dict() for item in turn.creative_insights],
            "advisor_call_count": advisor_call_count,
            "research": dict(research) if research is not None else None,
            "ui_action": self._resolve_ui_action(turn.ui_action, session),
            "background": background,
        }

    def _background_notes(
        self,
        asset_context: Sequence[Mapping[str, Any]],
        briefing: Sequence[str],
        turn: Any,
    ) -> str:
        """A short, data-driven account of what Ada analyzed in the background.

        Composed only from what actually happened this turn (image readings,
        research briefing, deductions) so the owner sees the analysis behind the
        reply instead of it being silently injected. Empty when there was
        nothing new to analyze - never a boilerplate line.
        """
        image_lines: list[str] = []
        for item in list(asset_context)[:4]:
            if not isinstance(item, Mapping):
                continue
            ocr = str(item.get("ocr_text") or "").strip()
            desc = str(item.get("description") or "").strip()
            tags = [str(tag) for tag in list(item.get("tags") or ())]
            is_logo = any(
                part in str(tag).lower()
                for part in ("logo", "brand", "logotype", "wordmark", "monogram")
                for tag in tags
            )
            if is_logo and ocr:
                image_lines.append(f'logo reads "{ocr[:80]}"')
            elif desc:
                image_lines.append(desc[:180])
            elif ocr:
                image_lines.append(ocr[:140])
        research_lines = [str(line)[:220] for line in list(briefing)[:3] if str(line or "").strip()]
        insight_lines: list[str] = []
        for item in list(getattr(turn, "creative_insights", ()) or ())[:3]:
            summary = str(getattr(item, "summary", "") or (item.get("summary", "") if isinstance(item, Mapping) else ""))[:220]
            if summary.strip():
                insight_lines.append(summary)
        lines: list[str] = []
        if image_lines:
            lines.append("Images: " + "; ".join(image_lines))
        if research_lines:
            lines.append("Research: " + "; ".join(research_lines))
        if insight_lines:
            lines.append("Deduction: " + "; ".join(insight_lines))
        if not lines:
            return ""
        return "BACKGROUND ANALYSIS — " + " | ".join(lines)

    @staticmethod
    def _owner_surface_context(value: Any) -> dict[str, Any]:
        """Keep only bounded, non-instructional metadata from the owner pane."""
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, Any] = {}
        for key in (
            "mode", "phase", "scope", "language", "site", "route", "collection", "document",
            "document_id", "slug", "state",
        ):
            if value.get(key) is not None:
                result[key] = str(value.get(key))[:300]
        raw_target = value.get("target")
        if isinstance(raw_target, Mapping):
            target: dict[str, Any] = {}
            for key in ("mode", "phase", "scope", "surface"):
                if raw_target.get(key) is not None:
                    target[key] = str(raw_target.get(key))[:120]
            for group, allowed in {
                "route": ("path", "kind", "sourceId", "source_id"),
                "preview": ("state", "url", "revision"),
                "payload": ("collection", "id", "sourceId", "source_id", "slug", "status"),
                "site": ("name", "url"),
            }.items():
                raw_group = raw_target.get(group)
                if not isinstance(raw_group, Mapping):
                    continue
                target[group] = {
                    key: str(raw_group[key])[:300]
                    for key in allowed
                    if raw_group.get(key) is not None
                }
                if group == "site" and isinstance(raw_group.get("routes"), list):
                    target[group]["routes"] = [
                        {
                            key: str(route.get(key))[:240]
                            for key in ("path", "kind", "collection", "sourceId", "source_id")
                            if route.get(key) is not None
                        }
                        for route in raw_group["routes"][:40]
                        if isinstance(route, Mapping)
                    ]
            if target:
                result["target"] = target
        snapshot = value.get("existing_site_snapshot")
        if isinstance(snapshot, Mapping):
            try:
                result["existing_site_snapshot"] = safe_payload(snapshot, max_bytes=24_000)
            except ContractError:
                result["existing_site_snapshot"] = {"status": "existing_live_website", "available": False}
        return result

    def _owner_language(self, value: Any) -> str:
        """Resolve the explicit workspace language without treating site text as a cue."""
        raw = value.get("language") if isinstance(value, Mapping) else None
        if not raw:
            site = self.config.get("site") if isinstance(self.config.get("site"), Mapping) else {}
            raw = site.get("language")
        if not raw:
            profile = self.config.get("customer_profile") if isinstance(self.config.get("customer_profile"), Mapping) else {}
            business = profile.get("business") if isinstance(profile.get("business"), Mapping) else {}
            raw = business.get("observed_language")
        language = str(raw or "").strip().replace("_", "-").lower()
        return language[:24] if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,2}", language) else ""

    def _customer_view_json(
        self,
        session: Mapping[str, Any],
        *,
        owner_context: Mapping[str, Any] | None = None,
    ) -> str:
        """A compact, truthful picture of the build state the owner can see.

        This lets the advisor answer "show me the new version" by referencing a
        run that actually exists instead of guessing. Best-effort: an unreadable
        or unavailable run yields an empty block, never an exception.
        """
        compact: dict[str, Any] = {}
        run_id = str(session.get("design_run_id") or "").strip()
        if self.lab_service is not None and run_id:
            try:
                run = self.lab_service.get_run(run_id)
            except Exception:  # noqa: BLE001 - customer view is advisory context only
                run = None
            if isinstance(run, Mapping) and str(run.get("run_id") or ""):
                revisions = run.get("revisions") if isinstance(run.get("revisions"), list) else []
                compact.update({
                    "active_run_id": str(run.get("run_id") or ""),
                    "active_status": str(run.get("status") or ""),
                    "preferred_run_id": str(run.get("preferred_run_id") or ""),
                    "versions": [
                        {
                            "run_id": str(item.get("run_id") or ""),
                            "number": item.get("number"),
                            "operation_kind": item.get("operation_kind"),
                            "status": item.get("status"),
                            "reviewable": bool(item.get("reviewable")),
                        }
                        for item in revisions
                        if isinstance(item, Mapping) and str(item.get("run_id") or "")
                    ],
                })
        site = self.config.get("site") if isinstance(self.config.get("site"), Mapping) else {}
        payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
        profile = self.config.get("customer_profile") if isinstance(self.config.get("customer_profile"), Mapping) else {}
        business = profile.get("business") if isinstance(profile.get("business"), Mapping) else {}
        observed = business.get("observed_site_settings") if isinstance(business.get("observed_site_settings"), Mapping) else {}
        public_url = str(observed.get("website_url") or "").strip()[:300]
        workspace_url = str(payload.get("url") or site.get("preview_url") or "").strip()[:300]
        if self.database_only or bool(payload.get("enabled")) or public_url:
            compact["existing_site"] = {
                "status": "existing_live_website",
                "public_url": public_url,
                "workspace_url": workspace_url,
                "owner_surface": "The owner is looking at this existing website in the adjacent review pane.",
            }
        surface = self._owner_surface_context(owner_context)
        if surface:
            compact["owner_visible_surface"] = surface
        if not compact:
            return ""
        return canonical_json(compact)[:6_000]

    def _resolve_ui_action(
        self,
        action: Mapping[str, Any] | None,
        session: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Whitelist an advisor-proposed action to one the owner can actually see.

        The advisor may propose ``open_preview`` (only against a run listed in
        this session's lineage) or ``start_build`` (only when the frozen brief is
        confirmed). Anything else is dropped so a stray model suggestion can never
        jump the owner to an unrelated run or start a build it did not confirm.
        """
        if not isinstance(action, Mapping):
            return None
        action_name = str(action.get("action") or "").strip()
        if action_name not in {"open_preview", "start_build"}:
            return None
        allowed: set[str] = set()
        if self.lab_service is not None:
            run_id = str(session.get("design_run_id") or "").strip()
            try:
                run = self.lab_service.get_run(run_id) if run_id else None
            except Exception:  # noqa: BLE001 - validation is best effort
                run = None
            if isinstance(run, Mapping):
                allowed.add(str(run.get("run_id") or ""))
                for item in run.get("revisions") or ():
                    if isinstance(item, Mapping):
                        allowed.add(str(item.get("run_id") or ""))
        if action_name == "start_build":
            if session.get("status") != IntakeSessionState.CONFIRMED.value:
                return None
            return {"action": "start_build", "fresh": True}
        candidate = str(action.get("run_id") or "")
        if candidate in allowed:
            return {"action": "open_preview", "run_id": candidate}
        return None

    def _persist_creative_insights(
        self,
        insights: Any,
        session: Mapping[str, Any],
        source_message_id: int,
        *,
        owner_language: str = "",
    ) -> None:
        """Persist the advisor's bounded design observations as incubation insights.

        These are Ada's interpretations from the intake conversation (never
        owner-confirmed facts). Persisting them lets the incubated creative
        context deliver Ada's personality to the builder, not only the neutral
        machinery. Best-effort: a persistence failure never strands the turn.
        """
        save = getattr(self.memory, "save_incubation_insight", None)
        if not callable(save):
            return
        for item in list(insights or ())[:8]:
            if not isinstance(item, Mapping) or str(item.get("summary") or "").strip() == "":
                continue
            summary = str(item.get("summary") or "").strip()[:2_000]
            supports = [str(path) for path in list(item.get("related_intake_paths") or ())[:12] if str(path).strip()]
            if not supports:
                supports = ["site.required_pages"]
            insight_language = str(owner_language or session.get("language") or "en").strip().lower()
            insight_id = "insight_" + hashlib.sha256(
                canonical_hash({
                    "source": "intake_turn",
                    "conversation_id": int(session.get("conversation_id") or 0) or None,
                    "source_message_id": source_message_id,
                    "summary": summary,
                }).encode("utf-8")
            ).hexdigest()[:32]
            try:
                from ..core.incubation_contracts import IncubationInsight

                insight = IncubationInsight.from_dict({
                    "insight_id": insight_id,
                    "kind": "creative_implication",
                    "summary": summary,
                    "owner_language": insight_language,
                    "source_languages": [],
                    "finding_ids": [],
                    "supports_paths": supports,
                    "contradicts_paths": [],
                    "confidence": float(item.get("confidence") or 0.5),
                    "status": "inferred",
                    "created_at": utc_now(),
                })
                save(insight)
            except Exception:  # noqa: BLE001 - creative insight persistence is best effort
                continue

    def _knowledge_briefing(self, limit: int = 6) -> list[str]:
        """Top deductions + research findings for the advisor (read-only, bounded)."""
        lines: list[str] = []
        try:
            for item in self.memory.list_incubation_deductions(limit=50):
                summary = str(item.get("summary") or "").strip()
                if summary:
                    lines.append(summary[:280])
        except Exception:  # noqa: BLE001 — knowledge must never block intake
            pass
        try:
            for item in self.memory.list_research_findings(limit=20):
                summary = str(item.get("summary") or "").strip()
                if summary:
                    lines.append(summary[:280])
        except Exception:  # noqa: BLE001
            pass
        for item in self.memory.list_incubation_insights(limit=12):
            try:
                summary = str(item.get("summary") or "").strip()
                if summary:
                    lines.append(summary[:280])
            except Exception:  # noqa: BLE001
                continue
        seen: set[str] = set()
        unique: list[str] = []
        for line in lines:
            key = line.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(line)
        return unique[:limit]

    def _confirmed_intake(self, session: Mapping[str, Any]) -> SiteIntake:
        draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
        asset_rows = self.memory.list_design_intake_assets(str(session["session_id"]))
        if asset_rows:
            draft = replace(draft, assets=tuple(
                IntakeAssetBinding.from_dict({
                    "asset_id": row["asset_id"],
                    "position": row["position"],
                    "usage": row["usage"],
                    "reference_aspects": row.get("reference_aspects") or [],
                    "owner_note": row.get("owner_note") or "",
                })
                for row in asset_rows
            ))
        offer_summary = draft.value("business.offer_summary")
        if not isinstance(offer_summary, str) or not offer_summary.strip():
            raise DesignIntakeServiceError("business.offer_summary is required before building")
        if draft.readiness != IntakeSessionState.READY_TO_BUILD.value:
            raise DesignIntakeServiceError("intake needs owner follow-up before confirmation")
        try:
            intake = draft.to_site_intake()
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        data = copy.deepcopy(intake.to_dict())
        provenance = dict(data.get("provenance") or {})
        provenance.update({
            "intake_session_id": session["session_id"],
            "confirmed_revision": int(session["revision"]),
            "confirmed_draft_hash": str(session["draft_hash"]),
        })
        data["provenance"] = provenance
        return SiteIntake.from_dict(data)

    def confirm(
        self,
        session_id: str,
        *,
        revision: int,
        draft_hash: str,
        confirmation_text: str = "Build this",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        session = self._row(session_id)
        token = self._operation_token(idempotency_key, "confirm")
        confirmation_text = _message(confirmation_text)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise DesignIntakeServiceError("revision is invalid")
        request_hash = canonical_hash({
            "revision": revision,
            "draft_hash": str(draft_hash or "").strip().lower(),
            "confirmation_text": confirmation_text,
        })
        try:
            if session.get("status") not in {
                IntakeSessionState.READY_TO_BUILD.value,
                IntakeSessionState.CONFIRMED.value,
            }:
                reconciled = self.memory.reconcile_confirmed_design_intake(
                    session_id,
                    revision=revision,
                    draft_hash=draft_hash,
                )
                if reconciled is not None:
                    session = reconciled
            intake = self._confirmed_intake(session)
            summary = DesignIntakeDraft.from_dict(session.get("draft") or {}).summary()
            confirmed = self.memory.confirm_design_intake(
                session["session_id"],
                revision=int(revision),
                draft_hash=str(draft_hash),
                site_intake_json=intake.to_dict(),
                summary_json=summary.to_dict(),
                confirmation_text=confirmation_text,
                idempotency_key=token,
                request_hash=request_hash,
            )
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        result = self.get_session(session_id)
        for key in ("confirmed_revision", "confirmed_revision_id", "confirmation_message_id", "site_intake_hash"):
            if key in confirmed:
                result[key] = confirmed[key]
        result["confirmation_idempotency_key"] = token
        return {"session": result, "confirmed": True}

    def build(
        self,
        session_id: str,
        *,
        confirmed_revision: int,
        owner_request: str = "",
        idempotency_key: str | None = None,
        context_extra: Mapping[str, Any] | None = None,
        force_new: bool = False,
    ) -> dict[str, Any]:
        session = self._row(session_id)
        if self.lab_service is None:
            raise DesignIntakeServiceError("design build service is unavailable")
        if session.get("status") != IntakeSessionState.CONFIRMED.value:
            raise DesignIntakeServiceError("intake must be confirmed before building")
        token = self._operation_token(idempotency_key, "build")
        if isinstance(confirmed_revision, bool) or not isinstance(confirmed_revision, int) or confirmed_revision < 1:
            raise DesignIntakeServiceError("confirmed_revision is invalid")
        requested_revision = confirmed_revision
        revisions = self.memory.list_design_intake_revisions(session_id, limit=500)
        revision_row = next(
            (
                item for item in reversed(revisions)
                if item.get("site_intake")
                and (int(item.get("id") or 0) == requested_revision or int(item.get("revision") or 0) == requested_revision)
            ),
            None,
        )
        if revision_row is None or int(revision_row.get("revision") or 0) != int(session.get("confirmed_revision") or 0):
            raise DesignIntakeServiceError("confirmed intake revision was not found")
        intake = SiteIntake.from_dict(revision_row["site_intake"])
        if str(owner_request or "").strip() not in _PLACEHOLDER_REQUESTS:
            request = _message(owner_request)
        else:
            request = _compose_creative_request(intake)
        request_identity = {
            "confirmed_revision_id": int(revision_row["id"]),
            "confirmed_revision": int(revision_row["revision"]),
            "owner_request": request,
            "force_new": bool(force_new),
        }
        if context_extra:
            request_identity["context_hash"] = canonical_hash(context_extra)
        request_hash = canonical_hash(request_identity)
        proposed_run_id = f"intake-lab-{uuid.uuid4().hex}"
        try:
            reservation = self.memory.reserve_design_intake_build(
                session_id,
                idempotency_key=token,
                request_hash=request_hash,
                confirmed_revision_id=int(revision_row["id"]),
                confirmed_revision=int(revision_row["revision"]),
                reserved_run_id=proposed_run_id,
                force_new=force_new,
            )
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        existing_run_id = str((reservation.get("response") or {}).get("run_id") or reservation.get("run_id") or "").strip()
        recovered = False
        if not reservation.get("created"):
            if existing_run_id:
                try:
                    existing_run = self.lab_service.get_run(existing_run_id)
                except Exception:
                    existing_run = None
                if existing_run is not None:
                    if reservation.get("state") == "reserved":
                        self.memory.complete_design_intake_build(session_id, str(reservation.get("idempotency_key") or token), request_hash, run_id=existing_run_id)
                    return {"session": self.get_session(session_id), "run": existing_run, "idempotent": True}
            if reservation.get("state") == "failed":
                message = str(reservation.get("error") or "the previous build reservation failed")
                raise DesignIntakeServiceError(message[:500])
            if reservation.get("state") == "reserved":
                try:
                    claimed = self.memory.claim_design_intake_build_submission(
                        session_id,
                        str(reservation.get("idempotency_key") or token),
                        request_hash,
                    )
                except (ContractError, ValueError) as exc:
                    raise DesignIntakeServiceError(str(exc)[:500]) from exc
                if claimed and claimed.get("claimed"):
                    reservation = claimed
                    recovered = True
                else:
                    return {
                        "session": self.get_session(session_id),
                        "run": None,
                        "idempotent": True,
                        "build_pending": True,
                        "idempotency_key": str(reservation.get("idempotency_key") or token),
                    }
            else:
                return {
                    "session": self.get_session(session_id),
                    "run": None,
                    "idempotent": True,
                    "build_pending": True,
                    "idempotency_key": str(reservation.get("idempotency_key") or token),
                }
        try:
            run = self.lab_service.submit(
                request,
                intake.to_dict(),
                run_id=existing_run_id or proposed_run_id,
                conversation_id=session.get("conversation_id"),
                source_message_id=session.get("latest_message_id"),
                intake_session_id=session_id,
                intake_revision_id=int(revision_row["id"]),
                context_extra=context_extra,
            )
            run_id = str(run.get("run_id") or "").strip()
            if not run_id:
                raise DesignIntakeServiceError("design build did not return a run ID")
            self.memory.update_design_intake_session(
                session_id,
                design_run_id=run_id,
                build_started_ts=utc_now(),
                build_error="",
            )
            self.memory.complete_design_intake_build(session_id, token, request_hash, run_id=run_id)
        except Exception as exc:
            self.memory.fail_design_intake_build(session_id, token, request_hash, str(exc)[:500])
            self.memory.update_design_intake_session(session_id, build_error=str(exc)[:500])
            if isinstance(exc, DesignIntakeServiceError):
                raise
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        result = {"session": self.get_session(session_id), "run": run, "idempotency_key": token}
        if recovered:
            result.update({"idempotent": True, "recovered": True})
        return result

    def confirm_and_build(self, session_id: str, *, revision: int, draft_hash: str, owner_request: str = "") -> dict[str, Any]:
        """Compatibility helper for callers that intentionally request both steps."""
        confirmed = self.confirm(
            session_id,
            revision=revision,
            draft_hash=draft_hash,
            confirmation_text="Build this",
        )
        session = confirmed["session"]
        return self.build(
            session_id,
            confirmed_revision=int(session.get("confirmed_revision_id") or session.get("confirmed_revision") or 0),
            owner_request=owner_request,
        )

    def record_feedback(self, session_id: str, kind: str, *, notes: str = "", run_id: str | None = None) -> dict[str, Any]:
        session = self._row(session_id)
        run_id = str(run_id or session.get("design_run_id") or "").strip() or None
        if run_id:
            run = self.memory.get_design_run(run_id)
            if run is None or str(run.get("intake_session_id") or "") != session_id:
                raise DesignIntakeServiceError("feedback run does not belong to this intake")
        try:
            self.memory.record_design_intake_feedback(session_id, kind, notes=notes, run_id=run_id)
            if str(kind or "").strip().lower() == "redesign":
                self.memory.update_design_intake_session(session_id, status=IntakeSessionState.COLLECTING.value)
        except (ContractError, ValueError) as exc:
            raise DesignIntakeServiceError(str(exc)[:500]) from exc
        return self.get_session(session_id)

    def record_run_feedback(self, run_id: str, kind: str, *, notes: str = "") -> dict[str, Any]:
        run_id = str(run_id or "").strip()
        run = self.memory.get_design_run(run_id)
        if run is None or not run.get("intake_session_id"):
            raise DesignIntakeServiceError("feedback run was not found")
        return self.record_feedback(str(run["intake_session_id"]), kind, notes=notes, run_id=run_id)

    def surface_review_asset_requests(self, run_id: str) -> list[str]:
        """Post a durable Ada chat request when the visual review asks for imagery
        the owner never supplied.

        This is the interactive leg of the design loop: Qwen flags e.g. "no
        photos of the jungle camp", Ada cannot fabricate that, so the intake
        asks the owner to upload. The owner's upload starts a new revision and
        a fresh build via the normal flow. Idempotent: only one request per run.
        """
        run_id = str(run_id or "").strip()
        run = self.memory.get_design_run(run_id)
        if run is None or not run.get("intake_session_id"):
            return []
        report = run.get("quality_report_json")
        critique = report.get("visual_critique") if isinstance(report, Mapping) else None
        notes = asset_request_notes(critique)
        if not notes:
            return []
        already_asked = any(
            isinstance(event, Mapping) and event.get("stage") == "asset_request_surfaced"
            for event in self.memory.list_design_run_events(run_id, limit=50)
        )
        if already_asked:
            return list(notes)
        conversation_id = run.get("conversation_id")
        if not conversation_id:
            return []
        intake = SiteIntake.from_dict(run.get("intake_json") or {})
        business_name = str((intake.business or {}).get("name") or "").strip()
        try:
            request = self._asset_request_message(business_name, notes)
        except DesignIntakeServiceError as exc:
            self._activity(
                category="design",
                kind="asset_request_surfaced",
                state="needs_attention",
                summary="Could not ask the owner for the missing imagery because Ada was unavailable.",
                provenance="host_validation",
                confidence=0.5,
                detail={"error_code": str(exc)[:120], "status": "needs_attention"},
                conversation_id=int(conversation_id),
                design_run_id=run_id,
                intake_session_id=str(run["intake_session_id"]),
            )
            return list(notes)
        if not request:
            return list(notes)
        try:
            self.memory.add_message(int(conversation_id), "assistant", request)
            self.memory.add_design_run_event(
                run_id,
                "asset_request_surfaced",
                "Ada asked the owner to upload imagery the visual review found missing.",
                {"notes": notes, "conversation_id": int(conversation_id)},
            )
            self._activity(
                category="design",
                kind="asset_request_surfaced",
                state="completed",
                summary="Surfaced a review-flagged imagery gap to the owner as a chat request.",
                provenance="model_inference",
                confidence=0.5,
                detail={"count": len(notes), "status": "requested"},
                conversation_id=int(conversation_id),
                design_run_id=run_id,
                intake_session_id=str(run["intake_session_id"]),
            )
        except Exception as exc:  # noqa: BLE001 - surfacing must never strand the design run
            self._activity(
                category="design",
                kind="asset_request_surfaced",
                state="needs_attention",
                summary="Could not surface a review-flagged imagery gap in chat.",
                provenance="host_validation",
                confidence=0.5,
                detail={"error_code": type(exc).__name__, "status": "needs_attention"},
                conversation_id=int(conversation_id) if conversation_id else None,
                design_run_id=run_id,
                intake_session_id=str(run["intake_session_id"]),
            )
        return list(notes)

    def _asset_request_message(self, business_name: str, notes: Sequence[str]) -> str:
        """Write the owner-facing asset request in Ada's voice.

        The prompt describes the goal and context only; it never contains an
        example sentence. An unavailable advisor must not create a fabricated
        conversation turn.
        """
        written = ""
        request = getattr(self.advisor, "request_owner_assets", None)
        if callable(request):
            try:
                written = request(business_name=business_name, context=notes)
            except Exception:  # noqa: BLE001 - provider failure is handled as a connection issue below
                written = ""
        if written:
            return written[:1_200]
        raise DesignIntakeServiceError(_CONNECTION_ISSUE)


__all__ = ["DesignIntakeService", "DesignIntakeServiceError"]
