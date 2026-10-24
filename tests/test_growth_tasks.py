from site_agent.application.growth_tasks import growth_tasks
from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction
from site_agent.core.memory import Memory
from site_agent.application.approvals import ApprovalService
from site_agent.application.actions import OwnerActionService
from site_agent.core.contracts import Artifact, ArtifactKind, EffectClass
from datetime import datetime, timezone
import pytest


@pytest.fixture(autouse=True)
def fixed_schedule_clock(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr('site_agent.application.growth_tasks.datetime', FixedDateTime)


def test_linked_improvement_is_one_task_not_three_cards(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    draft = memory.save_draft(title='Improve the homepage', body='A useful change', kind='article')
    action = memory.create_owner_action(OwnerAction(capability_id='growth.candidate.review', provider_id='site-agent',
        title='Review the homepage', summary='A useful change', action_label='Review',
        priority=ActionPriority.NORMAL, source_ref='growth:1', requirement=ActionRequirement.OWNER_DECISION, dedupe_key='growth:1', draft_id=draft))
    initiatives = [{'id': 1, 'title': 'Improve the homepage', 'summary': 'A useful change', 'state': 'ready_for_review',
        'draft_id': draft, 'owner_action_id': action.id, 'review_package_hash': 'sha256:exact'}]
    tasks = growth_tasks(memory, initiatives, memory.list_drafts(), [], [])
    assert len(tasks) == 1
    assert tasks[0]['focus'] == 'paused'
    assert tasks[0]['state'] == 'blocked'
    assert tasks[0]['draftId'] == draft
    assert tasks[0]['ownerActionId'] == action.id
    assert tasks[0]['priority'] == 'normal'
    assert tasks[0]['reviewPackageHash'] == 'sha256:exact'
    assert not tasks[0]['canApprove']
    memory.close()


def test_schedule_and_internal_block_are_not_fake_owner_decisions(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    tasks = growth_tasks(memory, [{'id': 1, 'title': 'Prepare an article', 'state': 'blocked', 'last_error': 'Search evidence unavailable'}], [],
        [{'id': 'growth_weekly', 'enabled': True, 'nextRun': '2026-10-07T13:30:00Z'},
         {'id': 'growth_monthly', 'enabled': False, 'nextRun': None}], [])
    by_id = {row['id']: row for row in tasks}
    assert by_id['initiative:1']['focus'] == 'paused'
    assert by_id['initiative:1']['lastError'] is None
    assert by_id['initiative:1']['executionIssue'] is True
    assert by_id['schedule:growth_weekly']['focus'] == 'planned'
    assert by_id['schedule:growth_weekly']['nextRun']
    assert by_id['schedule:growth_monthly']['state'] == 'paused'
    assert not any(row.get('canApprove') for row in tasks)
    memory.close()


def test_multiple_actions_for_one_draft_do_not_duplicate_the_decision(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    draft = memory.save_draft(title='One improvement', body='One candidate', kind='article')
    actions = [memory.create_owner_action(OwnerAction(capability_id='growth.candidate.review', provider_id='site-agent',
        title='One improvement', summary='One candidate', action_label='Review', priority=ActionPriority.NORMAL,
        source_ref=f'growth:{number}', requirement=ActionRequirement.OWNER_DECISION, dedupe_key=f'growth:{number}', draft_id=draft)) for number in (1, 2)]
    initiatives = [{'id': number, 'title': 'One improvement', 'state': 'ready_for_review', 'draft_id': draft,
        'owner_action_id': actions[number - 1].id, 'review_package_hash': 'sha256:exact'} for number in (1, 2)]
    tasks = growth_tasks(memory, initiatives, memory.list_drafts(), [], [])
    assert len(tasks) == 1
    assert tasks[0]['id'] == 'initiative:2'
    assert tasks[0]['history'][0]['initiativeId'] == 1
    assert not tasks[0]['canApprove']  # A hash alone is not a publishable review.
    memory.close()


def test_approved_work_is_with_ada_not_a_second_owner_decision(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    action = memory.create_owner_action(OwnerAction(capability_id='growth.publish', provider_id='payload',
        title='Reviewed improvement', summary='Publish the approved version', action_label='Approve',
        priority=ActionPriority.NORMAL, source_ref='growth:1', requirement=ActionRequirement.OWNER_DECISION, dedupe_key='growth:1'))
    approvals = ApprovalService(memory, actions=OwnerActionService(memory))
    approval = approvals.create(Artifact(kind=ArtifactKind.SITE_CHANGE, title='Reviewed improvement', summary='Exact change',
        renderer='site_change', capability_id='growth.publish', provider_id='payload', content_hash='sha256:exact'),
        owner_action_label='Publish', effect_class=EffectClass.SITE_MUTATION, action_id=action.id)
    approvals.decide(approval.approval_id, True)
    task, = growth_tasks(memory, [], [], [], [])
    assert task['focus'] == 'paused'
    assert task['state'] == 'not_running'
    assert task['executionIssue'] is True
    assert not task['canApprove']
    memory.close()


def test_approved_work_is_active_only_while_its_linked_chat_job_is_queued_or_running(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    action = memory.create_owner_action(OwnerAction(capability_id='growth.publish', provider_id='payload',
        title='Reviewed improvement', summary='Publish the approved version', action_label='Approve',
        priority=ActionPriority.NORMAL, source_ref='growth:1', requirement=ActionRequirement.OWNER_DECISION, dedupe_key='growth:1'))
    approvals = ApprovalService(memory, actions=OwnerActionService(memory))
    approval = approvals.create(Artifact(kind=ArtifactKind.SITE_CHANGE, title='Reviewed improvement', summary='Exact change',
        renderer='site_change', capability_id='growth.publish', provider_id='payload', content_hash='sha256:exact'),
        owner_action_label='Publish', effect_class=EffectClass.SITE_MUTATION, action_id=action.id)
    approvals.decide(approval.approval_id, True)
    conversation_id = memory.create_conversation('Publish approved change')
    job_id = memory.enqueue_chat_job(conversation_id, 'Publish approved change')
    memory.link_owner_action(action.id, conversation_id=conversation_id, job_id=job_id)

    task, = growth_tasks(memory, [], [], [], [])
    assert task['focus'] == 'preparing'
    assert task['state'] == 'publishing'
    assert task['executionIssue'] is False
    memory.close()


def test_running_and_retry_work_are_part_of_the_scheduled_task(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    task, = growth_tasks(memory, [], [], [{'id': 'growth_weekly', 'enabled': True, 'nextRun': '2026-10-07T13:30:00Z'}], [],
        [{'run_id': 'week-1', 'trigger': 'weekly', 'status': 'blocked', 'detail': {'error': 'Search source needs reconnection'},
          'next_due_ts': '2026-10-04T13:30:00Z', 'updated_ts': '2026-10-03T13:30:00Z'}])
    assert task['id'] == 'schedule:growth_weekly'
    assert task['focus'] == 'paused'
    assert task['state'] == 'blocked'
    assert task['nextRun'] is None  # A stale retry time must never be presented as a plan.
    assert task['lastError'] is None
    assert task['executionIssue'] is True
    assert task['runId'] == 'week-1'
    memory.close()


def test_uncertain_scheduled_research_is_visible_and_never_presented_as_a_future_retry(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    task, = growth_tasks(memory, [], [], [{'id': 'growth_monthly', 'enabled': True, 'nextRun': '2026-10-20T09:00:00Z'}], [],
        [{'run_id': 'month-1', 'trigger': 'monthly', 'status': 'uncertain', 'updated_ts': '2026-10-15T09:00:00Z',
          'detail': {'error': 'provider did not confirm'}}])
    assert task['focus'] == 'paused'
    assert task['state'] == 'uncertain'
    assert task['summaryKey'] == 'scheduleExecutionUncertain'
    assert task['nextRun'] is None
    assert task['lastError'] is None
    assert task['executionIssue'] is True
    memory.close()


def test_failed_owner_review_run_is_visible_as_service_work_not_an_owner_decision(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    tasks = growth_tasks(memory, [], [], [], [], [{
        'run_id': 'owner-review-1', 'trigger': 'owner_review', 'status': 'failed',
        'phase': 'preparing', 'updated_ts': '2026-10-15T09:00:00Z',
        'next_due_ts': '2099-10-15T09:00:00Z', 'detail': {'error': 'private validator detail'},
    }])

    task, = [row for row in tasks if row['kind'] == 'assessment']
    assert task['id'] == 'assessment:owner-review-1'
    assert task['focus'] == 'paused'
    assert task['summaryKey'] == 'assessmentExecutionFailed'
    assert task['executionIssue'] is True
    assert task['canApprove'] is False
    assert task['nextRun'] == '2099-10-15T09:00:00Z'
    assert task['lastError'] is None
    assert 'private validator detail' not in str(task)
    memory.close()


def test_completed_cycle_does_not_show_an_old_failure_as_current_work(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    task, = growth_tasks(memory, [], [], [{'id': 'growth_weekly', 'enabled': True, 'nextRun': '2026-10-07T13:30:00Z'}], [],
        [{'run_id': 'week-1', 'trigger': 'weekly', 'status': 'blocked', 'updated_ts': '2026-09-25T13:30:00Z'},
         {'run_id': 'week-2', 'trigger': 'weekly', 'status': 'complete', 'updated_ts': '2026-10-02T13:30:00Z'}])
    assert task['focus'] == 'planned'
    assert task['state'] == 'scheduled'
    assert task['runId'] is None
    memory.close()


def test_post_publication_measurements_are_planned_with_real_dates_not_review_decisions(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    initiative = {
        'id': 21,
        'title': 'Improve the local services page',
        'state': 'measuring',
        'expected': {'implementation_baseline': {'metric': 'gsc.clicks'}},
        'review_30_ts': '2099-01-30T09:00:00+00:00',
        'review_90_ts': '2099-04-30T09:00:00+00:00',
        'review_180_ts': '2099-07-30T09:00:00+00:00',
    }
    first = growth_tasks(memory, [initiative], [], [], [])
    measure, = [row for row in first if row['kind'] == 'measurement']
    assert measure['focus'] == 'planned'
    assert measure['nextRun'] == initiative['review_30_ts']
    assert measure['measurementMetric'] == 'gsc.clicks'
    assert not measure['canApprove']

    next_measure, = [row for row in growth_tasks(
        memory, [initiative], [], [], [{'initiative_id': 21, 'horizon_days': 30}],
    ) if row['kind'] == 'measurement']
    assert next_measure['id'] == 'measurement:21:90'
    assert next_measure['nextRun'] == initiative['review_90_ts']
    memory.close()


def test_ready_review_requires_a_complete_exact_pending_approval(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    package_hash = 'sha256:reviewed'
    draft = memory.save_draft(title='Improve the homepage', body='Exact candidate', kind='payload_content',
        meta={'review_package_hash': package_hash, 'growth_package': {'before': {'title': 'Old'}, 'after': {'title': 'New'}}})
    action = memory.create_owner_action(OwnerAction(capability_id='growth.candidate.review', provider_id='site-agent',
        title='Review the homepage', summary='Update the homepage', action_label='Review', priority=ActionPriority.NORMAL,
        source_ref='growth:verified', requirement=ActionRequirement.OWNER_DECISION, dedupe_key='growth:verified', draft_id=draft))
    approvals = ApprovalService(memory, actions=OwnerActionService(memory))
    approval = approvals.create(Artifact(kind=ArtifactKind.SITE_CHANGE, title='Homepage update', summary='Exact change',
        renderer='site_change', capability_id='growth.candidate.review', provider_id='site-agent', content_hash=package_hash),
        owner_action_label='Review', effect_class=EffectClass.SITE_MUTATION, action_id=action.id)
    initiative = {'id': 1, 'title': 'Improve the homepage', 'state': 'ready_for_review', 'draft_id': draft,
        'owner_action_id': action.id, 'approval_id': approval.approval_id, 'review_package_hash': package_hash,
        'validation': {'status': 'passed', 'packageHash': package_hash,
            'checks': {'exactDraft': True, 'publicRenderer': True, 'approvalBoundary': True}}}
    task, = growth_tasks(memory, [initiative], memory.list_drafts(), [], [])
    assert task['focus'] == 'needs_you'
    assert task['canApprove'] is True
    memory.close()


def test_unscheduled_enabled_job_and_completed_provider_failure_are_not_review_decisions(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    tasks = growth_tasks(memory, [], [], [{'id': 'growth_weekly', 'enabled': True, 'nextRun': None}], [],
        article_ideas=[{'id': 4, 'status': 'failed', 'error': 'DATAFORSEO_TASK_40501_INVALID_FIELD_LANGUAGE_CODE_',
            'idea_json': {'working_title': 'A useful article'}}])
    by_id = {row['id']: row for row in tasks}
    assert by_id['schedule:growth_weekly']['focus'] == 'paused'
    assert by_id['schedule:growth_weekly']['state'] == 'unscheduled'
    failure = by_id['article-idea:4']
    assert failure['focus'] == 'paused'
    assert 'DATAFORSEO' not in failure['summary']
    assert failure['lastError'] is None
    assert not any(row['focus'] == 'needs_you' for row in tasks)
    memory.close()


def test_frontend_rollback_enters_review_only_after_exact_preview_is_ready(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    candidate_sha = 'a' * 40
    base_sha = 'b' * 40
    meta = {
        'scope': 'frontend_only', 'contract': 'helloada-content-v1',
        'candidate_sha': candidate_sha, 'base_sha': base_sha,
        'review_package_hash': 'sha256:exact',
        'preview': {'status': 'building', 'requires_build': True, 'head_sha': candidate_sha},
    }
    draft_id = memory.save_draft('Restore website design', 'Frontend only', kind='rollback', meta=meta)

    task, = growth_tasks(memory, [], memory.list_drafts(), [], [])
    assert task['focus'] == 'preparing'
    assert task['canApprove'] is False

    meta['preview'] = {'status': 'ready', 'requires_build': False, 'head_sha': candidate_sha,
        'preview_url': '/api/workspace/source/preview/job/runtime/'}
    memory.save_draft('Restore website design', 'Frontend only', kind='rollback', meta=meta, draft_id=draft_id)
    task, = growth_tasks(memory, [], memory.list_drafts(), [], [])
    assert task['focus'] == 'needs_you'
    assert task['canApprove'] is True
    assert task['reviewPackageHash'] == 'sha256:exact'
    assert task['previewUrl'].endswith('/runtime/')

    meta['preview'] = {'status': 'ready', 'requires_build': False, 'head_sha': 'c' * 40}
    memory.save_draft('Restore website design', 'Frontend only', kind='rollback', meta=meta, draft_id=draft_id)
    task, = growth_tasks(memory, [], memory.list_drafts(), [], [])
    assert task['focus'] == 'preparing'
    assert task['canApprove'] is False
    memory.close()

def test_open_suggestions_remain_internal_and_do_not_become_owner_tasks(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    memory.create_owner_action(OwnerAction(
        capability_id='growth.suggestion', provider_id='site-agent',
        title='Improve the service guide', summary='Ada found a useful opportunity.',
        action_label='Ask Ada', priority=ActionPriority.NORMAL,
        source_ref='growth:suggestion', requirement=ActionRequirement.SUGGESTION,
        dedupe_key='growth:suggestion',
    ))
    assert growth_tasks(memory, [], [], [], []) == []
    memory.close()


def test_started_owner_action_requires_a_live_linked_chat_job(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    stale = memory.create_owner_action(OwnerAction(
        capability_id='growth.review', provider_id='site-agent', title='Review the service page',
        summary='Ask Ada to explain this recommendation.', action_label='Ask Ada', priority=ActionPriority.NORMAL,
        source_ref='growth:stale', requirement=ActionRequirement.OWNER_DECISION, dedupe_key='growth:stale',
        state='started',
    ))
    active = memory.create_owner_action(OwnerAction(
        capability_id='growth.review', provider_id='site-agent', title='Review the article outline',
        summary='Ada is answering the owner.', action_label='Ask Ada', priority=ActionPriority.NORMAL,
        source_ref='growth:active', requirement=ActionRequirement.OWNER_DECISION, dedupe_key='growth:active',
        state='started',
    ))
    conversation_id = memory.create_conversation('Review the article outline')
    job_id = memory.enqueue_chat_job(conversation_id, 'Explain this recommendation')
    memory.link_owner_action(active.id, conversation_id=conversation_id, job_id=job_id)

    tasks = {row['id']: row for row in growth_tasks(memory, [], [], [], [])}
    stale_task = tasks[f'action:{stale.id}']
    assert stale_task['focus'] == 'paused'
    assert stale_task['state'] == 'not_running'
    assert stale_task['executionIssue'] is True
    active_task = tasks[f'action:{active.id}']
    assert active_task['focus'] == 'preparing'
    assert active_task['state'] == 'started'
    assert active_task['executionIssue'] is False
    memory.close()


def test_blocked_article_body_is_available_only_in_explicit_detail_request(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    body = 'Private full article text must not appear in the task list.'
    memory.save_draft(title='A saved article', body=body, kind='article', meta={
        'payload_sync': {'state': 'blocked', 'validation': {'status': 'blocked', 'reason': 'schema mismatch'}},
    })
    task, = growth_tasks(memory, [], memory.list_drafts(), [], [])
    assert task['focus'] == 'paused'
    assert task['state'] == 'blocked'
    assert body not in task['summary']
    assert 'body' not in task['review']['article']
    detailed, = growth_tasks(memory, [], memory.list_drafts(), [], [], include_article_content=True)
    assert detailed['review']['article']['body'] == body
    assert detailed['canApprove'] is False
    memory.close()


def test_missing_article_cover_is_presented_as_a_specific_owner_action(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    memory.save_draft(title='A saved article', body='Article body.', kind='article', meta={
        'payload_sync': {
            'state': 'blocked',
            'validation': {
                'status': 'blocked',
                'reason': 'Ada cannot prepare this article for review because the Payload Library has no analyzed image with alt text and a public URL. Add and analyze a suitable image in Gallery.',
            },
        },
    })

    task, = growth_tasks(memory, [], memory.list_drafts(), [], [])

    assert task['summaryKey'] == 'articleImageNeeded'
    assert 'Gallery' in task['summary']
    assert task['canApprove'] is False
    memory.close()


def test_initiative_is_only_called_active_when_its_growth_run_has_a_live_lease(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    initiative = {'id': 12, 'kind': 'payload_content', 'title': 'Improve the services page',
        'state': 'preparing', 'growth_run_id': 'run-12', 'summary': 'Exact context for Ada.'}

    stale, = growth_tasks(memory, [initiative], [], [], [], [
        {'run_id': 'run-12', 'status': 'complete', 'lease_until': None},
    ])
    assert stale['focus'] == 'paused'
    assert stale['state'] == 'not_running'
    assert stale['executionIssue'] is True

    active, = growth_tasks(memory, [initiative], [], [], [], [
        {'run_id': 'run-12', 'status': 'running', 'lease_until': '2026-10-05T12:05:00+00:00'},
    ])
    assert active['focus'] == 'preparing'
    assert active['state'] == 'preparing'
    assert active['executionIssue'] is False
    memory.close()


def test_payload_revision_job_is_active_and_uncertain_failure_is_reported():
    class MemoryStub:
        def __init__(self):
            self.job = {"id": 71, "status": "running"}

        def list_owner_actions(self, limit=None):
            return []

        def get_chat_job(self, job_id):
            return dict(self.job) if int(job_id) == 71 else None

        def get_approval_request(self, _approval_id):
            return None

    memory = MemoryStub()
    initiative = {
        "id": 8, "kind": "payload_content", "title": "Revise the services page",
        "summary": "Improve the reviewed description.", "state": "validating",
        "validation": {"revision": {"chatJobId": 71, "status": "running"}},
    }

    active, = growth_tasks(memory, [initiative], [], [], [])
    assert active["focus"] == "preparing"
    assert active["state"] == "validating"
    assert active["executionIssue"] is False

    memory.job["status"] = "error"
    initiative["validation"]["revision"] = {
        "chatJobId": 71, "status": "uncertain",
        "error": "Payload returned no verifiable revision receipt",
    }
    uncertain, = growth_tasks(memory, [initiative], [], [], [])
    assert uncertain["focus"] == "paused"
    assert uncertain["state"] == "uncertain"
    assert uncertain["summaryKey"] == "payloadRevisionUncertain"
    assert uncertain["lastError"] == "Payload returned no verifiable revision receipt"
    assert uncertain["executionIssue"] is True


def test_retired_revision_error_is_historical_when_exact_candidate_is_review_ready():
    from types import SimpleNamespace

    class MemoryStub:
        def list_owner_actions(self, limit=None):
            return []

        def get_chat_job(self, _job_id):
            return None

        def get_approval_request(self, _approval_id):
            return SimpleNamespace(status=SimpleNamespace(value="pending"))

    package_hash = "sha256:reviewed"
    draft = {
        "id": 70, "kind": "payload_content", "status": "pending",
        "title": "Reviewed services page", "body": "Exact reviewed copy",
        "meta": {"review_package_hash": package_hash, "growth_package": {"fields": {"description": "Exact reviewed copy"}}},
    }
    initiative = {
        "id": 8, "kind": "payload_content", "title": "Revise the services page",
        "state": "ready_for_review", "draft_id": 70, "approval_id": "approval-70",
        "review_package_hash": package_hash,
        "validation": {
            "status": "passed", "packageHash": package_hash,
            "checks": {"exactDraft": True, "publicRenderer": True, "approvalBoundary": True},
            "revisionFailure": "The obsolete revision request was retired after exact prior-candidate verification.",
            "retiredRevision": {
                "status": "retired_with_exact_prior_candidate_proof",
                "reviewPackageHash": package_hash,
            },
        },
    }

    task, = growth_tasks(MemoryStub(), [initiative], [draft], [], [])
    assert task["canApprove"] is True
    assert task["focus"] == "needs_you"
    assert task["lastError"] is None
    assert task["executionIssue"] is False

    initiative["validation"]["retiredRevision"]["reviewPackageHash"] = "sha256:older-candidate"
    mismatched, = growth_tasks(MemoryStub(), [initiative], [draft], [], [])
    assert mismatched["canApprove"] is True
    assert mismatched["lastError"] == initiative["validation"]["revisionFailure"]
    assert mismatched["executionIssue"] is True
    initiative["validation"]["retiredRevision"]["reviewPackageHash"] = package_hash

    # Historical retirement metadata cannot suppress a current uncertain hold.
    initiative["state"] = "uncertain"
    initiative["validation"]["revision"] = {
        "status": "uncertain", "error": "Payload receipt is still missing",
    }
    held, = growth_tasks(MemoryStub(), [initiative], [draft], [], [])
    assert held["canApprove"] is False
    assert held["executionIssue"] is True
    assert held["lastError"] == "Payload receipt is still missing"


def test_stale_article_research_is_not_shown_as_active_or_as_a_full_brief(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    audience_need = 'A very long audience need that should be available in task detail but never shown as a list-row summary.'
    ideas = [
        {'id': 31, 'status': 'preparing', 'idea_json': {'working_title': 'A saved topic', 'audience_need': audience_need}},
        {'id': 32, 'status': 'research_requested', 'research_run_id': 'keyword-run-32', 'idea_json': {'working_title': 'A current topic', 'audience_need': audience_need}},
        {'id': 33, 'status': 'serp_requested', 'serp_run_id': 'serp-run-33', 'idea_json': {'working_title': 'A current SERP check', 'audience_need': audience_need}},
        {'id': 34, 'status': 'research_requested', 'idea_json': {'working_title': 'An unlinked research request', 'audience_need': audience_need}},
        {'id': 35, 'status': 'researched', 'researched_ts': '2026-10-05T11:00:00+00:00', 'idea_json': {'working_title': 'Research complete, draft pending', 'audience_need': audience_need}},
    ]
    tasks = {row['id']: row for row in growth_tasks(memory, [], [], [], [], article_ideas=ideas)}

    stale = tasks['article-idea:31']
    assert stale['focus'] == 'paused'
    assert stale['state'] == 'not_running'
    assert stale['summaryKey'] == 'articleResearchNotRunning'
    assert stale['summary'] != audience_need
    assert stale['scope'] == audience_need
    active = tasks['article-idea:32']
    assert active['focus'] == 'preparing'
    assert active['summary'] != audience_need
    assert active['scope'] == audience_need
    serp = tasks['article-idea:33']
    assert serp['focus'] == 'preparing'
    assert serp['summaryKey'] == 'articleResearchActive'
    unlinked = tasks['article-idea:34']
    assert unlinked['focus'] == 'paused'
    assert unlinked['state'] == 'not_running'
    assert unlinked['executionIssue'] is True
    complete = tasks['article-idea:35']
    assert complete['focus'] == 'opportunity'
    assert complete['summaryKey'] == 'articleResearchComplete'
    assert complete['executionIssue'] is False
    memory.close()


def test_deterministic_article_research_errors_are_service_work_not_opportunities(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    tasks = {row['id']: row for row in growth_tasks(memory, [], [], [], [], article_ideas=[
        {'id': 41, 'status': 'failed', 'error': 'DATAFORSEO_TASK_40501_INVALID_FIELD_LANGUAGE_CODE_',
         'idea_json': {'working_title': 'Locale-bound topic'}},
        {'id': 42, 'status': 'selected', 'error': 'CrawlSEO idea_summary is invalid',
         'idea_json': {'working_title': 'Invalid research brief'}},
    ])}

    locale = tasks['article-idea:41']
    assert locale['focus'] == 'paused'
    assert locale['summaryKey'] == 'articleResearchLocaleNeedsRepair'
    assert locale['executionIssue'] is True
    assert locale['canApprove'] is False
    assert 'DATAFORSEO' not in str(locale)

    brief = tasks['article-idea:42']
    assert brief['focus'] == 'paused'
    assert brief['summaryKey'] == 'articleResearchRequestNeedsRepair'
    assert brief['executionIssue'] is True
    assert brief['canApprove'] is False
    assert 'CrawlSEO idea_summary is invalid' not in str(brief)
    memory.close()


def test_saved_changes_and_incomplete_reflection_are_stopped_not_approvable(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    reflection_id = memory.save_draft(
        'Self-reflection: proposed voice adjustments', '', kind='reflection',
        meta={'voice_notes': ['Use clearer explanations'], 'avoid': ['generic claims']},
    )
    edit_id = memory.save_draft(
        'Review the journal links', '', kind='edit',
        meta={
            'summary': 'Connect the journal articles into a useful reading path.',
            'ops': [{
                'op': 'edit',
                'path': 'content/articles/example.md',
                'find': 'Read the next article.',
                'replace': 'Read the related guide.',
            }],
        },
    )
    merge_id = memory.save_draft(
        'Fix the Journal link', '', kind='merge',
        meta={'summary': 'Repair the broken Journal navigation link.', 'payload_sync': {'state': 'blocked'}},
    )
    tasks = {row['id']: row for row in growth_tasks(memory, [], memory.list_drafts(), [], [])}

    reflection = tasks[f'settings:{reflection_id}']
    assert reflection['focus'] == 'paused'
    assert reflection['state'] == 'not_running'
    assert reflection['executionIssue'] is False
    assert reflection['needsPreparation'] is True
    assert reflection['canApprove'] is False

    edit = tasks[f'draft:{edit_id}']
    assert edit['focus'] == 'paused'
    assert edit['summaryKey'] == 'websiteChangeNotReady'
    assert edit['executionIssue'] is False
    assert edit['needsPreparation'] is True
    assert edit['canApprove'] is False

    merge = tasks[f'draft:{merge_id}']
    assert merge['focus'] == 'paused'
    assert merge['summaryKey'] == 'codeChangeNotReady'
    assert merge['executionIssue'] is False
    assert merge['needsPreparation'] is True
    assert merge['canApprove'] is False
    memory.close()
