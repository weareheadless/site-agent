"""Approval workflow for immutable prepared artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ProviderTimeoutError
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .actions import OwnerActionService
from .capabilities import CapabilityRegistry, CapabilityRegistryError
from .renderers import render_artifact
from ..core.contracts import (
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    Capability,
    CapabilityAvailability,
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
        actions: OwnerActionService | None = None,
        capabilities: CapabilityRegistry | None = None,
    ) -> None:
        self.memory = memory
        self.providers = dict(providers or {})
        self.site_drafts = site_drafts
        self.actions = actions
        self.capabilities = capabilities

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
        self._capability(artifact, effect_class)
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
            "rendered_preview": render_artifact(artifact).to_dict(),
            "stale": artifact.content_hash != approval.artifact_hash,
        }

    def list(self, status: ApprovalStatus | str = ApprovalStatus.PENDING, limit: int = 50) -> list[dict[str, Any]]:
        approvals = self.memory.list_approval_requests(status=status, limit=limit)
        result: list[dict[str, Any]] = []
        for approval in approvals:
            artifact = self.memory.get_artifact(approval.artifact_id)
            result.append({
                "approval": approval.to_owner_dict(),
                "artifact": artifact.to_preview_dict() if artifact is not None else None,
                "rendered_preview": render_artifact(artifact).to_dict() if artifact is not None else None,
                "stale": artifact is None or artifact.content_hash != approval.artifact_hash,
            })
        return result

    def decide(self, approval_id: int, approved: bool, feedback: str = "") -> ApprovalRequest:
        approval = self._require(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalServiceError(f"approval already {approval.status.value}")
        self._ensure_current(approval)
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DECLINED
        decided = self.memory.transition_approval_request(approval_id, status, owner_feedback=feedback)
        if decided is not None and self.actions is not None and decided.action_id is not None:
            if approved:
                self.actions.wait(decided.action_id)
            else:
                self.actions.dismiss(decided.action_id)
        return decided

    def dispatch(self, approval_id: int) -> ProviderReceipt:
        approval = self._require(approval_id)
        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalServiceError("only approved effects can be dispatched")
        artifact = self._ensure_current(approval)
        if approval.provider_id != artifact.provider_id:
            raise ApprovalServiceError("approval provider does not match the prepared artifact")
        idempotency_key = self._idempotency_key(approval)
        existing = self.memory.get_provider_receipt_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        provider = self.providers.get(approval.provider_id)
        if provider is None:
            raise ApprovalServiceError(f"provider unavailable: {approval.provider_id}")
        capability = self._capability(artifact, approval.effect_class)
        if capability is not None and capability.availability == CapabilityAvailability.UNAVAILABLE:
            raise ApprovalServiceError("provider unavailable; prepared work is still saved")
        try:
            receipt = self._invoke(provider, artifact, approval, idempotency_key, capability)
            if not isinstance(receipt, ProviderReceipt):
                raise TypeError("effect provider must return ProviderReceipt")
        except ProviderTimeoutError:
            receipt = ProviderReceipt(
                provider_id=approval.provider_id,
                capability_id=artifact.capability_id,
                idempotency_key=idempotency_key,
                status=ReceiptStatus.UNCERTAIN,
                action_id=approval.action_id,
                approval_id=approval.approval_id,
                safe_message="The provider did not respond before the configured timeout.",
            )
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
        if receipt.provider_id != approval.provider_id or receipt.capability_id != artifact.capability_id:
            raise ApprovalServiceError("effect provider returned mismatched receipt identifiers")
        if capability is not None:
            encoded_size = len(json.dumps(receipt.to_dict(), separators=(",", ":")).encode("utf-8"))
            if encoded_size > capability.max_result_bytes:
                receipt = ProviderReceipt(
                    provider_id=approval.provider_id,
                    capability_id=artifact.capability_id,
                    idempotency_key=idempotency_key,
                    status=ReceiptStatus.UNCERTAIN,
                    action_id=approval.action_id,
                    approval_id=approval.approval_id,
                    safe_message="The provider response exceeded the configured size limit.",
                )
        try:
            saved = self.memory.create_provider_receipt(receipt)
        except sqlite3.IntegrityError:
            saved = self.memory.get_provider_receipt_by_idempotency_key(idempotency_key)
            if saved is None:
                raise
        self.memory.link_approval_request(approval_id, provider_receipt_id=saved.receipt_id)
        if saved.status in {ReceiptStatus.FAILURE, ReceiptStatus.UNCERTAIN}:
            self.memory.transition_approval_request(approval_id, ApprovalStatus.FAILED)
        elif self.actions is not None:
            self.actions.reconcile(approval_id=approval_id)
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

    def _capability(self, artifact: Artifact, effect_class: EffectClass) -> Capability | None:
        if self.capabilities is None:
            return None
        try:
            return self.capabilities.validate(
                artifact.capability_id,
                provider_id=artifact.provider_id,
                effect_class=effect_class,
            )
        except CapabilityRegistryError as exc:
            raise ApprovalServiceError(str(exc)) from exc

    @staticmethod
    def _invoke(provider, artifact, approval, idempotency_key, capability):
        if capability is None:
            return provider(artifact, approval, idempotency_key)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(provider, artifact, approval, idempotency_key)
        try:
            return future.result(timeout=capability.timeout_seconds)
        except ProviderTimeoutError:
            future.cancel()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _ensure_current(self, approval: ApprovalRequest) -> Artifact:
        artifact = self.memory.get_artifact(approval.artifact_id)
        if artifact is None:
            raise ApprovalServiceError(f"approval {approval.approval_id} references a missing artifact")
        if artifact.content_hash != approval.artifact_hash:
            if approval.status == ApprovalStatus.PENDING:
                self.memory.transition_approval_request(approval.approval_id, ApprovalStatus.EXPIRED)
                if self.actions is not None and approval.action_id is not None:
                    self.actions.mark_stale(approval.action_id)
            raise StaleApproval(f"approval {approval.approval_id} is stale")
        return artifact

    @staticmethod
    def _idempotency_key(approval: ApprovalRequest) -> str:
        digest = hashlib.sha256(approval.artifact_hash.encode()).hexdigest()[:24]
        return f"approval:{approval.approval_id}:{digest}"
