"""Shared, tenant-isolated application services for the Atelier API.

The public API is one process and one ingress.  Customer state is not shared:
each tenant has its own config file, Payload credential, SQLite memory database,
Runtime, and job executor.  The bearer token selects the tenant before any
conversation or job id is looked up.
"""

from __future__ import annotations

import hmac
import json
import re
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..config import ConfigError, load
from .atelier_intake import AtelierIntakeCoordinator
from ..core.memory import Memory
from ..core.reflect import effective_persona
from ..core.scheduler import Scheduler
from ..runtime import Runtime


class AtelierBridgeError(ValueError):
    """A trusted Atelier bridge request could not be accepted."""


_SAFE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SAFE_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class AtelierJourney:
    """The two independent facts that decide Ada's owner-facing phase."""

    website_present: bool
    incubation_needed: bool

    @property
    def initial_phase(self) -> str:
        if self.website_present and self.incubation_needed:
            return "incubation"
        if not self.website_present:
            return "intake"
        return "workspace"


def _journey_for_config(config: Mapping[str, Any]) -> AtelierJourney:
    site = config.get("site") if isinstance(config.get("site"), Mapping) else {}
    journey = config.get("ada_journey") or config.get("journey") or {}
    journey = journey if isinstance(journey, Mapping) else {}

    if "website_present" in journey:
        website_present = bool(journey.get("website_present"))
    elif "website_present" in site:
        website_present = bool(site.get("website_present"))
    else:
        payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
        profile = config.get("customer_profile") if isinstance(config.get("customer_profile"), Mapping) else {}
        business = profile.get("business") if isinstance(profile.get("business"), Mapping) else {}
        observed_settings = business.get("observed_site_settings") if isinstance(business.get("observed_site_settings"), Mapping) else {}
        website_present = bool(payload.get("enabled") or observed_settings.get("website_url"))

    intake = config.get("atelier_intake") if isinstance(config.get("atelier_intake"), Mapping) else {}
    if "incubation_needed" in journey:
        incubation_needed = bool(journey.get("incubation_needed"))
    elif "incubation_needed" in intake:
        incubation_needed = bool(intake.get("incubation_needed"))
    else:
        # Incubation is a research bridge for a site that already exists. A
        # new site gets the full intake/build path instead of this shortcut.
        incubation_needed = website_present and bool(intake.get("enabled", False))

    if not website_present:
        # A no-site tenant must never be put into the existing-site incubation
        # path by an old or copied config flag.
        incubation_needed = False
    return AtelierJourney(website_present=website_present, incubation_needed=incubation_needed)


