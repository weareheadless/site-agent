import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.intake_lab_contracts import (
    LivePreviewSnapshot,
    OwnerTraceEntry,
    TraceCategory,
    TraceBasis,
    trace_entry_id,
)


def test_owner_trace_entry_round_trips_bounded_owner_safe_evidence():
    entry = OwnerTraceEntry.from_dict({
        "entry_id": trace_entry_id("decision", {"path": "business.name"}),
        "category": TraceCategory.BUSINESS.value,
        "summary": "The offer is clearest when the visitor sees the outcome first.",
        "basis": TraceBasis.INFERENCE.value,
        "created_at": "2026-09-11T12:00:00+00:00",
        "source_ids": ["message:12", "finding:4"],
        "confidence": 0.72,
        "implications": ["Lead with the outcome before the service list."],
    })

    restored = OwnerTraceEntry.from_dict(entry.to_dict())

    assert restored == entry
    assert restored.source_ids == ("message:12", "finding:4")
    assert restored.confidence == 0.72


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("category", "CHAIN_OF_THOUGHT"),
        ("basis", "prompt"),
        ("confidence", 1.1),
        ("summary", ""),
    ],
)
def test_owner_trace_entry_rejects_unsafe_or_invalid_values(field, value):
    raw = {
        "entry_id": "trace_valid",
        "category": TraceCategory.INTAKE.value,
        "summary": "A bounded owner-facing fact.",
        "basis": TraceBasis.OWNER.value,
        "created_at": "2026-09-11T12:00:00+00:00",
    }
    raw[field] = value

    with pytest.raises(ContractError):
        OwnerTraceEntry.from_dict(raw)


def test_live_preview_snapshot_requires_a_real_immutable_commit():
    snapshot = LivePreviewSnapshot.from_dict({
        "snapshot_id": "live_abc123",
        "run_id": "design_abc123",
        "commit_sha": "a" * 40,
        "created_at": "2026-09-11T12:00:00+00:00",
        "label": "Ada saved a stable checkpoint",
        "variant": "live",
    })

    assert snapshot.to_dict()["commit_sha"] == "a" * 40
    with pytest.raises(ContractError):
        LivePreviewSnapshot.from_dict({**snapshot.to_dict(), "commit_sha": "not-a-sha"})
    with pytest.raises(ContractError):
        LivePreviewSnapshot.from_dict({**snapshot.to_dict(), "variant": "candidate"})
