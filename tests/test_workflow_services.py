import time

import pytest

from site_agent.application.approvals import (
    ApprovalService,
    ApprovalServiceError,
    SiteDraftApprovalAdapter,
    StaleApproval,
)
from site_agent.application.actions import OwnerActionService
from site_agent.application.capabilities import CapabilityRegistry
from site_agent.application.conversations import ConversationBusy, ConversationService
from site_agent.core.contracts import (
    ActionPriority,
    ActionRequirement,
    ApprovalStatus,
    Artifact,
    ArtifactKind,
    Capability,
    CapabilityAvailability,
    EffectClass,
    OwnerAction,
    ProviderReceipt,
    ReceiptStatus,
)
from site_agent.core.memory import Memory


def _artifact(provider_id="site-agent", content_hash="sha256:article", capability_id="content.article.prepare"):
    return Artifact(
        kind=ArtifactKind.ARTICLE,
        title="Prepared article",
        summary="An article ready for review.",
        renderer="article",
        capability_id=capability_id,
        provider_id=provider_id,
        content_hash=content_hash,
        preview_data={"body": "hello"},
    )


def test_approval_service_binds_hash_and_dispatches_idempotently(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    calls = []

    def provider(artifact, approval, idempotency_key):
        calls.append((artifact.artifact_id, approval.approval_id, idempotency_key))
        return ProviderReceipt(
            provider_id=approval.provider_id,
            capability_id=artifact.capability_id,
            idempotency_key=idempotency_key,
            status=ReceiptStatus.SUCCESS,
            approval_id=approval.approval_id,
            safe_message="published safely",
        )

    service = ApprovalService(memory, providers={"site-agent": provider})
    approval = service.create(
        _artifact(),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
    )
    preview = service.preview(approval.approval_id)
    assert preview["stale"] is False
    assert preview["artifact"]["renderer"] == "article"
    assert "provider_id" not in preview["artifact"]
    assert preview["artifact"]["details"]["provider_id"] == "site-agent"
    assert preview["rendered_preview"]["sections"][0]["label"] == "Article"

    approved = service.decide(approval.approval_id, True)
    assert approved.status is ApprovalStatus.APPROVED
    first = service.dispatch(approval.approval_id)
    second = service.dispatch(approval.approval_id)
    assert first.receipt_id == second.receipt_id
    assert len(calls) == 1
    assert memory.get_approval_request(approval.approval_id).provider_receipt_id == first.receipt_id
    memory.close()


@pytest.mark.parametrize("effect_class", [EffectClass.READ, EffectClass.PROPOSAL, EffectClass.EXTERNAL_MUTATION])
def test_fake_provider_contract_covers_read_proposal_and_external_effects(tmp_path, effect_class):
    memory = Memory(tmp_path / f"{effect_class.value}.db")
    capability_id = f"fake.{effect_class.value}"

    def provider(artifact, approval, idempotency_key):
        return ProviderReceipt(
            provider_id=approval.provider_id,
            capability_id=artifact.capability_id,
            idempotency_key=idempotency_key,
            status=ReceiptStatus.SUCCESS,
        )

    capability = Capability(
        capability_id=capability_id,
        provider_id="fake",
        effect_class=effect_class,
        availability=CapabilityAvailability.AVAILABLE,
        approval_required=effect_class in {EffectClass.SITE_MUTATION, EffectClass.EXTERNAL_MUTATION},
    )
    service = ApprovalService(
        memory,
        providers={"fake": provider},
        capabilities=CapabilityRegistry([capability]),
    )
    approval = service.create(
        _artifact(provider_id="fake", capability_id=capability_id),
        owner_action_label="Continue",
        effect_class=effect_class,
    )
    service.decide(approval.approval_id, True)
    assert service.dispatch(approval.approval_id).status is ReceiptStatus.SUCCESS
    memory.close()


def test_approval_service_expires_stale_work_and_safely_records_provider_failure(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = ApprovalService(memory, providers={"site-agent": lambda *_args: (_ for _ in ()).throw(RuntimeError("Bearer provider-secret"))})
    stale = service.create(
        _artifact(content_hash="sha256:old"),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
    )
    memory.conn.execute("UPDATE artifacts SET content_hash = 'sha256:new' WHERE id = ?", (stale.artifact_id,))
    memory.conn.commit()
    with pytest.raises(StaleApproval):
        service.decide(stale.approval_id, True)
    assert memory.get_approval_request(stale.approval_id).status is ApprovalStatus.EXPIRED

    failed = service.create(
        _artifact(content_hash="sha256:failure"),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
    )
    service.decide(failed.approval_id, True)
    receipt = service.dispatch(failed.approval_id)
    assert receipt.status is ReceiptStatus.UNCERTAIN
    assert "provider-secret" not in receipt.safe_message
    assert memory.get_approval_request(failed.approval_id).status is ApprovalStatus.APPROVED
    memory.close()


def test_approval_reconciles_linked_owner_action(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    action = memory.create_owner_action(
        OwnerAction(
            capability_id="content.article.publish",
            provider_id="site-agent",
            title="Publish the article",
            summary="The prepared article is ready.",
            action_label="Publish this change",
            priority=ActionPriority.NORMAL,
            requirement=ActionRequirement.OWNER_DECISION,
            source_ref="test:approval-action",
            dedupe_key="test:approval-action",
        )
    )

    def provider(artifact, approval, idempotency_key):
        return ProviderReceipt(
            provider_id=approval.provider_id,
            capability_id=artifact.capability_id,
            idempotency_key=idempotency_key,
            status=ReceiptStatus.SUCCESS,
            approval_id=approval.approval_id,
            action_id=approval.action_id,
        )

    service = ApprovalService(
        memory,
        providers={"site-agent": provider},
        actions=OwnerActionService(memory),
    )
    approval = service.create(
        _artifact(),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
        action_id=action.id,
    )
    service.decide(approval.approval_id, True)
    assert memory.get_owner_action(action.id).state.value == "waiting"
    service.dispatch(approval.approval_id)
    assert memory.get_owner_action(action.id).state.value == "completed"
    memory.close()


def test_site_draft_approval_adapter_is_a_small_compatibility_facade():
    calls = []
    adapter = SiteDraftApprovalAdapter(
        lambda draft_id: calls.append(("approve", draft_id)) or {"ok": True},
        lambda draft_id, feedback: calls.append(("decline", draft_id, feedback)) or {"ok": True},
    )
    assert adapter.approve(4) == {"ok": True}
    assert adapter.decline(5, "not this tone") == {"ok": True}
    assert calls == [("approve", 4), ("decline", 5, "not this tone")]


def test_unavailable_capability_preserves_approved_artifact(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    calls = []
    capability = Capability(
        capability_id="content.article.prepare",
        provider_id="site-agent",
        effect_class=EffectClass.EXTERNAL_MUTATION,
        availability=CapabilityAvailability.UNAVAILABLE,
        approval_required=True,
    )
    service = ApprovalService(
        memory,
        providers={"site-agent": lambda *_args: calls.append(True)},
        capabilities=CapabilityRegistry([capability]),
    )
    approval = service.create(
        _artifact(),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
    )
    service.decide(approval.approval_id, True)
    with pytest.raises(ApprovalServiceError, match="prepared work is still saved"):
        service.dispatch(approval.approval_id)
    assert memory.get_artifact(approval.artifact_id) is not None
    assert calls == []
    memory.close()


def test_capability_timeout_becomes_an_uncertain_safe_receipt(tmp_path):
    memory = Memory(tmp_path / "memory.db")

    def slow_provider(*_args):
        time.sleep(1.1)
        return None

    capability = Capability(
        capability_id="content.article.prepare",
        provider_id="site-agent",
        effect_class=EffectClass.EXTERNAL_MUTATION,
        availability=CapabilityAvailability.AVAILABLE,
        timeout_seconds=1,
        approval_required=True,
    )
    service = ApprovalService(
        memory,
        providers={"site-agent": slow_provider},
        capabilities=CapabilityRegistry([capability]),
    )
    approval = service.create(
        _artifact(),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
    )
    service.decide(approval.approval_id, True)
    receipt = service.dispatch(approval.approval_id)
    assert receipt.status is ReceiptStatus.UNCERTAIN
    assert "did not respond" in receipt.safe_message
    memory.close()


def test_capability_result_size_limit_discards_oversized_provider_details(tmp_path):
    memory = Memory(tmp_path / "memory.db")

    def provider(artifact, approval, idempotency_key):
        return ProviderReceipt(
            provider_id=approval.provider_id,
            capability_id=artifact.capability_id,
            idempotency_key=idempotency_key,
            status=ReceiptStatus.SUCCESS,
            safe_message="x" * 300,
        )

    capability = Capability(
        capability_id="content.article.prepare",
        provider_id="site-agent",
        effect_class=EffectClass.EXTERNAL_MUTATION,
        availability=CapabilityAvailability.AVAILABLE,
        max_result_bytes=100,
        approval_required=True,
    )
    service = ApprovalService(
        memory,
        providers={"site-agent": provider},
        capabilities=CapabilityRegistry([capability]),
    )
    approval = service.create(
        _artifact(),
        owner_action_label="Publish this change",
        effect_class=EffectClass.EXTERNAL_MUTATION,
    )
    service.decide(approval.approval_id, True)
    receipt = service.dispatch(approval.approval_id)
    assert receipt.status is ReceiptStatus.UNCERTAIN
    assert receipt.safe_message == "The provider response exceeded the configured size limit."
    memory.close()


def test_conversation_service_blocks_active_work_and_keeps_deleted_tombstone(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = ConversationService(memory)
    conversation_id = service.create("Owner discussion")
    memory.add_message(conversation_id, "user", "private question")
    job_id = memory.enqueue_chat_job(conversation_id, "long request")
    assert memory.claim_chat_job("test-worker")["id"] == job_id

    with pytest.raises(ConversationBusy) as blocked:
        service.delete(conversation_id)
    assert blocked.value.job_ids == [job_id]
    with pytest.raises(ConversationBusy):
        service.archive(conversation_id)

    memory.interrupt_running_chat_jobs()
    archived = service.archive(conversation_id)
    assert archived["archived"] is True
    assert conversation_id not in {row["id"] for row in service.list()}
    assert conversation_id in {row["id"] for row in service.list(include_archived=True)}
    service.restore(conversation_id)
    deleted = service.delete(conversation_id)
    assert deleted["already_deleted"] is False

    tombstone = service.get(conversation_id)
    assert tombstone["deleted"] is True
    assert tombstone["title"] == "Deleted conversation"
    assert tombstone["messages"] == []
    assert tombstone["jobs"][0]["message"] == ""
    assert tombstone["jobs"][0]["steps"] == []
    assert tombstone["jobs"][0]["result"] is None
    assert tombstone["jobs"][0]["error"] is None
    assert tombstone["jobs"][0]["message_id"] is None
    assert conversation_id not in {row["id"] for row in service.list(include_archived=True)}
    memory.close()
