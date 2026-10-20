"""Small, read-only account of delegated work for the conversation orchestrator."""
from __future__ import annotations

from typing import Any


def conversation_tasks(context: dict[str, Any]) -> list[dict[str, Any]]:
    memory = context['memory']
    current_id = context.get('_chat_job_id')
    if current_id is None:
        return []
    current = memory.get_chat_job(int(current_id))
    if not current or current.get('conversation_id') is None:
        return []
    tasks = []
    for job in memory.list_chat_jobs(current['conversation_id'], limit=7):
        if job['id'] == current_id:
            continue
        result = job.get('result') or {}
        failure = result.get('failure') or {}
        boundary = failure.get('boundary')
        if job['status'] == 'error' and not boundary:
            boundary = 'source_scope' if 'outside the writable sandbox' in str(job.get('error') or '') else 'execution'
        tasks.append({
            'job_id': job['id'], 'status': job['status'],
            'started_at': job['created_ts'], 'updated_at': job['updated_ts'],
            'latest_progress': [{'ts': step.get('ts'), 'text': str(step.get('text') or '')[:300]}
                                for step in (job.get('steps') or [])[-2:]],
            'failure_boundary': boundary,
            'draft_id': result.get('merge_draft_id') or result.get('proposal_id'),
            'preview_status': (result.get('preview') or {}).get('status'),
        })
    return tasks
