import pytest

from site_agent.core.contracts import (
    ActionPriority,
    ActionRequirement,
    ActionState,
    ApprovalStatus,
    ApprovalRequest,
    Artifact,
    ArtifactKind,
    Capability,
    CapabilityAvailability,
    ContractError,
    EffectClass,
    OwnerAction,
    ProviderReceipt,
    ReceiptStatus,
    safe_provider_message,
    validate_action_transition,
    validate_approval_transition,
)
from site_agent.application.capabilities import CapabilityRegistry, CapabilityRegistryError, default_capabilities


def _action(**overrides):
    values = {
        "capability_id": "content.article.prepare",
        "provider_id": "site-agent",
        "title": "Prepare an article",
        "summary": "Ada can prepare a useful article.",
        "action_label": "Ask Ada to prepare it",
        "priority": ActionPriority.OPTIONAL,
        "requirement": ActionRequirement.SUGGESTION,
        "source_ref": "test:article",
        "dedupe_key": "test:article",
    }
    values.update(overrides)
    return OwnerAction(**values)


def test_contracts_normalize_and_redact_payloads():
    action = _action(payload={"access_token": "secret", "nested": {"password": "hidden", "topic": "calm"}})
    assert action.priority is ActionPriority.OPTIONAL
    assert action.payload == {
        "access_token": "[REDACTED]",
        "nested": {"password": "[REDACTED]", "topic": "calm"},
    }

    receipt = ProviderReceipt(
        provider_id="social.example",
        capability_id="social.post.publish",
        idempotency_key="post-1",
        status=ReceiptStatus.FAILURE,
        safe_message="Bearer abc123; api_key=secret-value",
    )
    assert "abc123" not in receipt.safe_message
    assert "secret-value" not in receipt.safe_message
    assert safe_provider_message("password: top-secret") == "password=[REDACTED]"


def test_contracts_validate_fields_and_capability_limits():
    with pytest.raises(ContractError, match="artifact_id is required"):
        ApprovalRequest(
            artifact_id=None,
            artifact_hash="sha256:1",
            effect_class=EffectClass.PROPOSAL,
            owner_action_label="Review",
            provider_id="site-agent",
        )

    capability = Capability(
        capability_id="search.insights.read",
        provider_id="search.example",
        effect_class=EffectClass.READ,
        availability=CapabilityAvailability.AVAILABLE,
        input_contract={"query": {"type": "string"}},
        result_contract={"items": {"type": "array"}},
    )
    assert capability.to_dict()["effect_class"] == "read"
    assert capability.to_dict()["approval_required"] is False

    with pytest.raises(ContractError, match="require explicit approval"):
        Capability(
            capability_id="social.post.publish",
            provider_id="social.example",
            effect_class=EffectClass.EXTERNAL_MUTATION,
            availability=CapabilityAvailability.AVAILABLE,
        )


def test_capability_registry_is_explicit_and_validates_provider_and_effect():
    capability = Capability(
        capability_id="search.insights.read",
        provider_id="search.example",
        effect_class=EffectClass.READ,
        availability=CapabilityAvailability.AVAILABLE,
    )
    registry = CapabilityRegistry([capability])
    assert registry.validate("search.insights.read", provider_id="search.example").capability_id == capability.capability_id
    with pytest.raises(CapabilityRegistryError, match="another provider"):
        registry.validate("search.insights.read", provider_id="other.example")
    with pytest.raises(CapabilityRegistryError, match="already registered"):
        registry.register(capability)


def test_default_capabilities_are_finite_and_keep_social_unavailable():
    registry = CapabilityRegistry(default_capabilities())
    assert {item.capability_id for item in registry.values()} == {
        "content.suggestion",
        "content.article.prepare",
        "review.site_change",
        "social.post.prepare",
        "social.post.publish",
    }
    assert registry.available("content.suggestion") is True
    assert registry.available("social.post.prepare") is False
    assert registry.available("social.post.publish") is False


def test_action_and_approval_transitions_are_guarded():
    validate_action_transition(ActionState.OPEN, ActionState.STARTED)
    validate_action_transition(ActionState.SNOOZED, ActionState.OPEN)
    with pytest.raises(ContractError, match="cannot transition"):
        validate_action_transition(ActionState.COMPLETED, ActionState.OPEN)
    with pytest.raises(ContractError, match="cannot transition"):
        validate_action_transition(ActionState.DISMISSED, ActionState.OPEN)

    validate_approval_transition(ApprovalStatus.PENDING, ApprovalStatus.APPROVED)
    validate_approval_transition(ApprovalStatus.APPROVED, ApprovalStatus.FAILED)
    with pytest.raises(ContractError, match="cannot transition"):
        validate_approval_transition(ApprovalStatus.DECLINED, ApprovalStatus.APPROVED)
