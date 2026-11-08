"""Application service for assembling and serving accepted customer context."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.customer_context_contracts import CustomerContextSnapshot
from ..core.memory import Memory


class CustomerContextService:
    """Keep the complete accepted context available behind one service boundary."""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory

    def current(self) -> CustomerContextSnapshot | None:
        rows = self.memory.list_customer_contexts(limit=1, accepted_only=True)
        if not rows:
            return None
        item = rows[0]
        return item.get("context") if isinstance(item, Mapping) else None

    def accepted(self) -> CustomerContextSnapshot | None:
        return self.current()

    def get(self, context_id: str, revision: int | None = None) -> CustomerContextSnapshot | None:
        record = self.memory.get_customer_context(context_id, revision)
        return record.get("context") if record else None

    def task_view(self, task: str = "full", *, limits: "ContextLimits | None" = None) -> dict[str, Any]:
        """Return a task-shaped view without making a new source of truth."""
        context = self.current()
        if context is None:
            return {}
        full = context.to_dict()
        purpose = str(task or "full").strip().lower()
        limits = limits or ContextLimits()
        if purpose == "identity":
            keys = ("business", "audience", "conversion", "brand", "site", "relationship", "constraints")
        elif purpose == "design":
            keys = ("business", "audience", "conversion", "brand", "site", "constraints", "assets", "creative_identity", "design", "research", "research_manifest")
        elif purpose == "editorial":
            keys = (
                "business", "audience", "brand", "conversion", "constraints", "knowledge", "research",
                "research_manifest", "contradictions", "open_questions",
            )
        elif purpose in {"article", "article_research"}:
            keys = (
                "business", "audience", "brand", "conversion", "site", "constraints", "knowledge",
                "research", "research_manifest", "contradictions", "open_questions",
            )
        elif purpose == "research":
            keys = ("business", "audience", "research", "research_manifest", "knowledge", "contradictions", "open_questions")
        elif purpose == "strategy":
            keys = ("business", "audience", "conversion", "site", "constraints", "research", "knowledge")
        elif purpose in {"relationship", "owner_relationship"}:
            keys = ("relationship", "open_questions", "provenance")
        else:
            keys = tuple(full)
        result = {key: copy.deepcopy(full[key]) for key in keys}
        for key in ("assets", "knowledge", "open_questions", "contradictions"):
            if isinstance(result.get(key), list):
                result[key] = result[key][:limits.max_items]
        result["context"] = {
            "context_id": context.context_id,
            "revision": context.revision,
            "content_hash": context.computed_hash,
            "source_record_hashes": {
                "intake": context.source_intake_hash,
                "genesis": context.source_genesis_hash,
                "design_run": context.source_design_run_hash,
            },
            "truncation": {"max_items": limits.max_items},
        }
        return result

    def view(self, purpose: str = "full") -> dict[str, Any]:
        return self.task_view(purpose)


@dataclass(frozen=True)
class ContextLimits:
    max_items: int = 100
