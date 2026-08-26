"""chat_jobs.py — persistent, background execution of admin chat jobs.

A chat job is any owner message that may take minutes (a heavy build that
creates a whole page). Jobs are persisted in the DB (`chat_jobs` table) so
they survive a closed browser tab. A server restart marks in-progress work
interrupted; it is never replayed implicitly.

Execution model
---------------
- Jobs are stored with a status: queued -> running -> done | error.
- One worker runs in the admin app's FastAPI lifespan. Claims are persisted so
  the browser can reconnect, while the shared site clone remains single-owner.
"""

from __future__ import annotations

import threading
import time
from typing import Any

def _job_worker_id() -> str:
    return f"{time.time_ns()}-{threading.get_ident()}"


def run_job(context: dict[str, Any], job: dict[str, Any], worker: str,
            adapter_factory=None) -> dict[str, Any]:
    """Execute one claimed chat job and persist its outcome. Best-effort: a
    failure is recorded on the job, never raised to the caller (the poll loop
    keeps going)."""
    memory = context["memory"]
    job_id = job["id"]
    message = job["message"]
    conv_id = job["conversation_id"]

    def progress(text: str) -> None:
        memory.append_chat_job_step(job_id, worker, text)

    try:
        message_id = job.get("message_id")
        if message_id is not None:
            source_history = memory.get_messages_before(conv_id, int(message_id), limit=8)
        else:
            # Jobs created before schema v7 have no message id. Keep their old
            # behavior while all newly enqueued jobs use the precise snapshot.
            source_history = memory.get_messages(conv_id, limit=8)
            if source_history and source_history[-1]["role"] == "user" and source_history[-1]["text"] == message:
                source_history = source_history[:-1]
            else:
                # v6 queued jobs did not persist their user message at enqueue.
                memory.add_message(conv_id, "user", message)
        history = [{"role": m["role"], "content": m["text"]} for m in source_history]
        context["persona_prompt"] = context.get("persona_prompt") or ""

        if message.startswith("Set up the customer-facing journal for this website."):
            # Journal activation is a native OpenCode Build session. The runner
            # owns only the preview sandbox and objective validation.
            from ..hands import opencode_runner
            result = opencode_runner.stage_build(
                context, opencode_runner.normalize_journal_message(message), progress
            )
        else:
            from ..brain import editor as brain_editor

            if adapter_factory is None:
                from ..hands.base import get_adapter

                name = str((context["config"].get("site") or {}).get("adapter", "github_static"))
                adapter = get_adapter(name, context["config"])
            else:
                adapter = adapter_factory()
            result = brain_editor.handle_message(
                context, adapter, message, history, progress=progress
            )

        if result.get("build_brief"):
            from ..hands.base import get_adapter
            from ..hands import opencode_runner as runner

            outcome = runner.stage_build(context, result["build_brief"], progress)
            result["reply"] = outcome["reply"]
            result["merge_draft_id"] = outcome["merge_draft_id"]
        if result.get("error"):
            raise RuntimeError(str(result.get("reply") or "chat job failed")[:300])

        result["conversation_id"] = conv_id

        tail = f" -> proposal #{result['proposal_id']}" if result.get("proposal_id") else ""
        if result.get("merge_draft_id"):
            tail += f" -> merge draft #{result['merge_draft_id']}"
        memory.record_action("chat", f"conv#{conv_id}: {message[:60]}{tail}")

        if not memory.complete_chat_job(job_id, worker, result):
            raise RuntimeError("chat job ownership was lost before completion")
        return result
    except Exception as exc:  # noqa: BLE001 — a failing job must not kill the loop
        memory.fail_chat_job(job_id, worker, str(exc)[:300])
        return {"error": str(exc)[:300]}


class ChatJobExecutor:
    """The single admin-process worker for persisted chat jobs."""

    def __init__(self, context: dict[str, Any], adapter_factory=None) -> None:
        self.context = context
        self.memory = context["memory"]
        self.worker = _job_worker_id()
        self._adapter_factory = adapter_factory
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                # Wait for an LLM before claiming work (serve may start before the
                # client is ready / tests set llm after create_app).
                if self.context.get("llm") is None:
                    self._stop.wait(2.0)
                    continue
                job = self.memory.claim_chat_job(self.worker)
                if job is None:
                    self._stop.wait(2.0)
                    continue
                self._run_claimed(job)
            except Exception as exc:  # noqa: BLE001 — never let the worker thread die
                try:
                    self.memory.record_action("chat_worker_error", str(exc)[:300])
                except Exception:  # noqa: BLE001 — the database may be closing
                    pass
                self._stop.wait(2.0)

    def _run_claimed(self, job: dict[str, Any]) -> None:
        try:
            run_job(self.context, job, self.worker, self._adapter_factory)
        except Exception as exc:  # noqa: BLE001 — persist unexpected worker failures
            try:
                self.memory.fail_chat_job(job["id"], self.worker, str(exc)[:300])
            except Exception:  # noqa: BLE001
                pass
