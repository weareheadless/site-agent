"""Owner-confirmed business knowledge extracted from private media."""

from __future__ import annotations

import hashlib
from typing import Any

from ..core.contracts import (ActionPriority, ActionRequirement, Artifact, ArtifactKind,
                              EffectClass, OwnerAction, utc_now)
from ..core.media_contracts import KnowledgeStatus


class BusinessKnowledgeError(ValueError):
    pass


class BusinessKnowledgeService:
    def __init__(self, memory, approvals=None, actions=None):
        self.memory = memory
        self.approvals = approvals
        self.actions = actions

    def propose(self, asset, body: str) -> dict[str, Any]:
        body = str(body or "").strip()[:50_000]
        if not body:
            raise BusinessKnowledgeError("knowledge proposal is empty")
        row = self.memory.create_business_knowledge(asset.asset_id, body)
        digest = hashlib.sha256(f"{asset.asset_id}:{asset.analysis_version}:{body}".encode()).hexdigest()
        artifact = self.memory.create_artifact(Artifact(
            kind=ArtifactKind.BUSINESS_INFORMATION, title="Business information found in your Library",
            summary="Ada found information that may be useful in future owner work.",
            renderer="business_information", capability_id="knowledge.import", provider_id="site-agent",
            content_hash=f"sha256:{digest}",
            preview_data={"body": body, "asset_id": asset.asset_id, "media_kind": asset.media_kind.value,
                          "page_count": asset.page_count, "preview_url": f"/api/media/{asset.asset_id}/preview"},
        ))
        action = None
        if self.actions is not None:
            action = self.actions.create(OwnerAction(
                capability_id="knowledge.import", provider_id="site-agent",
                title="Review useful business information",
                summary="Ada found information from a Library file that may help with future work.",
                action_label="Review information", priority=ActionPriority.NORMAL,
                requirement=ActionRequirement.OWNER_DECISION, source_ref=f"knowledge:{row['id']}",
                dedupe_key=f"knowledge:{row['id']}", payload={"asset_id": asset.asset_id},
            ))
        approval = self.approvals.create(artifact, owner_action_label="Review information",
                                         effect_class=EffectClass.PROPOSAL,
                                         action_id=action.id if action else None)
        self.memory.update_business_knowledge(row["id"], artifact_id=artifact.artifact_id, approval_id=approval.approval_id)
        return self.memory.get_business_knowledge(row["id"])

    def confirm(self, approval_id: int, body: str | None = None) -> dict[str, Any]:
        approval = self.memory.get_approval_request(approval_id)
        if approval is None:
            raise BusinessKnowledgeError("no such knowledge review")
        row = next((r for r in self.memory.list_business_knowledge(limit=500) if r.get("approval_id") == approval_id), None)
        if row is None:
            raise BusinessKnowledgeError("knowledge review is unavailable")
        text = row["body"] if body is None else str(body).strip()[:50_000]
        if not text:
            raise BusinessKnowledgeError("knowledge text cannot be empty")
        if text == row["body"]:
            self.approvals.decide(approval_id, True)
            self.memory.update_business_knowledge(row["id"], status=KnowledgeStatus.APPROVED.value,
                                                  decided_ts=utc_now())
            result = self.memory.get_business_knowledge(row["id"])
        else:
            # Artifacts are immutable: edited confirmation becomes a new revision.
            self.memory.transition_approval_request(approval_id, "expired")
            replacement = self.propose(self.memory.get_media_asset(row["asset_id"]), text)
            replacement_approval = self.memory.get_approval_request(replacement["approval_id"])
            self.approvals.decide(replacement_approval.approval_id, True)
            result = self.memory.update_business_knowledge(replacement["id"], status=KnowledgeStatus.APPROVED.value,
                                                           decided_ts=utc_now())
        self.memory.update_media_asset(row["asset_id"], protected_ts=utc_now())
        return result

    def decline(self, approval_id: int) -> dict[str, Any]:
        row = next((r for r in self.memory.list_business_knowledge(limit=500) if r.get("approval_id") == approval_id), None)
        if row is None:
            raise BusinessKnowledgeError("knowledge review is unavailable")
        self.approvals.decide(approval_id, False)
        self.memory.update_business_knowledge(row["id"], status=KnowledgeStatus.DECLINED.value,
                                              decided_ts=utc_now())
        return self.memory.get_business_knowledge(row["id"])

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        return [{"knowledge_id": row["id"], "asset_id": row["asset_id"], "body": row["body"][:2_000],
                 "revision": row["revision"]} for row in self.memory.search_business_knowledge(query, limit)]


__all__ = ["BusinessKnowledgeError", "BusinessKnowledgeService"]
