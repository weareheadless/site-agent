"""Runtime composition boundary.

The application still passes a dictionary to legacy brain modules, but the
long-lived dependencies are assembled in one named object first. New services
should depend on this boundary instead of inventing another global context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core.memory import Memory
from .core.scheduler import Scheduler


@dataclass(frozen=True)
class Runtime:
    config: dict[str, Any]
    memory: Memory
    scheduler: Scheduler
    llm: Any
    persona_prompt: str

    def context(self) -> dict[str, Any]:
        """Compatibility context for modules not yet migrated to ``Runtime``."""
        return {
            "config": self.config,
            "memory": self.memory,
            "scheduler": self.scheduler,
            "llm": self.llm,
            "persona_prompt": self.persona_prompt,
        }
