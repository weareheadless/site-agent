from __future__ import annotations

import pytest

from site_agent.application.runtime_activation import RuntimeActivation


def test_runtime_activation_is_exact_secret_free_receipt_projection():
    receipt = {
        "tenant": "new-site",
        "releaseId": "release-1",
        "sourceSha": "a" * 40,
        "pipelineSha": "b" * 40,
        "sharedRuntimeFingerprint": "c" * 64,
        "uploadedVersion": "worker-version",
        "secret": "must-not-be-copied",
    }
    binding = RuntimeActivation.from_receipt("new-site", "release-1", receipt)
    assert binding is not None
    assert binding.to_dict() == {
        "schema": 1,
        "tenant_id": "new-site",
        "release_id": "release-1",
        "source_sha": "a" * 40,
        "control_sha": "b" * 40,
        "shared_runtime_fingerprint": "c" * 64,
        "uploaded_version": "worker-version",
    }
    assert RuntimeActivation.from_mapping(binding.to_dict()) == binding


@pytest.mark.parametrize("patch", [
    {"pipelineSha": "B" * 40},
    {"sharedRuntimeFingerprint": "bad"},
    {"pipelineSha": None},
    {"sourceSha": "A" * 40},
    {"uploadedVersion": " "},
])
def test_runtime_activation_rejects_malformed_partial_receipt_provenance(patch):
    receipt = {
        "sourceSha": "a" * 40,
        "pipelineSha": "b" * 40,
        "sharedRuntimeFingerprint": "c" * 64,
        "uploadedVersion": "worker-version",
        **patch,
    }
    with pytest.raises(ValueError):
        RuntimeActivation.from_receipt("new-site", "release-1", receipt)


def test_runtime_activation_preserves_historical_unbound_receipt():
    assert RuntimeActivation.from_receipt("new-site", "release-1", {
        "sourceSha": "a" * 40, "uploadedVersion": "worker-version",
    }) is None
    with pytest.raises(ValueError, match="unsupported fields"):
        RuntimeActivation.from_mapping({
            "schema": 1, "tenant_id": "new-site", "release_id": "release-1",
            "source_sha": "a" * 40, "control_sha": "b" * 40,
            "shared_runtime_fingerprint": "c" * 64, "uploaded_version": "worker-version",
            "secret": "not allowed",
        })
