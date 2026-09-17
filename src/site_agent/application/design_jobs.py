"""Single-worker execution for durable typed design builds."""

from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections.abc import Mapping
from typing import Any

from ..core.design_contracts import (
    BuildTarget,
    DesignRunStatus,
    PageBuildRequest,
)
from .designs import DesignService


class DesignJobExecutor:
    """Execute queued design runs while keeping the run ID as the job handle."""

    def __init__(self, context: dict[str, Any], service: DesignService) -> None:
        self.context = context
        self.memory = context["memory"]
        self.service = service
        self.activity_service = context.get("activity_service") or getattr(service, "activity_service", None)
        self._queue: queue.Queue[str] = queue.Queue()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.worker = f"design-{time.time_ns()}"

    def _after_visual_review(self, run_id: str) -> None:
        """Notify the runtime owner after a read-only visual review completes.

        The intake runtime uses this to surface review-flagged imagery gaps to
        the owner as a durable chat request. Bounded: an observer failure can
        never strand the design run it was called after.
        """
        observer = self.context.get("on_visual_review")
        if not callable(observer):
            return
        try:
            observer(run_id)
        except Exception:  # noqa: BLE001 - review notify must never break the run
            pass

    def _checkpoint_live_preview(self, run_id: str, *, label: str) -> None:
        """Publish a read-only immutable checkpoint after a candidate exists."""
        checkpoint = self.context.get("on_live_preview_checkpoint")
        if not callable(checkpoint):
            return
        try:
            run = self.service.get_run(run_id)
            if not run.get("candidate_sha"):
                return
            clone = self.service.clone_path_for_run(run_id)
            result = checkpoint(run_id, clone, label)
            snapshot = result.get("snapshot") if isinstance(result, Mapping) else {}
            detail = {
                "snapshot_id": str((snapshot or {}).get("snapshot_id") or ""),
                "commit_sha": str((snapshot or {}).get("commit_sha") or ""),
                "label": str((snapshot or {}).get("label") or label)[:240],
            }
            self.memory.add_design_run_event(
                run_id,
                "live_preview_checkpoint",
                "An immutable live preview checkpoint was published.",
                detail,
            )
            self._activity(
                run,
                kind="live_preview_checkpoint",
                state="completed",
                summary="Saved an immutable live preview checkpoint for owner review.",
                provenance="host_validation",
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - preview failure never mutates run state
            try:
                self.memory.add_design_run_event(
                    run_id,
                    "live_preview_checkpoint_error",
                    "The live preview checkpoint could not be published; the candidate remains isolated.",
                    {"error": str(exc)[:500]},
                )
            except Exception:
                pass

    def _run_visual_review_if_pending(self, run_id: str) -> None:
        """Run only the configured read-only visual gate; never mutate code."""
        run = self.service.get_run(run_id)
        quality = run.get("quality_report_json") or {}
        pending = any(
            isinstance(event, Mapping) and event.get("stage") == "visual_review_pending"
            for event in (run.get("events") or ())
        )
        # A pending marker is retained as durable history.  Do not run the
        # provider again after a completed review; explicit retry endpoints can
        # invoke the service directly and then use the same handoff below.
        if not pending or (isinstance(quality, Mapping) and quality.get("visual_critique")):
            return
        reviewer = getattr(self.service, "visual_review_run", None)
        if not callable(reviewer):
            return
        critique = reviewer(
            run_id,
            env=self.context.get("review_environment") or self.context.get("env"),
            source_media=self.context.get("media_service"),
        )
        self._after_visual_review(run_id)

    def _link_review_draft_if_ready(self, run_id: str) -> None:
        """Make a passed customer candidate visible in the existing Review flow."""
        run = self.service.get_run(run_id)
        if (
            run.get("mode") != "production_candidate"
            or run.get("status") != DesignRunStatus.READY_FOR_REVIEW.value
            or run.get("draft_id")
        ):
            return
        creator = getattr(self.service, "create_review_draft", None)
        if not callable(creator):
            return
        try:
            creator(run_id)
        except Exception as exc:  # noqa: BLE001 - retain a reviewable run if linking fails
            try:
                self.memory.add_design_run_event(
                    run_id,
                    "review_link_error",
                    "The candidate passed quality gates but could not be linked to Review.",
                    {"error": str(exc)[:500]},
                )
            except Exception:
                pass

    def _specialist_orchestration_enabled(self) -> bool:
        config = self.context.get("config") or {}
        engine = config.get("design_engine") or {}
        return str(engine.get("orchestration") or "legacy").strip().lower() == "specialist"

    def _run_specialist_reviews_if_ready(self, run_id: str) -> None:
        """Persist the single creative review and two independent critic phases.

        Reviews are read-only and never create a second creative direction. A
        later bounded repair step consumes their durable artifacts.
        """
        if not self._specialist_orchestration_enabled():
            return
        run = self.service.get_run(run_id)
        quality = run.get("quality_report_json") or {}
        if quality.get("state") != "passed" or not run.get("candidate_sha"):
            return
        from ..core.design_contracts import (
            BuildTarget,
            DesignPlanBundle,
            PageBuildRequest,
            VisualCritiqueReport,
        )
        from .design_orchestration import SpecialistDesignCoordinator

        planning = run.get("planning_json") or {}
        request = PageBuildRequest.from_dict(planning.get("build_request") or {})
        request = self._hydrate_refinement_plan(run, request)
        target = BuildTarget.from_dict(planning.get("build_target") or {})
        plan_records = self.memory.list_design_phase_artifacts(
            run_id,
            phase="creative_selection",
            status="completed",
        )
        director_session_id = ""
        if plan_records:
            plan = DesignPlanBundle.from_dict(plan_records[-1]["payload"])
            director_session_id = str(plan_records[-1].get("session_id") or "")
        else:
            content = request.content if isinstance(request.content, Mapping) else {}
            locked_plan = content.get("specialist_locked_plan") if isinstance(content, Mapping) else None
            if not isinstance(locked_plan, Mapping):
                raise RuntimeError("specialist review requires a completed creative selection")
            plan = DesignPlanBundle.from_dict(locked_plan)
            director_session_id = str(content.get("specialist_creative_director_session_id") or "")
        screenshots = self.service._screenshot_evidence(quality)
        coordinator = SpecialistDesignCoordinator(self.context)
        review = coordinator.review_candidate(
            request,
            target,
            plan=plan,
            candidate_sha=str(run.get("candidate_sha") or ""),
            creative_director_session_id=director_session_id,
            screenshots=screenshots,
            quality_evidence={
                "state": quality.get("state"),
                "gates": quality.get("gates") or {},
                "findings": list(quality.get("findings") or ())[:100],
            },
        )
        signoff_state = "not_run"
        if review.needs_repair:
            repair_brief = coordinator.create_repair_brief(
                request,
                target,
                plan=plan,
                review=review,
            )
            if repair_brief is None:
                raise RuntimeError("specialist review requested repair without a repair brief")
            findings = []
            repair_plan = []
            for label, report in (
                ("creative_director", review.creative_review),
                ("experience", review.experience_review),
                ("technical", review.technical_review),
            ):
                payload = report.payload
                raw_findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
                findings.extend({"review": label, **dict(item)} for item in raw_findings[:24] if isinstance(item, Mapping))
                raw_plan = payload.get("repair_plan") if isinstance(payload.get("repair_plan"), list) else []
                repair_plan.extend({"review": label, **dict(item)} for item in raw_plan[:24] if isinstance(item, Mapping))
            critique = VisualCritiqueReport.from_dict({
                "run_id": run_id,
                "candidate_sha": str(run.get("candidate_sha") or ""),
                "model_id": "specialist-review-panel",
                "state": "repair",
                "findings": findings,
                "repair_plan": repair_plan or [{"change": repair_brief.payload.get("scope", "Apply the frozen repair brief.")}],
                "screenshot_evidence": screenshots,
            })
            if str(run.get("operation_kind") or "initial_build") == "initial_build":
                self.memory.transition_design_run(
                    run_id,
                    DesignRunStatus.NEEDS_REPAIR.value,
                    error="specialist review requires one bounded repair",
                )
                child = self.service.create_visual_refinement_run(
                    run_id,
                    critique,
                    repair_brief=repair_brief.payload,
                    locked_plan=plan.to_dict(),
                    creative_director_session_id=director_session_id,
                )
                child_run = child.get("run") or {}
                if child_run.get("run_id"):
                    self.enqueue(str(child_run["run_id"]))
                self.memory.add_design_run_event(
                    run_id,
                    "specialist_repair_queued",
                    "Queued the single bounded specialist repair child from the review panel.",
                    {"child_run_id": child_run.get("run_id"), "candidate_sha": run.get("candidate_sha")},
                )
            else:
                self.memory.transition_design_run(
                    run_id,
                    DesignRunStatus.NEEDS_REPAIR.value,
                    error="specialist review requires another explicit repair decision",
                )
                self.memory.add_design_run_event(
                    run_id,
                    "specialist_repair_limit",
                    "A refinement candidate still needs repair; no nested repair run was created.",
                    {"candidate_sha": run.get("candidate_sha")},
                )
        else:
            signoff = coordinator.final_signoff(
                request,
                target,
                plan=plan,
                review=review,
                creative_director_session_id=director_session_id,
            )
            signoff_state = str((signoff.payload or {}).get("state") or "").strip().lower()
            if signoff_state != "passed":
                self.memory.transition_design_run(
                    run_id,
                    DesignRunStatus.NEEDS_REPAIR.value,
                    error="specialist final sign-off did not pass",
                )
                self.memory.add_design_run_event(
                    run_id,
                    "specialist_signoff_blocked",
                    "The final creative-director sign-off did not pass; the candidate remains blocked from review approval.",
                    {
                        "candidate_sha": run.get("candidate_sha"),
                        "state": signoff_state or "missing",
                    },
                )
        self.memory.add_design_run_event(
            run_id,
            "specialist_reviews_completed",
            "Creative-director realization review and independent critic reviews completed.",
            {
                "candidate_sha": run.get("candidate_sha"),
                "needs_repair": review.needs_repair or signoff_state != "passed",
                "signoff_state": signoff_state,
                "phases": [
                    "creative_realization_review",
                    "experience_review",
                    "technical_review",
                ],
            },
        )

    @property
    def running(self) -> bool:
        """Whether this executor currently has a live worker thread."""
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._recover_queued()
        self._thread = threading.Thread(target=self._loop, name="design-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def enqueue(self, run_id: str) -> None:
        run_id = str(run_id).strip()
        with self._lock:
            if run_id in self._queued:
                return
            self._queued.add(run_id)
            self._queue.put(run_id)

    def _interrupt_after_restart(self, run: Mapping[str, Any], *, error: str) -> None:
        """Surface a run that cannot be safely resumed after a worker restart."""
        run_id = str(run.get("run_id") or "")
        try:
            self.memory.transition_design_run(
                run_id,
                DesignRunStatus.INTERRUPTED.value,
                error=error,
            )
            self.memory.add_design_run_event(
                run_id,
                "interrupted",
                "The design run was interrupted because its persisted work could not be recovered.",
                {"worker": self.worker},
            )
            self._activity(
                {**dict(run), "status": DesignRunStatus.INTERRUPTED.value},
                kind="design_run_interrupted",
                state="needs_attention",
                summary="Interrupted a design run whose persisted work could not be recovered after restart.",
                provenance="system",
                detail={"status": DesignRunStatus.INTERRUPTED.value},
            )
        except Exception:
            # A concurrent worker or a terminal transition may already have
            # won the race; normal execution will surface it.
            pass

    def _recover_queued(self) -> None:
        for run in self.service.list_runs(limit=500):
            events = run.get("events") or []
            latest_stage = events[-1].get("stage") if events else ""
            status = run.get("status")
            if status in {
                DesignRunStatus.CREATED.value,
                DesignRunStatus.ASSESSING_INTAKE.value,
                DesignRunStatus.PLANNING.value,
            } and latest_stage == "queued":
                self.enqueue(run["run_id"])
                continue
            if status == DesignRunStatus.PLANNING.value:
                planning = run.get("planning_json")
                request = planning.get("build_request") if isinstance(planning, Mapping) else None
                target = planning.get("build_target") if isinstance(planning, Mapping) else None
                if isinstance(request, Mapping) and isinstance(target, Mapping):
                    # A run can be persisted in planning without reaching the
                    # queued event when the process dies between planning and
                    # submission. Its typed request is enough to recover it.
                    self.enqueue(run["run_id"])
                else:
                    self._interrupt_after_restart(
                        run,
                        error="interrupted by Intake Lab restart; persisted planning payload was not recoverable",
                    )
                continue
            if not self.context.get("recover_retained_candidates"):
                continue
            if status in {DesignRunStatus.CANDIDATE_READY.value, DesignRunStatus.VALIDATING.value}:
                self.enqueue(run["run_id"])
            elif status == DesignRunStatus.BUILDING.value:
                self._interrupt_after_restart(
                    run,
                    error="interrupted by Intake Lab restart; generate a new run to retry",
                )

    def _hydrate_refinement_plan(self, run: Mapping[str, Any], request: PageBuildRequest) -> PageBuildRequest:
        """Load a parent refinement plan without duplicating it in child state."""
        if request.mode != "visual_refinement":
            return request
        content = request.content if isinstance(request.content, Mapping) else {}
        engine = (self.context.get("config") or {}).get("design_engine") or {}
        creative_orchestration = str(engine.get("orchestration") or "legacy").strip().lower() == "creative"
        if isinstance(content.get("specialist_locked_plan"), Mapping):
            if creative_orchestration:
                parent_run_id = str(run.get("parent_run_id") or "").strip()
                if not parent_run_id:
                    raise RuntimeError("creative repair requires a persisted hash-bound experience plan and parent run")
                try:
                    from ..core.design_contracts import ExperiencePlanBundle

                    forwarded = ExperiencePlanBundle.from_dict(content["specialist_locked_plan"])
                    persisted = self._creative_locked_plan_for_run(parent_run_id)
                    expected_hash = str(content.get("specialist_locked_plan_hash") or "").strip().lower()
                    if persisted is None or forwarded.content_hash != persisted.content_hash:
                        raise ValueError("the forwarded plan does not match the persisted parent plan")
                    if expected_hash and forwarded.content_hash != expected_hash:
                        raise ValueError("the forwarded plan hash does not match the plan")
                except Exception as exc:  # noqa: BLE001 - a malformed locked plan must fail closed
                    raise RuntimeError(f"creative repair requires a valid hash-bound experience plan: {exc}") from exc
            return request
        if (
            not creative_orchestration
            and not isinstance(content.get("specialist_repair_brief"), Mapping)
            and not isinstance(content.get("specialist_locked_plan_ref"), Mapping)
        ):
            return request
        parent_run_id = str(run.get("parent_run_id") or "").strip()
        if not parent_run_id:
            if creative_orchestration:
                raise RuntimeError("creative repair requires a persisted hash-bound experience plan and parent run")
            return request
        if creative_orchestration:
            plan = self._creative_locked_plan_for_run(parent_run_id)
            if plan is None:
                raise RuntimeError("creative repair requires a persisted hash-bound experience plan")
            request_data = request.to_dict()
            request_content = dict(content)
            request_content["specialist_locked_plan"] = plan.to_dict()
            request_content["specialist_locked_plan_hash"] = plan.content_hash
            request_data["content"] = request_content
            return PageBuildRequest.from_dict(request_data)
        try:
            from ..core.design_contracts import DesignPlanBundle

            records = self.memory.list_design_phase_artifacts(
                parent_run_id,
                phase="creative_selection",
                status="completed",
            )
            if not records:
                return request
            plan = DesignPlanBundle.from_dict(records[-1].get("payload") or {})
            request_data = request.to_dict()
            request_content = dict(content)
            request_content["specialist_locked_plan"] = plan.to_dict()
            request_data["content"] = request_content
            return PageBuildRequest.from_dict(request_data)
        except Exception:
            # The repair brief remains actionable without a plan only for
            # legacy candidates; do not make state recovery fail a whole run.
            return request

    def _creative_locked_plan_for_run(self, run_id: str):
        """Return the immutable creative plan that a repair must preserve.

        Creative builds persist the raw ``ExperiencePlanBundle`` in planning
        state. Specialist-era runs persist a phase envelope instead, so the
        service's compatibility loader remains the fallback for those records.
        In either case, a repair may only receive a plan whose identity and
        recorded content hash match the parent run.
        """
        from ..core.design_contracts import ExperiencePlanBundle

        safe_id = str(run_id or "").strip()
        if not safe_id:
            return None
        source = self.memory.get_design_run(safe_id)
        if not isinstance(source, Mapping):
            return None
        planning = source.get("planning_json") if isinstance(source.get("planning_json"), Mapping) else {}

        # Repair/refinement children intentionally change the build and context
        # identities: each one is built from its parent's immutable candidate
        # and its snapshot is rebound to that candidate. The locked experience
        # plan is different. Its identity fields and content hash belong to the
        # original planning run and remain unchanged across repair generations.
        # Walk the persisted lineage before falling back to the service
        # compatibility loader so validation is against the plan origin, not
        # the immediate child.
        lineage: list[Mapping[str, Any]] = []
        lineage_by_id: dict[str, Mapping[str, Any]] = {}
        current_id = safe_id
        current: Mapping[str, Any] | None = source
        seen_ids: set[str] = set()
        while current is not None and current_id not in seen_ids:
            seen_ids.add(current_id)
            resolved_id = str(current.get("run_id") or current_id).strip()
            if resolved_id:
                lineage.append(current)
                lineage_by_id[resolved_id] = current
            current_id = str(current.get("parent_run_id") or "").strip()
            if not current_id:
                break
            parent = self.memory.get_design_run(current_id)
            current = parent if isinstance(parent, Mapping) else None

        plan = None
        raw_plan_owner: Mapping[str, Any] | None = None
        for lineage_item in lineage:
            lineage_planning = lineage_item.get("planning_json")
            if not isinstance(lineage_planning, Mapping):
                continue
            raw_plan = lineage_planning.get("experience_plan")
            if not isinstance(raw_plan, Mapping):
                continue
            try:
                plan = ExperiencePlanBundle.from_dict(raw_plan)
            except Exception as exc:  # noqa: BLE001 - preserve a typed repair failure
                raise RuntimeError(f"creative repair requires a valid hash-bound experience plan: {exc}") from exc
            raw_plan_owner = lineage_item
            break
        else:
            loader = getattr(self.service, "_experience_plan_for_run", None)
            if callable(loader):
                try:
                    loaded = loader(safe_id)
                except Exception as exc:  # noqa: BLE001 - preserve the durable failure boundary
                    raise RuntimeError(f"creative repair could not load its hash-bound experience plan: {exc}") from exc
                if loaded is not None:
                    try:
                        plan = loaded if isinstance(loaded, ExperiencePlanBundle) else ExperiencePlanBundle.from_dict(loaded)
                    except Exception as exc:  # noqa: BLE001 - preserve a typed repair failure
                        raise RuntimeError(f"creative repair requires a valid hash-bound experience plan: {exc}") from exc
        if plan is None:
            return None

        plan_origin = lineage_by_id.get(str(plan.run_id).strip())
        if plan_origin is None:
            raise RuntimeError(
                "creative repair requires a valid hash-bound experience plan: plan origin is not in the parent lineage"
            )
        expected_hashes: list[str] = []
        for owner in (raw_plan_owner, plan_origin):
            owner_planning = owner.get("planning_json") if isinstance(owner, Mapping) else None
            if isinstance(owner_planning, Mapping):
                expected_hash = str(owner_planning.get("experience_plan_hash") or "").strip().lower()
                if expected_hash and expected_hash not in expected_hashes:
                    expected_hashes.append(expected_hash)
        if any(plan.content_hash != expected_hash for expected_hash in expected_hashes):
            raise RuntimeError("creative repair requires a valid hash-bound experience plan: stored hash does not match")
        origin_base_sha = str(plan_origin.get("base_sha") or "").strip().lower()
        if origin_base_sha and plan.base_sha != origin_base_sha:
            raise RuntimeError("creative repair requires a valid hash-bound experience plan: base identity does not match")
        origin_context_hash = str(plan_origin.get("context_snapshot_hash") or "").strip().lower()
        if origin_context_hash and plan.context_snapshot_hash != origin_context_hash:
            raise RuntimeError(
                "creative repair requires a valid hash-bound experience plan: context identity does not match"
            )
        return plan

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._run(run_id)
            finally:
                with self._lock:
                    self._queued.discard(run_id)
                self._queue.task_done()

    def _run(self, run_id: str) -> None:
        try:
            run = self.service.get_run(run_id)
            self._activity(
                run,
                kind="design_run_started",
                state="started",
                summary="Started the isolated design candidate and its quality checks.",
                provenance="system",
                detail={"status": str(run.get("status") or "")},
            )
            self.memory.add_design_run_event(run_id, "claimed", "Design run claimed by the durable worker.", {
                "worker": self.worker,
                "conversation_id": run.get("conversation_id"),
                "source_message_id": run.get("source_message_id"),
                "chat_job_id": run.get("chat_job_id"),
            })
            if run.get("candidate_sha") and run.get("status") in {
                DesignRunStatus.CANDIDATE_READY.value,
                DesignRunStatus.VALIDATING.value,
            }:
                self._validate_retained(run_id, run)
                self._finish_validation(run_id)
                return
            planning = run.get("planning_json") or {}
            request = PageBuildRequest.from_dict(planning.get("build_request") or {})
            request = self._hydrate_refinement_plan(run, request)
            target = BuildTarget.from_dict(planning.get("build_target") or {})

            def progress(message: str) -> None:
                text = str(message)[:500]
                self.memory.add_design_run_event(run_id, "progress", text)
                self._activity(
                    run,
                    kind="design_progress",
                    state="progress",
                    summary=text,
                    provenance="system",
                    detail={"status": "building"},
                )

            self.service.execute_build(run_id, request, target, progress=progress)
            built = self.service.get_run(run_id)
            if built.get("candidate_sha") and built.get("status") in {
                DesignRunStatus.CANDIDATE_READY.value,
                DesignRunStatus.VALIDATING.value,
            }:
                self._validate_retained(run_id, built)
            elif built.get("status") not in {
                DesignRunStatus.FAILED.value,
                DesignRunStatus.CANCELLED.value,
                DesignRunStatus.NEEDS_REPAIR.value,
                DesignRunStatus.INCOMPLETE.value,
                DesignRunStatus.READY_FOR_REVIEW.value,
            }:
                browser = self._browser_for_run(run_id, built)
                validation_kwargs = {"browser": browser}
                if self.context.get("build_env") is not None:
                    validation_kwargs["build_env"] = self.context["build_env"]
                self.service.validate_run(
                    run_id,
                    self.service.clone_path_for_run(run_id),
                    **validation_kwargs,
                )
                if self.service.get_run(run_id).get("status") == DesignRunStatus.VALIDATING.value:
                    self._run_visual_review_if_pending(run_id)
            elif built.get("candidate_sha"):
                # Completed candidates are served from the retained output
                # artifact. A separate post-build live clone would make the
                # owner surface diverge from the bytes just validated.
                pass
            self._finish_validation(run_id)
        except Exception as exc:  # noqa: BLE001 — persist failure and keep worker alive
            try:
                run = self.memory.get_design_run(run_id)
                if run and run["status"] not in {
                    DesignRunStatus.FAILED.value,
                    DesignRunStatus.CANCELLED.value,
                    DesignRunStatus.READY_FOR_REVIEW.value,
                    DesignRunStatus.NEEDS_REPAIR.value,
                    DesignRunStatus.INCOMPLETE.value,
                }:
                    self.memory.transition_design_run(run_id, DesignRunStatus.FAILED.value, error=str(exc))
                    self.memory.add_design_run_event(run_id, "failed", "The queued design job failed.", {
                        "error": str(exc)[:500],
                        "worker": self.worker,
                    })
            except Exception:
                pass
        finally:
            self._record_final_activity(run_id)

    def _activity(
        self,
        run: Mapping[str, Any],
        *,
        kind: str,
        state: str,
        summary: str,
        provenance: str,
        confidence: float | None = None,
        detail: Mapping[str, Any] | None = None,
        activity_id: str | None = None,
    ) -> None:
        if self.activity_service is None:
            return
        try:
            self.activity_service.record(
                activity_id=activity_id,
                category="quality" if kind == "quality_checks_completed" else "design",
                kind=kind,
                state=state,
                summary=summary,
                provenance=provenance,
                confidence=confidence,
                detail=detail,
                conversation_id=run.get("conversation_id"),
                message_id=run.get("source_message_id"),
                chat_job_id=run.get("chat_job_id"),
                intake_session_id=run.get("intake_session_id"),
                intake_revision=run.get("intake_revision_id"),
                design_run_id=run.get("run_id"),
            )
        except Exception:
            # Activity is diagnostic; a ledger problem must not kill the build worker.
            pass

    def _record_final_activity(self, run_id: str) -> None:
        if self.activity_service is None:
            return
        try:
            run = self.service.get_run(run_id)
        except Exception:
            return
        status = str(run.get("status") or "")
        if status == DesignRunStatus.READY_FOR_REVIEW.value:
            state = "completed"
            summary = "Completed deterministic and visual quality checks; the candidate is ready for owner review."
            quality_state = "passed"
        elif status in {
            DesignRunStatus.NEEDS_REPAIR.value,
            DesignRunStatus.INCOMPLETE.value,
            DesignRunStatus.FAILED.value,
            DesignRunStatus.INTERRUPTED.value,
        }:
            state = "needs_attention"
            summary = "Design quality checks need attention before this candidate can be reviewed."
            quality_state = "needs_attention"
        else:
            return
        activity_id = "activity_" + hashlib.sha256(f"{run_id}:quality:{status}".encode("utf-8")).hexdigest()
        self._activity(
            run,
            kind="quality_checks_completed",
            state=state,
            summary=summary,
            provenance="host_validation",
            detail={"status": status, "quality_state": quality_state},
            activity_id=activity_id,
        )

    def _finish_validation(self, run_id: str) -> None:
        """Run required reviews and the bounded host-evidence repair handoff.

        Visual review is read-only and never creates a refinement child. A
        crashed required review must never leave a candidate looking reviewable;
        the run is downgraded to ``incomplete`` instead.
        """
        if self.service.get_run(run_id).get("status") in {
            DesignRunStatus.READY_FOR_REVIEW.value,
            DesignRunStatus.VALIDATING.value,
        }:
            try:
                self._run_specialist_reviews_if_ready(run_id)
            except Exception as exc:  # noqa: BLE001 - a required role failure must not look reviewable
                current = self.service.get_run(run_id)
                if current.get("status") in {
                    DesignRunStatus.READY_FOR_REVIEW.value,
                    DesignRunStatus.VALIDATING.value,
                }:
                    self.memory.transition_design_run(
                        run_id,
                        DesignRunStatus.INCOMPLETE.value,
                        error=f"required specialist review failed: {str(exc)[:400]}",
                    )
                    self.memory.add_design_run_event(
                        run_id,
                        "specialist_review_incomplete",
                        "A required specialist review did not complete; the candidate is not reviewable.",
                        {"error": str(exc)[:500], "candidate_sha": current.get("candidate_sha")},
                    )
        self._queue_host_evidence_repair_if_needed(run_id)
        self._link_review_draft_if_ready(run_id)

    def finish_validation(self, run_id: str) -> None:
        """Complete the durable post-validation handoff for revalidation callers.

        Normal queued builds already pass through this step in ``_run``. The
        explicit host-revalidation endpoint must use the same handoff so a
        failed deterministic gate can still produce Ada's single bounded
        host-evidence repair child instead of stopping at a manually initiated
        retry. Visual review remains an explicit read-only diagnostic and does
        not create a refinement child automatically.
        """
        safe_id = str(run_id or "").strip()
        self._run_visual_review_if_pending(safe_id)
        self._finish_validation(safe_id)

    def _locked_plan_for_run(self, run_id: str) -> dict[str, Any] | None:
        """Return the persisted locked plan for a run, when one exists."""
        engine = (self.context.get("config") or {}).get("design_engine") or {}
        if str(engine.get("orchestration") or "legacy").strip().lower() == "creative":
            try:
                plan = self._creative_locked_plan_for_run(run_id)
            except RuntimeError:
                # The child build will fail closed during hydration. Do not let
                # a malformed parent plan escape the durable repair handoff.
                plan = None
            if plan is not None:
                return plan.to_dict()
            return None
        from ..core.design_contracts import DesignPlanBundle

        records = self.memory.list_design_phase_artifacts(
            run_id,
            phase="creative_selection",
            status="completed",
        )
        if not records:
            return None
        try:
            return DesignPlanBundle.from_dict(records[-1]["payload"]).to_dict()
        except Exception:  # noqa: BLE001 - a repair may proceed from host evidence alone
            return None

    def _host_render_bundle(self, run: Mapping[str, Any]) -> dict[str, Any]:
        """Compact, immutable description of what the host actually rendered.

        This is the evidence Ada's bounded repair turn works from. It is data,
        never instructions, and it is derived only from the host quality report
        so a claim in the candidate cannot manufacture its own proof.
        """
        quality = run.get("quality_report_json") or {}
        evidence = quality.get("evidence") if isinstance(quality, Mapping) else {}
        evidence = evidence if isinstance(evidence, Mapping) else {}
        browser = evidence.get("browser") if isinstance(evidence.get("browser"), Mapping) else {}
        screenshots: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        console_errors: list[Any] = []
        failed_requests: list[Any] = []
        for viewport_item in browser.get("viewports") or ():
            if not isinstance(viewport_item, Mapping):
                continue
            viewport = viewport_item.get("viewport") if isinstance(viewport_item.get("viewport"), Mapping) else {}
            result = viewport_item.get("result") if isinstance(viewport_item.get("result"), Mapping) else {}
            console_errors.extend(result.get("console_errors") or ())
            failed_requests.extend(result.get("failed_requests") or ())
            for route in result.get("routes") or ():
                if not isinstance(route, Mapping):
                    continue
                path = str(route.get("screenshot_path") or "").strip()
                if path and path not in seen_paths:
                    seen_paths.add(path)
                    screenshots.append({
                        "route": str(route.get("route") or ""),
                        "viewport": dict(viewport),
                        "screenshot_path": path,
                        "screenshot_hash": str(route.get("screenshot_hash") or ""),
                        "phase": "resting",
                    })
                interaction = route.get("interaction_state") if isinstance(route.get("interaction_state"), Mapping) else {}
                visual = interaction.get("visual") if isinstance(interaction.get("visual"), Mapping) else {}
                for key, phase in (
                    ("before_screenshot_path", "before"),
                    ("intermediate_screenshot_path", "intermediate"),
                    ("after_screenshot_path", "after"),
                ):
                    candidate = str(visual.get(key) or "").strip()
                    if candidate and candidate not in seen_paths:
                        seen_paths.add(candidate)
                        screenshots.append({
                            "route": str(route.get("route") or ""),
                            "viewport": dict(viewport),
                            "screenshot_path": candidate,
                            "phase": phase,
                        })
        findings = [
            dict(item)
            for item in (quality.get("findings") or ())
            if isinstance(item, Mapping)
        ]
        return {
            "candidate_sha": str(run.get("candidate_sha") or ""),
            "quality_state": str(quality.get("state") or ""),
            "gates": dict(quality.get("gates") or {}),
            "findings": findings[:50],
            "screenshots": screenshots[:12],
            "motion": dict(evidence.get("motion") or {}) if isinstance(evidence.get("motion"), Mapping) else {},
            "experience_journey": dict(evidence.get("experience_journey") or {}) if isinstance(evidence.get("experience_journey"), Mapping) else {},
            "temporal": dict(evidence.get("temporal") or {}) if isinstance(evidence.get("temporal"), Mapping) else {},
            "console_errors": console_errors[:20],
            "failed_requests": failed_requests[:20],
        }

    def _host_evidence_critique(self, run_id: str, run: Mapping[str, Any], bundle: Mapping[str, Any]):
        """Turn deterministic host findings into one actionable typed critique."""
        from ..core.design_contracts import VisualCritiqueReport

        findings: list[dict[str, Any]] = []
        for item in bundle.get("findings") or ():
            if not isinstance(item, Mapping):
                continue
            conditions = list(item.get("missing_condition_ids") or ())
            if not conditions and item.get("signature_behavior_id"):
                conditions = [str(item["signature_behavior_id"])]
            findings.append({
                "severity": str(item.get("severity") or "blocker")[:30],
                "category": str(item.get("gate") or "experience")[:60],
                "code": str(item.get("code") or "")[:80],
                "message": str(item.get("message") or "The locked experience was not realized.")[:400],
                "conditions": conditions[:32],
            })
        repair_plan: list[dict[str, Any]] = []
        for item in findings:
            repair_plan.append({
                "finding": item.get("code") or "fidelity_defect",
                "change": item.get("message") or "Realize the locked condition in the visible rendered behavior.",
                "conditions": item.get("conditions") or [],
            })
        if not repair_plan:
            repair_plan = [{
                "finding": "fidelity_defect",
                "change": "Realize the locked experience in the visible rendered behavior.",
                "conditions": [],
            }]
        return VisualCritiqueReport.from_dict({
            "run_id": run_id,
            "candidate_sha": str(run.get("candidate_sha") or ""),
            "model_id": "host-deterministic-evidence",
            "state": "repair",
            "findings": findings[:50],
            "repair_plan": repair_plan[:50],
            "screenshot_evidence": list(bundle.get("screenshots") or ()),
        })

    def _host_repair_brief(self, run: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
        """A compact, plan-bound repair brief derived from host runtime evidence.

        The full measurements remain in the durable quality report; the brief
        carries only the failed conditions and a compact status summary so the
        child's persisted planning payload stays bounded. The rendered
        screenshots travel separately through the critique's
        ``screenshot_evidence``.
        """
        motion = bundle.get("motion") if isinstance(bundle.get("motion"), Mapping) else {}
        temporal = bundle.get("temporal") if isinstance(bundle.get("temporal"), Mapping) else {}
        journey = bundle.get("experience_journey") if isinstance(bundle.get("experience_journey"), Mapping) else {}
        return {
            "source": "host_deterministic_evidence",
            "candidate_sha": str(run.get("candidate_sha") or ""),
            "summary": "Host runtime evidence found the locked experience was not realized in the rendered candidate.",
            "failed_gates": {
                str(key): value
                for key, value in (bundle.get("gates") or {}).items()
                if value not in {"passed", "skipped", None}
            },
            "failed_findings": [
                {
                    "code": item.get("code"),
                    "gate": item.get("gate"),
                    "message": item.get("message"),
                    "missing_condition_ids": item.get("missing_condition_ids"),
                    "signature_behavior_id": item.get("signature_behavior_id"),
                }
                for item in (bundle.get("findings") or ())
                if isinstance(item, Mapping)
            ][:50],
            "requirements": [
                "Realize the locked experience in the visible rendered behavior at every required viewport.",
                "Preserve the locked plan, composition, copy, and concept; do not introduce a second concept.",
                "The host will re-render and re-validate this candidate; a coverage claim is not proof.",
            ],
            "render_status": {
                "motion": str(motion.get("status") or ""),
                "temporal": str(temporal.get("status") or ""),
                "experience_journey": str(journey.get("status") or ""),
                "console_error_count": len(bundle.get("console_errors") or ()),
                "failed_request_count": len(bundle.get("failed_requests") or ()),
                "screenshot_count": len(bundle.get("screenshots") or ()),
            },
        }

    def _queue_host_evidence_repair_if_needed(self, run_id: str) -> None:
        """Queue the single bounded Ada repair when host evidence finds a defect.

        The behavior-system plan requires exactly this handoff: host runtime
        evidence -> Ada experience-fidelity repair -> one plan-bound child,
        then stop. It only applies to an initial build; a repaired child never
        nests another repair.
        """
        run = self.service.get_run(run_id)
        if str(run.get("operation_kind") or "initial_build") != "initial_build":
            return
        if not run.get("candidate_sha"):
            return
        if run.get("status") not in {
            DesignRunStatus.NEEDS_REPAIR.value,
            DesignRunStatus.INCOMPLETE.value,
        }:
            return
        quality = run.get("quality_report_json") or {}
        if not isinstance(quality, Mapping) or quality.get("state") not in {"failed", "incomplete"}:
            return
        config = self.context.get("config") or {}
        engine = config.get("design_engine") or {}
        if int(engine.get("repair_attempts", 0) or 0) < 1:
            return
        existing = [
            item
            for item in self.memory.list_design_run_children(run_id, limit=500)
            if item.get("operation_kind") == "visual_refinement"
        ]
        if any(
            item.get("status") not in {DesignRunStatus.FAILED.value, DesignRunStatus.CANCELLED.value}
            for item in existing
        ):
            return
        bundle = self._host_render_bundle(run)
        critique = self._host_evidence_critique(run_id, run, bundle)
        repair_brief = self._host_repair_brief(run, bundle)
        locked_plan = self._locked_plan_for_run(run_id)
        try:
            child = self.service.create_visual_refinement_run(
                run_id,
                critique,
                repair_brief=repair_brief,
                locked_plan=locked_plan,
                host_evidence_repair=True,
            )
        except Exception as exc:  # noqa: BLE001 - never strand the parent on a repair-plumbing failure
            self.memory.add_design_run_event(
                run_id,
                "host_evidence_repair_error",
                "Host evidence found a fidelity defect but the bounded repair could not be queued.",
                {"error": str(exc)[:500], "candidate_sha": run.get("candidate_sha")},
            )
            return
        child_run = child.get("run") or {}
        if child_run.get("run_id"):
            self.enqueue(str(child_run["run_id"]))
        self.memory.add_design_run_event(
            run_id,
            "host_evidence_repair_queued",
            "Queued the single bounded Ada experience-fidelity repair from host runtime evidence.",
            {"child_run_id": child_run.get("run_id"), "candidate_sha": run.get("candidate_sha")},
        )

    def _browser_for_run(self, run_id: str, run: Mapping[str, Any]):
        factory = self.context.get("browser_quality_factory")
        if callable(factory):
            try:
                return factory(run_id, run)
            except Exception as exc:  # noqa: BLE001 - persist bounded adapter diagnostics
                self.memory.add_design_run_event(
                    run_id,
                    "browser_adapter_error",
                    "Browser quality adapter could not be created.",
                    {"error": str(exc)[:500], "worker": self.worker},
                )
                raise
        return self.context.get("browser_quality")

    def _validate_retained(self, run_id: str, run: Mapping[str, Any]) -> None:
        """Validate a retained candidate without ever invoking OpenCode again."""
        status = str(run.get("status") or "")
        if status == DesignRunStatus.CANDIDATE_READY.value:
            browser = self._browser_for_run(run_id, run)
            validation_kwargs = {"browser": browser}
            if self.context.get("build_env") is not None:
                validation_kwargs["build_env"] = self.context["build_env"]
            self.service.validate_run(
                run_id,
                self.service.clone_path_for_run(run_id),
                **validation_kwargs,
            )
            run = self.service.get_run(run_id)
        elif status != DesignRunStatus.VALIDATING.value:
            return

        current = self.service.get_run(run_id)
        if current.get("status") != DesignRunStatus.VALIDATING.value:
            return
        pending_visual_review = any(
            isinstance(event, Mapping) and event.get("stage") == "visual_review_pending"
            for event in (current.get("events") or ())
        )
        if pending_visual_review and (current.get("quality_report_json") or {}).get("state") == "passed":
            self._run_visual_review_if_pending(run_id)
            return
        browser = self._browser_for_run(run_id, current)
        validation_kwargs = {"browser": browser}
        if self.context.get("build_env") is not None:
            validation_kwargs["build_env"] = self.context["build_env"]
        self.service.validate_run(
            run_id,
            self.service.clone_path_for_run(run_id),
            **validation_kwargs,
        )
        if self.service.get_run(run_id).get("status") == DesignRunStatus.VALIDATING.value:
            self._run_visual_review_if_pending(run_id)


__all__ = ["DesignJobExecutor"]
