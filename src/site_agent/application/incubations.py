"""Application services for durable, isolated customer incubations."""

from __future__ import annotations

import hashlib
import shutil
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ..config import IntakeAdaSettings
from ..brain.incubation_infusion import (
    IncubationInfusionError,
    IncubationInfusionExecutor,
    IncubationInfusionService,
)
from ..brain.incubation_research import (
    IncubationResearchPlanningError,
    base_plan,
)
from ..core.contracts import ContractError, utc_now
from ..core.design_contracts import DesignRunStatus, DesignSkillReceipt, IncubatedCreativeContext, SiteIntake
from ..core.design_intake_contracts import DesignIntakeDraft
from ..core.incubation_contracts import (
    CustomerAdaGenesis,
    IncubationRecord,
    IncubationStatus,
    ResearchJobStatus,
)
from ..core.intake_ada_store import IntakeAdaStore
from ..core.memory import Memory
from ..brain.design_guidance import DesignSkillSet, load_design_skills
from .incubation_research import IncubationResearchError, IncubationResearchExecutor, IncubationResearchService
from .incubation_activity import IncubationActivityService
from .customer_genesis import CustomerGenesisService
from .customer_context import CustomerContextService
from .novelty import NoveltyService, NoveltyServiceError
from .provisioning import (
    CustomerActivationService,
    CustomerProvisioningService,
    ProvisioningBundleService,
    ProvisioningServiceError,
    _customer_id,
    _request_id,
)


class IncubationServiceError(ValueError):
    """The requested incubation operation is invalid or unavailable."""


@dataclass
class IncubationStore:
    """A scoped adapter that keeps one incubation database behind a named boundary."""

    incubation_id: str
    path: Path
    memory: Memory

    @classmethod
    def open(cls, incubation_id: str, path: str | Path) -> "IncubationStore":
        root = Path(path).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return cls(incubation_id=incubation_id, path=root / "incubation.db", memory=Memory(root / "incubation.db"))

    def close(self) -> None:
        self.memory.close()


@dataclass
class IncubationRuntime:
    """Optional design/chat dependencies attached to one incubation."""

    design_service: Any = None
    executor: Any = None
    intake_service: Any = None
    lab_service: Any = None
    chat_executor: Any = None
    research_service: Any = None
    research_executor: Any = None
    research_planner: Any = None
    activity_service: Any = None
    media_worker: Any = None
    novelty_service: Any = None
    genesis_service: Any = None
    provisioning_service: Any = None
    media_service: Any = None
    llm: Any = None
    infusion_service: Any = None
    infusion_executor: Any = None


