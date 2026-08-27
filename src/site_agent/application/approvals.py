"""Approval workflow for immutable prepared artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from ..core.contracts import (
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    EffectClass,
    ProviderReceipt,
    ReceiptStatus,
    safe_provider_message,
)


class ApprovalServiceError(ValueError):
    pass


class StaleApproval(ApprovalServiceError):
    pass


class EffectProvider(Protocol):
    def __call__(self, artifact: Artifact, approval: ApprovalRequest, idempotency_key: str) -> ProviderReceipt:
        ...


class SiteDraftApprovalAdapter:
    """Compatibility seam for the existing website-draft approval endpoints."""

    def __init__(self, approve: Callable[[int], Any], decline: Callable[[int, str], Any]) -> None:
        self._approve = approve
        self._decline = decline

    def approve(self, draft_id: int) -> Any:
        return self._approve(draft_id)

    def decline(self, draft_id: int, feedback: str = "") -> Any:
        return self._decline(draft_id, feedback)


class ApprovalService:
    def __init__(
        self,
        memory,
        providers: Mapping[str, EffectProvider] | None = None,
        site_drafts: SiteDraftApprovalAdapter | None = None,
    ) -> None:
        self.memory = memory
        self.providers = dict(providers or {})
        self.site_drafts = site_drafts

    def create(
        self,
        artifact: Artifact,
        *,
        owner_action_label: str,
        effect_class: EffectClass,
        action_id: int | None = None,
    ) -> ApprovalRequest:
        if artifact.artifact_id is None:
            artifact = self.memory.create_artifact(artifact)
        approval = self.memory.create_approval_request(
            ApprovalRequest(
                artifact_id=artifact.artifact_id,
                artifact_hash=artifact.content_hash,
                effect_class=effect_class,
                owner_action_label=owner_action_label,
                provider_id=artifact.provider_id,
                action_id=action_id,
            )
        )
        if action_id is not None:
            self.memory.link_owner_action(action_id, approval_id=approval.approval_id, artifact_id=artifact.artifact_id)
        return approval

    def preview(self, approval_id: int) -> dict[str, Any]:
        approval = self._require(approval_id)
        artifact = self.memory.get_artifact(approval.artifact_id)
        if artifact is None:
            raise ApprovalServiceError(f"approval {approval_id} references a missing artifact")
        return {
            "approval": approval.to_owner_dict(),
            "artifact": artifact.to_preview_dict(),
            "stale": artifact.content_hash != approval.artifact_hash,
        }

    def decide(self, approval_id: int, approved: bool, feedback: str = "") -> ApprovalRequest:
        approval = self._require(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalServiceError(f"approval already {approval.status.value}")
        self._ensure_current(approval)
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DECLINED
        return self.memory.transition_approval_request(approval_id, status, owner_feedback=feedback)

    def dispatch(self, approval_id: int) -> ProviderReceipt:
        approval = self._require(approval_id)
        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalServiceError("only approved effects can be dispatched")
        artifact = self._ensure_current(approval)
        idempotency_key = self._idempotency_key(approval)
        existing = self.memory.get_provider_receipt_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        provider = self.providers.get(approval.provider_id)
        if provider is None:
            raise ApprovalServiceError(f"provider unavailable: {approval.provider_id}")
        try:
            receipt = provider(artifact, approval, idempotency_key)
            if not isinstance(receipt, ProviderReceipt):
                raise TypeError("effect provider must return ProviderReceipt")
        except Exception as exc:  # noqa: BLE001 — provider failures become safe receipts
            receipt = ProviderReceipt(
                provider_id=approval.provider_id,
                capability_id=artifact.capability_id,
                idempotency_key=idempotency_key,
                status=ReceiptStatus.FAILURE,
                action_id=approval.action_id,
                approval_id=approval.approval_id,
                safe_message=safe_provider_message(str(exc)),
            )
        if receipt.idempotency_key != idempotency_key:
            raise ApprovalServiceError("effect provider returned the wrong idempotency key")
        saved = self.memory.create_provider_receipt(receipt)
        self.memory.link_approval_request(approval_id, provider_receipt_id=saved.receipt_id)
        if saved.status in {ReceiptStatus.FAILURE, ReceiptStatus.UNCERTAIN}:
            self.memory.transition_approval_request(approval_id, ApprovalStatus.FAILED)
        return saved

    def approve_site_draft(self, draft_id: int) -> Any:
        if self.site_drafts is None:
            raise ApprovalServiceError("website-draft approval adapter is not configured")
        return self.site_drafts.approve(draft_id)

    def decline_site_draft(self, draft_id: int, feedback: str = "") -> Any:
        if self.site_drafts is None:
            raise ApprovalServiceError("website-draft approval adapter is not configured")
        return self.site_drafts.decline(draft_id, feedback)

    def _require(self, approval_id: int) -> ApprovalRequest:
        approval = self.memory.get_approval_request(approval_id)
        if approval is None:
            raise ApprovalServiceError(f"no such approval: {approval_id}")
        return approval

    def _ensure_current(self, approval: ApprovalRequest) -> Artifact:
        artifact = self.memory.get_artifact(approval.artifact_id)
        if artifact is None:
            raise ApprovalServiceError(f"approval {approval.approval_id} references a missing artifact")
        if artifact.content_hash != approval.artifact_hash:
            if approval.status == ApprovalStatus.PENDING:
                self.memory.transition_approval_request(approval.approval_id, ApprovalStatus.EXPIRED)
            raise StaleApproval(f"approval {approval.approval_id} is stale")
        return artifact

    @staticmethod
    def _idempotency_key(approval: ApprovalRequest) -> str:
        digest = hashlib.sha256(approval.artifact_hash.encode()).hexdigest()[:24]
        return f"approval:{approval.approval_id}:{digest}"
