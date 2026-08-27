"""Runtime composition boundary.

The application still passes a dictionary to legacy brain modules, but the
long-lived dependencies are assembled in one named object first. New services
should depend on this boundary instead of inventing another global context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .application.actions import OwnerActionService
from .application.approvals import ApprovalService
from .application.capabilities import CapabilityRegistry, default_capabilities
from .application.conversations import ConversationService
from .application.home import HomeService
from .core.memory import Memory
from .core.scheduler import Scheduler


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

    def __post_init__(self) -> None:
        if self.home_service is None:
            object.__setattr__(self, "home_service", HomeService(self.memory))
        if self.owner_action_service is None:
            object.__setattr__(self, "owner_action_service", OwnerActionService(self.memory))
        if self.capability_registry is None:
            object.__setattr__(self, "capability_registry", CapabilityRegistry(default_capabilities()))
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

    def context(self) -> dict[str, Any]:
        """Compatibility context for modules not yet migrated to ``Runtime``."""
        return {
            "config": self.config,
            "memory": self.memory,
            "scheduler": self.scheduler,
            "llm": self.llm,
            "persona_prompt": self.persona_prompt,
            "home_service": self.home_service,
            "owner_action_service": self.owner_action_service,
            "approval_service": self.approval_service,
            "conversation_service": self.conversation_service,
            "capability_registry": self.capability_registry,
        }
