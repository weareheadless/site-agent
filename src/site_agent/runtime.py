"""Runtime composition boundary.

The application still passes a dictionary to legacy brain modules, but the
long-lived dependencies are assembled in one named object first. New services
should depend on this boundary instead of inventing another global context.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .application.actions import OwnerActionService
from .application.approvals import ApprovalService
from .application.capabilities import CapabilityRegistry, default_capabilities
from .application.conversations import ConversationService
from .application.customer_context import CustomerContextService
from .application.crawlseo import CrawlSEOApplicationService
from .application.designs import DesignService
from .application.home import HomeService
from .application.social_posts import SocialPostService
from .core.memory import Memory
from .core.scheduler import Scheduler
from .hands.cicero import CiceroClient, configured as cicero_configured
from .hands.crawlseo import CrawlSEOClient, CrawlSEOConfigurationError, configured as crawlseo_configured
from .hands.site_build import SiteOutputArtifactStore


@dataclass(frozen=True)
class Runtime:
    config: dict[str, Any]
    memory: Memory
    scheduler: Scheduler
    llm: Any
    persona_prompt: str
    home_service: HomeService | None = None
    owner_action_service: OwnerActionService | None = None
    approval_service: ApprovalService | None = None
    conversation_service: ConversationService | None = None
    capability_registry: CapabilityRegistry | None = None
    cicero_client: CiceroClient | None = None
    social_post_service: SocialPostService | None = None
    crawlseo_client: CrawlSEOClient | None = None
    crawlseo_service: CrawlSEOApplicationService | None = None
    media_store: Any | None = None
    media_service: Any | None = None
    media_analyzer: Any | None = None
    business_knowledge_service: Any | None = None
    design_service: DesignService | None = None
    customer_context_service: CustomerContextService | None = None
    env: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.home_service is None:
            object.__setattr__(self, "home_service", HomeService(self.memory))
        if self.owner_action_service is None:
            object.__setattr__(self, "owner_action_service", OwnerActionService(self.memory))
        if self.crawlseo_client is None and self.crawlseo_service is None and crawlseo_configured(self.config):
            try:
                object.__setattr__(self, "crawlseo_client", CrawlSEOClient.from_config(self.config, self.env))
            except CrawlSEOConfigurationError:
                provisioning = (self.config.get("seo") or {}).get("provisioning") or {}
                if not bool(isinstance(provisioning, dict) and provisioning.get("auto")):
                    raise
        if self.crawlseo_service is None and self.crawlseo_client is not None:
            object.__setattr__(self, "crawlseo_service", CrawlSEOApplicationService(self.crawlseo_client))
        if self.capability_registry is None:
            object.__setattr__(
                self,
                "capability_registry",
                CapabilityRegistry(
                    default_capabilities(
                        cicero_configured(self.config),
                        crawlseo_available=self.crawlseo_service is not None,
                        knowledge_available=bool(((self.config.get("site") or {}).get("media") or {}).get("enabled")),
                    )
                ),
            )
        if self.approval_service is None:
            object.__setattr__(
                self,
                "approval_service",
                ApprovalService(
                    self.memory,
                    actions=self.owner_action_service,
                    capabilities=self.capability_registry,
                ),
            )
        if self.conversation_service is None:
            object.__setattr__(self, "conversation_service", ConversationService(self.memory))
        if self.cicero_client is None:
            object.__setattr__(self, "cicero_client", CiceroClient.from_config(self.config))
        if self.social_post_service is None and self.cicero_client is not None:
            object.__setattr__(
                self,
                "social_post_service",
                SocialPostService(
                    self.memory,
                    self.cicero_client,
                    actions=self.owner_action_service,
                    approvals=self.approval_service,
                    capabilities=self.capability_registry,
                    poll_interval_seconds=float(
                        (((self.config.get("providers") or {}).get("cicero") or {}).get("poll_interval_seconds", 2))
                    ),
                    preparation_timeout_seconds=float(
                        (((self.config.get("providers") or {}).get("cicero") or {}).get("preparation_timeout_seconds", 600))
                    ),
                ),
            )
        media = ((self.config.get("site") or {}).get("media") or {})
        if media.get("enabled") and self.media_service is None:
            from .application.media import MediaService
            from .application.business_knowledge import BusinessKnowledgeService
            from .hands.r2_media import R2MediaStore
            from .core.vision import VisionClient
            from .config import resolve_secret
            store = R2MediaStore(str(media["account_id"]), str(media["bucket"]),
                                 resolve_secret(self.config, "r2_access_key_id"),
                                 resolve_secret(self.config, "r2_secret_access_key"))
            object.__setattr__(self, "media_store", store)
            object.__setattr__(self, "media_analyzer", VisionClient(self.config, memory=self.memory))
            object.__setattr__(self, "media_service", MediaService(self.memory, store, self.config))
            object.__setattr__(self, "business_knowledge_service",
                               BusinessKnowledgeService(self.memory, self.approval_service, self.owner_action_service))
        if self.design_service is None:
            object.__setattr__(
                self,
                "design_service",
                DesignService(
                    self.memory,
                    config=self.config,
                    media_service=self.media_service,
                    output_artifact_store=SiteOutputArtifactStore(
                        Path(str(self.config.get("data_dir") or ".")).expanduser().resolve()
                        / "design-output-artifacts"
                    ),
                ),
            )
        if self.customer_context_service is None:
            object.__setattr__(self, "customer_context_service", CustomerContextService(self.memory))

    def start(self) -> None:
        """Start optional long-lived provider runtimes for this process."""
        if self.crawlseo_client is not None:
            self.crawlseo_client.start()

    def close(self) -> None:
        """Stop optional provider runtimes deterministically."""
        if self.crawlseo_client is not None:
            self.crawlseo_client.close()

    def refresh_crawlseo(self, env: dict[str, str] | None = None) -> CrawlSEOApplicationService | None:
        """Attach a newly provisioned project without restarting the tenant.

        Automatic bootstrap may issue the project credential after this Runtime
        was constructed. Replacing the optional client here keeps recovery
        idempotent and makes the provider available to the next scheduler tick.
        """
        if env is not None:
            object.__setattr__(self, "env", dict(env))
        if self.crawlseo_client is not None:
            self.crawlseo_client.close()
        client = CrawlSEOClient.from_config(self.config, self.env)
        object.__setattr__(self, "crawlseo_client", client)
        service = CrawlSEOApplicationService(client) if client is not None else None
        object.__setattr__(self, "crawlseo_service", service)
        return service

    def context(self) -> dict[str, Any]:
        """Compatibility context for modules not yet migrated to ``Runtime``."""
        persona = self.persona_prompt
        if self.customer_context_service is not None and self.customer_context_service.current() is not None:
            from .brain.prompts import customer_context_prompt, inner_identity_prompt
            persona = inner_identity_prompt(self.config, self.memory) + "\n\n" + customer_context_prompt(
                self.customer_context_service.task_view("identity")
            )
        return {
            "config": self.config,
            "memory": self.memory,
            "scheduler": self.scheduler,
            "llm": self.llm,
            "persona_prompt": persona,
            "home_service": self.home_service,
            "owner_action_service": self.owner_action_service,
            "approval_service": self.approval_service,
            "conversation_service": self.conversation_service,
            "capability_registry": self.capability_registry,
            "cicero_client": self.cicero_client,
            "social_post_service": self.social_post_service,
            "crawlseo_client": self.crawlseo_client,
            "crawlseo_service": self.crawlseo_service,
            "media_store": self.media_store,
            "media_service": self.media_service,
            "media_analyzer": self.media_analyzer,
            "business_knowledge_service": self.business_knowledge_service,
            "design_service": self.design_service,
            "customer_context_service": self.customer_context_service,
            "runtime": self,
            "env": self.env,
        }