class AtelierDesignBuildHandoff:
    """Bridge confirmed no-site intake into the normal typed design worker."""

    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context

    def submit(
        self,
        request: str,
        intake: Mapping[str, Any],
        *,
        run_id: str,
        conversation_id: int | None,
        source_message_id: int | None,
        intake_session_id: str | None,
        intake_revision_id: int | None,
        context_extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        from ..core.design_contracts import SiteIntake

        service = self.context.get("design_service")
        executor = self.context.get("design_executor")
        if service is None or executor is None:
            raise AtelierBridgeError("the full design build service is unavailable")
        site_intake = SiteIntake.from_dict(dict(intake))
        base_sha = service.resolve_base_sha()
        run = service.create_run(
            site_intake,
            mode="production_candidate",
            base_sha=base_sha,
            candidate_ref=f"refs/ada-design/{run_id}",
            publishable=True,
            run_id=run_id,
            owner_request=request,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            chat_job_id=None,
            intake_session_id=intake_session_id,
            intake_revision_id=intake_revision_id,
        )
        service.capture_context_snapshot(
            run["run_id"],
            owner_request=request,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            chat_job_id=None,
            context_extra=context_extra,
        )
        build_request = service.prepare_initial_request(run["run_id"])
        target = service.build_target_for_run(run["run_id"])
        service.queue_build(run["run_id"], build_request, target)
        executor.enqueue(run["run_id"])
        return service.get_run(run["run_id"])


@dataclass
class AtelierTenant:
    """All process-local dependencies for one isolated customer workspace."""

    tenant_id: str
    config: dict[str, Any]
    memory: Memory
    runtime: Runtime
    context: dict[str, Any]
    api_token: str
    executor: Any = None
    design_executor: Any = None
    intake_coordinator: AtelierIntakeCoordinator | None = None


class AtelierTenantRegistry:
    """Load and own all tenants served by one shared API process."""

    def __init__(self, tenants: Mapping[str, AtelierTenant]) -> None:
        self.tenants = dict(tenants)
        self._started = False

    @classmethod
    def from_config(cls, config: Mapping[str, Any], env: Mapping[str, str]) -> "AtelierTenantRegistry":
        section = config.get("atelier_api") or {}
        if not isinstance(section, Mapping) or not bool(section.get("enabled", False)):
            raise ConfigError("atelier_api.enabled must be true for the shared Atelier API")
        declared = section.get("tenants") or {}
        if not isinstance(declared, Mapping) or not declared:
            raise ConfigError("atelier_api.tenants must contain at least one tenant")

        tenants: dict[str, AtelierTenant] = {}
        seen_data_dirs: set[Path] = set()
        seen_tokens: set[str] = set()
        try:
            for raw_tenant_id, raw_spec in declared.items():
                tenant_id = str(raw_tenant_id or "").strip().lower()
                if not _SAFE_NAME.fullmatch(tenant_id):
                    raise ConfigError(f"atelier_api tenant id is invalid: {tenant_id or '(empty)'}")
                if not isinstance(raw_spec, Mapping):
                    raise ConfigError(f"atelier_api.tenants.{tenant_id} must be an object")

                config_path = Path(str(raw_spec.get("config_path") or "")).expanduser()
                if not config_path.is_file():
                    raise ConfigError(f"Atelier tenant config not found: {config_path}")
                tenant_config, _ = load(config_path, dict(env))
                tenant_config["instance_name"] = tenant_id

                data_dir = Path(str(tenant_config.get("data_dir") or "")).expanduser().resolve()
                if not str(data_dir) or data_dir == Path("/"):
                    raise ConfigError(f"Atelier tenant {tenant_id} needs a dedicated data_dir")
                if data_dir in seen_data_dirs:
                    raise ConfigError(f"Atelier tenant data_dir is shared: {data_dir}")
                seen_data_dirs.add(data_dir)
                tenant_config["data_dir"] = str(data_dir)

                token_env = str(
                    raw_spec.get("api_token_env")
                    or f"ATELIER_{tenant_id.replace('-', '_').upper()}_TOKEN"
                ).strip()
                if not _SAFE_ENV.fullmatch(token_env):
                    raise ConfigError(f"Atelier tenant {tenant_id} api_token_env is invalid")
                api_token = str(env.get(token_env) or "")
                if not api_token:
                    raise ConfigError(f"Atelier tenant {tenant_id} is missing {token_env}")
                if api_token in seen_tokens:
                    raise ConfigError("Atelier API tenant tokens must be unique")
                seen_tokens.add(api_token)

                memory = Memory(data_dir / "memory.db")
                scheduler = Scheduler(memory, lock_path=data_dir / "scheduler.lock")
                from ..core.llm import Client

                llm = Client(tenant_config, memory, env=dict(env))
                runtime = Runtime(
                    tenant_config,
                    memory,
                    scheduler,
                    llm,
                    effective_persona(tenant_config, memory),
                )
                context = runtime.context()
                from ..hands.atelier_payload import AtelierPayloadClient

                payload_client = AtelierPayloadClient.from_config(tenant_config, dict(env))
                journey = _journey_for_config(tenant_config)
                context.update({
                    "atelier_payload": payload_client,
                    "atelier_tenant_id": tenant_id,
                    "atelier_journey": journey,
                })
                if payload_client is not None:
                    from ..hands.atelier_payload import AtelierPayloadMediaService

                    context["media_service"] = AtelierPayloadMediaService(payload_client)
                vision_config = tenant_config.get("vision") or {}
                if isinstance(vision_config, Mapping) and bool(vision_config.get("enabled")) and context.get("media_analyzer") is None:
                    from ..core.vision import VisionClient

                    context["media_analyzer"] = VisionClient(tenant_config, env=dict(env), memory=memory)
                design_engine = tenant_config.get("design_engine") or {}
                builder_config = tenant_config.get("builder") or {}
                site_config = tenant_config.get("site") or {}
                if (
                    isinstance(design_engine, Mapping)
                    and bool(design_engine.get("enabled"))
                    and isinstance(builder_config, Mapping)
                    and bool(builder_config.get("enabled"))
                    and str(site_config.get("clone_path") or "").strip()
                ):
                    from ..application.designs import DesignService
                    from ..core.design_contracts import SiteIntake
                    from ..hands.builder import OperationRoutingBuilder
                    from ..hands.playwright_quality import PlaywrightQualityAdapter

                    build_env = DesignService.experiment_environment(dict(env))
                    context.update({
                        "env": build_env,
                        "build_env": build_env,
                        "review_environment": build_env,
                    })
                    design_service = context.get("design_service")
                    if design_service is not None:
                        design_service.builder = OperationRoutingBuilder(context)

                        def browser_factory(run_id, run, *, _service=design_service, _config=tenant_config, _env=build_env):
                            try:
                                routes = _service.quality_policy_for_run(run_id).required_pages
                            except Exception:
                                intake = SiteIntake.from_dict(run.get("intake_json") or {})
                                routes = intake.site.get("required_pages") or ()
                            return PlaywrightQualityAdapter(
                                Path(str(_config.get("data_dir"))) / "screenshots" / str(run_id),
                                variant="candidate",
                                routes=routes,
                                env=_env,
                            )

                        context["browser_quality_factory"] = browser_factory
                if bool(isinstance(design_engine, Mapping) and design_engine.get("production_candidate")):
                    from ..hands.github_static import GithubStatic

                    try:
                        design_adapter = GithubStatic(tenant_config, dict(env))
                        design_adapter.validate()
                    except Exception as exc:  # noqa: BLE001 — fail closed when approval cannot be safe
                        raise ConfigError(f"Atelier design approval adapter is unavailable: {exc}") from exc
                    context["design_adapter"] = design_adapter
                intake_settings = tenant_config.get("atelier_intake") or {}
                if not isinstance(intake_settings, Mapping):
                    intake_settings = {}
                intake_enabled = bool(intake_settings.get("enabled", False)) or journey.incubation_needed
                if not journey.website_present and not journey.incubation_needed:
                    # New-site tenants still need the typed full-intake front
                    # door even when they do not carry the Atelier incubation
                    # block in their config.
                    intake_settings = dict(intake_settings)
                    intake_settings["enabled"] = True
                    intake_settings["database_only"] = False
                    research_settings = intake_settings.get("research")
                    research_settings = dict(research_settings) if isinstance(research_settings, Mapping) else {}
                    research_settings["enabled"] = False
                    intake_settings["research"] = research_settings
                    tenant_config = dict(tenant_config)
                    tenant_config["atelier_intake"] = intake_settings
                    intake_enabled = True
                intake_coordinator = None
                if intake_enabled:
                    intake_coordinator = AtelierIntakeCoordinator(
                        memory,
                        config=tenant_config,
                        llm=context.get("llm"),
                        media_service=context.get("media_service"),
                        payload_client=payload_client,
                    )
                    context.update({
                        "atelier_intake": intake_coordinator,
                        "design_intake_service": intake_coordinator.intake_service,
                    })
                tenants[tenant_id] = AtelierTenant(
                    tenant_id=tenant_id,
                    config=tenant_config,
                    memory=memory,
                    runtime=runtime,
                    context=context,
                    api_token=api_token,
                    intake_coordinator=intake_coordinator,
                )
        except Exception:
            for tenant in tenants.values():
                tenant.runtime.close()
                tenant.memory.close()
            raise
        return cls(tenants)

    def for_token(self, token: str) -> AtelierTenant | None:
        supplied = str(token or "")
        if not supplied:
            return None
        for tenant in self.tenants.values():
            if hmac.compare_digest(supplied.encode(), tenant.api_token.encode()):
                return tenant
        return None

    def start(self) -> None:
        if self._started:
            return
        from ..application.design_jobs import DesignJobExecutor
        from ..core.chat_jobs import ChatJobExecutor
        from ..hands.atelier_payload import AtelierPayloadSiteAdapter

        started: list[AtelierTenant] = []
        try:
            for tenant in self.tenants.values():
                tenant.runtime.start()
                tenant.memory.interrupt_running_chat_jobs()
                tenant.memory.interrupt_running_design_runs()
                if tenant.intake_coordinator is not None:
                    tenant.intake_coordinator.start()
                tenant.design_executor = DesignJobExecutor(
                    tenant.context,
                    tenant.context["design_service"],
                )
                tenant.context["design_executor"] = tenant.design_executor
                journey = self._tenant_journey(tenant)
                if journey is not None and not journey.website_present:
                    intake_service = tenant.context.get("design_intake_service")
                    if intake_service is not None:
                        handoff = AtelierDesignBuildHandoff(tenant.context)
                        intake_service.lab_service = handoff
                        tenant.context["design_intake_build_service"] = handoff
                tenant.design_executor.start()
                tenant.executor = ChatJobExecutor(
                    tenant.context,
                    adapter_factory=lambda tenant=tenant: (
                        AtelierPayloadSiteAdapter(
                            tenant.config,
                            payload_client=tenant.context.get("atelier_payload"),
                        )
                        if tenant.context.get("atelier_payload") is not None
                        else self._site_adapter(tenant)
                    ),
                )
                tenant.executor.start()
                started.append(tenant)
        except Exception:
            for tenant in reversed(started):
                self._stop_tenant(tenant)
            raise
        self._started = True

    @staticmethod
    def _site_adapter(tenant: AtelierTenant) -> Any:
        """Use the configured normal site adapter for a new-site tenant."""
        from ..hands.base import get_adapter

        site = tenant.config.get("site") if isinstance(tenant.config.get("site"), Mapping) else {}
        name = str(site.get("adapter") or "github_static").strip()
        return get_adapter(name, tenant.config)

    @staticmethod
    def _tenant_journey(tenant: AtelierTenant) -> AtelierJourney | None:
        value = tenant.context.get("atelier_journey")
        return value if isinstance(value, AtelierJourney) else None

    def _stop_tenant(self, tenant: AtelierTenant) -> None:
        if tenant.executor is not None:
            tenant.executor.stop()
            tenant.executor.join(timeout=10)
            tenant.executor = None
        if tenant.design_executor is not None:
            tenant.design_executor.stop()
            tenant.design_executor.join(timeout=10)
            tenant.design_executor = None
        if tenant.intake_coordinator is not None:
            tenant.intake_coordinator.stop()
        tenant.context.pop("design_executor", None)
        tenant.runtime.close()
        tenant.memory.close()

    def close(self) -> None:
        for tenant in self.tenants.values():
            self._stop_tenant(tenant)
        self._started = False


class AtelierChatService:
    """Translate the Payload workspace contract into durable, scoped chat jobs."""

    def __init__(
        self,
        memory: Any | None = None,
        llm: Any | None = None,
        *,
        registry: AtelierTenantRegistry | None = None,
    ) -> None:
        # ``memory`` + ``llm`` remains supported for the existing single-instance
        # admin server and its tests. The shared API always supplies a registry.
        self.memory = memory
        self.llm = llm
        self.registry = registry

    @staticmethod
    def _require_llm(llm: Any) -> None:
        if llm is None or (hasattr(llm, "api_key") and not llm.api_key):
            raise AtelierBridgeError("LLM not configured")

    def _scope(self, tenant: AtelierTenant | None) -> tuple[Any, Any, str]:
        if self.registry is not None:
            if tenant is None or tenant.tenant_id not in self.registry.tenants:
                raise AtelierBridgeError("tenant is not authorized")
            self._require_llm(tenant.context.get("llm"))
            return tenant.memory, tenant.context.get("llm"), tenant.tenant_id
        self._require_llm(self.llm)
        return self.memory, self.llm, "legacy"

    @staticmethod
    def _attachment_rows(value: Any) -> list[dict[str, int]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise AtelierBridgeError("attachments must be a list")
        if len(value) > 12:
            raise AtelierBridgeError("choose up to 12 images")
        rows: list[dict[str, int]] = []
        seen: set[int] = set()
        for position, raw in enumerate(value):
            raw_id = (raw.get("asset_id") or raw.get("id")) if isinstance(raw, Mapping) else raw
            try:
                asset_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise AtelierBridgeError("attachment ID is invalid") from exc
            if asset_id < 1 or asset_id in seen:
                raise AtelierBridgeError("attachments must contain unique positive IDs")
            seen.add(asset_id)
            rows.append({"asset_id": asset_id, "position": position})
        return rows

    @staticmethod
    def _journey(tenant: AtelierTenant | None) -> AtelierJourney | None:
        value = tenant.context.get("atelier_journey") if tenant is not None else None
        return value if isinstance(value, AtelierJourney) else None

    @classmethod
    def _intake_mode(cls, tenant: AtelierTenant | None) -> str:
        journey = cls._journey(tenant)
        return journey.initial_phase if journey is not None else "intake"

    def enqueue(self, body: Mapping[str, Any], *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        memory, _llm, tenant_id = self._scope(tenant)
        message = str(body.get("message") or "").strip()
        attachments = self._attachment_rows(body.get("attachments"))
        owner_context = body.get("context")
        owner_context = dict(owner_context) if isinstance(owner_context, Mapping) else {}
        if not message and not attachments:
            raise AtelierBridgeError("empty message")
        if len(message) > 8000:
            raise AtelierBridgeError("message too long")
        if not message:
            message = "Please review the attached images."

        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise AtelierBridgeError("conversation_id must be an integer") from exc

        if tenant is not None:
            intake = tenant.context.get("atelier_intake")
            if intake is not None and intake.needs_intake(conversation_id):
                try:
                    intake_kwargs = {
                        "conversation_id": conversation_id,
                        "idempotency_key": body.get("idempotency_key"),
                    }
                    if attachments:
                        intake_kwargs["attachments"] = [item["asset_id"] for item in attachments]
                    if owner_context:
                        intake_kwargs["owner_context"] = owner_context
                    result = intake.send_message(message, **intake_kwargs)
                except Exception as exc:  # noqa: BLE001 — keep bridge errors bounded
                    raise AtelierBridgeError(str(exc)[:500]) from exc
                response = {
                    "job_id": int(result["job_id"]),
                    "conversation_id": int(result["conversation_id"]),
                    "intake_session_id": str(result.get("session_id") or ""),
                    "mode": self._intake_mode(tenant),
                }
                if journey := self._journey(tenant):
                    response.update({
                        "phase": journey.initial_phase,
                        "website_present": journey.website_present,
                        "incubation_needed": journey.incubation_needed,
                    })
                return response
        conversations = {item["id"] for item in memory.list_conversations(limit=200)}
        if not conversation_id or conversation_id not in conversations:
            conversation_id = memory.create_conversation(title=message[:80])

        context = owner_context
        context["site"] = tenant_id
        journey = self._journey(tenant)
        if journey is not None:
            context["website_present"] = journey.website_present
            context["incubation_needed"] = journey.incubation_needed
            context["journey"] = "workspace"
        media_service = tenant.context.get("media_service") if tenant is not None else None
        if attachments and media_service is None:
            raise AtelierBridgeError("image attachments are unavailable")
        if attachments and media_service is not None:
            try:
                media_service.resolve_attachments([item["asset_id"] for item in attachments])
            except Exception as exc:  # noqa: BLE001 — normalize provider-specific errors
                raise AtelierBridgeError(str(exc)[:500]) from exc
        job_id = memory.enqueue_chat_job(
            conversation_id,
            self._contextual_message(message, context),
            attachments,
        )
        response = {
            "job_id": int(job_id),
            "conversation_id": int(conversation_id),
            "mode": "workspace",
            "phase": "workspace",
        }
        if journey is not None:
            response.update({
                "website_present": journey.website_present,
                "incubation_needed": journey.incubation_needed,
            })
        return response

    def status(self, conversation_id: Any = None, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Return the tenant-scoped chat phase without starting website work.

        Intake owns the phase decision.  The browser may use this to keep the
        page selector and website target dormant until the owner has accepted
        the working brief; it must not try to infer readiness from Payload.
        """
        _memory, _llm, tenant_id = self._scope(tenant)
        normalized_id: int | None = None
        if conversation_id is not None and str(conversation_id).strip():
            try:
                normalized_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise AtelierBridgeError("conversation_id must be an integer") from exc

        journey = self._journey(tenant)
        intake_enabled = bool(tenant is not None and tenant.context.get("atelier_intake") is not None)
        needs_intake = False
        intake_status: dict[str, Any] = {}
        if intake_enabled:
            try:
                coordinator = tenant.context["atelier_intake"]
                intake_status = coordinator.status(normalized_id)
                needs_intake = not bool(intake_status.get("confirmed"))
            except Exception as exc:  # noqa: BLE001 — keep status errors bounded
                raise AtelierBridgeError(str(exc)[:500]) from exc
        if journey is None:
            mode = "intake" if needs_intake else "workspace"
        elif needs_intake:
            mode = journey.initial_phase
        else:
            mode = "workspace"
        website_present = journey.website_present if journey is not None else mode == "workspace"
        incubation_needed = journey.incubation_needed if journey is not None else intake_enabled
        return {
            "tenant": tenant_id,
            "mode": mode,
            "phase": mode,
            "website_context_enabled": website_present and mode == "workspace",
            "website_present": website_present,
            "incubation_needed": incubation_needed,
            "journey": "incubation" if mode == "incubation" else "full_intake" if mode == "intake" else "workspace",
            "intake_enabled": intake_enabled,
            "conversation_id": normalized_id or intake_status.get("conversation_id"),
            "intake": intake_status,
        }

    def confirm_intake(
        self,
        body: Mapping[str, Any],
        *,
        tenant: AtelierTenant | None = None,
    ) -> dict[str, Any]:
        """Accept intake without starting a design run."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("atelier_intake") is None:
            raise AtelierBridgeError("Atelier intake is not enabled")
        coordinator = tenant.context["atelier_intake"]
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise AtelierBridgeError("conversation_id must be an integer") from exc
        try:
            revision = int(body.get("revision"))
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("revision must be an integer") from exc
        draft_hash = str(body.get("draft_hash") or "").strip().lower()
        confirmation_text = str(body.get("confirmation_text") or "Accept this working brief").strip()
        if not draft_hash:
            raise AtelierBridgeError("draft_hash is required")
        if not confirmation_text or len(confirmation_text) > 2_000:
            raise AtelierBridgeError("confirmation_text is invalid")
        try:
            result = coordinator.confirm(
                conversation_id,
                revision=revision,
                draft_hash=draft_hash,
                confirmation_text=confirmation_text,
                idempotency_key=body.get("idempotency_key"),
            )
            return result
        except Exception as exc:  # noqa: BLE001 — keep bridge errors bounded
            raise AtelierBridgeError(str(exc)[:500]) from exc

    def start_first_page(
        self,
        body: Mapping[str, Any],
        *,
        tenant: AtelierTenant | None = None,
    ) -> dict[str, Any]:
        """Start the first page only through an explicit post-intake action."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("atelier_intake") is None:
            raise AtelierBridgeError("Atelier intake is not enabled")
        journey = self._journey(tenant)
        if journey is not None and journey.website_present:
            raise AtelierBridgeError("an existing website needs an explicit page target")
        coordinator = tenant.context["atelier_intake"]
        intake_service = tenant.context.get("design_intake_service")
        if intake_service is None or getattr(intake_service, "lab_service", None) is None:
            raise AtelierBridgeError("the full design build service is unavailable")
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise AtelierBridgeError("conversation_id must be an integer") from exc
        status = coordinator.status(conversation_id)
        if not status.get("confirmed"):
            raise AtelierBridgeError("the working brief must be accepted before starting a page")
        session_id = str(status.get("session_id") or "")
        confirmed_revision = body.get("confirmed_revision") or status.get("confirmed_revision_id") or status.get("confirmed_revision")
        try:
            confirmed_revision = int(confirmed_revision)
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("confirmed_revision must be an integer") from exc
        try:
            build = intake_service.build(
                session_id,
                confirmed_revision=confirmed_revision,
                owner_request=str(body.get("owner_request") or "Start the first page design from the confirmed working brief."),
                idempotency_key=body.get("idempotency_key"),
                context_extra={"operation": "first_page_design", "page": "index.html"},
            )
        except Exception as exc:  # noqa: BLE001 — normalize bridge errors
            raise AtelierBridgeError(str(exc)[:500]) from exc
        response = {
            key: build[key]
            for key in ("idempotency_key", "build_pending", "idempotent", "recovered")
            if key in build
        }
        if isinstance(build.get("run"), Mapping):
            response["run"] = self._public_design_run(build["run"])
        return response

    def conversations(
        self,
        *,
        include_archived: bool = False,
        limit: int = 50,
        tenant: AtelierTenant | None = None,
    ) -> dict[str, Any]:
        """List durable conversations for the token-selected tenant."""
        memory, _llm, _tenant_id = self._scope(tenant)
        from .conversations import ConversationService

        media_service = tenant.context.get("media_service") if tenant is not None else None
        service = ConversationService(memory, media_service=media_service)
        bounded_limit = max(1, min(int(limit), 100))
        return {
            "conversations": service.list(include_archived=bool(include_archived), limit=bounded_limit),
        }

    def conversation(self, conversation_id: Any, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Return one durable conversation and its messages for the tenant."""
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            normalized_id = int(conversation_id)
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("conversation_id must be an integer") from exc
        from .conversations import ConversationNotFound, ConversationService

        media_service = tenant.context.get("media_service") if tenant is not None else None
        service = ConversationService(memory, media_service=media_service)
        try:
            return service.get(normalized_id)
        except ConversationNotFound as exc:
            raise AtelierBridgeError(str(exc)) from exc

    def history(self, *, limit: int = 50, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Return a bounded, tenant-scoped activity index without raw context."""
        memory, _llm, tenant_id = self._scope(tenant)
        bounded_limit = max(1, min(int(limit), 100))
        conversations = []
        for item in memory.list_conversations(limit=bounded_limit, include_archived=True):
            conversations.append({
                "id": int(item["id"]),
                "title": str(item.get("title") or "Untitled conversation"),
                "created_ts": item.get("created_ts"),
                "archived_ts": item.get("archived_ts"),
            })

        design_runs = []
        for item in memory.list_design_runs(limit=bounded_limit):
            snapshot = item.get("context_snapshot")
            workspace_target = snapshot.get("workspace_target") if isinstance(snapshot, dict) else None
            target_summary = None
            if isinstance(workspace_target, dict):
                route = workspace_target.get("route")
                target_summary = {
                    "mode": workspace_target.get("mode"),
                    "scope": workspace_target.get("scope"),
                    "path": route.get("path") if isinstance(route, dict) else None,
                }
            design_runs.append({
                "run_id": str(item["run_id"]),
                "status": str(item.get("status") or "unknown"),
                "mode": str(item.get("mode") or "unknown"),
                "operation_kind": str(item.get("operation_kind") or "initial_build"),
                "owner_request": str(item.get("owner_request") or "")[:240],
                "conversation_id": item.get("conversation_id"),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "publishable": bool(item.get("publishable")),
                "candidate_sha": str(item.get("candidate_sha") or ""),
                "draft_id": item.get("draft_id"),
                "target": target_summary,
            })

        drafts = []
        for item in memory.list_drafts(limit=bounded_limit):
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            drafts.append({
                "id": int(item["id"]),
                "title": str(item.get("title") or "Untitled draft"),
                "kind": str(item.get("kind") or "edit"),
                "status": str(item.get("status") or "unknown"),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "meta": {
                    key: meta[key]
                    for key in ("run_id", "candidate_sha", "base_sha", "target_sha", "target_publish_id", "summary")
                    if key in meta
                },
            })

        publishes = [
            {
                "id": int(item["id"]),
                "ts": item.get("ts"),
                "summary": str(item.get("summary") or ""),
                "path": str(item.get("path") or ""),
                "commit_sha": str(item.get("commit_sha") or ""),
                "parent_sha": str(item.get("parent_sha") or ""),
                "version_type": str(item.get("version_type") or "edit"),
                "reverted_ts": item.get("reverted_ts"),
            }
            for item in memory.list_publishes(limit=bounded_limit)
        ]

        return {
            "tenant": tenant_id,
            "conversations": conversations,
            "design_runs": design_runs,
            "drafts": drafts,
            "publishes": publishes,
            "actions": memory.recent_actions(limit=bounded_limit),
        }

    def design_runs(
        self,
        *,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
        tenant: AtelierTenant | None = None,
    ) -> dict[str, Any]:
        """List reviewable design runs without exposing mutable context snapshots."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise AtelierBridgeError("Atelier design service is not enabled")
        bounded_limit = max(1, min(int(limit), 100))
        service = tenant.context["design_service"]
        return {"runs": [self._public_design_run(item) for item in service.list_runs(status=status, mode=mode, limit=bounded_limit)]}

    def design_run(self, run_id: str, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Return one design run and its quality evidence for owner review."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise AtelierBridgeError("Atelier design service is not enabled")
        try:
            run = tenant.context["design_service"].get_run(str(run_id))
        except Exception as exc:  # noqa: BLE001 — normalize service-specific errors
            raise AtelierBridgeError(str(exc)[:500]) from exc
        return {"run": self._public_design_run(run, include_evidence=True)}

    def create_design_review(self, run_id: str, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Link a passed candidate to the owner approval lane."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise AtelierBridgeError("Atelier design service is not enabled")
        try:
            run = tenant.context["design_service"].create_review_draft(str(run_id))
        except Exception as exc:  # noqa: BLE001 — normalize service-specific errors
            raise AtelierBridgeError(str(exc)[:500]) from exc
        return {"run": self._public_design_run(run, include_evidence=True)}

    def approve_draft(self, draft_id: Any, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Approve exactly one pending design candidate through the configured adapter."""
        memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise AtelierBridgeError("Atelier design service is not enabled")
        try:
            normalized_id = int(draft_id)
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("draft_id must be an integer") from exc
        adapter = tenant.context.get("design_adapter")
        from ..hands.base import DesignMergeAdapter

        if not isinstance(adapter, DesignMergeAdapter):
            raise AtelierBridgeError("Atelier design approval adapter is unavailable")
        service = tenant.context["design_service"]
        try:
            result = service.approve_review_draft(
                normalized_id,
                lambda run: adapter.merge_design_candidate(
                    tenant.config,
                    run["candidate_sha"],
                    run["base_sha"],
                    f"Approve design candidate: {normalized_id}",
                ),
            )
        except Exception as exc:  # noqa: BLE001 — approval must return a bounded error
            raise AtelierBridgeError(str(exc)[:500]) from exc
        published = result.get("published") if isinstance(result, dict) else {}
        if isinstance(published, Mapping) and (published.get("committed") or published.get("commit_sha")):
            run = result.get("run") or {}
            memory.log_publish(
                summary=f"design: {normalized_id}",
                path=str(published.get("path") or "site"),
                commit_sha=str(published.get("commit_sha") or ""),
                draft_id=normalized_id,
                parent_sha=str(published.get("parent_sha") or ""),
                actor="owner",
                version_type="design",
                commit_message=f"Approve design candidate: {run.get('run_id') or normalized_id}",
            )
        memory.record_action("approve", f"design draft #{normalized_id}")
        return result

    def discard_draft(self, draft_id: Any, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Discard a pending draft without changing production."""
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            normalized_id = int(draft_id)
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("draft_id must be an integer") from exc
        if not memory.update_draft_status(normalized_id, "discarded"):
            raise AtelierBridgeError("no such draft")
        memory.record_action("discard", f"#{normalized_id}")
        return {"ok": True, "draft_id": normalized_id, "status": "discarded"}

    def restore_version(self, version_id: Any, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Create an approval-gated rollback draft; never mutate production directly."""
        memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None:
            raise AtelierBridgeError("Atelier tenant is required")
        try:
            normalized_id = int(version_id)
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("version_id must be an integer") from exc
        version = next((item for item in memory.list_publishes(limit=100) if int(item["id"]) == normalized_id), None)
        if not version or not version.get("commit_sha"):
            raise AtelierBridgeError("version not found")
        adapter = tenant.context.get("design_adapter")
        restore = getattr(adapter, "restore_snapshot", None)
        preview_branch = str((tenant.config.get("site") or {}).get("preview_branch") or "preview").strip()
        if not callable(restore) or not preview_branch:
            raise AtelierBridgeError("version restore is not configured")
        try:
            ensure_branch = getattr(adapter, "ensure_branch", None)
            if callable(ensure_branch):
                ensure_branch(preview_branch)
            preview = restore(
                str(version["commit_sha"]),
                preview_branch,
                f"Restore website version: {str(version.get('summary') or normalized_id)[:120]}",
            )
        except Exception as exc:  # noqa: BLE001 — keep rollback approval-gated
            raise AtelierBridgeError(str(exc)[:500]) from exc
        draft_id = memory.save_draft(
            title=f"Restore: {str(version.get('summary') or normalized_id)[:120]}",
            body=f"Restore the website to the published version from {str(version.get('ts') or '')[:10]}.",
            kind="rollback",
            meta={
                "target_sha": version["commit_sha"],
                "target_publish_id": normalized_id,
                "head_sha": preview.get("parent_sha", "") if isinstance(preview, Mapping) else "",
                "head": preview_branch,
                "base": (tenant.config.get("site") or {}).get("branch", "main"),
                "summary": version.get("summary") or "",
            },
        )
        memory.record_action("rollback_preview", f"version #{normalized_id} -> draft #{draft_id}")
        return {"ok": True, "draft_id": draft_id, "branch": preview_branch, "preview": preview}

    def analyze_media(self, body: Mapping[str, Any], *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """Analyze one Payload asset and write only the resulting metadata draft."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None:
            raise AtelierBridgeError("Atelier tenant is required")
        payload = tenant.context.get("atelier_payload")
        analyzer = tenant.context.get("media_analyzer")
        if payload is None or analyzer is None:
            raise AtelierBridgeError("Atelier media analysis is not configured")
        media_id = str(body.get("media_id") or body.get("id") or "").strip()
        if not media_id:
            raise AtelierBridgeError("media_id is required")
        focus = str(body.get("focus") or "").strip()
        if len(focus) > 500:
            raise AtelierBridgeError("focus is too long")
        try:
            media = payload.read_media(media_id, identifier_kind="id", draft=True)
            image_url = str(
                media.get("url")
                or ((media.get("sizes") or {}).get("large") or {}).get("url")
                or media.get("originalUrl")
                or ""
            ).strip()
            if image_url.startswith("/"):
                image_url = f"{payload.base_url}{image_url}"
            parsed = urlsplit(image_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise AtelierBridgeError("Payload media does not expose a readable image URL")
            analysis_data = analyzer.analyze_images(
                [image_url],
                "Analyze this owner-provided Atelier Harmonie image for a design and content library. "
                "Return only grounded observations: subject, composition, alt text, tags, dominant colors, "
                "suggested uses, quality notes, and visible text. Do not invent business claims or provenance."
                + (f" Owner focus: {focus}" if focus else ""),
            )
            analysis = analysis_data.to_dict() if hasattr(analysis_data, "to_dict") else dict(analysis_data)
            updated = payload.update_media(media_id, {
                "alt": analysis.get("alt_text") or media.get("alt") or media.get("filename") or "Atelier image",
                "description": analysis.get("description") or "",
                "tags": [{"value": value} for value in list(analysis.get("tags") or [])[:20]],
                "dominantColors": [{"value": value} for value in list(analysis.get("dominant_colors") or [])[:20]],
                "suggestedUses": [{"value": value} for value in list(analysis.get("suggested_uses") or [])[:20]],
                "qualityNotes": [{"value": value} for value in list(analysis.get("quality_notes") or [])[:20]],
                "ocrText": analysis.get("ocr_text") or "",
                "proposedKnowledge": analysis.get("proposed_knowledge_markdown") or "",
                "analysisStatus": "ready",
                "analysisProvider": str(getattr(analyzer, "provider_id", "vision")),
                "analysisModel": str(getattr(analyzer, "model", "")),
                "analysisVersion": 1,
                "analysisError": "",
                "analysisUpdatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "analysis": analysis,
            })
            return {"media": updated, "analysis": analysis, "draft": True}
        except AtelierBridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 — keep provider failures bounded
            try:
                payload.update_media(media_id, {
                    "analysisStatus": "failed",
                    "analysisError": str(exc)[:500],
                })
            except Exception:
                pass
            raise AtelierBridgeError(str(exc)[:500]) from exc

    def media(self, *, limit: int = 50, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        """List the tenant's Payload media records for the owner workspace."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("atelier_payload") is None:
            raise AtelierBridgeError("Atelier Payload media is not configured")
        bounded_limit = max(1, min(int(limit), 100))
        try:
            return {"media": tenant.context["atelier_payload"].list_media(draft=True, limit=bounded_limit)}
        except Exception as exc:  # noqa: BLE001 — normalize gateway failures
            raise AtelierBridgeError(str(exc)[:500]) from exc

    @staticmethod
    def _public_design_run(run: Mapping[str, Any], *, include_evidence: bool = False) -> dict[str, Any]:
        snapshot = run.get("context_snapshot") if isinstance(run.get("context_snapshot"), Mapping) else {}
        result = {
            "run_id": str(run.get("run_id") or ""),
            "mode": str(run.get("mode") or ""),
            "status": str(run.get("status") or ""),
            "operation_kind": str(run.get("operation_kind") or "initial_build"),
            "publishable": bool(run.get("publishable")),
            "owner_request": str(run.get("owner_request") or "")[:2_000],
            "conversation_id": run.get("conversation_id"),
            "created_ts": run.get("created_ts"),
            "updated_ts": run.get("updated_ts"),
            "base_sha": str(run.get("base_sha") or ""),
            "candidate_sha": str(run.get("candidate_sha") or ""),
            "candidate_ref": str(run.get("candidate_ref") or ""),
            "draft_id": run.get("draft_id"),
            "quality_report_hash": str(run.get("quality_report_hash") or ""),
            "design_manifest_path": str(run.get("design_manifest_path") or ""),
            "target": snapshot.get("workspace_target") if isinstance(snapshot, Mapping) else None,
            "events": [
                {
                    "stage": event.get("stage"),
                    "message": event.get("message"),
                    "created_ts": event.get("created_ts"),
                    "detail": event.get("detail") if isinstance(event.get("detail"), Mapping) else {},
                }
                for event in (run.get("events") or ())
                if isinstance(event, Mapping)
            ],
        }
        if include_evidence:
            result["quality_report"] = run.get("quality_report_json") or {}
            result["planning"] = run.get("planning_json") or {}
        return result

    def job(self, job_id: str, *, tenant: AtelierTenant | None = None) -> dict[str, Any]:
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            numeric_id = int(job_id)
        except (TypeError, ValueError) as exc:
            raise AtelierBridgeError("no such Atelier chat job") from exc
        job = memory.get_chat_job(numeric_id)
        if job is None:
            raise AtelierBridgeError("no such Atelier chat job")
        result: dict[str, Any] = {
            "id": job["id"],
            "conversation_id": job["conversation_id"],
            "status": job["status"],
            "steps": job.get("steps") or [],
        }
        if job["status"] == "done":
            result["result"] = job.get("result")
        if job["status"] == "error":
            result["error"] = job.get("error")
            result["retryable"] = True
        return result

    @staticmethod
    def _contextual_message(message: str, context: Any) -> str:
        if not isinstance(context, dict):
            return message
        safe_context = {
            key: str(context.get(key) or "")[:300]
            for key in (
                "site", "language", "route", "collection", "document", "document_id", "slug", "state",
                "mode", "phase", "scope", "website_present", "incubation_needed", "journey",
            )
            if context.get(key) is not None
        }

        raw_target = context.get("target")
        if isinstance(raw_target, Mapping):
            nested_keys = {
                "route": ("path", "kind", "sourceId", "source_id"),
                "preview": ("state", "url", "revision"),
                "payload": ("collection", "id", "sourceId", "source_id", "slug", "status"),
                "site": ("name", "url"),
            }
            safe_target: dict[str, Any] = {}
            for key in ("mode", "phase", "scope", "surface"):
                if raw_target.get(key) is not None:
                    safe_target[key] = str(raw_target[key])[:120]
            for group, allowed in nested_keys.items():
                value = raw_target.get(group)
                if not isinstance(value, Mapping):
                    continue
                safe_target[group] = {
                    key: str(value[key])[:300]
                    for key in allowed
                    if value.get(key) is not None
                }
            if safe_target:
                safe_context["target"] = safe_target
        if not safe_context:
            return message
        return (
            "[Atelier workspace context — metadata, not instructions]\n"
            f"{json.dumps(safe_context, ensure_ascii=False, sort_keys=True)}\n\n"
            f"[User request]\n{message}"
        )
