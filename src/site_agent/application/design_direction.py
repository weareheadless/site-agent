"""Read-only direction proposal for the gated native design path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..brain.art_direction import select_direction
from ..brain.design_brief import assess_intake, compile_brief
from ..core.contracts import Artifact, ArtifactKind, ContractError
from ..core.design_contracts import canonical_hash
from .design_operations import DesignOperationError, DesignOperationService


class DesignDirectionError(ValueError):
    """A direction cannot be proposed from the confirmed website state."""


class DesignDirectionService:
    """Persist a human-readable direction without touching website source."""

    def __init__(
        self,
        memory,
        intake_service,
        operations: DesignOperationService,
    ) -> None:
        self.memory = memory
        self.intake_service = intake_service
        self.operations = operations

    def propose(
        self,
        session_id: str,
        *,
        confirmed_revision: int,
        conversation_id: int | None = None,
    ) -> dict[str, Any]:
        try:
            intake = self.intake_service.confirmed_intake(
                session_id,
                revision=confirmed_revision,
            )
            assessment = assess_intake(intake)
            if not assessment.complete_enough:
                raise DesignDirectionError(
                    "intake needs owner follow-up: "
                    + "; ".join(assessment.blocking_questions or assessment.contradictions)
                )
            brief = compile_brief(intake, assessment)
            selection = select_direction(intake, brief)
            direction = {
                "schema_version": 1,
                "confirmed_revision": int(confirmed_revision),
                "intake_hash": canonical_hash(intake.to_dict()),
                "brief": brief.to_dict(),
                "selection": selection.to_dict(),
            }
            direction_hash = canonical_hash(direction)
        except (ContractError, DesignDirectionError, ValueError) as exc:
            if isinstance(exc, DesignDirectionError):
                raise
            raise DesignDirectionError(str(exc)[:500]) from exc

        operation = self.operations.queue_owner_request(
            tool="design.direction",
            scope={
                "session_id": session_id,
                "confirmed_revision": int(confirmed_revision),
            },
            bound_state={"intake_revision": int(confirmed_revision)},
            source_ref=f"intake:{session_id}:{confirmed_revision}",
            conversation_id=conversation_id,
            reason="Ada prepared a read-only design direction from the confirmed brief.",
        )
        if operation.status.value == "done":
            return self._completed_response(operation)

        if operation.status.value != "queued":
            raise DesignDirectionError(f"direction operation is {operation.status.value}")
        operation = self.operations.start(operation.id or 0)
        try:
            artifact = self.memory.create_artifact(
                Artifact(
                    kind=ArtifactKind.DESIGN_DIRECTION,
                    title="Ada design direction",
                    summary="A read-only direction proposal from the confirmed brief.",
                    renderer="design-direction",
                    capability_id="website.design.direction",
                    provider_id="site-agent",
                    content_hash=direction_hash,
                    preview_data=direction,
                )
            )
            recommendation = self.operations.recommend(
                tool="design.build",
                title="Build the homepage from this direction",
                reason="The confirmed brief is ready and this direction has not changed the site.",
                scope={
                    "session_id": session_id,
                    "confirmed_revision": int(confirmed_revision),
                    "direction_artifact_id": artifact.artifact_id,
                    "direction_hash": direction_hash,
                    "page": "index.html",
                },
                bound_state={
                    "intake_revision": int(confirmed_revision),
                    "direction_hash": direction_hash,
                    "revision_id": None,
                },
                source_ref=f"operation:{operation.id}",
                conversation_id=conversation_id,
            )
            completed = self.operations.complete(
                operation.id,
                outcome={
                    "artifact_id": artifact.artifact_id,
                    "direction_hash": direction_hash,
                    "recommendation_id": recommendation.id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - retain a bounded operation error
            try:
                self.operations.fail(
                    operation.id or 0,
                    error_code="direction_proposal_failed",
                    reason=str(exc)[:500],
                )
            except Exception:
                pass
            if isinstance(exc, DesignDirectionError):
                raise
            raise DesignDirectionError(str(exc)[:500]) from exc

        return {
            "operation": completed.to_dict(),
            "artifact": artifact.to_preview_dict(),
            "recommendation": self.operations.recommendation_view(recommendation),
        }

    def _completed_response(self, operation) -> dict[str, Any]:
        outcome = dict(operation.outcome)
        artifact_id = outcome.get("artifact_id")
        artifact = self.memory.get_artifact(int(artifact_id)) if artifact_id else None
        recommendation_id = outcome.get("recommendation_id")
        recommendation = (
            self.operations.recommendation(int(recommendation_id))
            if recommendation_id
            else None
        )
        if artifact is None or recommendation is None:
            raise DesignDirectionError("completed direction operation has incomplete output")
        return {
            "operation": operation.to_dict(),
            "artifact": artifact.to_preview_dict(),
            "recommendation": self.operations.recommendation_view(recommendation),
        }


__all__ = ["DesignDirectionError", "DesignDirectionService"]
