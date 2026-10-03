"""One read-only queue joins existing work; it is not another task store."""
from __future__ import annotations

from typing import Any
from ..core.contracts import safe_provider_message


def growth_tasks(memory, initiatives, drafts, activities, outcomes, runs=(), article_ideas=()) -> list[dict[str, Any]]:
    actions = {row.id: row.to_record() for row in memory.list_owner_actions(limit=None)}
    draft_by_id = {row['id']: row for row in drafts}
    linked_actions, linked_drafts, linked_approvals, tasks = set(), set(), set(), []
    terminal = {'reviewed', 'rejected', 'superseded'}
    for initiative in sorted(initiatives, key=lambda row: row['id'], reverse=True):
        action_id, draft_id = initiative.get('owner_action_id'), initiative.get('draft_id')
        related = [row for row in actions.values() if row['id'] == action_id or (draft_id and row.get('draft_id') == draft_id) or (
            initiative.get('approval_id') and row.get('approval_id') == initiative['approval_id'])]
        linked_actions.update(row['id'] for row in related)
        if draft_id and draft_id in linked_drafts:
            primary = next(row for row in tasks if row.get('draftId') == draft_id)
            primary.setdefault('history', []).append({'initiativeId': initiative['id'], 'state': initiative.get('state'), 'title': initiative.get('title')})
            continue
        action = actions.get(action_id) or next((row for row in actions.values() if draft_id and row.get('draft_id') == draft_id), {})
        draft = draft_by_id.get(draft_id, {})
        if action:
            linked_actions.add(action['id'])
        if draft_id:
            linked_drafts.add(draft_id)
        state = initiative.get('state')
        focus = 'completed' if state in terminal or state == 'measuring' else 'needs_you' if state == 'ready_for_review' else 'planned' if state == 'snoozed' else 'preparing'
        if action.get('requirement') == 'owner_information' and action.get('state') in {'open', 'started', 'waiting'}:
            focus = 'needs_you'
        meta = draft.get('meta') or {}
        package = meta.get('growth_package') or {}
        validation = initiative.get('validation') or {}
        approval_id = initiative.get('approval_id') or action.get('approval_id')
        approval = memory.get_approval_request(approval_id) if approval_id else None
        if approval_id:
            linked_approvals.add(approval_id)
        verified_review = validation.get('status') == 'passed' and validation.get('packageHash') == initiative.get('review_package_hash') and all(
            (validation.get('checks') or {}).get(key) is True for key in ('exactDraft', 'publicRenderer', 'approvalBoundary'))
        tasks.append({'id': f"initiative:{initiative['id']}", 'kind': initiative.get('kind'), 'title': initiative.get('title'),
            'summary': initiative.get('rationale') or initiative.get('summary'), 'scope': initiative.get('summary'),
            'focus': focus, 'state': state, 'draftId': draft_id, 'ownerActionId': action.get('id'),
            'conversationId': action.get('conversation_id'), 'approvalId': approval_id,
            'reviewPackageHash': initiative.get('review_package_hash'), 'lastError': safe_provider_message(str(initiative.get('last_error') or '')),
            'canApprove': state == 'ready_for_review' and draft.get('status') == 'pending' and meta.get('review_package_hash') == initiative.get('review_package_hash') and verified_review and bool(draft_id and approval and approval.status.value == 'pending'),
            'review': {'before': package.get('before'), 'after': package.get('after'), 'changes': package.get('changes'), 'route': package.get('route')},
            'outcomes': [row for row in outcomes if row.get('initiative_id') == initiative['id']],
            'updatedAt': initiative.get('updated_ts'), 'nextRun': initiative.get('review_30_ts') if state == 'measuring' else action.get('snoozed_until')})
    for action in actions.values():
        if action['id'] in linked_actions or action.get('draft_id') in linked_drafts or action.get('approval_id') in linked_approvals or action['state'] in {'completed', 'dismissed', 'stale'}:
            continue
        if action.get('draft_id'):
            linked_drafts.add(action['draft_id'])
        approval = memory.get_approval_request(action['approval_id']) if action.get('approval_id') else None
        state = action['state']
        focus = 'planned' if state == 'snoozed' or action.get('requirement') == 'suggestion' else 'needs_you'
        if approval and approval.status.value == 'approved':
            state, focus = 'publishing', 'preparing'
        elif approval and approval.status.value == 'failed':
            state, focus = 'blocked', 'preparing'
        elif approval and approval.status.value in {'declined', 'expired'}:
            state, focus = ('rejected' if approval.status.value == 'declined' else 'superseded'), 'completed'
        elif state in {'started', 'waiting'} and action.get('requirement') != 'owner_information':
            focus = 'preparing'
        tasks.append({'id': f"action:{action['id']}", 'kind': 'owner_action', 'title': action['title'], 'summary': action['summary'],
            'focus': focus, 'state': state,
            'ownerActionId': action['id'], 'conversationId': action.get('conversation_id'), 'draftId': action.get('draft_id'),
            'approvalId': action.get('approval_id'), 'requirement': action.get('requirement'), 'canApprove': False,
            'nextRun': action.get('snoozed_until'), 'updatedAt': action.get('updated_ts')})
    for draft in drafts:
        if draft['id'] in linked_drafts or draft.get('kind') not in {'article', 'payload_content', 'design', 'merge', 'rollback'} or draft.get('status') != 'pending':
            continue
        sync = (draft.get('meta') or {}).get('payload_sync') or {}
        tasks.append({'id': f"draft:{draft['id']}", 'kind': draft['kind'], 'title': draft['title'], 'summary': str(draft.get('body') or '')[:2000],
            'focus': 'preparing', 'state': sync.get('state') or 'preparing', 'draftId': draft['id'], 'canApprove': False,
            'lastError': safe_provider_message(str((sync.get('validation') or {}).get('reason') or '')), 'updatedAt': draft.get('updated_ts')})
    for idea in article_ideas:
        if idea.get('draft_id'):
            continue
        idea_data = idea.get('idea_json') if isinstance(idea.get('idea_json'), dict) else {}
        state = str(idea.get('status') or 'preparing')
        blocked = state in {'held', 'blocked', 'failed', 'uncertain'}
        tasks.append({
            'id': f"article-idea:{idea.get('id')}",
            'kind': 'article_research',
            'title': idea_data.get('working_title') or 'Ada article research',
            'summary': idea.get('error') or idea_data.get('audience_need') or 'Ada is researching a useful reader-led article opportunity.',
            'focus': 'needs_you' if blocked else 'preparing',
            'state': state,
            'canApprove': False,
            'lastError': safe_provider_message(str(idea.get('error') or '')),
            'updatedAt': idea.get('updated_ts') or idea.get('created_ts'),
        })
    latest_by_trigger = {}
    for row in sorted(runs, key=lambda row: row.get('updated_ts') or '', reverse=True):
        latest_by_trigger.setdefault(row.get('trigger'), row)
    for activity in activities:
        trigger = activity['id'].removeprefix('growth_')
        run = latest_by_trigger.get(trigger)
        if run and run.get('status') not in {'pending', 'running', 'failed', 'blocked'}:
            run = None
        detail = (run or {}).get('detail') or {}
        error = detail.get('error') or '; '.join(str(row.get('reason') or '') for row in detail.get('blocks', []))
        state = 'scheduled' if activity['enabled'] else 'paused'
        if run and activity['enabled']:
            state = {'pending': 'queued', 'running': 'running', 'failed': 'blocked', 'blocked': 'blocked'}[run['status']]
        tasks.append({'id': f"schedule:{activity['id']}", 'kind': 'schedule', 'titleKey': activity['id'],
            'focus': 'preparing' if state in {'queued', 'running', 'blocked'} else 'planned', 'state': state, 'canApprove': False,
            'nextRun': (run.get('next_due_ts') or activity['nextRun']) if run and activity['enabled'] else activity['nextRun'],
            'lastError': safe_provider_message(str(error)) if run and state == 'blocked' else None,
            'runId': run.get('run_id') if run else None, 'schedule': activity.get('schedule')})
    order = {'needs_you': 0, 'preparing': 1, 'planned': 2, 'completed': 3}
    return sorted(tasks, key=lambda row: (order[row['focus']], row.get('nextRun') or '9999', row['id']))
