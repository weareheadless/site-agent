"""Secret-free provenance for an already verified tenant runtime activation.

This records the receipt identity selected by activation; it does not certify
that control source bytes or the currently serving Worker were revalidated.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RuntimeActivation:
    schema: int
    tenant_id: str
    release_id: str
    source_sha: str
    control_sha: str
    shared_runtime_fingerprint: str
    uploaded_version: str

    @classmethod
    def from_receipt(
        cls, tenant_id: str, release_id: str, receipt: Mapping[str, Any],
    ) -> "RuntimeActivation | None":
        """Build only from validated canonical receipt fields; legacy absence is unbound."""
        source = receipt.get("pipelineSha")
        fingerprint = receipt.get("sharedRuntimeFingerprint")
        if source is None and fingerprint is None:
            return None
        if not isinstance(source, str) or not isinstance(fingerprint, str):
            raise ValueError("runtime activation provenance is incomplete")
        control_sha = source
        source_sha = receipt.get("sourceSha")
        uploaded_version = receipt.get("uploadedVersion")
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", tenant_id)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", release_id)
            or not isinstance(source_sha, str)
            or not re.fullmatch(r"[0-9a-f]{40}", source_sha)
            or not re.fullmatch(r"[0-9a-f]{40}", control_sha)
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
            or not isinstance(uploaded_version, str)
            or not uploaded_version.strip()
            or uploaded_version != uploaded_version.strip()
        ):
            raise ValueError("runtime activation provenance is invalid")
        return cls(1, tenant_id, release_id, source_sha, control_sha, fingerprint, uploaded_version)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuntimeActivation":
        expected = {
            "schema", "tenant_id", "release_id", "source_sha", "control_sha",
            "shared_runtime_fingerprint", "uploaded_version",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("runtime activation binding has unsupported fields")
        if type(value.get("schema")) is not int or value["schema"] != 1:
            raise ValueError("runtime activation binding schema is invalid")
        # Reuse receipt validation without allowing extra serialized keys.
        receipt = {
            "sourceSha": value.get("source_sha"),
            "pipelineSha": value.get("control_sha"),
            "sharedRuntimeFingerprint": value.get("shared_runtime_fingerprint"),
            "uploadedVersion": value.get("uploaded_version"),
        }
        parsed = cls.from_receipt(value.get("tenant_id"), value.get("release_id"), receipt)
        if parsed is None:
            raise ValueError("runtime activation binding is incomplete")
        return parsed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