class IncubationApplicationService:
    """Own registry lifecycle and route all customer state through one scope."""

    def __init__(
        self,
        intake_store: IntakeAdaStore,
        *,
        root: str | Path,
        config: Mapping[str, Any],
        runtime_factory: Callable[[IncubationStore], IncubationRuntime] | None = None,
    ) -> None:
        self.intake_store = intake_store
        self.root = Path(root).expanduser().resolve()
        if self.root == Path(self.root.anchor):
            raise IncubationServiceError("incubation root is too broad")
        if _overlaps(self.root, self.intake_store.path.parent):
            raise IncubationServiceError("incubation root overlaps Intake Ada storage")
        self.config = dict(config)
        self.settings = IntakeAdaSettings.from_config(self.config)
        from ..config import InfusionSettings

        self.infusion_settings = InfusionSettings.from_config(self.config)
        self.runtime_factory = runtime_factory
        self._stores: dict[str, IncubationStore] = {}
        self._runtimes: dict[str, IncubationRuntime] = {}
        self._lock = threading.RLock()
        self._started = False

    def _workspace(self, incubation_id: str) -> Path:
        value = str(incubation_id or "").strip()
        if not value.startswith("inc_") or len(value) != 36 or any(char not in "inc_0123456789abcdef" for char in value):
            raise IncubationServiceError("incubation was not found")
        path = (self.root / value).resolve()
        if path != self.root and self.root not in path.parents:
            raise IncubationServiceError("incubation path is outside the configured root")
        return path

    def _expires_at(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=self.settings.abandoned_ttl_days)).isoformat(timespec="seconds")

    def create_incubation(self, *, incubation_id: str | None = None) -> IncubationRecord:
        incubation_id = incubation_id or f"inc_{uuid.uuid4().hex}"
        workspace = self._workspace(incubation_id)
        if workspace.exists() and any(workspace.iterdir()):
            raise IncubationServiceError("incubation workspace already exists")
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            record = self.intake_store.create_incubation(incubation_id, workspace, expires_at=self._expires_at())
            scoped = IncubationStore.open(incubation_id, workspace)
            scoped.memory.save_customer_genesis_revision(
                CustomerAdaGenesis.empty(),
                source_kind="genesis_created",
                expected_revision=0,
            )
            self._stores[incubation_id] = scoped
            self.activity_service(incubation_id).record(
                category="system",
                kind="incubation_created",
                state="completed",
                summary="Created a private incubation workspace.",
                provenance="system",
            )
            return record
        except Exception as exc:
            scoped = self._stores.pop(incubation_id, None)
            if scoped is not None:
                scoped.close()
            shutil.rmtree(workspace, ignore_errors=True)
            if isinstance(exc, IncubationServiceError):
                raise
            raise IncubationServiceError(str(exc)[:500]) from exc

    def get_record(self, incubation_id: str) -> IncubationRecord:
        try:
            record = self.intake_store.get_incubation(incubation_id)
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError("incubation was not found") from exc
        if record is None:
            raise IncubationServiceError("incubation was not found")
        expected = self._workspace(record.incubation_id)
        if Path(record.workspace_path).resolve() != expected:
            raise IncubationServiceError("incubation workspace identity is invalid")
        return record

    def _registry_record_for_purge(self, incubation_id: str) -> tuple[IncubationRecord, Path]:
        try:
            record = self.intake_store.get_incubation(incubation_id, include_purged=True)
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError("incubation was not found") from exc
        if record is None:
            raise IncubationServiceError("incubation was not found")
        workspace = self._workspace(record.incubation_id)
        if record.status != IncubationStatus.PURGED.value and Path(record.workspace_path).resolve() != workspace:
            raise IncubationServiceError("incubation workspace identity is invalid")
        return record, workspace

    def list_incubations(self, limit: int = 100) -> list[IncubationRecord]:
        try:
            return self.intake_store.list_incubations(limit=limit)
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def get_or_create_default(self) -> IncubationRecord:
        active = self.intake_store.list_incubations(statuses=(
            IncubationStatus.COLLECTING.value,
            IncubationStatus.RESEARCHING.value,
            IncubationStatus.READY_TO_BUILD.value,
            IncubationStatus.BUILDING.value,
            IncubationStatus.READY_FOR_FEEDBACK.value,
            IncubationStatus.BLOCKED.value,
        ), limit=50)
        # A fresh reload must reconnect to the incumbent conversation, not to a
        # bare shell created by an earlier load. Prefer the most recently
        # updated active incubation that has persisted intake sessions.
        for record in active:
            try:
                scoped = self.open_store(record.incubation_id)
                if scoped.memory.list_design_intake_sessions(limit=1):
                    return record
            except Exception:
                continue
        return active[0] if active else self.create_incubation()

    def open_store(self, incubation_id: str) -> IncubationStore:
        record = self.get_record(incubation_id)
        with self._lock:
            existing = self._stores.get(record.incubation_id)
            if existing is not None:
                return existing
            try:
                scoped = IncubationStore.open(record.incubation_id, self._workspace(record.incubation_id))
            except Exception as exc:
                raise IncubationServiceError(str(exc)[:500]) from exc
            self._stores[record.incubation_id] = scoped
            return scoped

    def attach_runtime(self, incubation_id: str, runtime: IncubationRuntime) -> None:
        self.get_record(incubation_id)
        if not isinstance(runtime, IncubationRuntime):
            raise IncubationServiceError("incubation runtime is invalid")
        with self._lock:
            self._runtimes[incubation_id] = runtime
            if self._started:
                self._start_runtime(runtime)

    @staticmethod
    def _runtime_components(runtime: IncubationRuntime) -> tuple[Any, ...]:
        return runtime.chat_executor, runtime.executor, runtime.research_executor, runtime.media_worker, runtime.infusion_executor

    @classmethod
    def _start_runtime(cls, runtime: IncubationRuntime) -> None:
        for component in cls._runtime_components(runtime):
            starter = getattr(component, "start", None)
            if callable(starter):
                starter()

    @classmethod
    def _stop_runtime(cls, runtime: IncubationRuntime) -> None:
        components = cls._runtime_components(runtime)
        for component in components:
            stopper = getattr(component, "stop", None)
            if callable(stopper):
                stopper()
        for component in components:
            joiner = getattr(component, "join", None)
            if callable(joiner):
                joiner(timeout=10)

    def _pending_research_incubations(self) -> tuple[str, ...]:
        pending: list[str] = []
        for record in self.intake_store.list_incubations(limit=500):
            memory = self.open_store(record.incubation_id).memory
            jobs = memory.list_research_jobs(limit=500)
            runs = memory.list_infusion_runs(limit=500)
            if any(job.get("status") in {
                ResearchJobStatus.QUEUED.value,
                ResearchJobStatus.RUNNING.value,
            } for job in jobs) or any(run.get("status") in {
                "pending", "running",
            } for run in runs):
                pending.append(record.incubation_id)
        return tuple(pending)

    def start(self) -> None:
        """Start workers for attached and subsequently created incubations."""
        with self._lock:
            if self._started:
                return
            runtimes: list[IncubationRuntime] = []
            try:
                # Rebuild only runtimes with durable work so a fresh process can
                # recover queued research without eagerly constructing every
                # customer runtime.
                for incubation_id in self._pending_research_incubations():
                    self.research_executor(incubation_id)
                    self.infusion_executor(incubation_id)
                    self.infusion_service(incubation_id).memory.requeue_abandoned_infusion_runs()
                runtimes = list(self._runtimes.values())
                self._started = True
                for runtime in runtimes:
                    self._start_runtime(runtime)
            except Exception:
                self._started = False
                for started in runtimes:
                    self._stop_runtime(started)
                raise

    def runtime(self, incubation_id: str) -> IncubationRuntime:
        self.get_record(incubation_id)
        with self._lock:
            current = self._runtimes.get(incubation_id)
            if current is not None:
                return current
            if self.runtime_factory is not None:
                current = self.runtime_factory(self.open_store(incubation_id))
                self._runtimes[incubation_id] = current
                if self._started:
                    self._start_runtime(current)
                return current
        return IncubationRuntime()

    def intake_service(self, incubation_id: str):
        runtime = self.runtime(incubation_id)
        if runtime.intake_service is not None:
            return runtime.intake_service
        from .design_intake import DesignIntakeService

        scoped = self.open_store(incubation_id)
        runtime.intake_service = DesignIntakeService(
            scoped.memory,
            config=self.config,
            activity_service=self.activity_service(incubation_id),
            genesis_service=self.genesis_service(incubation_id),
            on_revision_saved=self.on_intake_revision(incubation_id),
        )
        with self._lock:
            self._runtimes[incubation_id] = runtime
        return runtime.intake_service

    def on_intake_revision(self, incubation_id: str) -> Callable[[str, DesignIntakeDraft, Mapping[str, Any]], Mapping[str, Any] | None]:
        def callback(session_id: str, draft: DesignIntakeDraft, revision: Mapping[str, Any]) -> Mapping[str, Any] | None:
            research = self.schedule_threshold_research(
                incubation_id,
                session_id=session_id,
                draft=draft,
                revision=revision,
            )
            self.schedule_infusion(incubation_id, "intake_revision", session_id=session_id)
            return research

        return callback

    def research_service(self, incubation_id: str) -> IncubationResearchService:
        runtime = self.runtime(incubation_id)
        if runtime.research_service is not None:
            return runtime.research_service
        service = IncubationResearchService(
            self.open_store(incubation_id).memory,
            activity_service=self.activity_service(incubation_id),
            max_sources_per_pass=self.settings.max_sources_per_pass,
            max_items_per_source=self.settings.max_items_per_source,
            fallback_reader=self._pipeworx_fallback_reader(incubation_id),
        )
        runtime.research_service = service
        with self._lock:
            self._runtimes[incubation_id] = runtime
        return service

    def _pipeworx_fallback_reader(self, incubation_id: str):
        """A bounded pipeworx/web evidence reader used when a public-source pass
        finds nothing readable, so an automatic pass still yields evidence."""
        try:
            include_pipeworx = bool((self.config.get("infusion") or {}).get("include_pipeworx", True))
        except Exception:
            include_pipeworx = True
        if not include_pipeworx:
            return None
        runtime = self.runtime(incubation_id)
        context = getattr(runtime.chat_executor, "context", None)
        if not isinstance(context, Mapping) or not context.get("config"):
            context = getattr(runtime.lab_service, "context", None)
        if not isinstance(context, Mapping) or not context.get("config"):
            context = {"config": self.config}
        from ..hands.pipeworx import build_fallback_reader

        return build_fallback_reader(context)

    @staticmethod
    def _present_intake_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set)):
            return any(IncubationApplicationService._present_intake_value(item) for item in value)
        return True

    def _research_context_ready(self, draft: DesignIntakeDraft) -> bool:
        try:
            offer = draft.value("business.offer_summary")
            context = (
                draft.value("business.primary_services"),
                draft.value("audience.primary"),
                draft.owner_confirmed_value("business.location"),
                draft.owner_confirmed_value("business.service_area"),
            )
        except ContractError:
            return False
        return (
            draft.location_context_resolved
            and self._present_intake_value(offer)
            and any(self._present_intake_value(item) for item in context)
        )

    @staticmethod
    def _excluded_communities(memory: Memory) -> tuple[str, ...]:
        names: list[str] = []
        for source in memory.list_research_sources(limit=500):
            if source.get("trust_state") == "excluded" or source.get("excluded"):
                title = str(source.get("title") or "").strip()
                if title:
                    names.append(title)
        for request in memory.list_research_requests(limit=500):
            for candidate in request.get("candidate_communities") or []:
                if candidate.get("status") in {"rejected", "excluded"} and candidate.get("name"):
                    names.append(str(candidate["name"]))
        return tuple(dict.fromkeys(names))

    def schedule_threshold_research(
        self,
        incubation_id: str,
        *,
        session_id: str,
        draft: DesignIntakeDraft,
        revision: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Queue one bounded pass after a useful intake revision is durable."""
        if not self.settings.research_enabled:
            return {"status": "disabled"}
        if not self._research_context_ready(draft):
            return {"status": "not_ready"}
        memory = self.open_store(incubation_id).memory
        current_revision = int(revision.get("revision") or 0)
        automatic_requests = [
            item for item in memory.list_research_requests(limit=500)
            if item.get("trigger") == "intake_threshold"
        ]
        # One automatic pass per intake revision, never more: the owner's next
        # message advances the revision and unlocks one fresh pass, so research
        # keeps pace with the conversation without ever bursting.
        passes_on_revision = [
            item for item in automatic_requests
            if int(item.get("intake_revision") or 0) == current_revision
        ]
        if len(passes_on_revision) >= self.settings.max_passes_before_owner_turn:
            self.activity_service(incubation_id).record(
                category="research",
                kind="research_threshold",
                state="needs_attention",
                summary="This intake revision already triggered an automatic research pass.",
                provenance="system",
                confidence=1.0,
                detail={"status": "per_revision_cap", "count": len(passes_on_revision)},
                intake_session_id=session_id,
                intake_revision=current_revision or None,
            )
            return {"status": "owner_turn_required", "count": len(passes_on_revision)}

        owner_language = str(draft.value("site.language") or "en").strip().lower().replace("_", "-")
        planner = self.runtime(incubation_id).research_planner
        planning_error = ""
        try:
            if planner is None:
                raise IncubationResearchPlanningError("research planner is unavailable")
            plan = planner.plan(
                draft,
                owner_language=owner_language,
                excluded_communities=self._excluded_communities(memory),
            )
        except IncubationResearchPlanningError as exc:
            planning_error = f"planner_{type(exc).__name__}"
            plan = base_plan(draft, owner_language=owner_language)

        plan_data = plan.to_dict()
        request_body = {
            **plan_data,
            "feed_urls": [str(item.get("url") or "") for item in plan_data.get("candidate_feeds") or []],
            "trigger": "intake_threshold",
            "intake_revision": int(revision.get("revision") or 0),
            "fetch": True,
        }
        service = self.research_service(incubation_id)
        result = service.request(request_body, enqueue=True)
        if planning_error:
            request_id = str(result.get("request", {}).get("request_id") or "")
            if request_id:
                memory.update_research_request(request_id, error=planning_error)
            result["planner_error"] = planning_error
        if result.get("status") == "queued":
            record = self.get_record(incubation_id)
            if record.status == IncubationStatus.COLLECTING.value:
                self.transition(
                    incubation_id,
                    IncubationStatus.RESEARCHING.value,
                    event="research_started",
                    detail={"request_id": result.get("request", {}).get("request_id")},
                )
            self.research_executor(incubation_id)
        return {
            "status": result.get("status"),
            "request_id": result.get("request", {}).get("request_id"),
            "job_id": result.get("job", {}).get("job_id"),
            **({"planner_error": planning_error} if planning_error else {}),
        }

    def research_executor(self, incubation_id: str) -> IncubationResearchExecutor:
        runtime = self.runtime(incubation_id)
        if runtime.research_executor is not None:
            return runtime.research_executor
        executor = IncubationResearchExecutor(
            self.research_service(incubation_id),
            on_finished=lambda request_id, error: self._research_finished(incubation_id, request_id, error),
        )
        with self._lock:
            runtime.research_executor = executor
            started = self._started
        if started:
            executor.start()
        return executor

    def _research_finished(self, incubation_id: str, request_id: str, error: str | None) -> None:
        try:
            record = self.get_record(incubation_id)
            if record.status != IncubationStatus.RESEARCHING.value:
                return
            self.transition(
                incubation_id,
                IncubationStatus.COLLECTING.value,
                event="research_blocked" if error else "research_completed",
                detail={"request_id": request_id, **({"error": error} if error else {})},
            )
        except Exception:
            # Research completion is diagnostic and must not terminate its worker.
            pass
        self.schedule_infusion(incubation_id, "research_completed")

    def infusion_service(self, incubation_id: str) -> IncubationInfusionService:
        runtime = self.runtime(incubation_id)
        if runtime.infusion_service is not None:
            return runtime.infusion_service
        from ..config import resolve_secret
        from ..core.llm import Client

        scoped = self.open_store(incubation_id)
        llm = runtime.llm
        if llm is None:
            llm = Client(self.config, scoped.memory, env=self._runtime_env(incubation_id))
        runner_context: dict[str, Any] = {}
        if runtime.chat_executor is not None and getattr(runtime.chat_executor, "context", None):
            runner_context = dict(runtime.chat_executor.context)
        elif getattr(runtime, "lab_service", None) is not None and getattr(runtime.lab_service, "context", None):
            runner_context = dict(runtime.lab_service.context)
        runner_context.setdefault("config", self.config)
        from ..hands import opencode_runner

        service = IncubationInfusionService(
            scoped.memory,
            config=self.config,
            llm=llm,
            activity_service=self.activity_service(incubation_id),
            research_service=self.research_service(incubation_id),
            genesis_service=self.genesis_service(incubation_id),
            opencode_runner=opencode_runner.stage_infusion,
            runner_context=runner_context,
        )
        runtime.infusion_service = service
        with self._lock:
            self._runtimes[incubation_id] = runtime
        return service

    def _runtime_env(self, incubation_id: str) -> dict[str, str] | None:
        runtime = self.runtime(incubation_id)
        context = getattr(runtime.chat_executor, "context", None)
        if isinstance(context, Mapping):
            env = context.get("env")
            if isinstance(env, Mapping):
                return {str(k): str(v) for k, v in env.items()}
        return None

    def infusion_executor(self, incubation_id: str) -> IncubationInfusionExecutor:
        runtime = self.runtime(incubation_id)
        if runtime.infusion_executor is not None:
            return runtime.infusion_executor
        executor = IncubationInfusionExecutor(
            self.infusion_service(incubation_id),
            on_finished=lambda run_id, error: self._infusion_finished(incubation_id, run_id, error),
        )
        with self._lock:
            runtime.infusion_executor = executor
            started = self._started
        if started:
            executor.start()
        return executor

    def _infusion_finished(self, incubation_id: str, run_id: str, error: str | None) -> None:
        try:
            if not run_id or error:
                return
            self.activity_service(incubation_id).record(
                category="research",
                kind="infusion_pass",
                state="completed",
                summary="A background knowledge pass extended the incubation.",
                provenance="model_inference",
                confidence=0.5,
                detail={"run_id": run_id, "status": "completed"},
            )
        except Exception:
            pass

    def schedule_infusion(
        self,
        incubation_id: str,
        trigger: str,
        *,
        session_id: str = "",
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue one durable background knowledge pass without blocking the
        calling turn. Returns queued/skipped/disabled status."""
        if not self.infusion_settings.enabled:
            return {"status": "disabled", "trigger": trigger}
        try:
            service = self.infusion_service(incubation_id)
            run = service.enqueue(trigger=trigger, session_id=session_id, snapshot=snapshot)
        except (IncubationInfusionError, ContractError, ValueError) as exc:
            return {"status": "needs_attention", "error": str(exc)[:200], "trigger": trigger}
        if run is not None:
            self.infusion_executor(incubation_id)
            return {"status": "queued", "run_id": run.get("run_id"), "trigger": trigger}
        return {"status": "skipped", "trigger": trigger}

    def activity_service(self, incubation_id: str) -> IncubationActivityService:
        runtime = self.runtime(incubation_id)
        if runtime.activity_service is not None:
            return runtime.activity_service
        service = IncubationActivityService(self.open_store(incubation_id).memory)
        runtime.activity_service = service
        with self._lock:
            self._runtimes[incubation_id] = runtime
        return service

    def activity_projection(
        self,
        incubation_id: str,
        *,
        after_id: int | str | None = None,
        before_id: int | str | None = None,
        limit: int = 100,
        categories: tuple[str, ...] | list[str] = (),
    ) -> dict[str, Any]:
        self.get_record(incubation_id)
        try:
            return self.activity_service(incubation_id).list(
                after_id=after_id,
                before_id=before_id,
                limit=limit,
                categories=categories,
            )
        except Exception as exc:
            if isinstance(exc, IncubationServiceError):
                raise
            raise IncubationServiceError(str(exc)[:500]) from exc

    def activity_detail(self, incubation_id: str, activity_id: str | int) -> dict[str, Any] | None:
        self.get_record(incubation_id)
        try:
            return self.activity_service(incubation_id).get(activity_id)
        except Exception as exc:
            if isinstance(exc, IncubationServiceError):
                raise
            raise IncubationServiceError(str(exc)[:500]) from exc

    def novelty_service(self, incubation_id: str) -> NoveltyService:
        runtime = self.runtime(incubation_id)
        if runtime.novelty_service is not None:
            return runtime.novelty_service
        service = NoveltyService(self.intake_store)
        runtime.novelty_service = service
        with self._lock:
            self._runtimes[incubation_id] = runtime
        return service

    def genesis_service(self, incubation_id: str) -> CustomerGenesisService:
        runtime = self.runtime(incubation_id)
        if runtime.genesis_service is not None:
            return runtime.genesis_service
        service = CustomerGenesisService(self.open_store(incubation_id).memory)
        runtime.genesis_service = service
        with self._lock:
            self._runtimes[incubation_id] = runtime
        return service

    def _session(self, incubation_id: str) -> dict[str, Any]:
        intake = self.intake_service(incubation_id)
        memory = self.open_store(incubation_id).memory
        sessions = memory.list_design_intake_sessions(limit=1)
        if sessions:
            return intake.get_session(str(sessions[0]["session_id"]))
        return intake.create_session()

    def send_message(
        self,
        incubation_id: str,
        message: str,
        *,
        attachments: Any = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = self.get_record(incubation_id)
        if record.status == IncubationStatus.ACCEPTED.value:
            self.transition(incubation_id, IncubationStatus.COLLECTING.value, event="new_intake_revision")
        session = self._session(incubation_id)
        try:
            result = self.intake_service(incubation_id).send_message(
                session["session_id"],
                message,
                attachments=attachments,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        self.activity_service(incubation_id).record(
            category="conversation",
            kind="owner_message_queued",
            state="completed",
            summary="Recorded the owner's message and queued Ada's next intake turn.",
            provenance="owner",
            conversation_id=int(result.get("conversation_id") or session.get("conversation_id") or 0) or None,
            message_id=int(result.get("message_id") or 0) or None,
            chat_job_id=int(result.get("job_id") or 0) or None,
            intake_session_id=str(result.get("session_id") or session.get("session_id") or "") or None,
        )
        return {"session": self.intake_service(incubation_id).get_session(session["session_id"]), **result}

    def request_research(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        record = self.get_record(incubation_id)
        if record.status == IncubationStatus.COLLECTING.value:
            self.transition(incubation_id, IncubationStatus.RESEARCHING.value, event="research_started")
        try:
            result = self.research_service(incubation_id).request(body, enqueue=True)
            if result.get("status") == "queued":
                self.research_executor(incubation_id)
        except IncubationResearchError as exc:
            if self.get_record(incubation_id).status == IncubationStatus.RESEARCHING.value:
                self.transition(incubation_id, IncubationStatus.COLLECTING.value, event="research_blocked", detail={"error": str(exc)})
            raise IncubationServiceError(str(exc)[:500]) from exc
        if result.get("status") != "queued" and self.get_record(incubation_id).status == IncubationStatus.RESEARCHING.value:
            event = "research_completed" if result.get("status") == "complete" else "research_blocked"
            self.transition(incubation_id, IncubationStatus.COLLECTING.value, event=event)
        return result

    def research_projection(self, incubation_id: str) -> dict[str, Any]:
        self.get_record(incubation_id)
        return self.research_service(incubation_id).projection()

    def update_research_source(self, incubation_id: str, source_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        self.get_record(incubation_id)
        try:
            return self.research_service(incubation_id).update_source(source_id, changes)
        except IncubationResearchError as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def media_service_for(self, incubation_id: str) -> Any:
        self.get_record(incubation_id)
        runtime = self.runtime(incubation_id)
        service = runtime.media_service
        if service is None:
            raise IncubationServiceError("incubation media is unavailable")
        return service

    def lab_service_for(self, incubation_id: str) -> Any:
        self.get_record(incubation_id)
        runtime = self.runtime(incubation_id)
        service = runtime.lab_service
        if service is None:
            raise IncubationServiceError("scoped design service is unavailable")
        return service

    def design_run(self, incubation_id: str, run_id: str) -> dict[str, Any]:
        try:
            return self.lab_service_for(incubation_id).get_run(run_id)
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError("design run was not found") from exc

    def technical_repair(
        self,
        incubation_id: str,
        run_id: str,
        *,
        owner_request: str = "",
    ) -> dict[str, Any]:
        try:
            return self.lab_service_for(incubation_id).create_technical_repair(
                run_id,
                owner_request=owner_request,
            )
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def retry_visual_review(self, incubation_id: str, run_id: str) -> dict[str, Any]:
        try:
            return self.lab_service_for(incubation_id).retry_visual_review(run_id)
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def design_pages(self, incubation_id: str, run_id: str) -> list[str]:
        try:
            return self.lab_service_for(incubation_id).pages(run_id)
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError("design run was not found") from exc

    def design_preview_identity(self, incubation_id: str, run_id: str, variant: str) -> tuple[Path, str]:
        try:
            return self.lab_service_for(incubation_id).preview_identity(run_id, variant)
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError("design preview is unavailable") from exc

    def design_preview_profile(self, incubation_id: str, run_id: str) -> str:
        try:
            service = self.lab_service_for(incubation_id)
            resolver = getattr(service, "preview_profile", None)
            if not callable(resolver):
                return ""
            return str(resolver(run_id) or "").strip()
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError("design preview is unavailable") from exc

    def list_media(self, incubation_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self.media_service_for(incubation_id).list(
                media_kind="image", include_archived=False, limit=max(1, min(int(limit), 100))
            )
        except (IncubationServiceError, TypeError, ValueError) as exc:
            if isinstance(exc, IncubationServiceError):
                raise
            raise IncubationServiceError("incubation media is unavailable") from exc

    def upload_media(self, incubation_id: str, name: str, data: bytes, content_type: str = "") -> dict[str, Any]:
        try:
            return self.media_service_for(incubation_id).upload(name, data, content_type).get("asset")
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def update_intake_assets(self, incubation_id: str, session_id: str, assets: Any) -> dict[str, Any]:
        self.get_record(incubation_id)
        try:
            return self.intake_service(incubation_id).update_assets(session_id, assets)
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def chat_job(self, incubation_id: str, job_id: int) -> dict[str, Any]:
        self.get_record(incubation_id)
        try:
            job = self.open_store(incubation_id).memory.get_chat_job(int(job_id))
        except (TypeError, ValueError) as exc:
            raise IncubationServiceError("advice job was not found") from exc
        if not job or job.get("operation_kind") != "design_intake_advice":
            raise IncubationServiceError("advice job was not found")
        return {
            "id": job.get("id"),
            "status": job.get("status"),
            "steps": job.get("steps") or [],
            "result": job.get("result"),
            "error": job.get("error"),
            "session_id": job.get("intake_session_id"),
            "message_id": job.get("message_id"),
        }

    def chat_jobs(self, incubation_id: str, limit: int = 50) -> dict[str, Any]:
        """Diagnostic list of advice jobs with ages for a "stuck turn" report."""
        self.get_record(incubation_id)
        memory = self.open_store(incubation_id).memory
        conversation_rows = memory.list_design_intake_sessions(limit=1)
        conversation_id = int(conversation_rows[0].get("conversation_id") or 0) if conversation_rows else None
        items = memory.list_chat_jobs(conversation_id, limit=max(1, min(int(limit), 200))) if conversation_id else []
        now = datetime.now(timezone.utc)
        jobs = []
        for job in items:
            stamp = str(job.get("updated_ts") or job.get("created_ts") or "")
            age_seconds = None
            try:
                age_seconds = int((now - datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
            jobs.append({
                "id": job.get("id"),
                "status": job.get("status"),
                "age_seconds": max(age_seconds, 0) if age_seconds is not None else None,
                "operation_kind": job.get("operation_kind"),
                "session_id": job.get("intake_session_id"),
                "message_id": job.get("message_id"),
                "error": job.get("error"),
                "result_duration_ms": (job.get("result") or {}).get("duration_ms") if job.get("result") else None,
            })
        return {"conversation_id": conversation_id, "jobs": jobs}

    def media_object(self, incubation_id: str, key: str) -> tuple[bytes, str]:
        try:
            return self.media_service_for(incubation_id).read_object(key)
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError("media object not found") from exc

    def media_preview(self, incubation_id: str, asset_id: int, *, thumbnail: bool) -> tuple[bytes, str]:
        try:
            return self.media_service_for(incubation_id).read_preview(asset_id, thumbnail=thumbnail)
        except IncubationServiceError:
            raise
        except Exception as exc:
            raise IncubationServiceError("media object not found") from exc

    def genesis_projection(self, incubation_id: str) -> dict[str, Any]:
        self.get_record(incubation_id)
        memory = self.open_store(incubation_id).memory
        current = memory.get_customer_genesis_revision()
        return {
            "current": current["genesis"].to_dict() if current else None,
            "revisions": [item["genesis"].to_dict() for item in memory.list_customer_genesis_revisions(limit=100)],
        }

    def _refresh_lifecycle(self, incubation_id: str) -> IncubationRecord:
        record = self.get_record(incubation_id)
        if record.status in {
            IncubationStatus.ACCEPTED.value,
            IncubationStatus.PROVISIONING.value,
            IncubationStatus.PROVISIONED.value,
            IncubationStatus.REJECTED.value,
            IncubationStatus.EXPIRED.value,
        }:
            return record
        memory = self.open_store(incubation_id).memory
        sessions = memory.list_design_intake_sessions(limit=1)
        if not sessions:
            return record
        session = dict(sessions[0])
        session_id = str(session.get("session_id") or "")
        current_revision_id = None
        try:
            intake_session = self.intake_service(incubation_id).get_session(session_id)
            current_revision_id = intake_session.get("confirmed_revision_id")
        except Exception:
            intake_session = session
        root_run_id = str(session.get("design_run_id") or "")
        all_runs = []
        for candidate in memory.list_design_runs(mode="local_experiment", limit=500):
            if str(candidate.get("intake_session_id") or "") != session_id:
                continue
            all_runs.append(candidate)
        runs_by_id = {
            str(candidate.get("run_id") or ""): candidate
            for candidate in all_runs
            if str(candidate.get("run_id") or "").strip()
        }
        relevant_ids: set[str] = set()
        for candidate in all_runs:
            candidate_id = str(candidate.get("run_id") or "")
            candidate_revision_id = candidate.get("intake_revision_id")
            if current_revision_id is not None and candidate_revision_id == current_revision_id:
                relevant_ids.add(candidate_id)
        root = runs_by_id.get(root_run_id)
        if root is not None and (
            current_revision_id is None
            or root.get("intake_revision_id") in {None, current_revision_id}
        ):
            relevant_ids.add(root_run_id)
        changed = True
        while changed:
            changed = False
            for candidate in all_runs:
                candidate_id = str(candidate.get("run_id") or "")
                parent_id = str(candidate.get("parent_run_id") or "")
                if candidate_id not in relevant_ids and parent_id in relevant_ids:
                    relevant_ids.add(candidate_id)
                    changed = True
        runs = [candidate for candidate in all_runs if str(candidate.get("run_id") or "") in relevant_ids]
        if not runs:
            return record

        active_statuses = {
            DesignRunStatus.CREATED.value,
            DesignRunStatus.ASSESSING_INTAKE.value,
            DesignRunStatus.PLANNING.value,
            DesignRunStatus.BUILDING.value,
            DesignRunStatus.CANDIDATE_READY.value,
            DesignRunStatus.VALIDATING.value,
        }
        terminal_statuses = {
            DesignRunStatus.FAILED.value,
            DesignRunStatus.CANCELLED.value,
            DesignRunStatus.INTERRUPTED.value,
            DesignRunStatus.INCOMPLETE.value,
            DesignRunStatus.NEEDS_REPAIR.value,
        }
        active = [run for run in runs if run.get("status") in active_statuses]
        reviewable = [run for run in runs if run.get("status") == DesignRunStatus.READY_FOR_REVIEW.value]
        if active:
            if record.status != IncubationStatus.BUILDING.value:
                return self.transition(
                    incubation_id,
                    IncubationStatus.BUILDING.value,
                    event="descendant_active",
                    detail={"run_ids": [str(run.get("run_id") or "") for run in active]},
                )
            return record
        if reviewable and record.status in {
            IncubationStatus.BUILDING.value,
            IncubationStatus.BLOCKED.value,
        }:
            latest = max(reviewable, key=lambda run: str(run.get("updated_ts") or run.get("created_ts") or ""))
            return self.transition(
                incubation_id,
                IncubationStatus.READY_FOR_FEEDBACK.value,
                event="candidate_ready",
                detail={"run_id": latest.get("run_id"), "candidate_count": len(reviewable)},
            )
        if not reviewable and record.status == IncubationStatus.BUILDING.value:
            terminal = [run for run in runs if run.get("status") in terminal_statuses]
            if terminal and len(terminal) == len(runs):
                latest = max(terminal, key=lambda run: str(run.get("updated_ts") or run.get("created_ts") or ""))
                return self.transition(
                    incubation_id,
                    IncubationStatus.BLOCKED.value,
                    event="candidate_failed",
                    detail={"run_id": latest.get("run_id"), "status": latest.get("status"), "run_count": len(runs)},
                )
        return record

    def _shared_design_skill_set(self, incubation_id: str) -> DesignSkillSet:
        runtime = self.runtime(incubation_id)
        for service in (runtime.design_service, runtime.lab_service, runtime.intake_service):
            skill_set = getattr(service, "skill_set", None)
            if isinstance(skill_set, DesignSkillSet):
                return skill_set
        return load_design_skills()

    @staticmethod
    def _context_texts(value: Any, *, limit: int = 20) -> list[str]:
        values = [value] if isinstance(value, str) else list(value or ()) if isinstance(value, (list, tuple, set)) else []
        result: list[str] = []
        for item in values:
            text = str(item or "").strip()[:500]
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _insight_context(item: Mapping[str, Any]) -> dict[str, Any]:
        """Expose only the safe, evidence-linked part of an insight to design."""
        return {
            "insight_id": str(item.get("insight_id") or ""),
            "kind": str(item.get("kind") or ""),
            "summary": str(item.get("summary") or "")[:2_000],
            "confidence": float(item.get("confidence") or 0.0),
            "status": str(item.get("status") or ""),
            "owner_language": str(item.get("owner_language") or ""),
            "source_languages": list(item.get("source_languages") or ())[:20],
            "finding_ids": list(item.get("finding_ids") or ())[:50],
            "supports_paths": list(item.get("supports_paths") or ())[:20],
        }

    @staticmethod
    def _deduction_context(item: Mapping[str, Any]) -> dict[str, Any]:
        """Expose bounded infusion knowledge without its execution metadata."""
        return {
            "deduction_id": str(item.get("deduction_id") or ""),
            "kind": str(item.get("kind") or ""),
            "summary": str(item.get("summary") or "")[:2_000],
            "confidence": float(item.get("confidence") or 0.0),
            "basis": str(item.get("basis") or ""),
            "source_refs": list(item.get("source_refs") or ())[:20],
            "supports_paths": list(item.get("supports_paths") or ())[:20],
            "citation_uris": [
                str(uri) for uri in list(item.get("citation_uris") or ())[:20]
                if str(uri).startswith("pipeworx://")
            ],
        }

    @classmethod
    def _genesis_context(cls, genesis: Any) -> dict[str, Any]:
        """Keep only customer-facing genesis guidance relevant to design."""
        sections = {
            "business_world": ("purpose", "values", "customer_promises", "tensions", "language"),
            "relationship": ("owner_preferences", "decision_style", "communication_preferences", "boundaries"),
            "creative_identity": ("principles", "developing_tastes", "patterns_to_avoid", "open_questions"),
            "research_identity": ("subjects", "communities"),
        }
        result: dict[str, Any] = {}
        for section_name, fields in sections.items():
            source = getattr(genesis, section_name, {})
            if not isinstance(source, Mapping):
                continue
            section: dict[str, Any] = {}
            for field_name in fields:
                value = source.get(field_name)
                if field_name in {"purpose", "decision_style"}:
                    text = str(value or "").strip()[:2_000]
                    if text:
                        section[field_name] = text
                else:
                    values = cls._context_texts(value, limit=50)
                    if values:
                        section[field_name] = values
            if section:
                result[section_name] = section
        return result

    def _incubated_creative_context(
        self,
        incubation_id: str,
        *,
        session: Mapping[str, Any],
        intake: SiteIntake,
        novelty: Any,
    ) -> IncubatedCreativeContext:
        memory = self.open_store(incubation_id).memory
        genesis = self.genesis_service(incubation_id).current()
        skill_set = self._shared_design_skill_set(incubation_id)
        summary = session.get("summary") if isinstance(session.get("summary"), Mapping) else {}
        # Owner-facing direction can be confirmed by the owner, advised by Ada
        # and accepted, or carried as a reversible default. All of it is part of
        # the business's own voice and must reach the builder; only the neutral
        # machinery in here is generic. Merge confirmed + advised first, then
        # fall back to assumed values so nothing the owner accepted is dropped.
        views: list[Mapping[str, Any]] = []
        for key in ("confirmed", "advised", "assumed"):
            value = summary.get(key)
            if isinstance(value, Mapping):
                views.append(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, Mapping) and item.get("path") is not None:
                        views.append({str(item["path"]): item.get("value")})
            else:
                views.append({})
        merged: dict[str, Any] = {}
        for view in reversed(views):
            for key, value in view.items():
                merged.setdefault(str(key), value)
        preferences: list[str] = []
        for path in (
            "brand.visual_preferences", "brand.vibe", "brand.colors", "brand.typography",
        ):
            preferences.extend(self._context_texts(merged.get(path)))
        dislikes: list[str] = []
        for path in ("brand.visual_dislikes", "brand.styles_to_avoid"):
            dislikes.extend(self._context_texts(merged.get(path)))

        owner_language = str(intake.site.get("language") or "en").strip().lower().replace("_", "-")
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", owner_language):
            owner_language = "en"
        insights = [
            self._insight_context(item)
            for item in memory.list_incubation_insights(limit=200)
            if item.get("status") != "excluded" and str(item.get("summary") or "").strip()
        ]
        deductions = [
            self._deduction_context(item)
            for item in memory.list_incubation_deductions(limit=100)
            if str(item.get("summary") or "").strip()
        ]
        cross_language = [
            item for item in insights
            if any(language not in {"", "und", owner_language} for language in item.get("source_languages") or ())
        ]
        patterns = list(genesis.creative_identity.get("patterns_to_avoid") or ())
        patterns.extend(dislikes)
        novelty_data = novelty.to_dict() if hasattr(novelty, "to_dict") else {}
        patterns.extend(novelty_data.get("constraints") or ())
        visual_notes = _asset_visual_reference_notes(session.get("assets"))
        context = IncubatedCreativeContext.from_dict({
            "genesis_revision": genesis.revision,
            "genesis_hash": genesis.content_hash,
            "owner_confirmed_visual_preferences": preferences,
            "owner_confirmed_visual_dislikes": dislikes,
            "research_backed_creative_implications": insights,
            "cross_language_audience_insights": cross_language,
            "customer_genesis": self._genesis_context(genesis),
            "infusion_deductions": deductions,
            "novelty_constraints": novelty_data,
            "patterns_to_avoid": patterns,
            "design_skill_set": DesignSkillReceipt(skill_set.names, skill_set.content_hash).to_dict(),
            "visual_reference_notes": list(visual_notes),
        })
        self.activity_service(incubation_id).record(
            category="design",
            kind="creative_context_frozen",
            state="completed",
            summary="Froze owner-confirmed preferences, research implications, novelty constraints, and trusted design guidance for the candidate.",
            provenance="host_validation",
            confidence=1.0,
            detail={
                "genesis_revision": genesis.revision,
                "count": len(insights),
                "infusion_deduction_count": len(deductions),
                "genesis_sections": sorted(self._genesis_context(genesis)),
                "languages": sorted({language for item in insights for language in item.get("source_languages") or () if language}),
                "translation_note": "cross-language insights remain evidence-linked and non-authoritative",
            },
            intake_session_id=str(session.get("session_id") or "") or None,
            intake_revision=int(session.get("confirmed_revision") or session.get("revision") or 0) or None,
            genesis_revision=genesis.revision,
        )
        return context

    def confirm_intake(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationServiceError("intake confirmation must be an object")
        self.get_record(incubation_id)
        session_id = str(body.get("session_id") or "").strip()
        if not session_id:
            session = self._session(incubation_id)
            session_id = str(session["session_id"])
        session = self.intake_service(incubation_id).get_session(session_id)
        try:
            revision = int(body.get("revision"))
        except (TypeError, ValueError) as exc:
            raise IncubationServiceError("revision is invalid") from exc
        draft_hash = str(body.get("draft_hash") or body.get("intake_hash") or "").strip()
        if not draft_hash:
            raise IncubationServiceError("draft_hash is required")
        try:
            result = self.intake_service(incubation_id).confirm(
                session_id,
                revision=revision,
                draft_hash=draft_hash,
                confirmation_text=str(body.get("confirmation_text") or "Build this"),
                idempotency_key=body.get("idempotency_key"),
            )
            genesis = self.genesis_service(incubation_id).propose_from_session(session, updates=body)
            self.genesis_service(incubation_id).save(genesis, source_kind="owner_confirmation")
            self.activity_service(incubation_id).record(
                category="genesis",
                kind="genesis_revision_created",
                state="completed",
                summary="Recorded an owner-confirmed customer-Ada genesis revision.",
                provenance="owner_confirmation",
                confidence=1.0,
                detail={"revision": genesis.revision, "status": "owner_confirmed"},
                intake_session_id=session_id,
                intake_revision=revision,
                genesis_revision=genesis.revision,
            )
            confirmed_session = result["session"]
            self.intake_store.update_incubation_revisions(incubation_id, current_intake_revision=int(confirmed_session.get("revision") or revision), current_genesis_revision=genesis.revision)
            record = self.get_record(incubation_id)
            if record.status == IncubationStatus.COLLECTING.value:
                record = self.transition(incubation_id, IncubationStatus.READY_TO_BUILD.value, event="intake_confirmed", detail={"session_id": session_id, "revision": revision})
        except Exception as exc:
            if isinstance(exc, IncubationServiceError):
                raise
            raise IncubationServiceError(str(exc)[:500]) from exc
        return {"session": result["session"], "genesis": genesis.to_dict(), "incubation": record.to_dict()}

    def build(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationServiceError("build request must be an object")
        record = self._refresh_lifecycle(incubation_id)
        if record.status == IncubationStatus.BUILDING.value:
            # An owner retry while a candidate is already in flight reconnects
            # to it: intake_service.build reuses the active run idempotently.
            pass
        elif record.status not in {IncubationStatus.READY_TO_BUILD.value, IncubationStatus.BLOCKED.value}:
            # BLOCKED only ever means a candidate that failed (see
            # _refresh_lifecycle), so the owner can retry the frozen brief by
            # starting a fresh candidate. Any other state is not buildable.
            raise IncubationServiceError("incubation is not ready to build")
        runtime = self.runtime(incubation_id)
        if runtime.lab_service is None:
            raise IncubationServiceError("scoped design build service is unavailable")
        try:
            session = self._session(incubation_id)
            session = self.intake_service(incubation_id).get_session(str(session["session_id"]))
            draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
            offer_summary = draft.value("business.offer_summary")
            if not isinstance(offer_summary, str) or not offer_summary.strip():
                raise IncubationServiceError("business.offer_summary is required before building")
            intake = draft.to_site_intake()
        except IncubationServiceError:
            raise
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        for component in (runtime.executor, runtime.chat_executor, runtime.media_worker):
            if component is not None and callable(getattr(component, "start", None)):
                component.start()
        raw_revision = body.get("confirmed_revision") or body.get("revision") or session.get("confirmed_revision")
        try:
            confirmed_revision = int(raw_revision)
        except (TypeError, ValueError) as exc:
            raise IncubationServiceError("confirmed_revision is invalid") from exc
        try:
            novelty = self.novelty_service(incubation_id).context_for(intake)
            creative_context = self._incubated_creative_context(
                incubation_id,
                session=session,
                intake=intake,
                novelty=novelty,
            )
            result = self.intake_service(incubation_id).build(
                session["session_id"],
                confirmed_revision=confirmed_revision,
                owner_request=str(body.get("owner_request") or ""),
                idempotency_key=body.get("idempotency_key"),
                force_new=bool(body.get("force_new")),
                context_extra={
                    "novelty_context": novelty.to_dict(),
                    "incubated_creative_context": creative_context.to_dict(),
                },
            )
            run_id = str((result.get("run") or {}).get("run_id") or "")
            self.activity_service(incubation_id).record(
                category="design",
                kind="design_run_queued",
                state="started",
                summary="Queued an isolated design candidate using the frozen creative context.",
                provenance="owner_confirmation",
                detail={"status": "queued", "count": len(creative_context.research_backed_creative_implications)},
                intake_session_id=session["session_id"],
                intake_revision=confirmed_revision,
                genesis_revision=creative_context.genesis_revision,
                design_run_id=run_id or None,
            )
            if record.status != IncubationStatus.BUILDING.value:
                record = self.transition(incubation_id, IncubationStatus.BUILDING.value, event="build_started", detail={"run_id": (result.get("run") or {}).get("run_id")})
        except (NoveltyServiceError, ContractError, ValueError) as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        return {**result, "incubation": record.to_dict()}

    def feedback(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationServiceError("feedback must be an object")
        self._refresh_lifecycle(incubation_id)
        session_id = str(body.get("session_id") or "").strip()
        if not session_id:
            session_id = self._session(incubation_id)["session_id"]
        try:
            session = self.intake_service(incubation_id).record_feedback(
                session_id,
                str(body.get("kind") or body.get("disposition") or "note"),
                notes=str(body.get("notes") or body.get("message") or ""),
                run_id=body.get("run_id"),
            )
        except Exception as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        record = self.get_record(incubation_id)
        if str(body.get("kind") or "").strip().lower() == "redesign" and record.status == IncubationStatus.READY_FOR_FEEDBACK.value:
            record = self.transition(incubation_id, IncubationStatus.COLLECTING.value, event="feedback_requests_redesign")
        self.activity_service(incubation_id).record(
            category="feedback",
            kind="owner_feedback_recorded",
            state="completed",
            summary="Recorded the owner's feedback on the candidate.",
            provenance="owner",
            detail={"status": str(body.get("kind") or body.get("disposition") or "note")[:40]},
            intake_session_id=session_id,
            design_run_id=str(body.get("run_id") or "") or None,
        )
        return {"session": session, "incubation": record.to_dict()}

    def accept(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationServiceError("acceptance must be an object")
        record = self._refresh_lifecycle(incubation_id)
        if record.status != IncubationStatus.READY_FOR_FEEDBACK.value:
            raise IncubationServiceError("incubation is not ready for acceptance")
        memory = self.open_store(incubation_id).memory
        sessions = memory.list_design_intake_sessions(limit=1)
        selected_run_id = str(body.get("run_id") or "").strip()
        run = memory.get_design_run(selected_run_id) if selected_run_id else None
        if run is None:
            session_id = str(sessions[0].get("session_id") or "") if sessions else ""
            candidates = [
                item for item in memory.list_design_runs(mode="local_experiment", limit=500)
                if str(item.get("intake_session_id") or "") == session_id
                and item.get("status") == DesignRunStatus.READY_FOR_REVIEW.value
            ]
            run = max(candidates, key=lambda item: str(item.get("updated_ts") or item.get("created_ts") or ""), default=None)
            selected_run_id = str((run or {}).get("run_id") or "")
        run_id = selected_run_id
        if not run or run.get("status") != DesignRunStatus.READY_FOR_REVIEW.value:
            raise IncubationServiceError("a ready-for-review candidate is required")
        candidate_sha = str(body.get("candidate_sha") or run.get("candidate_sha") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", candidate_sha):
            raise IncubationServiceError("candidate_sha is invalid")
        if str(run.get("candidate_sha") or "").strip().lower() != candidate_sha:
            raise IncubationServiceError("candidate_sha does not match the selected design run")
        website_source: dict[str, Any] = {
            "design_manifest_path": str(run.get("design_manifest_path") or ""),
            "operation_kind": str(run.get("operation_kind") or ""),
            "source_candidate_sha": str(run.get("source_candidate_sha") or ""),
        }
        try:
            design_service = self.runtime(incubation_id).design_service
            if design_service is not None:
                website_source["source_path"] = str(design_service.clone_path_for_run(run_id))
        except Exception:
            # Acceptance remains a durable context decision; provisioning will
            # refuse verification if the exact candidate source is unavailable.
            website_source["source_path"] = ""
        try:
            _context, manifest = CustomerContextService(memory).snapshot_for_run(
                incubation_id,
                run,
                website_source=website_source,
            )
            memory.update_design_run(
                run_id,
                customer_context_id=manifest.context_id,
                customer_context_hash=manifest.context_hash,
                customer_context_revision=manifest.context_revision,
            )
            run = memory.get_design_run(run_id) or run
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        # Store the immutable acceptance in the registry after all review checks pass.
        try:
            accepted = self.intake_store.transition_incubation(
                incubation_id,
                IncubationStatus.ACCEPTED.value,
                expected_status=record.status,
                accepted_candidate_sha=candidate_sha,
                accepted_run_id=run_id,
                acceptance_manifest_id=manifest.manifest_id,
                detail={"event": "candidate_accepted", "run_id": run_id},
            )
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc
        self.activity_service(incubation_id).record(
            category="feedback",
            kind="candidate_accepted",
            state="completed",
            summary="Accepted the exact candidate for the provisioning handoff.",
            provenance="owner_confirmation",
            confidence=1.0,
            detail={"status": "accepted"},
            genesis_revision=self.get_record(incubation_id).current_genesis_revision,
            design_run_id=run_id,
        )
        return {"incubation": accepted.to_dict(), "run": run}

    def provisioning_projection(self, incubation_id: str) -> dict[str, Any]:
        record = self.get_record(incubation_id)
        receipt = self.intake_store.get_receipt(record.provisioning_request_id) if record.provisioning_request_id else None
        bundle = None
        if record.provisioning_request_id:
            bundle_id = "bundle_" + hashlib.sha256(record.provisioning_request_id.encode("utf-8")).hexdigest()[:32]
            stored = self.open_store(incubation_id).memory.get_provisioning_bundle(bundle_id)
            if stored:
                bundle = {"bundle_id": bundle_id, "bundle_hash": stored.get("bundle_hash"), "created_ts": stored.get("created_ts")}
        return {
            "incubation": record.to_dict(),
            "request_id": record.provisioning_request_id,
            "customer_instance_id": record.customer_instance_id,
            "bundle": bundle,
            "receipt": receipt.to_dict() if receipt else None,
        }

    def provision(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._provision(incubation_id, body)

    def _provision(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationServiceError("provisioning request must be an object")
        record = self.get_record(incubation_id)
        if record.status == IncubationStatus.PROVISIONED.value and record.provisioning_request_id:
            receipt = self.intake_store.get_receipt(record.provisioning_request_id)
            if receipt:
                return {"receipt": receipt.to_dict(), "incubation": record.to_dict(), "idempotent": True}
        if record.status != IncubationStatus.ACCEPTED.value:
            raise IncubationServiceError("incubation must be accepted before provisioning")
        request_id = _request_id(body.get("request_id"), incubation_id)
        customer_id = _customer_id(body.get("customer_instance_id"), request_id)
        try:
            bundle = ProvisioningBundleService(self.open_store(incubation_id).memory, record).freeze(request_id)
            self.intake_store.transition_incubation(
                incubation_id,
                IncubationStatus.PROVISIONING.value,
                expected_status=record.status,
                provisioning_request_id=request_id,
                detail={"event": "provisioning_started", "bundle_id": bundle.bundle_id},
            )
            self.activity_service(incubation_id).record(
                category="provisioning",
                kind="provisioning_started",
                state="started",
                summary="Started the approved customer-Ada provisioning handoff.",
                provenance="owner_confirmation",
                detail={"status": "provisioning"},
            )
            with self._lock:
                runtime = self._runtimes.get(incubation_id) or IncubationRuntime()
            website_source_path = ""
            accepted_run_id = self.get_record(incubation_id).accepted_run_id
            design_service = getattr(runtime, "design_service", None)
            if accepted_run_id and design_service is not None:
                try:
                    website_source_path = str(design_service.clone_path_for_run(accepted_run_id)).strip()
                except Exception:
                    website_source_path = ""
            if self.get_record(incubation_id).accepted_run_id and not website_source_path:
                raise IncubationServiceError("accepted website source is unavailable")
            provisioner = CustomerProvisioningService(
                self.open_store(incubation_id).memory,
                self.intake_store,
                self.get_record(incubation_id),
                customer_root=self.settings.customer_root,
                source_media=getattr(runtime, "media_service", None),
                website_source_path=website_source_path or None,
            )
            receipt = provisioner.provision(body, bundle=bundle)
            final = self.intake_store.transition_incubation(
                incubation_id,
                IncubationStatus.PROVISIONED.value,
                expected_status=IncubationStatus.PROVISIONING.value,
                customer_instance_id=customer_id,
                detail={"event": "provisioned", "receipt_id": receipt.request_id},
            )
            episode_id = None
            try:
                episode_id = self.novelty_service(incubation_id).record_accepted_bundle(bundle).episode_id
            except Exception as exc:
                self.intake_store.transition_incubation(
                    incubation_id,
                    IncubationStatus.PROVISIONED.value,
                    detail={"event": "intake_episode_skipped", "error": str(exc)[:500]},
                )
            self.activity_service(incubation_id).record(
                category="provisioning",
                kind="customer_provisioned",
                state="completed",
                summary="Provisioned the separate customer-Ada instance from the accepted bundle.",
                provenance="host_validation",
                confidence=1.0,
                detail={"status": "provisioned"},
            )
        except (ProvisioningServiceError, ContractError, ValueError) as exc:
            try:
                if self.get_record(incubation_id).status == IncubationStatus.PROVISIONING.value:
                    self.intake_store.transition_incubation(
                        incubation_id,
                        IncubationStatus.ACCEPTED.value,
                        expected_status=IncubationStatus.PROVISIONING.value,
                        detail={"event": "provisioning_failed", "error": str(exc)[:500]},
                    )
            except Exception:
                pass
            self.activity_service(incubation_id).record(
                category="provisioning",
                kind="provisioning_failed",
                state="needs_attention",
                summary="The approved provisioning handoff needs attention and was not completed.",
                provenance="host_validation",
                detail={"status": "accepted"},
            )
            raise IncubationServiceError(str(exc)[:500]) from exc
        return {"receipt": receipt.to_dict(), "bundle_id": bundle.bundle_id, "episode_id": episode_id, "incubation": final.to_dict()}

    def activate(self, incubation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationServiceError("activation request must be an object")
        with self._lock:
            record = self.get_record(incubation_id)
            if record.status != IncubationStatus.PROVISIONED.value or not record.provisioning_request_id:
                raise IncubationServiceError("incubation must be provisioned before activation")
            receipt = self.intake_store.get_receipt(record.provisioning_request_id)
            if receipt is None:
                raise IncubationServiceError("verified provisioning receipt is missing")
            try:
                result = CustomerActivationService(self.settings.customer_root).activate(receipt)
                self.intake_store.transition_incubation(
                    incubation_id,
                    IncubationStatus.PROVISIONED.value,
                    detail={"event": "customer_activated", "customer_instance_id": receipt.customer_instance_id},
                )
                self.activity_service(incubation_id).record(
                    category="provisioning",
                    kind="customer_activated",
                    state="completed",
                    summary="Activated the separate customer-Ada runtime after provisioning verification.",
                    provenance="owner_confirmation",
                    confidence=1.0,
                    detail={"status": "active"},
                )
            except (ProvisioningServiceError, ContractError, ValueError) as exc:
                raise IncubationServiceError(str(exc)[:500]) from exc
            return {"activation": result, "incubation": self.get_record(incubation_id).to_dict()}

    def purge(self, incubation_id: str) -> bool:
        with self._lock:
            record, _ = self._registry_record_for_purge(incubation_id)
            if record.status in {IncubationStatus.ACCEPTED.value, IncubationStatus.PROVISIONING.value, IncubationStatus.PROVISIONED.value}:
                raise IncubationServiceError("accepted incubations cannot be purged")
            scoped = self._stores.pop(incubation_id, None)
            runtime = self._runtimes.pop(incubation_id, None)
            cleanup_errors: list[str] = []
            components = self._runtime_components(runtime) if runtime is not None else ()
            for component in components:
                stop = getattr(component, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception as exc:  # noqa: BLE001 - purge must leave a retryable tombstone
                        cleanup_errors.append(f"worker stop: {exc}")
            for component in components:
                join = getattr(component, "join", None)
                if callable(join):
                    try:
                        join(timeout=10)
                    except Exception as exc:  # noqa: BLE001 - purge must leave a retryable tombstone
                        cleanup_errors.append(f"worker join: {exc}")
            if scoped is not None:
                try:
                    scoped.close()
                except Exception as exc:  # noqa: BLE001 - purge must leave a retryable tombstone
                    cleanup_errors.append(f"store close: {exc}")

            try:
                self.intake_store.mark_purged(
                    incubation_id,
                    expected_status=None if record.status == IncubationStatus.PURGED.value else record.status,
                    outcome="pending",
                )
            except (ContractError, ValueError) as exc:
                raise IncubationServiceError(str(exc)[:500]) from exc

            workspace = self.root / record.incubation_id
            try:
                if workspace.is_symlink():
                    workspace.unlink()
                elif workspace.exists():
                    resolved = workspace.resolve()
                    if resolved == self.root or self.root not in resolved.parents:
                        raise IncubationServiceError("incubation workspace is outside the configured root")
                    shutil.rmtree(workspace)
            except Exception as exc:  # noqa: BLE001 - keep the tombstone non-reopenable
                cleanup_errors.append(f"workspace removal: {exc}")

            if cleanup_errors:
                message = "; ".join(cleanup_errors)[:500]
                self.intake_store.record_purge_result(incubation_id, outcome="failed", error=message)
                raise IncubationServiceError(message)
            self.intake_store.record_purge_result(incubation_id, outcome="removed")
            return True

    def transition(
        self,
        incubation_id: str,
        status: str,
        *,
        event: str | None = None,
        detail: Mapping[str, Any] | None = None,
        accepted_candidate_sha: str | None = None,
        provisioning_request_id: str | None = None,
        customer_instance_id: str | None = None,
    ) -> IncubationRecord:
        try:
            result = self.intake_store.transition_incubation(
                incubation_id,
                status,
                detail={**dict(detail or {}), "event": event or status},
                accepted_candidate_sha=accepted_candidate_sha,
                provisioning_request_id=provisioning_request_id,
                customer_instance_id=customer_instance_id,
            )
            self.activity_service(incubation_id).record(
                category=_activity_category(event or status),
                kind="lifecycle_transition",
                state="completed",
                summary=f"Incubation moved to {result.status.replace('_', ' ')}.",
                provenance="system",
                detail={"status": result.status, "reason": event or status},
            )
            return result
        except (ContractError, ValueError) as exc:
            raise IncubationServiceError(str(exc)[:500]) from exc

    def summary(self, incubation_id: str) -> dict[str, Any]:
        record = self._refresh_lifecycle(incubation_id)
        scoped = self.open_store(incubation_id)
        intake = self.intake_service(incubation_id)
        genesis = scoped.memory.get_customer_genesis_revision()
        return {
            "incubation": record.to_dict(),
            "events": self.intake_store.list_events(incubation_id, limit=100),
            "intake": intake.get_session(next(iter([row["session_id"] for row in scoped.memory.list_design_intake_sessions(limit=1)]), "")) if scoped.memory.list_design_intake_sessions(limit=1) else None,
            "genesis": genesis["genesis"].to_dict() if genesis else None,
            "research_sources": scoped.memory.list_research_sources(limit=100),
            "research_findings": [item.to_dict() for item in scoped.memory.list_research_findings(limit=200)],
            "research_requests": scoped.memory.list_research_requests(limit=100),
            "research_jobs": scoped.memory.list_research_jobs(limit=100),
            "research_insights": scoped.memory.list_incubation_insights(limit=200),
            "deductions": scoped.memory.list_incubation_deductions(limit=200),
            "infusion_runs": scoped.memory.list_infusion_runs(limit=50),
            "activity": self.activity_service(incubation_id).list(limit=100),
            "design_runs": [_design_projection(item) for item in scoped.memory.list_design_runs(mode="local_experiment", limit=50)],
        }

    def close(self) -> None:
        self.stop()
        with self._lock:
            runtimes = list(self._runtimes.values())
            stores = list(self._stores.values())
            self._runtimes.clear()
            self._stores.clear()
        for scoped in stores:
            scoped.close()

    def stop(self) -> None:
        """Stop all incubation workers without closing their stores."""
        with self._lock:
            self._started = False
            runtimes = list(self._runtimes.values())
            for runtime in runtimes:
                self._stop_runtime(runtime)


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _activity_category(event: str) -> str:
    value = str(event or "").strip().lower()
    if any(token in value for token in ("research", "source", "finding")):
        return "research"
    if any(token in value for token in ("build", "candidate", "design")):
        return "design"
    if any(token in value for token in ("feedback", "accept")):
        return "feedback"
    if any(token in value for token in ("provision", "activat")):
        return "provisioning"
    return "system"


__all__ = [
    "IncubationApplicationService",
    "IncubationRuntime",
    "IncubationServiceError",
    "IncubationStore",
]


def _asset_visual_reference_notes(assets: Any) -> tuple[str, ...]:
    """Bounded, owner-safe visual readings of the bound reference images so the
    builder sees the Qwen analysis alongside the real files. Inspiration-only
    images stay out of the notes (the owner chose not to put them on the site)."""
    if not isinstance(assets, list):
        return ()
    notes: list[str] = []
    for item in assets[:12]:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("usage") or "undecided") == "inspiration_only":
            continue
        name = str(item.get("name") or f"image {item.get('asset_id') or item.get('id') or ''}").strip()[:80]
        analysis = item.get("analysis") if isinstance(item.get("analysis"), Mapping) else {}
        description = _sanitize_note(analysis.get("description") or item.get("description") or "")[:300]
        tags = ", ".join(str(tag)[:60] for tag in list(analysis.get("tags") or item.get("tags") or [])[:8])
        colors = ", ".join(str(color)[:40] for color in list(analysis.get("dominant_colors") or item.get("dominant_colors") or [])[:6])
        uses = ", ".join(str(use)[:80] for use in list(analysis.get("suggested_uses") or [])[:4])
        ocr = _sanitize_note(analysis.get("ocr_text") or item.get("ocr_text") or "")[:180]
        parts = [f"reference {name}"]
        if description:
            parts.append(f"description: {description}")
        if colors:
            parts.append(f"palette: {colors}")
        if tags:
            parts.append(f"tags: {tags}")
        if uses:
            parts.append(f"suggested use: {uses}")
        if ocr:
            parts.append(f"visible text: {ocr}")
        note = "; ".join(parts)
        if len(note) > 700:
            note = note[:700]
        if note:
            notes.append(note)
    return tuple(notes[:12])


def _sanitize_note(value: Any) -> str:
    import re as _re

    text = str(value or "").strip()
    text = _re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[contact]", text)
    text = _re.sub(r"https?://\S+", "[url]", text)
    return _re.sub(r"\s+", " ", text).strip()


def _design_projection(run: Mapping[str, Any]) -> dict[str, Any]:
    """Expose review metadata without filesystem, provider, or transcript paths."""
    return {
        key: run.get(key)
        for key in (
            "run_id", "mode", "status", "candidate_sha", "operation_kind", "parent_run_id",
            "source_candidate_sha", "publishable", "created_ts", "updated_ts", "error",
            "quality_report_hash", "design_manifest_hash", "planning_hash", "context_snapshot_hash",
        )
    }
