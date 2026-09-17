"""Tenant-scoped intake and research for an Atelier conversation.

An existing Payload website uses this coordinator for an incubation/research
conversation and deliberately stays out of the design/build pipeline until the
owner accepts the working brief.  A tenant without a website can use the same
typed intake contract as its full-intake front door; the normal workspace/build
handoff remains a separate explicit transition.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..brain.incubation_research import (
    IncubationResearchPlanningError,
    LLMIncubationResearchPlanner,
    base_plan,
)
from ..core.contracts import ContractError
from ..core.design_intake_contracts import (
    DesignIntakeDraft,
    IntakeFieldProvenance,
    IntakeOrigin,
    IntakeSessionState,
)
from ..core.incubation_contracts import ResearchTrigger
from ..core.memory import Memory
from .customer_genesis import CustomerGenesisService
from .design_intake import DesignIntakeService
from .incubation_activity import IncubationActivityService
from .incubation_research import IncubationResearchExecutor, IncubationResearchService


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(_present(item) for item in value)
    return True


class AtelierIntakeCoordinator:
    """Route an Atelier owner through intake until the working brief is ready."""

    def __init__(self, memory: Memory, *, config: Mapping[str, Any], llm: Any, media_service: Any = None) -> None:
        self.memory = memory
        self.config = dict(config)
        settings = self.config.get("atelier_intake") or {}
        self.settings = dict(settings) if isinstance(settings, Mapping) else {}
        research_config = self.settings.get("research") or {}
        self.research_config = dict(research_config) if isinstance(research_config, Mapping) else {}
        self.database_only = bool(self.settings.get("database_only", True))
        self.research_enabled = bool(self.research_config.get("enabled", True))
        self.max_passes_per_revision = max(
            1,
            min(int(self.research_config.get("max_passes_before_owner_turn", 1)), 4),
        )

        self.activity_service = IncubationActivityService(memory)
        self.genesis_service = CustomerGenesisService(memory)
        self.research_service = IncubationResearchService(
            memory,
            activity_service=self.activity_service,
            max_sources_per_pass=int(self.research_config.get("max_sources_per_pass", 8)),
            max_items_per_source=int(self.research_config.get("max_items_per_source", 15)),
        )
        self.research_planner = LLMIncubationResearchPlanner(llm, self.research_config)
        self.research_executor = IncubationResearchExecutor(self.research_service)
        # The coordinator itself never starts a build. Existing-site tenants
        # therefore remain database-only, while no-site tenants can hand the
        # confirmed session to the normal design/build conversation explicitly.
        self.intake_service = DesignIntakeService(
            memory,
            config=self.config,
            llm=llm,
            default_intake=None,
            design_service=None,
            lab_service=None,
            media_service=media_service,
            activity_service=self.activity_service,
            genesis_service=self.genesis_service,
            on_revision_saved=self._on_revision_saved,
        )

    def start(self) -> None:
        if self.research_enabled:
            self.research_executor.start()

    def stop(self) -> None:
        self.research_executor.stop()
        self.research_executor.join(timeout=10)

    def _bootstrap_draft(self) -> DesignIntakeDraft:
        """Seed observations as assumptions so Ada asks the owner to confirm them."""
        profile = self.config.get("customer_profile") or {}
        if not isinstance(profile, Mapping):
            return DesignIntakeDraft.empty()
        business = profile.get("business") if isinstance(profile.get("business"), Mapping) else {}
        audience = profile.get("audience") if isinstance(profile.get("audience"), Mapping) else {}
        brand = profile.get("brand") if isinstance(profile.get("brand"), Mapping) else {}
        settings = business.get("observed_site_settings") if isinstance(business.get("observed_site_settings"), Mapping) else {}
        persona = self.config.get("persona") if isinstance(self.config.get("persona"), Mapping) else {}

        values = (
            ("business.name", business.get("name") or settings.get("business_name")),
            ("business.offer_summary", business.get("observed_description") or settings.get("public_description")),
            ("business.primary_services", business.get("observed_offerings")),
            ("business.location", settings.get("locality")),
            ("audience.primary", audience.get("observed") or persona.get("audience")),
            ("brand.voice", persona.get("voice") or brand.get("observed_voice")),
            ("site.language", brand.get("observed_language")),
        )
        draft = DesignIntakeDraft.empty()
        for path, value in values:
            if not _present(value):
                continue
            draft = draft.with_value(
                path,
                value,
                IntakeFieldProvenance(
                    path=path,
                    origin=IntakeOrigin.ASSUMED.value,
                    note="Observed in the tenant bootstrap profile; owner confirmation is still required.",
                ),
            )
        return draft

    def _session(self, conversation_id: int | None = None) -> dict[str, Any]:
        if conversation_id is not None:
            existing = self.memory.find_design_intake_session_for_conversation(conversation_id)
            if existing is not None:
                return self.intake_service.get_session(str(existing["session_id"]))
            return self.intake_service.create_session(
                conversation_id=conversation_id,
                draft=self._bootstrap_draft(),
            )
        sessions = self.memory.list_design_intake_sessions(limit=1)
        if sessions:
            return self.intake_service.get_session(str(sessions[0]["session_id"]))
        return self.intake_service.create_session(draft=self._bootstrap_draft())

    def needs_intake(self, conversation_id: int | None = None) -> bool:
        session = self._session(conversation_id)
        if str(session.get("status") or "") == IntakeSessionState.CONFIRMED.value:
            return False
        try:
            draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
        except (ContractError, TypeError, ValueError):
            return True
        return bool(draft.unresolved_core_paths)

    def status(self, conversation_id: int | None = None) -> dict[str, Any]:
        """Return the minimal owner-facing acceptance state for one conversation."""
        session = self._session(conversation_id)
        readiness = session.get("readiness") if isinstance(session.get("readiness"), Mapping) else {}
        return {
            "session_id": str(session["session_id"]),
            "conversation_id": session.get("conversation_id"),
            "status": str(session.get("status") or IntakeSessionState.COLLECTING.value),
            "revision": int(session.get("revision") or 0),
            "draft_hash": str(session.get("draft_hash") or ""),
            "readiness": dict(readiness),
            "summary": session.get("summary") if isinstance(session.get("summary"), Mapping) else {},
            "confirmed_revision": session.get("confirmed_revision"),
            "confirmed_revision_id": session.get("confirmed_revision_id"),
            "confirmed": str(session.get("status") or "") == IntakeSessionState.CONFIRMED.value,
        }

    def confirm(
        self,
        conversation_id: int | None,
        *,
        revision: int,
        draft_hash: str,
        confirmation_text: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Record explicit owner acceptance without starting a design build."""
        session = self._session(conversation_id)
        try:
            result = self.intake_service.confirm(
                str(session["session_id"]),
                revision=revision,
                draft_hash=draft_hash,
                confirmation_text=confirmation_text,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001 — normalize application errors at the bridge boundary
            raise ValueError(str(exc)[:500]) from exc
        return self.status(conversation_id)

    def send_message(
        self,
        message: str,
        *,
        conversation_id: int | None = None,
        attachments: Any = None,
        owner_context: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        session = self._session(conversation_id)
        return self.intake_service.send_message(
            str(session["session_id"]),
            message,
            attachments=attachments,
            owner_context=owner_context,
            idempotency_key=idempotency_key,
        )

    def context_prompt(self) -> str:
        """Return the durable intake draft for normal post-intake editor turns."""
        sessions = self.memory.list_design_intake_sessions(limit=1)
        if not sessions:
            return ""
        try:
            session = self.intake_service.get_session(str(sessions[0]["session_id"]))
            draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
        except (ContractError, TypeError, ValueError):
            return ""
        unresolved = list(draft.unresolved_core_paths)
        return (
            "Working Atelier intake context (durable database record; field provenance is authoritative):\n"
            "Use owner-confirmed values as facts. Treat assumed, recommended, or deferred values as leads to verify, "
            "not as permission to invent. Do not present research findings as owner-confirmed business facts.\n"
            f"Readiness: {draft.readiness}; unresolved core paths: {json.dumps(unresolved, ensure_ascii=False)}\n"
            + json.dumps(draft.to_dict(), ensure_ascii=False, sort_keys=True)[:16_000]
        )

    def _research_context_ready(self, draft: DesignIntakeDraft) -> bool:
        try:
            offer = draft.value("business.offer_summary")
            services = draft.value("business.primary_services")
            audience = draft.value("audience.primary")
        except ContractError:
            return False
        return bool(
            draft.location_context_resolved
            and _present(offer)
            and _present(services)
            and _present(audience)
        )

    def _excluded_communities(self) -> tuple[str, ...]:
        names: list[str] = []
        for source in self.memory.list_research_sources(limit=500):
            if source.get("trust_state") == "excluded" or source.get("excluded"):
                title = str(source.get("title") or "").strip()
                if title:
                    names.append(title)
        return tuple(dict.fromkeys(names))

    def _on_revision_saved(
        self,
        session_id: str,
        draft: DesignIntakeDraft,
        revision: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        if not self.research_enabled or not self._research_context_ready(draft):
            return {"status": "not_ready"}
        current_revision = int(revision.get("revision") or 0)
        existing = [
            item
            for item in self.memory.list_research_requests(limit=500)
            if item.get("trigger") == ResearchTrigger.INTAKE_THRESHOLD.value
            and int(item.get("intake_revision") or 0) == current_revision
        ]
        if len(existing) >= self.max_passes_per_revision:
            return {"status": "owner_turn_required", "count": len(existing)}

        owner_language = str(draft.value("site.language") or "en").strip().lower().replace("_", "-")
        planning_error = ""
        try:
            plan = self.research_planner.plan(
                draft,
                owner_language=owner_language,
                excluded_communities=self._excluded_communities(),
            )
        except IncubationResearchPlanningError as exc:
            planning_error = f"planner_{type(exc).__name__}"
            plan = base_plan(draft, owner_language=owner_language)

        plan_data = plan.to_dict()
        result = self.research_service.request(
            {
                **plan_data,
                "feed_urls": [str(item.get("url") or "") for item in plan_data.get("candidate_feeds") or []],
                "trigger": ResearchTrigger.INTAKE_THRESHOLD.value,
                "intake_revision": current_revision,
                "fetch": True,
            },
            enqueue=True,
        )
        if planning_error:
            request_id = str(result.get("request", {}).get("request_id") or "")
            if request_id:
                self.memory.update_research_request(request_id, error=planning_error)
        if result.get("status") == "queued":
            self.research_executor.start()
        return {
            "status": result.get("status"),
            "request_id": result.get("request", {}).get("request_id"),
            "job_id": result.get("job", {}).get("job_id"),
            **({"planner_error": planning_error} if planning_error else {}),
        }


__all__ = ["AtelierIntakeCoordinator"]
