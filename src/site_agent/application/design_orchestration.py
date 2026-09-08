"""Finite specialist orchestration for typed design planning.

The coordinator owns phase order and persistence. OpenCode specialists only
return phase artifacts; they cannot dispatch another phase or decide whether a
new creative round is needed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping, Protocol, Sequence, Type

from ..core.contracts import ContractError
from ..core.design_contracts import (
    BuildTarget,
    CopyDeck,
    CreativeConcept,
    DesignPhase,
    DesignPhaseArtifact,
    DesignPlanBundle,
    PageBuildRequest,
    canonical_hash,
    canonical_json,
)
from ..hands.opencode_provider import (
    OpenCodeSpecialistAdapter,
    SpecialistInvocation,
    SpecialistProviderError,
    decode_structured_output,
    structured_output_prompt,
)


class DesignOrchestrationError(RuntimeError):
    """A finite specialist workflow could not complete a phase."""


class SpecialistInvoker(Protocol):
    def invoke(self, request: SpecialistInvocation, progress=None):
        ...


@dataclass(frozen=True)
class DesignPlanResult:
    copy_deck: CopyDeck
    concepts: tuple[CreativeConcept, ...]
    plan: DesignPlanBundle
    creative_director_session_id: str


class SpecialistDesignCoordinator:
    """Run the finite copy/concept/selection portion of a design workflow."""

    CONCEPT_VARIANTS = ("a", "b", "c")

    def __init__(
        self,
        context: Mapping[str, Any],
        *,
        invoker: SpecialistInvoker | None = None,
        scratch_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.context = dict(context)
        self.memory = self.context.get("memory")
        if self.memory is None:
            raise DesignOrchestrationError("specialist orchestration requires durable memory")
        self.config = dict(self.context.get("config") or {})
        self.invoker = invoker or OpenCodeSpecialistAdapter()
        self.scratch_factory = scratch_factory or TemporaryDirectory

    @staticmethod
    def _brief(request: PageBuildRequest) -> dict[str, Any]:
        snapshot = request.context_snapshot
        site_facts = snapshot.site_facts if snapshot is not None else {}
        return {
            "owner_request": str((request.content or {}).get("creative_prompt") or request.purpose),
            "purpose": request.purpose,
            "acceptance_criteria": list(request.acceptance_criteria),
            "required_files": list(request.required_files),
            "media_paths": list(request.supplied_media_paths),
            "business": dict(site_facts.get("business") or {}),
            "audience": dict(site_facts.get("audience") or {}),
            "conversion": dict(site_facts.get("conversion") or {}),
            "brand": dict(site_facts.get("brand") or {}),
            "constraints": dict(site_facts.get("constraints") or {}),
            "unknowns": list(snapshot.unknowns if snapshot is not None else ()),
            "capabilities": list(snapshot.capabilities if snapshot is not None else ()),
        }

    @staticmethod
    def _input_hashes(request: PageBuildRequest, *artifacts: DesignPhaseArtifact) -> tuple[str, ...]:
        hashes = [canonical_hash(request.to_dict())]
        if request.context_snapshot_hash:
            hashes.append(request.context_snapshot_hash)
        hashes.extend(artifact.content_hash for artifact in artifacts)
        return tuple(dict.fromkeys(hashes))

    def _invoke_phase(
        self,
        *,
        request: PageBuildRequest,
        target: BuildTarget,
        role: str,
        phase: str,
        variant_key: str,
        contract: Type[DesignPhaseArtifact],
        instruction: str,
        input_hashes: tuple[str, ...],
        progress=None,
        session_id: str | None = None,
        image_files: Sequence[str] = (),
    ) -> tuple[DesignPhaseArtifact, str]:
        claimed = self.memory.claim_design_phase(
            request.run_id,
            phase,
            variant_key=variant_key,
            base_sha=target.base_sha,
            context_snapshot_hash=request.context_snapshot_hash,
            input_hashes=input_hashes,
            provider_id=str((self.config.get("design_engine") or {}).get("provider") or "openrouter"),
            model=str((self.config.get("design_engine") or {}).get("model") or ""),
            session_id=session_id or "",
        )
        if claimed["status"] == "completed":
            artifact = contract.from_dict(claimed["payload"])
            return artifact, str(claimed.get("session_id") or "")
        if claimed["status"] == "running" and not claimed.get("claimed"):
            raise DesignOrchestrationError(
                f"design phase is already running: {phase}/{variant_key}"
            )
        attempt = int(claimed["attempt"])
        envelope_prompt = structured_output_prompt(
            instruction
            + "\nPHASE INPUTS:\n"
            + canonical_json(self._brief(request))
            + f"\nThe host expects attempt {attempt} and variant {variant_key or 'primary'}. "
            "Preserve all verified unknowns and do not invent destinations or claims.",
            contract.__name__,
        )
        try:
            with self.scratch_factory() as scratch:
                invocation = SpecialistInvocation(
                    role=role,
                    workspace=scratch,
                    prompt=envelope_prompt,
                    config=self.config,
                    session_id=session_id,
                    timeout_seconds=int((self.config.get("design_engine") or {}).get("specialist_timeout_seconds", 300)),
                    api_key_env=str((self.config.get("design_engine") or {}).get("api_key_env") or "") or None,
                    api_key=self.context.get("api_key"),
                    env=self.context.get("env"),
                    image_files=tuple(str(item) for item in image_files),
                    memory=self.memory,
                )
                result = self.invoker.invoke(invocation, progress=progress)
            raw = result.provider_dict() if hasattr(result, "provider_dict") else result
            payload = decode_structured_output(raw)
            artifact = contract.from_dict(payload)
            if artifact.run_id != request.run_id or artifact.base_sha != target.base_sha:
                raise DesignOrchestrationError("specialist artifact identity does not match the design run")
            if artifact.context_snapshot_hash != request.context_snapshot_hash:
                raise DesignOrchestrationError("specialist artifact context hash does not match the design run")
            if artifact.phase != phase or artifact.variant_key != variant_key or artifact.attempt != attempt:
                raise DesignOrchestrationError("specialist artifact phase identity does not match its claim")
            completed = self.memory.complete_design_phase(
                claimed["id"],
                artifact.to_dict(),
                output_hash=artifact.content_hash,
                prompt_tokens=int((getattr(result, "usage", {}) or {}).get("prompt_tokens", 0)),
                completion_tokens=int((getattr(result, "usage", {}) or {}).get("completion_tokens", 0)),
                reported_cost_usd=getattr(result, "cost", None),
            )
            return contract.from_dict(completed["payload"]), str(getattr(result, "session_id", "") or "")
        except Exception as exc:  # noqa: BLE001 - failure is persisted before surfacing
            self.memory.fail_design_phase(
                claimed["id"],
                error_code="specialist_error",
                error_detail=str(exc),
            )
            if isinstance(exc, (DesignOrchestrationError, SpecialistProviderError, ContractError)):
                raise
            raise DesignOrchestrationError(str(exc)) from exc

    def create_plan(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress=None,
        *,
        image_files: Sequence[str] = (),
    ) -> DesignPlanResult:
        """Create exactly one copy deck, three concepts, and one selection."""
        if not request.run_id:
            raise DesignOrchestrationError("design request has no stable run identity")
        input_hashes = self._input_hashes(request)
        copy_instruction = (
            "Act as the copywriter. Produce the final visible copy hierarchy for the required page. "
            "Use verified facts only, preserve unresolved contact details, and make the primary action honest."
        )
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="design-specialist") as pool:
            futures = {
                "copy": pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="copywriter",
                    phase=DesignPhase.COPY.value,
                    variant_key="primary",
                    contract=CopyDeck,
                    instruction=copy_instruction,
                    input_hashes=input_hashes,
                    progress=progress,
                    image_files=image_files,
                )
            }
            for variant in self.CONCEPT_VARIANTS:
                futures[f"concept-{variant}"] = pool.submit(
                    self._invoke_phase,
                    request=request,
                    target=target,
                    role="concept-designer",
                    phase=DesignPhase.CONCEPT.value,
                    variant_key=variant,
                    contract=CreativeConcept,
                    instruction=(
                        "Act as an independent visual concept designer. Develop one distinctive concept "
                        "for this specific audience and supplied media. Do not implement source or copy a template."
                    ),
                    input_hashes=input_hashes,
                    progress=progress,
                    image_files=image_files,
                )
            results: dict[str, tuple[DesignPhaseArtifact, str]] = {}
            for future in as_completed(futures.values()):
                key = next(name for name, item in futures.items() if item is future)
                results[key] = future.result()
        copy_deck, copy_session = results["copy"]
        concepts = tuple(results[f"concept-{variant}"][0] for variant in self.CONCEPT_VARIANTS)
        selection_inputs = self._input_hashes(request, copy_deck, *concepts)
        selection_prompt = (
            "Act as the creative director. Compare the three independent concepts, select the strongest direction "
            "or synthesize only named strengths, and lock a concrete implementation bundle. Protect the chosen concept "
            "from generic-template drift. The same session will later review the rendered realization.\n"
            "COPY DECK:\n" + canonical_json(copy_deck.to_dict())
            + "\nCONCEPTS:\n" + canonical_json([concept.to_dict() for concept in concepts])
        )
        plan, director_session = self._invoke_phase(
            request=request,
            target=target,
            role="creative-director",
            phase=DesignPhase.CREATIVE_SELECTION.value,
            variant_key="primary",
            contract=DesignPlanBundle,
            instruction=selection_prompt,
            input_hashes=selection_inputs,
            progress=progress,
            image_files=image_files,
        )
        return DesignPlanResult(
            copy_deck=copy_deck,  # type: ignore[arg-type]
            concepts=tuple(concepts),  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            creative_director_session_id=director_session or copy_session,
        )
