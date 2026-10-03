from site_agent.application.growth_tasks import growth_tasks
from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction
from site_agent.core.memory import Memory
from site_agent.application.approvals import ApprovalService
from site_agent.application.actions import OwnerActionService
from site_agent.core.contracts import Artifact, ArtifactKind, EffectClass


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
    assert tasks[0]['focus'] == 'preparing'
    assert tasks[0]['draftId'] == draft
    assert tasks[0]['ownerActionId'] == action.id
    assert tasks[0]['reviewPackageHash'] == 'sha256:exact'
    assert not tasks[0]['canApprove']
    memory.close()


def test_schedule_and_internal_block_are_not_fake_owner_decisions(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    tasks = growth_tasks(memory, [{'id': 1, 'title': 'Prepare an article', 'state': 'blocked', 'last_error': 'Search evidence unavailable'}], [],
        [{'id': 'growth_weekly', 'enabled': True, 'nextRun': '2026-10-05T13:30:00Z'},
         {'id': 'growth_monthly', 'enabled': False, 'nextRun': None}], [])
    assert [row['focus'] for row in tasks] == ['preparing', 'planned', 'paused']
    assert tasks[0]['lastError'] is None
    assert tasks[0]['executionIssue'] is True
    assert tasks[1]['nextRun']
    assert tasks[2]['state'] == 'paused'
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
    assert task['focus'] == 'preparing'
    assert task['state'] == 'publishing'
    assert not task['canApprove']
    memory.close()


def test_running_and_retry_work_are_part_of_the_scheduled_task(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    task, = growth_tasks(memory, [], [], [{'id': 'growth_weekly', 'enabled': True, 'nextRun': '2026-10-05T13:30:00Z'}], [],
        [{'run_id': 'week-1', 'trigger': 'weekly', 'status': 'blocked', 'detail': {'error': 'Search source needs reconnection'},
          'next_due_ts': '2026-10-04T13:30:00Z', 'updated_ts': '2026-10-03T13:30:00Z'}])
    assert task['id'] == 'schedule:growth_weekly'
    assert task['focus'] == 'preparing'
    assert task['nextRun'] == '2026-10-04T13:30:00Z'
    assert task['lastError'] is None
    assert task['executionIssue'] is True
    assert task['runId'] == 'week-1'
    memory.close()


def test_completed_cycle_does_not_show_an_old_failure_as_current_work(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    task, = growth_tasks(memory, [], [], [{'id': 'growth_weekly', 'enabled': True, 'nextRun': '2026-10-05T13:30:00Z'}], [],
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
    assert failure['focus'] == 'completed'
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
