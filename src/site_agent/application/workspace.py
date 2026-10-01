"""Shared, tenant-isolated application services for the owner workspace API.

The public API is one process and one ingress.  Customer state is not shared:
each tenant has its own config file, Payload credential, SQLite memory database,
Runtime, and job executor.  The bearer token selects the tenant before any
conversation or job id is looked up.
 Customer-specific configuration and Payload adapters stay at the edge; this
 module is the reusable multi-tenant bridge.
"""

from __future__ import annotations

import hmac
import json
import re
import datetime
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

from ..config import ConfigError, deep_merge, intake_settings, load
from .intake_coordinator import IntakeCoordinator
from ..core.memory import Memory
from ..core.reflect import effective_persona
from ..core.scheduler import Scheduler
from ..brain.owner_copy import owner_safe_failure
from ..runtime import Runtime
from .tenant_registration import tenant_token_env


class BridgeError(ValueError):
    """A trusted workspace bridge request could not be accepted."""


class SourceConflict(BridgeError):
    """A source edit was based on stale or mismatched source evidence."""


_SAFE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SAFE_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_edit_ops(meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the legacy and current draft shapes as editor operations."""
    if isinstance(meta.get("ops"), list):
        return [dict(item) for item in meta["ops"] if isinstance(item, Mapping)]
    if meta.get("file_op"):
        return [{
            "op": "edit",
            "path": meta.get("path"),
            "find": meta.get("find"),
            "replace": meta.get("replace"),
        }]
    return [
        {"op": "set_field", "path": change.get("path", ""), "field": change["field"], "value": change["after"]}
        for change in (meta.get("changes") or [])
        if isinstance(change, Mapping) and change.get("field") is not None and "after" in change
    ]


@dataclass(frozen=True)
class Journey:
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


def _journey_for_config(config: Mapping[str, Any]) -> Journey:
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

    intake = intake_settings(config)
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
    return Journey(website_present=website_present, incubation_needed=incubation_needed)


class DesignBuildHandoff:
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
            raise BridgeError("the full design build service is unavailable")
        # Runtime composition owns the tenant config.  Keep a recovered
        # DesignService instance from an older process/config snapshot from
        # losing the newly provisioned local clone before resolving its base
        # SHA.  This is intentionally one-way and only repairs the missing
        # clone path; it never overwrites a configured customer target.
        runtime_config = self.context.get("config")
        service_config = getattr(service, "config", None)
        runtime_site = runtime_config.get("site") if isinstance(runtime_config, Mapping) else {}
        service_site = service_config.get("site") if isinstance(service_config, Mapping) else {}
        if (
            isinstance(runtime_site, Mapping)
            and str(runtime_site.get("clone_path") or "").strip()
            and not str(service_site.get("clone_path") or "").strip()
        ):
            service.config = {
                **dict(service_config or {}),
                "site": {**dict(service_site or {}), **dict(runtime_site)},
            }
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
class Tenant:
    """All process-local dependencies for one isolated customer workspace."""

    tenant_id: str
    config: dict[str, Any]
    memory: Memory
    runtime: Runtime
    context: dict[str, Any]
    api_token: str
    executor: Any = None
    design_executor: Any = None
    intake_coordinator: IntakeCoordinator | None = None
    scheduler_thread: threading.Thread | None = None
    scheduler_stop: threading.Event | None = None


class TenantRegistry:
    """Load and own all tenants served by one shared API process."""

    def __init__(
        self,
        tenants: Mapping[str, Tenant],
        *,
        env: Mapping[str, str] | None = None,
        shared_credentials: Mapping[str, Any] | None = None,
        shared_observability: Mapping[str, Any] | None = None,
    ) -> None:
        self.tenants = dict(tenants)
        self._env = dict(env or {})
        self._shared_credentials = dict(shared_credentials or {})
        self._shared_observability = dict(shared_observability or {})
        self._started = False

    @classmethod
    def from_config(cls, config: Mapping[str, Any], env: Mapping[str, str]) -> "TenantRegistry":
        section = config.get("workspace_api") or {}
        if not isinstance(section, Mapping) or not bool(section.get("enabled", False)):
            raise ConfigError("workspace_api.enabled must be true for the shared workspace API")
        declared = section.get("tenants") or {}
        if not isinstance(declared, Mapping):
            raise ConfigError("workspace_api.tenants must be an object")
        # Runtime-registered tenants (HelloAda website creations) are persisted
        # separately and reloaded here so the API process can restart without
        # losing a provisioned workspace.  Their token values live in per-tenant
        # env files next to the tenant registry, never in a config file.
        from .tenant_registration import load_provisioned_tenants

        provisioned_declared, provisioned_env = load_provisioned_tenants(config, env)
        declared = {**dict(declared), **provisioned_declared}
        env = {**dict(env), **provisioned_env}

        tenants: dict[str, Tenant] = {}
        seen_data_dirs: set[Path] = set()
        seen_tokens: set[str] = set()
        # Keep the reusable host profile valid in both shapes: the shared API
        # config historically placed it at the root, while newer configs may
        # Scope it under workspace_api. Section-local values take precedence.
        root_credentials = config.get("credentials") if isinstance(config.get("credentials"), Mapping) else {}
        section_credentials = section.get("credentials") if isinstance(section.get("credentials"), Mapping) else {}
        shared_credentials = deep_merge(dict(root_credentials), dict(section_credentials))
        shared_observability = config.get("observability") if isinstance(config.get("observability"), Mapping) else {}
        try:
            for raw_tenant_id, raw_spec in declared.items():
                tenant_id = str(raw_tenant_id or "").strip().lower()
                if not _SAFE_NAME.fullmatch(tenant_id):
                    raise ConfigError(f"workspace_api tenant id is invalid: {tenant_id or '(empty)'}")
                if not isinstance(raw_spec, Mapping):
                    raise ConfigError(f"workspace_api.tenants.{tenant_id} must be an object")

                config_path = Path(str(raw_spec.get("config_path") or "")).expanduser()
                if not config_path.is_file():
                    raise ConfigError(f"tenant config not found: {config_path}")
                tenant_config, _ = load(config_path, dict(env))
                raw_tenant_config = yaml.safe_load(config_path.read_text()) or {}
                raw_tenant_credentials = (
                    raw_tenant_config.get("credentials")
                    if isinstance(raw_tenant_config, Mapping)
                    and isinstance(raw_tenant_config.get("credentials"), Mapping)
                    else {}
                )
                raw_tenant_observability = (
                    raw_tenant_config.get("observability")
                    if isinstance(raw_tenant_config, Mapping)
                    and isinstance(raw_tenant_config.get("observability"), Mapping)
                    else {}
                )
                tenant_config["instance_name"] = tenant_id
                # The shared API owns the reusable platform connections. A
                # tenant may override a profile deliberately, but omission
                # must not make every future site rediscover GitHub/Cloudflare
                # credentials independently.
                tenant_config["credentials"] = deep_merge(
                    dict(shared_credentials),
                    dict(raw_tenant_credentials),
                )
                tenant_config["observability"] = deep_merge(
                    dict(shared_observability),
                    dict(raw_tenant_observability),
                )

                data_dir = Path(str(tenant_config.get("data_dir") or "")).expanduser().resolve()
                if not str(data_dir) or data_dir == Path("/"):
                    raise ConfigError(f"tenant {tenant_id} needs a dedicated data_dir")
                if data_dir in seen_data_dirs:
                    raise ConfigError(f"tenant data_dir is shared: {data_dir}")
                seen_data_dirs.add(data_dir)
                tenant_config["data_dir"] = str(data_dir)

                token_env = str(
                    raw_spec.get("api_token_env")
                    or tenant_token_env(tenant_id)
                ).strip()
                if not _SAFE_ENV.fullmatch(token_env):
                    raise ConfigError(f"tenant {tenant_id} api_token_env is invalid")
                payload_settings = (
                    (tenant_config.get("site") or {}).get("payload")
                    if isinstance(tenant_config.get("site"), Mapping)
                    else None
                )
                if isinstance(payload_settings, Mapping) and bool(payload_settings.get("enabled", False)):
                    payload_token_env = str(payload_settings.get("token_env") or "PAYLOAD_GATEWAY_TOKEN").strip()
                    if payload_token_env != token_env:
                        raise ConfigError(
                            f"tenant {tenant_id} payload.token_env must match "
                            f"workspace_api api_token_env ({token_env}); got {payload_token_env}"
                        )
                api_token = str(env.get(token_env) or "")
                if not api_token:
                    raise ConfigError(f"tenant {tenant_id} is missing {token_env}")
                if api_token in seen_tokens:
                    raise ConfigError("tenant API tokens must be unique")
                seen_tokens.add(api_token)

                memory = Memory(data_dir / "memory.db")
                from .seo_bootstrap import auto_provision_seo, load_tenant_environment

                tenant_env = load_tenant_environment(tenant_config, env)
                seo_state: dict[str, Any] = {}
                if isinstance(tenant_config.get("seo"), Mapping):
                    try:
                        seo_state, tenant_env = auto_provision_seo(
                            tenant_config,
                            tenant_id=tenant_id,
                            memory=memory,
                            env=tenant_env,
                        )
                    except Exception as exc:  # noqa: BLE001 - bootstrap is retried by the scheduler
                        memory.kv_set(
                            "seo_provisioning_state",
                            {"state": "error", "error": str(exc)[:500]},
                        )
                        seo_state = memory.kv_get("seo_provisioning_state", {}) or {}
                scheduler = Scheduler(memory, lock_path=data_dir / "scheduler.lock")
                from ..core.llm import Client

                llm = Client(tenant_config, memory, env=dict(tenant_env))
                runtime = Runtime(
                    tenant_config,
                    memory,
                    scheduler,
                    llm,
                    effective_persona(tenant_config, memory),
                    env=dict(tenant_env),
                )
                context = runtime.context()
                from ..hands.payload_gateway import PayloadGatewayClient

                google_platform = None
                try:
                    from .seo_provisioning import SeoProvisioningService

                    google_platform = SeoProvisioningService(tenant_config, tenant_env).google_client()
                except Exception as exc:  # noqa: BLE001 - analytics reports surface provider availability to the owner
                    memory.record_action("analytics", f"Google analytics client unavailable: {str(exc)[:180]}")

                payload_client = PayloadGatewayClient.from_config(tenant_config, dict(tenant_env))
                journey = _journey_for_config(tenant_config)
                context.update({
                    "payload_gateway": payload_client,
                    "tenant_id": tenant_id,
                    "journey": journey,
                    "seo_provisioning_state": seo_state,
                    "google_platform": google_platform,
                })
                from .design_operations import DesignOperationService

                # The operation service is tenant-scoped and provider-neutral;
                # both HelloAda and the full workspace use this same instance.
                context["design_operations"] = DesignOperationService(
                    memory,
                    website_id=tenant_id,
                )
                from .source_editor import SourceEditorService
                from .source_deployment import SourceDeploymentService
                from ..hands.base import get_adapter

                site_config = tenant_config.get("site") or {}
                site_adapter_name = str(site_config.get("adapter") or "github_static").strip()
                context["source_editor"] = SourceEditorService(
                    tenant_config,
                    dict(env),
                    adapter=get_adapter(site_adapter_name, tenant_config),
                )
                # A neutral scaffold is deliberately host-local.  Do not create
                # the GitHub/Cloudflare deployment lane for it; approval merges
                # the reviewed SHA into the local main branch and stops there
                # until the separately-authorized infrastructure saga exists.
                context["source_deployment"] = (
                    None
                    if site_adapter_name == "neutral_scaffold"
                    else SourceDeploymentService(tenant_config, dict(env), memory=memory)
                )
                if payload_client is not None:
                    from ..hands.payload_gateway import PayloadMediaService

                    context["media_service"] = PayloadMediaService(payload_client)
                vision_config = tenant_config.get("vision") or {}
                if isinstance(vision_config, Mapping) and bool(vision_config.get("enabled")) and context.get("media_analyzer") is None:
                    from ..core.vision import VisionClient

                    context["media_analyzer"] = VisionClient(tenant_config, env=dict(env), memory=memory)
                design_engine = tenant_config.get("design_engine") or {}
                builder_config = tenant_config.get("builder") or {}
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
                    try:
                        design_adapter = get_adapter(site_adapter_name, tenant_config)
                        design_adapter.validate()
                    except Exception as exc:  # noqa: BLE001 — fail closed when approval cannot be safe
                        raise ConfigError(f"design approval adapter is unavailable: {exc}") from exc
                    context["design_adapter"] = design_adapter
                intake_options = intake_settings(tenant_config)
                intake_enabled = bool(intake_options.get("enabled", False)) or journey.incubation_needed
                if not journey.website_present and not journey.incubation_needed:
                    # New-site tenants still need the typed full-intake front
                    # door even when they do not carry the incubation block in
                    # their config.
                    intake_options = dict(intake_options)
                    intake_options["enabled"] = True
                    intake_options["database_only"] = False
                    research_options = intake_options.get("research")
                    research_options = dict(research_options) if isinstance(research_options, Mapping) else {}
                    research_options["enabled"] = False
                    intake_options["research"] = research_options
                    tenant_config = dict(tenant_config)
                    tenant_config["intake"] = intake_options
                    intake_enabled = True
                intake_coordinator = None
                if intake_enabled:
                    intake_coordinator = IntakeCoordinator(
                        memory,
                        config=tenant_config,
                        llm=context.get("llm"),
                        media_service=context.get("media_service"),
                        payload_client=payload_client,
                    )
                    context.update({
                        "intake_coordinator": intake_coordinator,
                        "design_intake_service": intake_coordinator.intake_service,
                    })
                    from .design_direction import DesignDirectionService

                    context["design_direction"] = DesignDirectionService(
                        memory,
                        intake_coordinator.intake_service,
                        context["design_operations"],
                    )
                tenants[tenant_id] = Tenant(
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
        return cls(
            tenants,
            env=dict(env),
            shared_credentials=shared_credentials,
            shared_observability=shared_observability,
        )

    def for_token(self, token: str) -> Tenant | None:
        supplied = str(token or "")
        if not supplied:
            return None
        for tenant in self.tenants.values():
            if hmac.compare_digest(supplied.encode(), tenant.api_token.encode()):
                return tenant
        return None

    def for_tenant_id(self, tenant_id: str) -> Tenant | None:
        """Resolve a tenant by id for the server-only HelloAda control plane."""
        normalized = str(tenant_id or "").strip().lower()
        if not normalized:
            return None
        return self.tenants.get(normalized)

    def start(self) -> None:
        if self._started:
            return
        started: list[Tenant] = []
        try:
            for tenant in self.tenants.values():
                self._start_tenant(tenant)
                started.append(tenant)
        except Exception:
            for tenant in reversed(started):
                self._stop_tenant(tenant)
            raise
        self._started = True

    def _start_tenant(self, tenant: Tenant) -> None:
        """Start every runtime dependency for a single tenant."""
        from ..application.design_jobs import DesignJobExecutor
        from ..core.chat_jobs import ChatJobExecutor
        from ..hands.payload_gateway import PayloadGatewaySiteAdapter

        tenant.runtime.start()
        tenant.memory.interrupt_running_chat_jobs()
        tenant.memory.interrupt_running_design_runs()
        if tenant.intake_coordinator is not None:
            tenant.intake_coordinator.start()
        self._start_scheduler(tenant)
        tenant.design_executor = DesignJobExecutor(
            tenant.context,
            tenant.context["design_service"],
        )
        tenant.context["design_executor"] = tenant.design_executor
        journey = self._tenant_journey(tenant)
        if journey is not None and not journey.website_present:
            intake_service = tenant.context.get("design_intake_service")
            if intake_service is not None:
                handoff = DesignBuildHandoff(tenant.context)
                intake_service.lab_service = handoff
                tenant.context["design_intake_build_service"] = handoff
        tenant.design_executor.start()
        tenant.executor = ChatJobExecutor(
            tenant.context,
            adapter_factory=lambda tenant=tenant: (
                PayloadGatewaySiteAdapter(
                    tenant.config,
                    payload_client=tenant.context.get("payload_gateway"),
                    read_adapter=getattr(
                        tenant.context.get("source_editor"), "adapter", None
                    ),
                )
                if tenant.context.get("payload_gateway") is not None
                else self._site_adapter(tenant)
            ),
        )
        tenant.executor.start()

    def register_tenant(
        self,
        tenant_id: str,
        config_path: str,
        *,
        api_token: str,
        api_token_env: str | None = None,
        env: Mapping[str, str] | None = None,
        start: bool = True,
    ) -> Tenant:
        """Build, register, and optionally start one runtime-registered tenant.

        The tenant is constructed through the exact same path used at API
        startup (``from_config``), so a provisioned website behaves identically
        to a tenant declared in the host config.  The call is idempotent: a
        tenant already registered under the same id is returned as-is.
        """
        normalized = str(tenant_id or "").strip().lower()
        if not _SAFE_NAME.fullmatch(normalized):
            raise ConfigError(f"tenant id is invalid: {normalized or '(empty)'}")
        existing = self.tenants.get(normalized)
        if existing is not None:
            return existing
        if not str(api_token or "").strip():
            raise ConfigError(f"tenant {normalized} requires an api token")
        merged_env = dict(self._env)
        if env:
            merged_env.update(env)
        token_env = str(
            api_token_env or tenant_token_env(normalized)
        ).strip()
        if not _SAFE_ENV.fullmatch(token_env):
            raise ConfigError(f"tenant {normalized} api_token_env is invalid")
        merged_env[token_env] = api_token
        spec = {"config_path": str(config_path), "api_token_env": token_env}

        proxy = {
            "credentials": dict(self._shared_credentials),
            "observability": dict(self._shared_observability),
            "workspace_api": {
                "enabled": True,
                "provisioned_root": str(
                    Path(config_path).expanduser().resolve().parent.parent / ".registration-proxy"
                ),
                "tenants": {normalized: spec},
            },
        }
        temporary = TenantRegistry.from_config(proxy, merged_env)
        try:
            tenant = temporary.tenants[normalized]
        except Exception:
            temporary.close()
            raise
        data_dir = Path(str(tenant.config.get("data_dir") or "")).expanduser().resolve()
        for other in self.tenants.values():
            other_dir = Path(str(other.config.get("data_dir") or "")).expanduser().resolve()
            if other_dir == data_dir:
                temporary.close()
                raise ConfigError(f"tenant data_dir is already in use: {data_dir}")
        temporary.tenants.clear()
        self.tenants[normalized] = tenant
        if self._started and start:
            try:
                self._start_tenant(tenant)
            except Exception:
                self.tenants.pop(normalized, None)
                self._stop_tenant(tenant)
                raise
        return tenant

    def reload_tenant(
        self,
        tenant_id: str,
        config_path: str,
        *,
        api_token: str,
        api_token_env: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Tenant:
        """Rebuild one tenant after bootstrap changes its runtime config.

        Runtime registration normally happens before a website has a remote
        source. Bootstrap later adds GitHub/Payload/Worker settings to the same
        config file; replacing only the in-memory config would leave the old
        adapter graph alive. This method performs the same isolated construction
        as startup without restarting the shared API process.
        """
        normalized = str(tenant_id or "").strip().lower()
        if not _SAFE_NAME.fullmatch(normalized):
            raise ConfigError(f"tenant id is invalid: {normalized or '(empty)'}")
        if not str(api_token or "").strip():
            raise ConfigError(f"tenant {normalized} requires an api token")
        token_env = str(
            api_token_env or tenant_token_env(normalized)
        ).strip()
        if not _SAFE_ENV.fullmatch(token_env):
            raise ConfigError(f"tenant {normalized} api_token_env is invalid")
        merged_env = dict(self._env)
        if env:
            merged_env.update(env)
        merged_env[token_env] = api_token
        proxy = {
            "credentials": dict(self._shared_credentials),
            "observability": dict(self._shared_observability),
            "workspace_api": {
                "enabled": True,
                "provisioned_root": str(
                    Path(config_path).expanduser().resolve().parent.parent / ".registration-proxy"
                ),
                "tenants": {normalized: {"config_path": str(config_path), "api_token_env": token_env}},
            },
        }
        temporary = TenantRegistry.from_config(proxy, merged_env)
        try:
            replacement = temporary.tenants[normalized]
        except Exception:
            temporary.close()
            raise
        temporary.tenants.clear()
        previous = self.tenants.get(normalized)
        if previous is not None:
            self._stop_tenant(previous)
        self.tenants[normalized] = replacement
        if self._started:
            try:
                self._start_tenant(replacement)
            except Exception:
                self.tenants.pop(normalized, None)
                self._stop_tenant(replacement)
                raise
        return replacement

    @staticmethod
    def _start_scheduler(tenant: Tenant) -> None:
        """Start the reusable reading/editorial loop for an opted-in tenant."""
        settings = tenant.config.get("scheduler") or {}
        if not isinstance(settings, Mapping) or not bool(settings.get("enabled", False)):
            return
        from ..core.jobs import register_jobs

        register_jobs(tenant.runtime.scheduler, tenant.config, tenant.context)
        if not tenant.runtime.scheduler.jobs:
            return
        stop_event = threading.Event()
        try:
            poll_seconds = max(5, int(settings.get("poll_seconds", tenant.config.get("poll_seconds", 300))))
        except (TypeError, ValueError):
            poll_seconds = 300

        def run() -> None:
            try:
                tenant.runtime.scheduler.run_forever(poll_seconds=poll_seconds, stop_event=stop_event)
            except Exception as exc:  # noqa: BLE001 — one tenant must not take down the API
                try:
                    tenant.memory.record_action("scheduler_error", str(exc)[:500])
                except Exception:
                    pass

        tenant.scheduler_stop = stop_event
        tenant.scheduler_thread = threading.Thread(
            target=run,
            name=f"ada-scheduler-{tenant.tenant_id}",
            daemon=True,
        )
        tenant.scheduler_thread.start()

    @staticmethod
    def _site_adapter(tenant: Tenant) -> Any:
        """Use the configured normal site adapter for a new-site tenant."""
        from ..hands.base import get_adapter

        site = tenant.config.get("site") if isinstance(tenant.config.get("site"), Mapping) else {}
        name = str(site.get("adapter") or "github_static").strip()
        return get_adapter(name, tenant.config)

    @staticmethod
    def _tenant_journey(tenant: Tenant) -> Journey | None:
        value = tenant.context.get("journey")
        return value if isinstance(value, Journey) else None

    def _stop_tenant(self, tenant: Tenant) -> None:
        if tenant.scheduler_stop is not None:
            tenant.scheduler_stop.set()
        if tenant.scheduler_thread is not None:
            tenant.scheduler_thread.join(timeout=10)
            tenant.scheduler_thread = None
            tenant.scheduler_stop = None
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
        source_deployment = tenant.context.pop("source_deployment", None)
        close_source_deployment = getattr(source_deployment, "close", None)
        if callable(close_source_deployment):
            close_source_deployment()
        tenant.context.pop("design_executor", None)
        tenant.runtime.close()
        tenant.memory.close()

    def close(self) -> None:
        for tenant in self.tenants.values():
            self._stop_tenant(tenant)
        self._started = False


class ChatService:
    """Translate the Payload workspace contract into durable, scoped chat jobs."""

    def __init__(
        self,
        memory: Any | None = None,
        llm: Any | None = None,
        *,
        registry: TenantRegistry | None = None,
        config: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
        source_editor: Any | None = None,
        source_deployment: Any | None = None,
    ) -> None:
        # ``memory`` + ``llm`` remains supported for the existing single-instance
        # admin server and its tests. The shared API always supplies a registry.
        self.memory = memory
        self.llm = llm
        self.registry = registry
        self.config = dict(config or {})
        self.env = dict(env or {})
        self.source_editor = source_editor
        self.source_deployment = source_deployment
        self._approval_lock = threading.RLock()

    @staticmethod
    def _require_llm(llm: Any) -> None:
        if llm is None or (hasattr(llm, "api_key") and not llm.api_key):
            raise BridgeError("LLM not configured")

    def _scope(self, tenant: Tenant | None) -> tuple[Any, Any, str]:
        if self.registry is not None:
            if tenant is None or tenant.tenant_id not in self.registry.tenants:
                raise BridgeError("tenant is not authorized")
            self._require_llm(tenant.context.get("llm"))
            return tenant.memory, tenant.context.get("llm"), tenant.tenant_id
        self._require_llm(self.llm)
        return self.memory, self.llm, "legacy"

    def design_operations(self, *, tenant: Tenant | None = None):
        """Return the tenant-scoped shared owner-operation service."""
        if self.registry is not None:
            if tenant is None or tenant.tenant_id not in self.registry.tenants:
                raise BridgeError("tenant is not authorized")
            service = tenant.context.get("design_operations")
            if service is None:
                raise BridgeError("design operations are unavailable")
            return service
        if self.memory is None:
            raise BridgeError("design operations are unavailable")
        from .design_operations import DesignOperationService

        return DesignOperationService(self.memory, website_id="legacy")

    def recommendations(self, *, limit: int = 50, tenant: Tenant | None = None) -> dict[str, Any]:
        return {
            "recommendations": self.design_operations(tenant=tenant).list_recommendations(limit=limit),
        }

    def propose_direction(
        self,
        body: Mapping[str, Any],
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Run the read-only direction step and wait with a build recommendation."""
        if tenant is None or tenant.context.get("intake_coordinator") is None:
            raise BridgeError("tenant intake is not enabled")
        direction = tenant.context.get("design_direction")
        if direction is None:
            raise BridgeError("design direction is unavailable")
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("conversation_id must be an integer") from exc
        coordinator = tenant.context["intake_coordinator"]
        status = coordinator.status(conversation_id)
        if not status.get("confirmed"):
            raise BridgeError("the working brief must be accepted before proposing a direction")
        confirmed_revision = body.get("confirmed_revision") or status.get("confirmed_revision")
        try:
            confirmed_revision = int(confirmed_revision)
        except (TypeError, ValueError) as exc:
            raise BridgeError("confirmed_revision must be an integer") from exc
        try:
            return direction.propose(
                str(status.get("session_id") or ""),
                confirmed_revision=confirmed_revision,
                conversation_id=conversation_id,
            )
        except Exception as exc:  # noqa: BLE001 - normalize the application boundary
            raise BridgeError(str(exc)[:500]) from exc

    def accept_recommendation(
        self,
        action_id: int,
        body: Mapping[str, Any] | None = None,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        body = dict(body or {})
        current_state = body.get("current_state")
        if current_state is not None and not isinstance(current_state, Mapping):
            raise BridgeError("current_state must be an object")
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("conversation_id must be an integer") from exc
        try:
            operation_service = self.design_operations(tenant=tenant)
            if current_state is None and tenant is not None:
                action = operation_service.recommendation(action_id)
                bound = action.payload.get("bound_state") if isinstance(action.payload, Mapping) else {}
                bound = bound if isinstance(bound, Mapping) else {}
                coordinator = tenant.context.get("intake_coordinator")
                if coordinator is not None and "intake_revision" in bound:
                    intake_status = coordinator.status(conversation_id or action.conversation_id)
                    # The server knows the current confirmed revision; the
                    # browser should not have to copy a hidden hash into an
                    # approval request.  Direction hashes remain bound to the
                    # recommendation and are checked by the operation gate.
                    current_state = {
                        "intake_revision": intake_status.get("confirmed_revision"),
                    }
                    if "direction_hash" in bound:
                        current_state["direction_hash"] = bound.get("direction_hash")
            operation = operation_service.accept(
                action_id,
                current_state=current_state,
                conversation_id=conversation_id,
            )
            operation = self._execute_operation(operation, tenant=tenant)
            action = operation_service.recommendation(action_id)
            return {
                "recommendation": operation_service.recommendation_view(action),
                "operation": operation.to_dict(),
            }
        except Exception as exc:  # noqa: BLE001 - normalize service errors at the bridge boundary
            raise BridgeError(str(exc)[:500]) from exc

    def _execute_operation(self, operation, *, tenant: Tenant | None = None):
        """Execute the first real tool while keeping operation state durable.

        Direction is completed by ``DesignDirectionService``. The initial build
        remains an asynchronous design job, so this method only reserves the
        existing intake build and records the resulting run as the operation
        outcome; it does not duplicate the design executor.
        """
        if operation.tool != "design.build" or tenant is None:
            return operation
        intake_service = tenant.context.get("design_intake_service")
        coordinator = tenant.context.get("intake_coordinator")
        if intake_service is None or coordinator is None:
            return operation
        if operation.status.value == "done":
            return operation
        if operation.status.value != "queued":
            return operation
        operation_service = self.design_operations(tenant=tenant)
        scope = operation.payload.get("scope") if isinstance(operation.payload, Mapping) else {}
        scope = scope if isinstance(scope, Mapping) else {}
        session_id = str(scope.get("session_id") or "").strip()
        if not session_id:
            return operation_service.fail(
                operation.id or 0,
                error_code="missing_intake_session",
                reason="design.build requires an intake session",
            )
        try:
            running = operation_service.start(operation.id or 0)
            try:
                retry_count = int(operation.payload.get("retry_count") or 0)
            except (AttributeError, TypeError, ValueError):
                retry_count = 0
            build = intake_service.build(
                session_id,
                confirmed_revision=int(scope.get("confirmed_revision") or 0),
                owner_request=str(scope.get("owner_request") or "Start the homepage design from the approved direction."),
                idempotency_key=f"design-operation:{operation.id}:{retry_count}",
                force_new=retry_count > 0,
                context_extra={
                    "operation_id": operation.id,
                    "approved_direction_hash": str(scope.get("direction_hash") or ""),
                    "direction_artifact_id": scope.get("direction_artifact_id"),
                    "page": str(scope.get("page") or "index.html"),
                },
            )
            run = build.get("run") if isinstance(build, Mapping) else None
            run_id = str(run.get("run_id") or "") if isinstance(run, Mapping) else ""
            return operation_service.complete(
                running.id or 0,
                outcome={
                    "run": self._public_design_run(run) if isinstance(run, Mapping) else None,
                    "build_pending": bool(build.get("build_pending")) if isinstance(build, Mapping) else False,
                },
                revision_id=run_id or None,
            )
        except Exception as exc:  # noqa: BLE001 - retain failure and expose a bounded message
            try:
                return operation_service.fail(
                    operation.id or 0,
                    error_code="design_build_submission_failed",
                    reason=str(exc)[:500],
                )
            except Exception:
                raise

    def dismiss_recommendation(
        self,
        action_id: int,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        try:
            operation_service = self.design_operations(tenant=tenant)
            action = operation_service.dismiss(action_id)
            return {"recommendation": operation_service.recommendation_view(action)}
        except Exception as exc:  # noqa: BLE001 - normalize service errors at the bridge boundary
            raise BridgeError(str(exc)[:500]) from exc

    def operations(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        try:
            return {
                "operations": [
                    operation.to_dict()
                    for operation in self.design_operations(tenant=tenant).list(
                        status=status,
                        limit=limit,
                    )
                ],
            }
        except Exception as exc:  # noqa: BLE001 - normalize service errors at the bridge boundary
            raise BridgeError(str(exc)[:500]) from exc

    def operation(self, operation_id: int, *, tenant: Tenant | None = None) -> dict[str, Any]:
        try:
            return self.design_operations(tenant=tenant).get(operation_id).to_dict()
        except Exception as exc:  # noqa: BLE001 - normalize service errors at the bridge boundary
            raise BridgeError(str(exc)[:500]) from exc

    def _merge_adapter(self, tenant: Tenant | None) -> Any:
        """Resolve the existing tenant-scoped Git-backed publish adapter."""
        if tenant is not None:
            for context_key in ("design_adapter", "source_deployment", "source_editor"):
                candidate = tenant.context.get(context_key)
                if candidate is not None and any(
                    callable(getattr(candidate, capability, None))
                    for capability in ("merge_preview", "restore_snapshot", "reset_preview_branch")
                ):
                    return candidate
                adapter = getattr(candidate, "adapter", None) if candidate is not None else None
                if adapter is not None:
                    return adapter
            site = tenant.config.get("site") if isinstance(tenant.config.get("site"), Mapping) else {}
            config = tenant.config
        else:
            for candidate in (self.source_deployment, self.source_editor):
                if candidate is not None and any(
                    callable(getattr(candidate, capability, None))
                    for capability in ("merge_preview", "restore_snapshot", "reset_preview_branch")
                ):
                    return candidate
                adapter = getattr(candidate, "adapter", None) if candidate is not None else None
                if adapter is not None:
                    return adapter
            if not self.config:
                raise BridgeError("tenant publish adapter is not configured")
            site = self.config.get("site") if isinstance(self.config.get("site"), Mapping) else {}
            config = self.config

        from ..hands.base import get_adapter

        return get_adapter(str(site.get("adapter") or "github_static").strip(), dict(config))

    def _assert_reviewable_merge_candidate(
        self,
        draft: Mapping[str, Any],
        adapter: Any,
        tenant: Tenant | None,
    ) -> None:
        """Refuse approval unless the owner can be tied to one verified SHA."""
        meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
        expected = str(meta.get("head_sha") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise BridgeError("this draft has no immutable candidate revision; create a new preview")

        branch = str(meta.get("head") or ((tenant.config.get("site") if tenant else self.config.get("site")) or {}).get("preview_branch") or "preview")
        get_head = getattr(adapter, "get_branch_head", None)
        if not callable(get_head):
            raise BridgeError("the preview revision cannot be verified")
        try:
            actual = str(get_head(branch) or "").strip().lower()
        except Exception as exc:  # noqa: BLE001 - keep approval bounded
            raise BridgeError("the preview revision could not be read") from exc
        if actual != expected:
            raise BridgeError("the preview changed after review; create a fresh preview before approving")

        base_branch = str(meta.get("base") or ((tenant.config.get("site") if tenant else self.config.get("site")) or {}).get("branch") or "main")
        expected_base = str(meta.get("base_sha") or "").strip().lower()
        if expected_base and re.fullmatch(r"[0-9a-f]{40}", expected_base):
            try:
                actual_base = str(get_head(base_branch) or "").strip().lower()
            except Exception as exc:  # noqa: BLE001
                raise BridgeError("the production base revision could not be read") from exc
            if actual_base != expected_base:
                raise BridgeError("the production site changed after this preview; create a fresh candidate")

        preview = meta.get("preview") if isinstance(meta.get("preview"), Mapping) else {}
        if preview.get("requires_build"):
            job_id = str(preview.get("job_id") or "").strip()
            deployer = tenant.context.get("source_deployment") if tenant is not None else self.source_deployment
            status = getattr(deployer, "status", None)
            if not job_id or not callable(status):
                raise BridgeError("the compiled preview is not ready for review")
            try:
                receipt = status(job_id)
            except Exception as exc:  # noqa: BLE001
                raise BridgeError("the compiled preview status could not be read") from exc
            if receipt.get("status") != "ready" or str(receipt.get("commit") or "").lower() != expected:
                raise BridgeError("the compiled preview is not ready for this candidate")
        elif preview.get("status") != "ready":
            raise BridgeError("the website preview is not ready for review")

    @staticmethod
    def _attachment_rows(value: Any) -> list[dict[str, int]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise BridgeError("attachments must be a list")
        if len(value) > 12:
            raise BridgeError("choose up to 12 images")
        rows: list[dict[str, int]] = []
        seen: set[int] = set()
        for position, raw in enumerate(value):
            raw_id = (raw.get("asset_id") or raw.get("id")) if isinstance(raw, Mapping) else raw
            try:
                asset_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("attachment ID is invalid") from exc
            if asset_id < 1 or asset_id in seen:
                raise BridgeError("attachments must contain unique positive IDs")
            seen.add(asset_id)
            rows.append({"asset_id": asset_id, "position": position})
        return rows

    @staticmethod
    def _journey(tenant: Tenant | None) -> Journey | None:
        value = tenant.context.get("journey") if tenant is not None else None
        return value if isinstance(value, Journey) else None

    @classmethod
    def _intake_mode(cls, tenant: Tenant | None) -> str:
        journey = cls._journey(tenant)
        return journey.initial_phase if journey is not None else "intake"

    def enqueue(self, body: Mapping[str, Any], *, tenant: Tenant | None = None) -> dict[str, Any]:
        memory, _llm, tenant_id = self._scope(tenant)
        message = str(body.get("message") or "").strip()
        attachments = self._attachment_rows(body.get("attachments"))
        owner_context = body.get("context")
        owner_context = dict(owner_context) if isinstance(owner_context, Mapping) else {}
        if not message and not attachments:
            raise BridgeError("empty message")
        if len(message) > 8000:
            raise BridgeError("message too long")
        if not message:
            message = "Please review the attached images."

        # The tenant journey is authoritative. Preserve it in the intake
        # context instead of asking the advisor to infer an existing site from
        # the owner's wording or from a page label.
        journey = self._journey(tenant)
        if journey is not None:
            owner_context.update({
                "website_present": journey.website_present,
                "incubation_needed": journey.incubation_needed,
                "journey": journey.initial_phase,
            })

        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("conversation_id must be an integer") from exc

        if tenant is not None:
            intake = tenant.context.get("intake_coordinator")
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
                    raise BridgeError(str(exc)[:500]) from exc
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
        if journey is not None:
            context["website_present"] = journey.website_present
            context["incubation_needed"] = journey.incubation_needed
            context["journey"] = "workspace"
        media_service = tenant.context.get("media_service") if tenant is not None else None
        if attachments and media_service is None:
            raise BridgeError("image attachments are unavailable")
        if attachments and media_service is not None:
            try:
                media_service.resolve_attachments([item["asset_id"] for item in attachments])
            except Exception as exc:  # noqa: BLE001 — normalize provider-specific errors
                raise BridgeError(str(exc)[:500]) from exc
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

    def status(self, conversation_id: Any = None, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Return the tenant-scoped chat phase without starting website work.

        Intake owns the phase decision.  The browser may use this to keep the
        page selector and website target dormant until the owner has accepted
        the working brief; it must not try to infer readiness from Payload.
        """
        memory, _llm, tenant_id = self._scope(tenant)
        normalized_id: int | None = None
        if conversation_id is not None and str(conversation_id).strip():
            try:
                normalized_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("conversation_id must be an integer") from exc

        journey = self._journey(tenant)
        intake_enabled = bool(tenant is not None and tenant.context.get("intake_coordinator") is not None)
        needs_intake = False
        intake_status: dict[str, Any] = {}
        if intake_enabled:
            try:
                coordinator = tenant.context["intake_coordinator"]
                intake_status = coordinator.status(normalized_id)
                needs_intake = not bool(intake_status.get("confirmed"))
            except Exception as exc:  # noqa: BLE001 — keep status errors bounded
                raise BridgeError(str(exc)[:500]) from exc
        if journey is None:
            mode = "intake" if needs_intake else "workspace"
        elif needs_intake:
            mode = journey.initial_phase
        else:
            mode = "workspace"
        website_present = journey.website_present if journey is not None else mode == "workspace"
        incubation_needed = journey.incubation_needed if journey is not None else intake_enabled
        active_jobs = memory.list_active_chat_jobs(conversation_id=normalized_id, limit=1)
        active_job = active_jobs[0] if active_jobs else None
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
            "active_job": {
                "id": int(active_job["id"]),
                "conversation_id": int(active_job["conversation_id"]),
                "status": str(active_job["status"]),
                "created_ts": active_job.get("created_ts"),
                "updated_ts": active_job.get("updated_ts"),
            } if active_job else None,
        }

    def confirm_intake(
        self,
        body: Mapping[str, Any],
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Accept intake without starting a design run."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("intake_coordinator") is None:
            raise BridgeError("tenant intake is not enabled")
        coordinator = tenant.context["intake_coordinator"]
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("conversation_id must be an integer") from exc
        try:
            revision = int(body.get("revision"))
        except (TypeError, ValueError) as exc:
                raise BridgeError("revision must be an integer") from exc
        draft_hash = str(body.get("draft_hash") or "").strip().lower()
        confirmation_text = str(body.get("confirmation_text") or "Accept this working brief").strip()
        if not draft_hash:
                raise BridgeError("draft_hash is required")
        if not confirmation_text or len(confirmation_text) > 2_000:
                raise BridgeError("confirmation_text is invalid")
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
            raise BridgeError(str(exc)[:500]) from exc

    def start_first_page(
        self,
        body: Mapping[str, Any],
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Start the first page only through an explicit post-intake action."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("intake_coordinator") is None:
            raise BridgeError("tenant intake is not enabled")
        journey = self._journey(tenant)
        if journey is not None and journey.website_present:
            raise BridgeError("an existing website needs an explicit page target")
        # Real tenants have the shared operation spine. The compatibility
        # fallback below remains for the legacy single-instance test adapter;
        # it is not used by TenantRegistry-created websites.
        if tenant.context.get("design_operations") is not None:
            recommendation_id = body.get("recommendation_id")
            if recommendation_id is None:
                raise BridgeError("direction_not_approved: propose and approve a design direction first")
            try:
                recommendation_id = int(recommendation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("recommendation_id must be an integer") from exc
            return self.accept_recommendation(recommendation_id, body, tenant=tenant)
        coordinator = tenant.context["intake_coordinator"]
        intake_service = tenant.context.get("design_intake_service")
        if intake_service is None or getattr(intake_service, "lab_service", None) is None:
            raise BridgeError("the full design build service is unavailable")
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise BridgeError("conversation_id must be an integer") from exc
        status = coordinator.status(conversation_id)
        if not status.get("confirmed"):
            raise BridgeError("the working brief must be accepted before starting a page")
        session_id = str(status.get("session_id") or "")
        confirmed_revision = body.get("confirmed_revision") or status.get("confirmed_revision_id") or status.get("confirmed_revision")
        try:
            confirmed_revision = int(confirmed_revision)
        except (TypeError, ValueError) as exc:
            raise BridgeError("confirmed_revision must be an integer") from exc
        try:
            build = intake_service.build(
                session_id,
                confirmed_revision=confirmed_revision,
                owner_request=str(body.get("owner_request") or "Start the first page design from the confirmed working brief."),
                idempotency_key=body.get("idempotency_key"),
                context_extra={"operation": "first_page_design", "page": "index.html"},
            )
        except Exception as exc:  # noqa: BLE001 — normalize bridge errors
            raise BridgeError(str(exc)[:500]) from exc
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
        tenant: Tenant | None = None,
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

    def conversation(self, conversation_id: Any, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Return one durable conversation and its messages for the tenant."""
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            normalized_id = int(conversation_id)
        except (TypeError, ValueError) as exc:
            raise BridgeError("conversation_id must be an integer") from exc
        from .conversations import ConversationNotFound, ConversationService

        media_service = tenant.context.get("media_service") if tenant is not None else None
        service = ConversationService(memory, media_service=media_service)
        try:
            return service.get(normalized_id)
        except ConversationNotFound as exc:
            raise BridgeError(str(exc)) from exc

    def history(self, *, limit: int = 50, tenant: Tenant | None = None) -> dict[str, Any]:
        """Return a bounded, tenant-scoped activity index without raw context."""
        memory, _llm, tenant_id = self._scope(tenant)
        bounded_limit = max(1, min(int(limit), 100))
        preview_head = ""
        if tenant is not None:
            try:
                editor = tenant.context.get("source_editor")
                adapter = getattr(editor, "adapter", None)
                get_head = getattr(adapter, "get_branch_head", None)
                preview_branch = str((tenant.config.get("site") or {}).get("preview_branch") or "preview")
                if callable(get_head):
                    preview_head = str(get_head(preview_branch) or "").strip().lower()
            except Exception:
                preview_head = ""
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
        deployer = tenant.context.get("source_deployment") if tenant else self.source_deployment
        deployment_for_draft = getattr(deployer, "for_draft", None)
        for item in memory.list_drafts(limit=bounded_limit):
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            public_meta = {
                key: meta[key]
                for key in (
                    "run_id", "candidate_sha", "base_sha", "target_sha", "target_publish_id",
                    "summary", "head", "base", "changed_paths", "preview", "head_sha",
                )
                if key in meta
            }
            if str(item.get("kind") or "") in {"merge", "rollback"} and preview_head and not public_meta.get("head_sha"):
                public_meta["head_sha"] = preview_head
            if callable(deployment_for_draft):
                receipt = deployment_for_draft(int(item["id"]))
                if receipt:
                    public_meta["deployment"] = {
                        key: receipt[key] for key in ("id", "status", "commit", "phase", "live", "verified_commit", "created_at", "updated_at")
                        if key in receipt
                    }
                    if receipt.get("status") == "failed":
                        public_meta["deployment"]["error"] = "Publication could not be verified. The candidate preview is retained."
            drafts.append({
                "id": int(item["id"]),
                "title": str(item.get("title") or "Untitled draft"),
                "kind": str(item.get("kind") or "edit"),
                "status": str(item.get("status") or "unknown"),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "meta": public_meta,
            })

        pending_owner_updates = [
            item for item in drafts
            if item.get("status") in {"pending", "publishing", "publish_failed"}
            and item.get("kind") in {"design", "merge", "rollback"}
        ]
        current_update = dict(pending_owner_updates[0]) if pending_owner_updates else None
        if current_update is not None:
            current_update["action_surface"] = "review"
            current_update["pending_count"] = len(pending_owner_updates)

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

        worktree = self._public_worktree(tenant, self.config)
        source_preview = self._public_source_preview(tenant)

        return {
            "tenant": tenant_id,
            "conversations": conversations,
            "design_runs": design_runs,
            "drafts": drafts,
            "current_update": current_update,
            "publishes": publishes,
            "actions": memory.recent_actions(limit=bounded_limit),
            "worktree": worktree,
            "source_preview": source_preview,
        }

    @staticmethod
    def _current_pending_owner_update(memory: Memory) -> dict[str, Any] | None:
        """Return the one owner decision surfaced by the Review screen.

        Older pending rows remain in the durable record for auditability, but
        approval must not be able to act on an obsolete row after a newer
        website update has replaced it.
        """
        candidates = [
            item for item in memory.list_drafts(status="pending", limit=500)
            if item.get("kind") in {"design", "merge", "rollback"}
        ]
        return candidates[0] if candidates else None

    @staticmethod
    def _public_worktree(tenant: Tenant | None, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Expose only the owner-useful local-change summary, never host paths."""
        try:
            from ..hands.opencode_runner import worktree_status

            raw_config = dict(tenant.config if tenant is not None else (config or {}))
            state = worktree_status(raw_config)
        except Exception as exc:  # noqa: BLE001 — history must remain readable
            return {"available": False, "dirty": False, "files": [], "file_count": 0, "error": str(exc)[:300]}
        return {
            "available": bool(state.get("available")),
            "dirty": bool(state.get("dirty")),
            "files": [
                {
                    "status": str(item.get("status") or ""),
                    "path": str(item.get("path") or ""),
                }
                for item in (state.get("files") or [])
                if isinstance(item, Mapping)
            ][:100],
            "file_count": int(state.get("file_count") or 0),
            "error": str(state.get("error") or "")[:300],
        }

    def _public_source_preview(self, tenant: Tenant | None) -> dict[str, Any]:
        """Return the latest source-preview job without command output or paths."""
        deployer = None
        if tenant is not None:
            deployer = tenant.context.get("source_deployment")
        elif self.source_deployment is not None:
            deployer = self.source_deployment
        if deployer is None:
            return {}
        try:
            latest = getattr(deployer, "latest_preview", deployer.latest)()
        except Exception as exc:  # noqa: BLE001 — history must remain readable
            return {"status": "failed", "error": str(exc)[:300]}
        if not isinstance(latest, Mapping) or not latest:
            return {}
        return {
            key: latest.get(key)
            for key in (
                "id", "status", "mode", "branch", "commit", "created_at", "updated_at", "ok",
                "runtime_path", "deployment_mode", "preview_url",
                "live", "verified_commit", "revision_verification",
            )
            if key in latest
        } | ({"error": "The latest preview check could not be completed."} if latest.get("status") == "failed" else {})

    def worktree(self, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Return the tenant's local source-change summary."""
        self._scope(tenant)
        return {"worktree": self._public_worktree(tenant, self.config)}

    def discard_worktree(self, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Discard only uncommitted local clone files for this tenant."""
        memory, _llm, _tenant_id = self._scope(tenant)
        config = tenant.config if tenant is not None else self.config
        if memory.list_active_chat_jobs(limit=1):
            raise BridgeError("cannot discard local work while Ada is working")
        from ..hands.opencode_runner import RunnerError, discard_worktree

        try:
            state = discard_worktree(dict(config))
        except RunnerError as exc:
            raise BridgeError(str(exc)[:500]) from exc
        memory.record_action("worktree", "discarded uncommitted local site work")
        return {"ok": True, "worktree": self._public_worktree(tenant, config)}

    def design_runs(
        self,
        *,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """List reviewable design runs without exposing mutable context snapshots."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise BridgeError("tenant design service is not enabled")
        bounded_limit = max(1, min(int(limit), 100))
        service = tenant.context["design_service"]
        return {"runs": [self._public_design_run(item) for item in service.list_runs(status=status, mode=mode, limit=bounded_limit)]}

    def design_run(self, run_id: str, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Return one design run and its quality evidence for owner review."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise BridgeError("tenant design service is not enabled")
        try:
            run = tenant.context["design_service"].get_run(str(run_id))
        except Exception as exc:  # noqa: BLE001 — normalize service-specific errors
            raise BridgeError(str(exc)[:500]) from exc
        return {"run": self._public_design_run(run, include_evidence=True)}

    def retry_design_run(
        self,
        run_id: str,
        body: Mapping[str, Any] | None = None,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Regenerate a failed native candidate from the same confirmed intake.

        A failed provider/build turn must not be repaired by mutating its
        immutable run. Instead, reserve a fresh intake build with the same
        confirmed revision and preserve the approved direction binding.
        """
        memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None:
            raise BridgeError("tenant-scoped design retry is unavailable")
        safe_run_id = str(run_id or "").strip()
        source_run = memory.get_design_run(safe_run_id)
        if source_run is None:
            raise BridgeError("no such design run")
        if str(source_run.get("status") or "") not in {"failed", "incomplete", "interrupted"}:
            raise BridgeError("only failed design runs can be retried")
        if source_run.get("candidate_sha"):
            raise BridgeError("a retained candidate must be revalidated or repaired, not retried")

        intake_service = tenant.context.get("design_intake_service")
        coordinator = tenant.context.get("intake_coordinator")
        if intake_service is None or coordinator is None:
            raise BridgeError("the full design build service is unavailable")
        session_id = str(source_run.get("intake_session_id") or "").strip()
        if not session_id:
            raise BridgeError("failed design run is not bound to an intake session")

        request_body = dict(body or {})
        intake_status = coordinator.status(source_run.get("conversation_id"))
        confirmed_revision = request_body.get("confirmed_revision")
        if confirmed_revision is None:
            confirmed_revision = (
                intake_status.get("confirmed_revision")
                or intake_status.get("confirmed_revision_id")
                or source_run.get("intake_revision_id")
            )
        try:
            confirmed_revision = int(confirmed_revision)
        except (TypeError, ValueError) as exc:
            raise BridgeError("confirmed_revision is invalid") from exc
        try:
            intake_service.confirmed_intake(session_id, revision=confirmed_revision)
        except Exception as exc:  # noqa: BLE001 - keep the retry boundary bounded
            raise BridgeError(str(exc)[:500]) from exc

        snapshot = source_run.get("context_snapshot")
        snapshot = snapshot if isinstance(snapshot, Mapping) else {}
        context_extra = {
            "operation": "design_retry",
            "page": str(request_body.get("page") or snapshot.get("page") or "index.html"),
            "retry_source_run_id": safe_run_id,
            "approved_direction_hash": str(snapshot.get("approved_direction_hash") or ""),
            "direction_artifact_id": snapshot.get("direction_artifact_id"),
        }
        retry_key = str(request_body.get("idempotency_key") or f"design-retry:{safe_run_id}").strip()
        owner_request = str(
            request_body.get("owner_request")
            or source_run.get("owner_request")
            or "Start the homepage design from the approved direction."
        ).strip()
        try:
            build = intake_service.build(
                session_id,
                confirmed_revision=confirmed_revision,
                owner_request=owner_request,
                idempotency_key=retry_key,
                force_new=True,
                context_extra=context_extra,
            )
        except Exception as exc:  # noqa: BLE001 - normalize the bridge boundary
            raise BridgeError(str(exc)[:500]) from exc
        retry_run = build.get("run") if isinstance(build, Mapping) else None
        if not isinstance(retry_run, Mapping):
            raise BridgeError("design retry did not return a run")
        return {
            "source_run_id": safe_run_id,
            "idempotency_key": str(build.get("idempotency_key") or retry_key),
            "recovered": bool(build.get("recovered")),
            "run": self._public_design_run(retry_run),
        }

    def create_design_review(self, run_id: str, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Link a passed candidate to the owner approval lane."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("design_service") is None:
            raise BridgeError("tenant design service is not enabled")
        try:
            run = tenant.context["design_service"].create_review_draft(str(run_id))
        except Exception as exc:  # noqa: BLE001 — normalize service-specific errors
            raise BridgeError(str(exc)[:500]) from exc
        return {"run": self._public_design_run(run, include_evidence=True)}

    def seo_insights(self, *, limit: int = 12, tenant: Tenant | None = None) -> dict[str, Any]:
        """Owner-facing SEO synthesis, newest first, scoped to one tenant."""
        memory, _llm, tenant_id = self._scope(tenant)
        bounded = max(1, min(int(limit), 50))
        return {
            "tenant": tenant_id,
            "latest": memory.latest_seo_insight(),
            "insights": memory.list_seo_insights(limit=bounded),
        }

    def approve_draft(self, draft_id: Any, *, tenant: Tenant | None = None) -> dict[str, Any]:
        # A retried HTTP request must observe the first approval's durable
        # receipt rather than perform the same merge twice.
        with self._approval_lock:
            return self._approve_draft(draft_id, tenant=tenant)

    def _approve_draft(self, draft_id: Any, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Publish exactly one pending owner change through its existing lane.

        Design candidates use the immutable design service. Legacy/source merge
        and rollback drafts use the configured preview merge adapter. Keeping
        both paths here is important: the workspace API is the tenant-scoped
        approval boundary, while the old standalone admin server is not in the
        request path for Payload's workspace.
        """
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            normalized_id = int(draft_id)
        except (TypeError, ValueError) as exc:
            raise BridgeError("draft_id must be an integer") from exc

        draft = next((item for item in memory.list_drafts(limit=500) if int(item["id"]) == normalized_id), None)
        # The immutable design service owns its draft/run lifecycle. Keep the
        # legacy service contract usable for callers that pass a run-backed
        # draft id before the memory row has been materialized.
        if draft is None and tenant is not None and tenant.context.get("design_service") is not None:
            draft = {"id": normalized_id, "title": f"Design candidate {normalized_id}", "kind": "design", "status": "pending", "meta": {}}
        if draft is None:
            raise BridgeError("no such draft")
        if draft.get("status") != "pending":
            deployer = tenant.context.get("source_deployment") if tenant else self.source_deployment
            lookup = getattr(deployer, "for_draft", None)
            receipt = lookup(normalized_id) if callable(lookup) else {}
            if receipt and draft.get("status") in {"publishing", "publish_failed", "live"}:
                return {"ok": receipt.get("status") != "failed", "draft_id": normalized_id,
                        "status": draft["status"], "deployment": receipt, "idempotent": True}
            raise BridgeError(f"draft already {draft.get('status')}")

        kind = str(draft.get("kind") or "edit")
        if kind in {"design", "merge", "rollback"}:
            current = self._current_pending_owner_update(memory)
            if current is not None and int(current.get("id") or 0) != normalized_id:
                raise BridgeError("only the current website update can be reviewed")
        meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
        published: Mapping[str, Any] | None = None
        production_deployment: Mapping[str, Any] | None = None
        result: dict[str, Any] = {"ok": True, "draft_id": normalized_id}

        if kind == "design":
            if tenant is None or tenant.context.get("design_service") is None:
                raise BridgeError("tenant design service is not enabled")
            adapter = tenant.context.get("design_adapter")
            from ..hands.base import DesignMergeAdapter

            if not isinstance(adapter, DesignMergeAdapter):
                raise BridgeError("tenant design approval adapter is unavailable")
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
                raise BridgeError(str(exc)[:500]) from exc
            candidate = result.get("published") if isinstance(result, dict) else {}
            published = candidate if isinstance(candidate, Mapping) else None
            version_type = "design"
            summary = f"design: {normalized_id}"
            commit_message = f"Approve design candidate: {(result.get('run') or {}).get('run_id') or normalized_id}"
            deployer = tenant.context.get("source_deployment") if tenant is not None else self.source_deployment
            start = getattr(deployer, "start", None)
            if callable(start):
                commit_sha = str((published or {}).get("commit_sha") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
                    memory.update_draft_status(normalized_id, "publish_failed")
                    raise BridgeError("design approved but the production commit could not be identified")
                try:
                    memory.update_draft_status(normalized_id, "publishing")
                    production_deployment = start({
                        "branch": str(((tenant.config if tenant is not None else self.config).get("site") or {}).get("branch") or "main"),
                        "commit": commit_sha,
                        "mode": "production",
                        "draft_id": normalized_id,
                        "publish": {
                            "summary": summary,
                            "path": str((published or {}).get("path") or "site"),
                            "parent_sha": str((published or {}).get("parent_sha") or ""),
                            "version_type": version_type,
                            "commit_message": commit_message,
                        },
                    }, allow_production=True)
                except Exception as exc:  # noqa: BLE001 - keep the approval boundary explicit
                    memory.update_draft_status(normalized_id, "publish_failed")
                    memory.record_action("publish_failed", f"#{normalized_id}: {str(exc)[:400]}")
                    raise BridgeError(f"design approved but live deployment could not be queued: {str(exc)[:400]}") from exc
                result["status"] = {"deployed": "live", "failed": "publish_failed"}.get(production_deployment.get("status"), "publishing")
                result["deployment"] = dict(production_deployment)
        elif kind in {"merge", "rollback"}:
            adapter = self._merge_adapter(tenant)
            merge = getattr(adapter, "merge_preview", None)
            if not callable(merge):
                raise BridgeError("the configured site cannot publish preview changes")
            config = tenant.config if tenant is not None else self.config
            if kind == "merge" and tenant is not None and tenant.context.get("source_deployment") is not None:
                self._assert_reviewable_merge_candidate(draft, adapter, tenant)
            try:
                candidate = merge(
                    config,
                    f"Publish website update: {str(draft.get('title') or normalized_id)[:160]}",
                )
            except Exception as exc:  # noqa: BLE001 — approval must return a bounded error
                raise BridgeError(str(exc)[:500]) from exc
            if not isinstance(candidate, Mapping) or not candidate.get("merged"):
                reason = candidate.get("reason") if isinstance(candidate, Mapping) else "merge was rejected"
                raise BridgeError(str(reason)[:500])
            published = candidate
            version_type = "rollback" if kind == "rollback" else "merge"
            summary = str(draft.get("title") or f"{kind}: {normalized_id}")
            commit_message = str(candidate.get("commit_message") or "")
            deployer = tenant.context.get("source_deployment") if tenant is not None else self.source_deployment
            start = getattr(deployer, "start", None)
            if callable(start):
                commit_sha = str(candidate.get("commit_sha") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
                    memory.update_draft_status(normalized_id, "publish_failed")
                    raise BridgeError("preview merged but the production commit could not be identified")
                try:
                    memory.update_draft_status(normalized_id, "publishing")
                    production_deployment = start({
                        "branch": str(((config.get("site") if isinstance(config, Mapping) else {}) or {}).get("branch") or "main"),
                        "commit": commit_sha,
                        "mode": "production",
                        "draft_id": normalized_id,
                        "publish": {
                            "summary": summary,
                            "path": str(candidate.get("path") or "site"),
                            "parent_sha": str(candidate.get("parent_sha") or ""),
                            "version_type": version_type,
                            "commit_message": commit_message,
                        },
                    }, allow_production=True)
                except Exception as exc:  # noqa: BLE001 — the merge already happened; retain an explicit failed state
                    memory.update_draft_status(normalized_id, "publish_failed")
                    memory.record_action("publish_failed", f"#{normalized_id}: {str(exc)[:400]}")
                    raise BridgeError(f"preview merged but live deployment could not be queued: {str(exc)[:400]}") from exc
                result["status"] = {"deployed": "live", "failed": "publish_failed"}.get(production_deployment.get("status"), "publishing")
                result["deployment"] = dict(production_deployment)
            else:
                memory.update_draft_status(normalized_id, "approved")
            if kind == "rollback":
                target_publish_id = meta.get("target_publish_id")
                try:
                    if target_publish_id is not None:
                        memory.mark_publishes_reverted_after(int(target_publish_id))
                except (TypeError, ValueError):
                    pass
        elif kind == "edit":
            if tenant is not None and tenant.context.get("source_deployment") is not None:
                raise BridgeError(
                    "this is a legacy edit draft without a verified preview; ask Ada to create a fresh implementation preview"
                )
            adapter = self._merge_adapter(tenant)
            from ..brain import editor as brain_editor

            try:
                results = brain_editor._apply_ops(adapter, _normalize_edit_ops(meta))
            except Exception as exc:  # noqa: BLE001 — keep provider errors bounded
                raise BridgeError(str(exc)[:500]) from exc
            published = results[0] if results and isinstance(results[0], Mapping) else None
            version_type = "edit"
            summary = str(draft.get("title") or f"edit: {normalized_id}")
            commit_message = str((published or {}).get("commit_message") or "")
            memory.update_draft_status(normalized_id, "approved")
        else:
            raise BridgeError(f"draft type '{kind}' cannot be published from the workspace")

        if published and not production_deployment and (published.get("committed") or published.get("commit_sha")):
            memory.log_publish(
                summary=summary,
                path=str(published.get("path") or "site"),
                commit_sha=str(published.get("commit_sha") or ""),
                draft_id=normalized_id,
                parent_sha=str(published.get("parent_sha") or ""),
                actor="owner",
                version_type=version_type,
                commit_message=commit_message,
            )
        memory.record_action(
            "publish_queued" if production_deployment else "approve",
            f"#{normalized_id} [{kind}] {draft.get('title') or ''}".strip(),
        )
        result.setdefault("published", dict(published) if published else None)
        return result

    def discard_draft(self, draft_id: Any, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Cancel one pending draft and clean its review branch when needed."""
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            normalized_id = int(draft_id)
        except (TypeError, ValueError) as exc:
            raise BridgeError("draft_id must be an integer") from exc
        draft = next((item for item in memory.list_drafts(limit=500) if int(item["id"]) == normalized_id), None)
        if draft is None:
            raise BridgeError("no such draft")
        if draft.get("status") != "pending":
            raise BridgeError(f"draft already {draft.get('status')}")

        kind = str(draft.get("kind") or "")
        if kind in {"design", "merge", "rollback"}:
            current = self._current_pending_owner_update(memory)
            if current is not None and int(current.get("id") or 0) != normalized_id:
                raise BridgeError("only the current website update can be reviewed")
        if kind in {"merge", "rollback"}:
            other_pending = [
                item for item in memory.list_drafts(status="pending", limit=500)
                if int(item["id"]) != normalized_id and item.get("kind") in {"merge", "rollback"}
            ]
            if not other_pending:
                adapter = self._merge_adapter(tenant)
                reset = getattr(adapter, "reset_preview_branch", None)
                preview_branch = str(
                    ((tenant.config if tenant is not None else self.config).get("site") or {}).get(
                        "preview_branch", "preview"
                    )
                ).strip()
                if callable(reset) and preview_branch:
                    try:
                        reset(preview_branch)
                    except Exception as exc:  # noqa: BLE001 — preserve the pending draft if cleanup failed
                        raise BridgeError(str(exc)[:500]) from exc
                try:
                    from ..hands import tweakmap

                    tweakmap.drop_builder_map(memory)
                except Exception:
                    pass
        elif kind == "design" and tenant is not None:
            run_id = str((draft.get("meta") or {}).get("run_id") or "")
            cancel = getattr(tenant.context.get("design_service"), "cancel", None)
            if run_id and callable(cancel):
                try:
                    cancel(run_id)
                except Exception as exc:  # noqa: BLE001 — draft cancellation remains bounded
                    raise BridgeError(str(exc)[:500]) from exc

        if not memory.update_draft_status(normalized_id, "discarded"):
            raise BridgeError("no such draft")
        memory.record_action("discard", f"#{normalized_id}")
        return {"ok": True, "draft_id": normalized_id, "status": "discarded"}

    def restore_version(self, version_id: Any, *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Create an approval-gated rollback draft; never mutate production directly."""
        memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None:
            raise BridgeError("tenant is required")
        try:
            normalized_id = int(version_id)
        except (TypeError, ValueError) as exc:
            raise BridgeError("version_id must be an integer") from exc
        version = next((item for item in memory.list_publishes(limit=100) if int(item["id"]) == normalized_id), None)
        if not version or not version.get("commit_sha"):
            raise BridgeError("version not found")
        if version.get("reverted_ts"):
            raise BridgeError("version has already been rolled back")
        for pending in memory.list_drafts(status="pending", limit=500):
            if pending.get("kind") in {"merge", "rollback"}:
                memory.update_draft_status(int(pending["id"]), "discarded")
        adapter = self._merge_adapter(tenant)
        restore = getattr(adapter, "restore_snapshot", None)
        preview_branch = str((tenant.config.get("site") or {}).get("preview_branch") or "preview").strip()
        if not callable(restore) or not preview_branch:
            raise BridgeError("version restore is not configured")
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
            raise BridgeError(str(exc)[:500]) from exc
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

    def analyze_media(self, body: Mapping[str, Any], *, tenant: Tenant | None = None) -> dict[str, Any]:
        """Analyze one Payload asset and write only the resulting metadata draft."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None:
            raise BridgeError("tenant is required")
        payload = tenant.context.get("payload_gateway")
        analyzer = tenant.context.get("media_analyzer")
        if payload is None or analyzer is None:
            raise BridgeError("tenant media analysis is not configured")
        media_id = str(body.get("media_id") or body.get("id") or "").strip()
        if not media_id:
            raise BridgeError("media_id is required")
        focus = str(body.get("focus") or "").strip()
        if len(focus) > 500:
            raise BridgeError("focus is too long")
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
                raise BridgeError("Payload media does not expose a readable image URL")
            analysis_data = analyzer.analyze_images(
                [image_url],
                "Analyze this owner-provided image for a design and content library. "
                "Return only grounded observations: subject, composition, alt text, tags, dominant colors, "
                "suggested uses, quality notes, and visible text. Do not invent business claims or provenance."
                + (f" Owner focus: {focus}" if focus else ""),
            )
            analysis = analysis_data.to_dict() if hasattr(analysis_data, "to_dict") else dict(analysis_data)
            updated = payload.update_media(media_id, {
                "alt": analysis.get("alt_text") or media.get("alt") or media.get("filename") or "Site image",
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
        except BridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 — keep provider failures bounded
            try:
                payload.update_media(media_id, {
                    "analysisStatus": "failed",
                    "analysisError": str(exc)[:500],
                })
            except Exception:
                pass
            raise BridgeError(str(exc)[:500]) from exc

    def media(self, *, limit: int = 50, tenant: Tenant | None = None) -> dict[str, Any]:
        """List the tenant's Payload media records for the owner workspace."""
        _memory, _llm, _tenant_id = self._scope(tenant)
        if tenant is None or tenant.context.get("payload_gateway") is None:
            raise BridgeError("Payload media is not configured")
        bounded_limit = max(1, min(int(limit), 100))
        try:
            return {"media": tenant.context["payload_gateway"].list_media(draft=True, limit=bounded_limit)}
        except Exception as exc:  # noqa: BLE001 — normalize gateway failures
            raise BridgeError(str(exc)[:500]) from exc

    def _source_editor(self, tenant: Tenant | None) -> Any:
        if self.registry is not None:
            if tenant is None or tenant.tenant_id not in self.registry.tenants:
                raise BridgeError("tenant is not authorized")
            editor = tenant.context.get("source_editor")
            if editor is not None:
                return editor
            config = tenant.config
            env = tenant.context.get("env") or {}
        else:
            editor = self.source_editor
            if editor is not None:
                return editor
            config = self.config
            env = self.env
        if not config:
            raise BridgeError("tenant source editing is not configured")
        from .source_editor import SourceEditorService

        return SourceEditorService(config, env)

    def _source_deployer(self, tenant: Tenant | None) -> Any:
        if self.registry is not None:
            if tenant is None or tenant.tenant_id not in self.registry.tenants:
                raise BridgeError("tenant is not authorized")
            deployer = tenant.context.get("source_deployment")
            if deployer is not None:
                return deployer
            config = tenant.config
            env = tenant.context.get("env") or {}
        else:
            deployer = self.source_deployment
            if deployer is not None:
                return deployer
            config = self.config
            env = self.env
        if not config:
            raise BridgeError("tenant source deployment is not configured")
        from .source_deployment import SourceDeploymentService

        return SourceDeploymentService(config, env)

    def source_inventory(
        self,
        body: Mapping[str, Any] | None = None,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Inventory editable source fields for the tenant's selected branch."""
        if body is not None and not isinstance(body, Mapping):
            raise BridgeError("source inventory body must be an object")
        from .source_editor import SourceEditorError

        try:
            return self._source_editor(tenant).inventory(body or {})
        except SourceEditorError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_edit(
        self,
        body: Mapping[str, Any],
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Apply one hash/range-checked source edit to the preview branch."""
        if not isinstance(body, Mapping):
            raise BridgeError("source edit body must be an object")
        from .source_editor import SourceConflictError, SourceEditorError

        try:
            return self._source_editor(tenant).edit(body)
        except SourceConflictError as exc:
            raise SourceConflict(str(exc)[:500]) from exc
        except SourceEditorError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_preview_start(
        self,
        body: Mapping[str, Any] | None = None,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Validate a GitHub draft asynchronously and upload a version preview."""
        if body is not None and not isinstance(body, Mapping):
            raise BridgeError("source preview body must be an object")
        from .source_deployment import SourceDeploymentError

        try:
            return self._source_deployer(tenant).start(body or {})
        except SourceDeploymentError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_preview_status(
        self,
        job_id: str,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Return one source preview build without exposing command secrets."""
        from .source_deployment import SourceDeploymentError

        try:
            return self._source_deployer(tenant).status(job_id)
        except SourceDeploymentError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_preview_runtime(
        self,
        job_id: str,
        path: str,
        query: str = "",
        headers: Mapping[str, str] | None = None,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Proxy an authenticated browser request to one compiled source preview."""
        from .source_deployment import SourceDeploymentError

        try:
            return self._source_deployer(tenant).runtime(job_id, path, query, headers)
        except SourceDeploymentError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_preview_latest(
        self,
        branch: str | None = None,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        from .source_deployment import SourceDeploymentError

        try:
            deployer = self._source_deployer(tenant)
            return getattr(deployer, "latest_preview", deployer.latest)(branch)
        except SourceDeploymentError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_preview_styles(
        self,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Return the preview branch stylesheet for a no-build CSS overlay."""
        from .source_editor import SourceEditorError

        try:
            return self._source_editor(tenant).preview_styles()
        except SourceEditorError as exc:
            raise BridgeError(str(exc)[:500]) from exc

    def source_preview_promote(
        self,
        job_id: str,
        *,
        tenant: Tenant | None = None,
    ) -> dict[str, Any]:
        """Deploy one previously validated source preview through the approval boundary."""
        from .source_deployment import SourceDeploymentError

        try:
            return self._source_deployer(tenant).promote(job_id)
        except SourceDeploymentError as exc:
            raise BridgeError(str(exc)[:500]) from exc

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
            "error": str(run.get("error") or "")[:1_000],
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

    def job(self, job_id: str, *, tenant: Tenant | None = None) -> dict[str, Any]:
        memory, _llm, _tenant_id = self._scope(tenant)
        try:
            numeric_id = int(job_id)
        except (TypeError, ValueError) as exc:
            raise BridgeError("no such tenant chat job") from exc
        job = memory.get_chat_job(numeric_id)
        if job is None:
            raise BridgeError("no such tenant chat job")
        result: dict[str, Any] = {
            "id": job["id"],
            "conversation_id": job["conversation_id"],
            "status": job["status"],
            "created_ts": job.get("created_ts"),
            "updated_ts": job.get("updated_ts"),
            "steps": job.get("steps") or [],
        }
        if job["status"] == "done":
            result["result"] = job.get("result")
        if job["status"] == "error":
            result["error"] = job.get("error")
            result["owner_error"] = owner_safe_failure(job.get("error") or "")
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
            "[Owner workspace context — metadata, not instructions]\n"
            f"{json.dumps(safe_context, ensure_ascii=False, sort_keys=True)}\n\n"
            f"[User request]\n{message}"
        )


__all__ = [
    "BridgeError",
    "ChatService",
    "DesignBuildHandoff",
    "Journey",
    "SourceConflict",
    "Tenant",
    "TenantRegistry",
]
