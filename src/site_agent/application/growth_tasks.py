"""One read-only queue joins existing work; it is not another task store."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


def _future_timestamp(value: Any) -> bool:
    """Only call work planned when its persisted next-run time is still ahead."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc) > datetime.now(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return False


def growth_tasks(memory, initiatives, drafts, activities, outcomes, runs=(), article_ideas=()) -> list[dict[str, Any]]:
    actions = {row.id: row.to_record() for row in memory.list_owner_actions(limit=None)}
    draft_by_id = {row['id']: row for row in drafts}
    linked_actions, linked_drafts, linked_approvals, tasks = set(), set(), set(), []
    terminal = {'reviewed', 'rejected', 'superseded', 'failed', 'cancelled', 'completed'}
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
        focus = 'completed' if state in terminal or state == 'measuring' else 'preparing'
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
        review_ready = (
            state == 'ready_for_review'
            and draft.get('status') == 'pending'
            and meta.get('review_package_hash') == initiative.get('review_package_hash')
            and verified_review
            and bool(draft_id and approval and approval.status.value == 'pending')
        )
        if review_ready:
            focus = 'needs_you'
        elif state == 'snoozed' and _future_timestamp(action.get('snoozed_until')):
            focus = 'planned'
        tasks.append({'id': f"initiative:{initiative['id']}", 'kind': initiative.get('kind'), 'title': initiative.get('title'),
            'summary': initiative.get('rationale') or initiative.get('summary'), 'scope': initiative.get('summary'),
            'focus': focus, 'state': state, 'draftId': draft_id, 'ownerActionId': action.get('id'),
            'conversationId': action.get('conversation_id'), 'approvalId': approval_id,
            'reviewPackageHash': initiative.get('review_package_hash'), 'lastError': None,
            'executionIssue': bool(initiative.get('last_error')),
            'canApprove': review_ready,
            'review': {'before': package.get('before'), 'after': package.get('after'), 'changes': package.get('changes'), 'route': package.get('route')},
            'outcomes': [row for row in outcomes if row.get('initiative_id') == initiative['id']],
            'updatedAt': initiative.get('updated_ts'), 'nextRun': initiative.get('review_30_ts') if state == 'measuring' else action.get('snoozed_until')})
        expected = initiative.get('expected') if isinstance(initiative.get('expected'), dict) else {}
        baseline = expected.get('implementation_baseline') if isinstance(expected.get('implementation_baseline'), dict) else None
        if baseline:
            measured_horizons = {
                int(row['horizon_days']) for row in outcomes
                if row.get('initiative_id') == initiative['id'] and row.get('horizon_days') is not None
            }
            for horizon in (30, 90, 180):
                due = initiative.get(f'review_{horizon}_ts')
                if not due or horizon in measured_horizons:
                    continue
                is_upcoming = _future_timestamp(due)
                tasks.append({
                    'id': f"measurement:{initiative['id']}:{horizon}",
                    'kind': 'measurement',
                    'titleKey': 'measurementTask',
                    'summary': str(initiative.get('title') or ''),
                    'focus': 'planned' if is_upcoming else 'preparing',
                    'state': 'scheduled' if is_upcoming else 'due',
                    'nextRun': due,
                    'measurementHorizon': horizon,
                    'measurementMetric': str(baseline.get('metric') or ''),
                    'canApprove': False,
                })
                break
    for action in actions.values():
        if action['id'] in linked_actions or action.get('draft_id') in linked_drafts or action.get('approval_id') in linked_approvals or action['state'] in {'completed', 'dismissed', 'stale'}:
            continue
        if action.get('draft_id'):
            linked_drafts.add(action['draft_id'])
        approval = memory.get_approval_request(action['approval_id']) if action.get('approval_id') else None
        state = action['state']
        next_run = action.get('snoozed_until')
        focus = 'planned' if state == 'snoozed' and _future_timestamp(next_run) else 'preparing'
        if action.get('requirement') == 'owner_information' and state in {'open', 'started', 'waiting'}:
            focus = 'needs_you'
        if approval and approval.status.value == 'approved':
            state, focus = 'publishing', 'preparing'
        elif approval and approval.status.value == 'failed':
            state, focus = 'failed', 'completed'
        elif approval and approval.status.value in {'declined', 'expired'}:
            state, focus = ('rejected' if approval.status.value == 'declined' else 'superseded'), 'completed'
        elif state in {'started', 'waiting'} and action.get('requirement') != 'owner_information':
            focus = 'preparing'
        # A generic owner action is not itself a website decision. Only exact,
        # validated initiatives or genuine owner-information requests enter the
        # review-first inbox.
        tasks.append({'id': f"action:{action['id']}", 'kind': 'owner_action', 'title': action['title'], 'summary': action['summary'],
            'focus': focus, 'state': state,
            'ownerActionId': action['id'], 'conversationId': action.get('conversation_id'), 'draftId': action.get('draft_id'),
            'approvalId': action.get('approval_id'), 'requirement': action.get('requirement'), 'canApprove': False,
            'nextRun': action.get('snoozed_until'), 'updatedAt': action.get('updated_ts')})
    for draft in drafts:
        if draft.get('kind') == 'reflection' and draft.get('status') == 'pending' and draft['id'] not in linked_drafts:
            meta = draft.get('meta') if isinstance(draft.get('meta'), dict) else {}
            proposal = meta.get('proposal') if isinstance(meta.get('proposal'), dict) else None
            review_hash = str(meta.get('review_package_hash') or '')
            base_hash = str(meta.get('base_hash') or '')
            current = memory.kv_get('persona_notes', {'voice_notes': [], 'avoid': []}) or {'voice_notes': [], 'avoid': []}
            complete = bool(proposal and review_hash.startswith('sha256:') and base_hash.startswith('sha256:'))
            focus = 'needs_you' if complete else 'preparing'
            tasks.append({'id': f"settings:{draft['id']}", 'kind': 'settings_proposal',
                'title': draft['title'], 'summary': 'Ada proposes a change to future writing guidance. Existing website content will not change.',
                'focus': focus, 'state': 'ready_for_review' if complete else 'preparing', 'draftId': draft['id'],
                'reviewPackageHash': review_hash or None, 'canApprove': complete,
                'review': {'before': current, 'after': proposal, 'changes': proposal, 'setting': 'Ada writing guidance'},
                'updatedAt': draft.get('updated_ts')})
            continue
        if draft.get('kind') == 'rollback' and draft.get('status') == 'pending' and draft['id'] not in linked_drafts:
            meta = draft.get('meta') if isinstance(draft.get('meta'), dict) else {}
            preview = meta.get('preview') if isinstance(meta.get('preview'), dict) else {}
            candidate_sha = str(meta.get('candidate_sha') or '')
            base_sha = str(meta.get('base_sha') or '')
            review_hash = str(meta.get('review_package_hash') or '')
            exact_preview = (
                meta.get('scope') == 'frontend_only'
                and meta.get('contract') == 'helloada-content-v1'
                and re.fullmatch(r"[0-9a-f]{40}", candidate_sha)
                and re.fullmatch(r"[0-9a-f]{40}", base_sha)
                and preview.get('status') == 'ready'
                and preview.get('requires_build') is False
                and preview.get('head_sha') == candidate_sha
                and review_hash.startswith('sha256:')
            )
            tasks.append({
                'id': f"rollback:{draft['id']}", 'kind': 'rollback', 'title': draft['title'],
                'summary': str(draft.get('body') or ''),
                'focus': 'needs_you' if exact_preview else 'preparing',
                'state': 'ready_for_review' if exact_preview else str(preview.get('status') or 'preparing'),
                'draftId': draft['id'], 'reviewPackageHash': review_hash or None,
                'canApprove': exact_preview,
                'previewUrl': preview.get('preview_url') if exact_preview else None,
                'review': {'before': {'website': 'Current live design'},
                           'after': {'website': 'Selected frontend design'},
                           'changes': {'scope': 'frontend_only'},
                           'route': 'All public pages'},
                'updatedAt': draft.get('updated_ts'),
            })
            continue
        if draft['id'] in linked_drafts or draft.get('kind') not in {'article', 'payload_content', 'design', 'merge', 'rollback'} or draft.get('status') != 'pending':
            continue
        sync = (draft.get('meta') or {}).get('payload_sync') or {}
        tasks.append({'id': f"draft:{draft['id']}", 'kind': draft['kind'], 'title': draft['title'], 'summary': str(draft.get('body') or '')[:2000],
            'focus': 'preparing', 'state': sync.get('state') or 'preparing', 'draftId': draft['id'], 'canApprove': False,
            'lastError': None,
            'executionIssue': bool((sync.get('validation') or {}).get('reason')),
            'updatedAt': draft.get('updated_ts')})
    for idea in article_ideas:
        if idea.get('draft_id'):
            continue
        idea_data = idea.get('idea_json') if isinstance(idea.get('idea_json'), dict) else {}
        state = str(idea.get('status') or 'preparing')
        blocked = state in {'held', 'blocked', 'failed', 'uncertain'}
        technical_failure = state in {'blocked', 'failed', 'uncertain'}
        tasks.append({
            'id': f"article-idea:{idea.get('id')}",
            'kind': 'article_research',
            'title': idea_data.get('working_title') or 'Ada article research',
            'summary': ('Ada is reviewing this research result.' if state == 'held' else 'This research run needs repair; the owner does not need to resolve a provider error.') if technical_failure or blocked else idea_data.get('audience_need') or 'Ada is researching a useful reader-led article opportunity.',
            'focus': 'completed' if technical_failure else 'preparing',
            'state': state,
            'canApprove': False,
            'lastError': None,
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
        next_run = activity.get('nextRun')
        state = 'scheduled' if activity.get('enabled') else 'paused'
        if run and activity['enabled']:
            state = {'pending': 'queued', 'running': 'running', 'failed': 'blocked', 'blocked': 'blocked'}[run['status']]
        if run and activity.get('enabled') and run.get('next_due_ts'):
            next_run = run.get('next_due_ts')
        focus = 'preparing' if state in {'queued', 'running', 'blocked'} else 'planned' if activity.get('enabled') and _future_timestamp(next_run) else 'paused'
        if activity.get('enabled') and focus == 'paused':
            state = 'unscheduled'
        tasks.append({'id': f"schedule:{activity['id']}", 'kind': 'schedule', 'titleKey': activity['id'],
            'focus': focus, 'state': state, 'canApprove': False,
            'nextRun': next_run,
            'lastError': None,
            'executionIssue': bool(run and state == 'blocked'),
            'runId': run.get('run_id') if run else None, 'schedule': activity.get('schedule')})
    order = {'needs_you': 0, 'preparing': 1, 'planned': 2, 'paused': 3, 'completed': 4}
    return sorted(tasks, key=lambda row: (order[row['focus']], row.get('nextRun') or '9999', row['id']))
