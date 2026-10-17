"""One read-only queue joins existing work; it is not another task store."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from typing import Any

from ..core.article_routes import public_article_path
from .growth_candidates import content_hash


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


def _active_run_ids(runs: Any) -> set[str]:
    """Only a live lease makes initiative preparation active work."""
    return {
        str(row.get("run_id"))
        for row in runs
        if isinstance(row, Mapping)
        and str(row.get("status") or "") == "running"
        and row.get("run_id")
        and _future_timestamp(row.get("lease_until"))
    }


def _action_chat_job(memory: Any, action: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return a linked job only while the durable chat queue says it is active."""
    job_id = action.get("job_id")
    if not job_id:
        return None
    try:
        job = memory.get_chat_job(int(job_id))
    except (TypeError, ValueError):
        return None
    return job if isinstance(job, Mapping) and job.get("status") in {"queued", "running"} else None


def _compact_summary(value: Any, limit: int = 220) -> str:
    """Keep list rows purpose-written and bounded, even for old persisted data."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _article_review(
    draft: Mapping[str, Any],
    sync: Mapping[str, Any],
    idea: Mapping[str, Any] | None,
    *,
    include_body: bool,
) -> dict[str, Any]:
    meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
    editorial = meta.get("editorial_brief") if isinstance(meta.get("editorial_brief"), Mapping) else {}
    research = meta.get("article_research") if isinstance(meta.get("article_research"), Mapping) else {}
    idea_data = idea.get("idea_json") if isinstance(idea, Mapping) and isinstance(idea.get("idea_json"), Mapping) else {}
    research_note = idea.get("research_note_json") if isinstance(idea, Mapping) and isinstance(idea.get("research_note_json"), Mapping) else {}
    image = sync.get("featured_image") if isinstance(sync.get("featured_image"), Mapping) else None
    raw_sources = idea_data.get("source_urls") or research.get("source_urls") or []
    sources = []
    if isinstance(raw_sources, list):
        for url in raw_sources[:5]:
            value = str(url or "").strip()
            if value.startswith(("https://", "http://")):
                sources.append({"url": value[:1000], "label": value[:180]})
    slug = str(sync.get("slug") or "").strip()
    review = {
        "slug": slug,
        "path": public_article_path(slug),
        "excerpt": str(sync.get("excerpt") or "").strip(),
        "metaDescription": str(sync.get("meta_description") or "").strip(),
        "primaryKeyword": str(research_note.get("selected_query") or sync.get("primary_keyword") or "").strip(),
        "rationale": str(meta.get("why") or idea_data.get("business_relevance") or meta.get("angle") or "").strip(),
        "readerQuestion": str(editorial.get("reader_question") or idea_data.get("reader_question") or "").strip(),
        "demandInterpretation": str(research_note.get("demand_interpretation") or "").strip(),
        "researchDecision": str(research_note.get("decision") or "").strip(),
        "featuredImage": dict(image) if image else None,
        "sources": sources,
    }
    if include_body:
        review["body"] = str(draft.get("body") or "")
    return review


def _article_is_reviewable(draft: Mapping[str, Any], sync: Mapping[str, Any]) -> bool:
    meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
    validation = sync.get("validation") if isinstance(sync.get("validation"), Mapping) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), Mapping) else {}
    return bool(
        draft.get("kind") == "article"
        and draft.get("status") == "pending"
        and sync.get("state") == "ready_for_review"
        and validation.get("status") == "passed"
        and checks
        and all(value is True for value in checks.values())
        and sync.get("collection") == "posts"
        and str(sync.get("document_id") or "").strip()
        and str(sync.get("draft_hash") or "").strip()
        and str(meta.get("review_package_hash") or "").strip()
    )


def _visible_edit_operations(meta: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = meta.get("ops")
    if not isinstance(raw, list):
        return []
    operations = []
    for item in raw[:12]:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        operations.append({
            "path": path[:500],
            "find": str(item.get("find") or "")[:1200],
            "replace": str(item.get("replace") or "")[:1200],
        })
    return operations


def growth_tasks(
    memory,
    initiatives,
    drafts,
    activities,
    outcomes,
    runs=(),
    article_ideas=(),
    *,
    include_article_content: bool = False,
) -> list[dict[str, Any]]:
    actions = {row.id: row.to_record() for row in memory.list_owner_actions(limit=None)}
    active_runs = _active_run_ids(runs)
    draft_by_id = {row['id']: row for row in drafts}
    pending_website_changes = [
        row for row in drafts
        if row.get('kind') in {'design', 'merge', 'rollback'}
        and row.get('status') in {'pending', 'publishing', 'publish_failed'}
    ]
    actionable_website_changes = [
        row for row in pending_website_changes
        if not (row.get('status') in {'pending', 'blocked'} and
            isinstance(row.get('meta'), Mapping)
            and isinstance(row['meta'].get('preview'), Mapping)
            and row['meta']['preview'].get('status') in {'blocked', 'failed', 'error'}
        )
    ]
    failed_website_change = next((
        row for row in pending_website_changes
        if row.get('status') in {'pending', 'blocked'}
        if isinstance(row.get('meta'), Mapping)
        and isinstance(row['meta'].get('preview'), Mapping)
        and row['meta']['preview'].get('status') in {'blocked', 'failed', 'error'}
    ), None)
    idea_by_draft = {str(row.get("draft_id")): row for row in article_ideas if row.get("draft_id") is not None}
    idea_by_id = {str(row.get("id")): row for row in article_ideas if row.get("id") is not None}
    linked_actions, linked_drafts, linked_approvals, tasks = set(), set(), set(), []
    terminal = {'reviewed', 'rejected', 'superseded', 'cancelled', 'completed'}
    for initiative in sorted(initiatives, key=lambda row: row['id'], reverse=True):
        if initiative.get('state') == 'deferred':
            continue
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
        action_job = _action_chat_job(memory, action)
        validation = initiative.get('validation') if isinstance(initiative.get('validation'), Mapping) else {}
        preparation = validation.get('preparation') if isinstance(validation.get('preparation'), Mapping) else {}
        source_job = None
        if initiative.get('kind') == 'code' and preparation.get('kind') == 'source_code' and preparation.get('jobId'):
            try:
                source_job = memory.get_chat_job(int(preparation['jobId']))
            except (TypeError, ValueError):
                source_job = None
        revision = validation.get('revision') if isinstance(validation.get('revision'), Mapping) else {}
        revision_job = None
        if initiative.get('kind') == 'code' and revision.get('chatJobId'):
            try:
                revision_job = memory.get_chat_job(int(revision['chatJobId']))
            except (TypeError, ValueError):
                revision_job = None
        draft_meta = draft.get('meta') if isinstance(draft.get('meta'), Mapping) else {}
        source_preview = draft_meta.get('preview') if isinstance(draft_meta.get('preview'), Mapping) else {}
        source_work_active = bool(
            source_job and source_job.get('status') in {'queued', 'running'}
            or revision_job and revision_job.get('status') in {'queued', 'running'}
            or source_preview.get('requires_build') is True
            and source_preview.get('status') not in {'blocked', 'failed', 'error'}
        )
        source_waiting_for_owner = bool(validation.get('waitingForWebsiteDecision') and actionable_website_changes)
        source_blocked_by_preview = bool(
            validation.get('waitingForWebsiteDecision')
            and not actionable_website_changes
            and failed_website_change
        )
        source_failure_reason = None
        if source_blocked_by_preview and isinstance(failed_website_change.get('meta'), Mapping):
            failed_preview = failed_website_change['meta'].get('preview')
            if isinstance(failed_preview, Mapping):
                source_failure_reason = str(failed_preview.get('error') or '') or None
        if action:
            linked_actions.add(action['id'])
        if draft_id:
            linked_drafts.add(draft_id)
        state = initiative.get('state')
        next_run = initiative.get('review_30_ts') if state == 'measuring' else action.get('snoozed_until')
        if state in terminal:
            focus = 'completed'
        elif state in {'blocked', 'uncertain'}:
            focus = 'paused'
        elif state == 'snoozed':
            focus = 'planned' if _future_timestamp(next_run) else 'paused'
        elif state == 'measuring':
            focus = 'planned' if _future_timestamp(next_run) else 'paused'
        elif state == 'waiting_for_owner':
            focus = 'needs_you'
        elif state in {'preparing', 'validating'}:
            focus = 'preparing' if str(initiative.get('growth_run_id') or '') in active_runs or source_work_active else 'paused'
        elif state in {'publishing', 'verifying_live'}:
            focus = 'preparing' if action_job else 'paused'
        else:
            focus = 'paused'
        if action.get('requirement') == 'owner_information' and action.get('state') in {'open', 'started', 'waiting'}:
            focus = 'needs_you'
        meta = draft.get('meta') or {}
        package = meta.get('growth_package') or {}
        approval_id = initiative.get('approval_id') or action.get('approval_id')
        approval = memory.get_approval_request(approval_id) if approval_id else None
        if approval_id:
            linked_approvals.add(approval_id)
        verified_review = validation.get('status') == 'passed' and validation.get('packageHash') == initiative.get('review_package_hash') and all(
            (validation.get('checks') or {}).get(key) is True for key in ('exactDraft', 'publicRenderer', 'approvalBoundary'))
        article_ready = _article_is_reviewable(draft, meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {})
        source = package.get('source') if isinstance(package.get('source'), Mapping) else {}
        source_candidate_ready = bool(
            initiative.get('kind') == 'code'
            and package.get('candidateType') == 'source_code'
            and content_hash(package) == meta.get('review_package_hash') == initiative.get('review_package_hash')
            and re.fullmatch(r'[0-9a-f]{40}', str(source.get('candidateSha') or ''))
            and re.fullmatch(r'[0-9a-f]{40}', str(source.get('baseSha') or ''))
            and str(meta.get('head_sha') or '').lower() == str(source.get('candidateSha') or '').lower()
            and str(meta.get('base_sha') or '').lower() == str(source.get('baseSha') or '').lower()
            and source_preview.get('status') == 'ready'
            and source_preview.get('requires_build') is not True
            and str(source_preview.get('head_sha') or '').lower() == str(source.get('candidateSha') or '').lower()
            and bool(source.get('changedPaths'))
        )
        review_ready = article_ready or (
            state == 'ready_for_review'
            and (initiative.get('kind') != 'code' or source_candidate_ready)
            and draft.get('status') == 'pending'
            and meta.get('review_package_hash') == initiative.get('review_package_hash')
            and verified_review
            and bool(draft_id and approval and approval.status.value == 'pending')
        )
        review_hash = meta.get("review_package_hash") if article_ready else initiative.get("review_package_hash")
        article_idea = idea_by_draft.get(str(draft_id))
        if article_idea is None and isinstance(meta.get("article_research"), Mapping):
            article_idea = idea_by_id.get(str(meta["article_research"].get("article_idea_id")))
        article_draft = draft.get("kind") == "article"
        article_related = article_draft or "article" in str(initiative.get("kind") or "").lower()
        article_data = _article_review(draft, meta.get("payload_sync", {}), article_idea, include_body=include_article_content) if article_draft else None
        initiative_summary = str(initiative.get('rationale') or initiative.get('summary') or '').strip()
        stale_work = (
            state in {'preparing', 'validating'}
            and str(initiative.get('growth_run_id') or '') not in active_runs
            and not source_work_active
            and not source_waiting_for_owner
        ) or (state in {'publishing', 'verifying_live'} and action_job is None)
        summary_key = None
        if initiative.get('kind') == 'code' and validation.get('revisionFailure'):
            summary_key = 'sourceRevisionFailed'
            initiative_summary = str(validation['revisionFailure'])
        elif initiative.get('kind') == 'code' and source_blocked_by_preview and not review_ready:
            summary_key = 'sourceWebsitePreviewBlocked'
            initiative_summary = 'Ada’s earlier website preview failed a required check. It was not published; Ada must prepare a valid preview before continuing this source change.'
        elif initiative.get('kind') == 'code' and source_waiting_for_owner and not review_ready:
            summary_key = 'sourceWaitingForWebsiteDecision'
            initiative_summary = 'Ada is ready to continue this recommendation after the current website change is decided.'
        elif initiative.get('kind') == 'code' and source_work_active and not review_ready:
            summary_key = 'sourceCandidatePreparing'
            initiative_summary = 'Ada is preparing and checking the exact website preview. Nothing is published until you approve it.'
        if article_related and not review_ready:
            sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
            sync_validation = sync.get("validation") if isinstance(sync.get("validation"), Mapping) else {}
            is_blocked = state in {"blocked", "uncertain"} or sync.get("state") == "blocked" or sync_validation.get("status") == "blocked"
            summary_key = "articleNeedsRepair" if is_blocked else "articleNotRunning" if stale_work else "articlePreparing"
            initiative_summary = "This article needs a successful shared Payload check before it can be reviewed." if is_blocked else "This saved article is not currently being prepared for review." if stale_work else "Ada is preparing this article for review against the shared blog structure."
        elif article_related:
            initiative_summary = initiative_summary or "Ada prepared this article for your review."
        initiative_scope = str(initiative.get('summary') or '').strip()
        if review_ready:
            focus = 'needs_you'
        elif stale_work:
            focus = 'paused'
        task_state = 'ready_for_review' if review_ready else 'blocked' if state in {'ready_for_review', 'blocked', 'uncertain'} else state
        if stale_work or source_waiting_for_owner:
            task_state = 'not_running'
        tasks.append({'id': f"initiative:{initiative['id']}", 'kind': initiative.get('kind'), 'title': (draft.get('title') or initiative.get('title')) if article_draft else initiative.get('title'),
            'summary': _compact_summary(initiative_summary), 'summaryKey': summary_key, 'scope': initiative_scope,
            'focus': 'needs_you' if review_ready else focus, 'state': task_state, 'draftId': draft_id, 'ownerActionId': action.get('id'),
            'priority': action.get('priority') or initiative.get('priority') or 'normal',
            'requirement': action.get('requirement'),
            'conversationId': action.get('conversation_id'), 'approvalId': approval_id,
            'reviewPackageHash': review_hash,
            'lastError': validation.get('revisionFailure') or source_failure_reason,
            'executionIssue': state in {'blocked', 'uncertain'} or bool(validation.get('revisionFailure')) or stale_work or source_blocked_by_preview,
            'canApprove': review_ready,
            'previewUrl': ((package.get('source') or {}).get('previewUrl') if isinstance(package.get('source'), Mapping) else None),
            'review': {'before': package.get('before'), 'after': package.get('after'), 'changes': package.get('changes'), 'route': package.get('route'),
                **({'source': source} if package.get('candidateType') == 'source_code' else {}),
                **({'article': article_data} if article_data else {})},
            'outcomes': [row for row in outcomes if row.get('initiative_id') == initiative['id']],
            'updatedAt': initiative.get('updated_ts'), 'nextRun': next_run})
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
                    'focus': 'planned' if is_upcoming else 'paused',
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
        # Suggestions are internal ideas, not owner tasks. Only exact review
        # candidates and genuine owner-information requests belong in Growth.
        if action.get('requirement') == 'suggestion':
            continue
        if action.get('draft_id'):
            linked_drafts.add(action['draft_id'])
        approval = memory.get_approval_request(action['approval_id']) if action.get('approval_id') else None
        state = action['state']
        next_run = action.get('snoozed_until')
        job = _action_chat_job(memory, action)
        execution_issue = False
        focus = 'planned' if state == 'snoozed' and _future_timestamp(next_run) else 'opportunity'
        if action.get('requirement') == 'owner_information' and state == 'open':
            focus = 'needs_you'
        if approval and approval.status.value == 'approved':
            if job:
                state, focus = 'publishing', 'preparing'
            else:
                state, focus, execution_issue = 'not_running', 'paused', True
        elif approval and approval.status.value == 'failed':
            state, focus = 'failed', 'paused'
            execution_issue = True
        elif approval and approval.status.value in {'declined', 'expired'}:
            state, focus = ('rejected' if approval.status.value == 'declined' else 'superseded'), 'completed'
        elif state in {'started', 'waiting'}:
            if job:
                focus = 'preparing'
            else:
                state, focus, execution_issue = 'not_running', 'paused', True
        elif state == 'snoozed' and not _future_timestamp(next_run):
            state, focus, execution_issue = 'not_running', 'paused', True
        # A generic owner action is not itself a website decision. Only exact,
        # validated initiatives or genuine owner-information requests enter the
        # review-first inbox.
        tasks.append({'id': f"action:{action['id']}", 'kind': 'owner_action', 'title': action['title'], 'summary': action['summary'],
            'focus': focus, 'state': state,
            'ownerActionId': action['id'], 'conversationId': action.get('conversation_id'), 'draftId': action.get('draft_id'),
            'approvalId': action.get('approval_id'), 'requirement': action.get('requirement'), 'canApprove': False,
            'priority': action.get('priority') or 'normal',
            'executionIssue': execution_issue,
            'nextRun': action.get('snoozed_until'), 'updatedAt': action.get('updated_ts')})
    for draft in drafts:
        if draft.get('kind') == 'reflection' and draft.get('status') == 'pending' and draft['id'] not in linked_drafts:
            meta = draft.get('meta') if isinstance(draft.get('meta'), dict) else {}
            proposal = meta.get('proposal') if isinstance(meta.get('proposal'), dict) else None
            review_hash = str(meta.get('review_package_hash') or '')
            base_hash = str(meta.get('base_hash') or '')
            current = memory.kv_get('persona_notes', {'voice_notes': [], 'avoid': []}) or {'voice_notes': [], 'avoid': []}
            complete = bool(proposal and review_hash.startswith('sha256:') and base_hash.startswith('sha256:'))
            focus = 'needs_you' if complete else 'paused'
            summary_key = None if complete else 'settingsProposalNotReady'
            tasks.append({'id': f"settings:{draft['id']}", 'kind': 'settings_proposal',
                'title': draft['title'], 'summary': 'Ada proposes a change to future writing guidance. Existing website content will not change.',
                'summaryKey': summary_key,
                'focus': focus, 'state': 'ready_for_review' if complete else 'not_running', 'draftId': draft['id'],
                'reviewPackageHash': review_hash or None, 'canApprove': complete,
                'needsPreparation': not complete,
                'executionIssue': False,
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
        meta = draft.get('meta') if isinstance(draft.get('meta'), Mapping) else {}
        preview = meta.get('preview') if isinstance(meta.get('preview'), Mapping) else {}
        failed_preview = (
            draft.get('kind') in {'design', 'merge', 'rollback'}
            and draft.get('status') in {'pending', 'blocked'}
            and preview.get('status') in {'blocked', 'failed', 'error'}
        )
        if draft['id'] in linked_drafts or draft.get('kind') not in {'article', 'edit', 'payload_content', 'design', 'merge', 'rollback'} or (draft.get('status') != 'pending' and not failed_preview):
            continue
        sync = meta.get('payload_sync') if isinstance(meta.get('payload_sync'), Mapping) else {}
        article_ready = _article_is_reviewable(draft, sync)
        article_idea = idea_by_draft.get(str(draft.get("id")))
        if article_idea is None and isinstance(meta.get("article_research"), Mapping):
            article_idea = idea_by_id.get(str(meta["article_research"].get("article_idea_id")))
        article_draft = draft.get('kind') == 'article'
        article_data = _article_review(draft, sync, article_idea, include_body=include_article_content) if article_draft else None
        state = str(sync.get('state') or 'not_synced')
        if not article_draft:
            state = 'not_running'
        if article_ready:
            focus = 'needs_you'
        else:
            focus = 'paused'
        stale_sync = state in {'syncing', 'validating', 'preparing'}
        rationale = str((article_data or {}).get('rationale') or '').strip()
        validation = sync.get('validation') if isinstance(sync.get('validation'), Mapping) else {}
        blocked = sync.get('state') == 'blocked' or validation.get('status') == 'blocked'
        summary_key = None
        needs_preparation = False
        change_operations = []
        if article_draft:
            if article_ready:
                summary = _compact_summary(rationale or 'Ada prepared this article for your review.')
            elif blocked:
                summary = 'This article needs a successful shared Payload check before it can be reviewed.'
                summary_key = 'articleNeedsRepair'
            elif stale_sync:
                summary = 'This saved article is not currently being prepared for review.'
                summary_key = 'articleNotRunning'
            else:
                summary = 'This saved article has not entered a validated review package.'
                summary_key = 'articleNotReady'
            scope = rationale
        elif failed_preview:
            summary = 'The private website preview failed a required check. Nothing was published; Ada needs to prepare a valid preview before you can review this change.'
            summary_key = 'websitePreviewBlocked'
            scope = _compact_summary(meta.get('summary') or '', limit=700)
            change_operations = []
        else:
            needs_preparation = True
            summary_key = 'codeChangeNotReady' if draft.get('kind') == 'merge' else 'websiteChangeNotReady'
            summary = ''
            scope = _compact_summary(meta.get('summary') or '', limit=700)
            change_operations = _visible_edit_operations(meta) if draft.get('kind') == 'edit' else []
        task_title = str(meta.get('summary') or draft.get('title') or '') if failed_preview else draft['title']
        tasks.append({'id': f"draft:{draft['id']}", 'kind': draft['kind'], 'title': task_title,
            'summary': summary, 'summaryKey': summary_key, 'scope': scope,
            'focus': focus, 'state': 'blocked' if failed_preview else 'ready_for_review' if article_ready else 'not_running' if stale_sync else state, 'draftId': draft['id'],
            'reviewPackageHash': meta.get('review_package_hash') if article_ready else None,
            'review': {'article': article_data} if article_data else {'changeOperations': change_operations} if change_operations else None,
            'canApprove': article_ready,
            'needsPreparation': needs_preparation,
            'lastError': str(preview.get('error') or '') if failed_preview else None,
            'executionIssue': failed_preview or bool(article_draft and (blocked or stale_sync)),
            'updatedAt': draft.get('updated_ts')})
    for idea in article_ideas:
        if idea.get('draft_id'):
            continue
        idea_data = idea.get('idea_json') if isinstance(idea.get('idea_json'), dict) else {}
        state = str(idea.get('status') or 'preparing')
        if state == 'held':
            continue
        saved_error = str(idea.get('error') or '')
        deterministic_locale_error = 'DATAFORSEO_TASK_40501_INVALID_FIELD_LANGUAGE_CODE_' in saved_error
        invalid_request_error = 'crawlseo idea_summary is invalid' in saved_error.lower()
        technical_failure = state in {'blocked', 'failed', 'uncertain'} or bool(saved_error) and state in {'selected', 'research_requested', 'serp_requested'}
        research_active = state == 'research_requested' and bool(idea.get('research_run_id'))
        serp_active = state == 'serp_requested' and bool(idea.get('serp_run_id'))
        research_complete = state == 'researched' and bool(idea.get('researched_ts'))
        missing_run = state == 'research_requested' and not research_active or state == 'serp_requested' and not serp_active
        stale_idea = state == 'preparing' or missing_run or state == 'researched' and not research_complete
        genuinely_active = research_active or serp_active
        focus = 'paused' if technical_failure or stale_idea else 'opportunity' if state in {'selected', 'proposed'} or research_complete else 'preparing' if genuinely_active else 'paused'
        audience_need = str(idea_data.get('audience_need') or '').strip()
        summary_key = (
            'articleResearchLocaleNeedsRepair' if deterministic_locale_error
            else 'articleResearchRequestNeedsRepair' if invalid_request_error
            else 'articleResearchNeedsRepair' if technical_failure or missing_run
            else 'articleResearchNotRunning' if stale_idea
            else 'articleResearchComplete' if research_complete
            else 'articleResearchActive' if genuinely_active
            else 'articleOpportunity'
        )
        tasks.append({
            'id': f"article-idea:{idea.get('id')}",
            'kind': 'article_research',
            'title': idea_data.get('working_title') or 'Ada article research',
            'summary': ('Ada could not complete this research and needs to repair it.' if technical_failure or missing_run else 'This research has stopped before an article draft was prepared.' if stale_idea else 'Ada’s research is complete; an article draft is not ready for review yet.' if research_complete else 'Ada is processing the requested research; no article draft is ready yet.' if genuinely_active else 'Ada found a reader question worth exploring.'),
            'summaryKey': summary_key,
            'scope': audience_need,
            'focus': focus,
            'state': 'not_running' if stale_idea else state,
            'canApprove': False,
            'executionIssue': technical_failure or stale_idea,
            'lastError': None,
            'updatedAt': idea.get('updated_ts') or idea.get('created_ts'),
        })
    latest_by_trigger = {}
    for row in sorted(runs, key=lambda row: row.get('updated_ts') or '', reverse=True):
        latest_by_trigger.setdefault(row.get('trigger'), row)
    for activity in activities:
        trigger = activity['id'].removeprefix('growth_')
        run = latest_by_trigger.get(trigger)
        if run and run.get('status') not in {'pending', 'running', 'failed', 'blocked', 'uncertain'}:
            run = None
        next_run = activity.get('nextRun')
        state = 'scheduled' if activity.get('enabled') else 'paused'
        if run and activity['enabled']:
            state = {'pending': 'queued', 'running': 'running', 'failed': 'blocked', 'blocked': 'blocked', 'uncertain': 'uncertain'}[run['status']]
        if run and activity.get('enabled') and run.get('next_due_ts'):
            next_run = run.get('next_due_ts')
        if run and state in {'blocked', 'uncertain'}:
            # A provider outcome that did not settle is not a schedule. Never
            # present the activity's normal cadence as though retry were safe.
            next_run = None
        if not _future_timestamp(next_run):
            next_run = None
        focus = 'paused' if state in {'blocked', 'uncertain'} else 'preparing' if state in {'queued', 'running'} else 'planned' if activity.get('enabled') and _future_timestamp(next_run) else 'paused'
        if activity.get('enabled') and state == 'scheduled' and focus == 'paused':
            state = 'unscheduled'
        schedule_summary_key = "scheduleExecutionUncertain" if state == "uncertain" else "scheduleExecutionFailed" if state == "blocked" else "scheduleNotRegistered" if state == "unscheduled" else None
        tasks.append({'id': f"schedule:{activity['id']}", 'kind': 'schedule', 'titleKey': activity['id'],
            'focus': focus, 'state': state, 'summaryKey': schedule_summary_key, 'canApprove': False,
            'nextRun': next_run,
            'lastError': None,
            'executionIssue': bool(run and state in {'blocked', 'uncertain'}) or state == 'unscheduled',
            'runId': run.get('run_id') if run else None, 'schedule': activity.get('schedule')})
    # An owner-triggered review has a durable run record but no recurring
    # schedule row. Keep its real failure/lease visible without turning the
    # technical issue into a business-owner approval or losing its retry date.
    for run in runs:
        if run.get('trigger') != 'owner_review' or run.get('status') not in {'pending', 'running', 'failed', 'blocked', 'uncertain'}:
            continue
        status = str(run['status'])
        has_live_lease = status == 'running' and str(run.get('run_id') or '') in active_runs
        next_run = run.get('next_due_ts') if _future_timestamp(run.get('next_due_ts')) else None
        if status in {'failed', 'blocked', 'uncertain'}:
            focus = 'paused'
            summary_key = 'assessmentExecutionUncertain' if status == 'uncertain' else 'assessmentExecutionBlocked' if status == 'blocked' else 'assessmentExecutionFailed'
        elif status == 'running' and not has_live_lease:
            focus = 'paused'
            summary_key = 'assessmentExecutionStale'
        else:
            focus = 'preparing' if has_live_lease or not next_run else 'planned'
            summary_key = None
        tasks.append({
            'id': f"assessment:{run['run_id']}", 'kind': 'assessment', 'titleKey': 'growthOwnerReviewTask',
            'focus': focus, 'state': status, 'summaryKey': summary_key,
            'nextRun': next_run, 'runId': run['run_id'], 'updatedAt': run.get('updated_ts'),
            'lastError': None, 'executionIssue': status in {'failed', 'blocked', 'uncertain'} or status == 'running' and not has_live_lease, 'canApprove': False,
        })
    order = {'needs_you': 0, 'preparing': 1, 'planned': 2, 'paused': 3, 'opportunity': 4, 'completed': 5}
    return sorted(tasks, key=lambda row: (order[row['focus']], row.get('nextRun') or '9999', row['id']))
