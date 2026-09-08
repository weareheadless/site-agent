"""Single-worker execution for durable typed design builds."""

from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections.abc import Mapping
from typing import Any

from ..core.design_contracts import BuildTarget, DesignRunStatus, PageBuildRequest
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

    def _run_visual_review_if_pending(self, run_id: str) -> None:
        """Run only the configured read-only visual gate; never mutate code."""
        run = self.service.get_run(run_id)
        pending = any(
            isinstance(event, Mapping) and event.get("stage") == "visual_review_pending"
            for event in (run.get("events") or ())
        )
        if not pending:
            return
        reviewer = getattr(self.service, "visual_review_run", None)
        if not callable(reviewer):
            return
        reviewer(
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
            if not self.context.get("recover_retained_candidates"):
                continue
            if status in {DesignRunStatus.CANDIDATE_READY.value, DesignRunStatus.VALIDATING.value}:
                self.enqueue(run["run_id"])
            elif status == DesignRunStatus.BUILDING.value:
                try:
                    self.memory.transition_design_run(
                        run["run_id"],
                        DesignRunStatus.INTERRUPTED.value,
                        error="interrupted by Intake Lab restart; generate a new run to retry",
                    )
                    self.memory.add_design_run_event(
                        run["run_id"],
                        "interrupted",
                        "The in-progress build was interrupted by a worker restart.",
                        {"worker": self.worker},
                    )
                    self._activity(
                        {**run, "status": DesignRunStatus.INTERRUPTED.value},
                        kind="design_run_interrupted",
                        state="needs_attention",
                        summary="Interrupted an in-progress design run after the worker restarted.",
                        provenance="system",
                        detail={"status": DesignRunStatus.INTERRUPTED.value},
                    )
                except Exception:
                    # A concurrent worker or a terminal transition may already
                    # have won the race; normal execution will surface it.
                    pass

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
                self._link_review_draft_if_ready(run_id)
                return
            planning = run.get("planning_json") or {}
            request = PageBuildRequest.from_dict(planning.get("build_request") or {})
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
            if self.service.get_run(run_id).get("status") in {
                DesignRunStatus.READY_FOR_REVIEW.value,
                DesignRunStatus.VALIDATING.value,
            }:
                self._run_specialist_reviews_if_ready(run_id)
            self._link_review_draft_if_ready(run_id)
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
