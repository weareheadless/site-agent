"""Journal setup state used by the admin transport and Design UI."""

from __future__ import annotations

from typing import Any


def setup_job(memory: Any) -> dict[str, Any] | None:
    """Find the durable journal setup job, including legacy records."""
    job_id = memory.kv_get("journal_setup_job_id")
    if job_id:
        job = memory.get_chat_job(int(job_id))
        if job:
            return job
    for conversation in memory.list_conversations(limit=100):
        if conversation.get("title") != "Set up Ada's journal":
            continue
        jobs = memory.list_chat_jobs(conversation["id"], limit=20)
        if jobs:
            return jobs[0]
    return None


def status(config: dict[str, Any], memory: Any) -> dict[str, Any]:
    """Return stable journal state for the UI without exposing route concerns."""
    blog = config.get("blog") or {}
    configured = bool(blog.get("journal_enabled", False))
    enabled = bool(memory.kv_get("journal_enabled", configured))
    requested = bool(memory.kv_get("journal_setup_requested", False))
    site_url = str(
        blog.get("site_url") or (config.get("site") or {}).get("preview_url") or ""
    ).strip().rstrip("/")
    job = setup_job(memory) if requested else None
    raw_status = job["status"] if job else "not_started"
    setup_status = "failed" if raw_status == "error" else raw_status
    result = job.get("result") if job else None
    result = result if isinstance(result, dict) else {}
    draft_id = result.get("merge_draft_id")
    draft = next(
        (item for item in memory.list_drafts(limit=100) if item["id"] == draft_id),
        None,
    ) if draft_id else None
    error = job.get("error") if job else None
    if setup_status == "done" and not draft_id:
        setup_status = "failed"
        error = error or "Ada finished without creating a journal design preview."
    elif setup_status == "done" and draft is None:
        setup_status = "failed"
        error = error or "Ada finished with a missing journal design draft."
    steps = job.get("steps") or [] if job else []
    return {
        "pelican": str(blog.get("engine", "pelican")).lower() == "pelican",
        "enabled": enabled,
        "setup_requested": requested,
        "setup_status": setup_status,
        "setup_job_id": job.get("id") if job else None,
        "setup_draft_id": draft_id,
        "setup_draft_status": draft.get("status") if draft else None,
        "setup_error": error,
        "setup_step": steps[-1].get("text") if steps else "",
        "journal_url": f"{site_url}/articles.html" if site_url else "",
        "schedule": (config.get("schedule") or {}).get("article"),
    }
