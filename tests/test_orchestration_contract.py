import pytest
from contextlib import closing

from site_agent.brain.editor import _validate_website_change_plan
from site_agent.hands.repo_changes import source_path_allowed


def config():
    return {'design_engine': {'build_profile': 'next_react'}, 'site': {
        'writable_patterns': ['next.config.mjs', 'src/app/(frontend)/**', 'src/components/**', 'public/**']}}


def test_source_plan_and_validator_share_the_ownership_boundary():
    plan = {'content_effects': [], 'source_brief': 'Improve the section typography',
            'source_paths': ['src/components/site/presentation/Training.tsx'],
            'acceptance_criteria': ['Typography stays readable at mobile widths'], 'response_only': False}
    accepted = _validate_website_change_plan(plan, None, config())
    assert accepted['source_paths'] == plan['source_paths']
    assert source_path_allowed(config(), accepted['source_paths'][0])
    for path in ['public/robots.txt', 'src/app/(frontend)/page.tsx', 'src/app/sitemap.ts', 'next.config.mjs']:
        assert not source_path_allowed(config(), path)
        with pytest.raises(ValueError, match='outside tenant ownership'):
            _validate_website_change_plan({**plan, 'source_paths': [path]}, None, config())


def test_source_plan_requires_an_explicit_scope_before_delegation():
    with pytest.raises(ValueError, match='declare source_paths'):
        _validate_website_change_plan({'content_effects': [], 'source_brief': 'Improve SEO',
                                      'response_only': False}, None, config())


@pytest.mark.parametrize('failure', ['worker', 'restart', 'stale'])
def test_failure_outcome_is_durable_and_not_duplicated(tmp_path, failure):
    from site_agent.core.memory import Memory

    with closing(Memory(tmp_path / 'memory.db')) as memory:
        conversation = memory.create_conversation()
        job_id = memory.enqueue_chat_job(conversation, 'Prepare the requested changes')
        memory.claim_chat_job('test-worker')
        if failure == 'worker':
            assert memory.fail_chat_job(job_id, 'test-worker', 'Builder failed: outside the writable sandbox')
            assert not memory.fail_chat_job(job_id, 'test-worker', 'duplicate terminal result')
        elif failure == 'restart':
            assert memory.interrupt_running_chat_jobs() == 1
            assert memory.interrupt_running_chat_jobs() == 0
        else:
            assert memory.fail_stale_chat_jobs(cut=10**12) == [job_id]
            assert memory.fail_stale_chat_jobs(cut=10**12) == []
        job = memory.get_chat_job(job_id)
        assert job['status'] == 'error'
        messages = memory.get_messages(conversation)
        answers = [message for message in messages if message['role'] == 'assistant']
        assert len(answers) == 1
        assert answers[0]['text'] == job['result']['reply']
        assert 'sandbox' not in answers[0]['text']
        assert job['result']['failure']['job_id'] == job_id


def test_orchestrator_gets_previous_job_evidence_without_raw_errors(tmp_path):
    from site_agent.core.memory import Memory
    from site_agent.brain.task_context import conversation_tasks

    with closing(Memory(tmp_path / 'memory.db')) as memory:
        conversation = memory.create_conversation()
        previous_id = memory.enqueue_chat_job(conversation, 'Review the crawl')
        memory.claim_chat_job('worker')
        memory.append_chat_job_step(previous_id, 'worker', 'validating the generated preview')
        memory.fail_chat_job(previous_id, 'worker', 'Builder failed: outside the writable sandbox: private-path')
        current_id = memory.enqueue_chat_job(conversation, 'What happened?')
        tasks = conversation_tasks({'memory': memory, '_chat_job_id': current_id})
        assert len(tasks) == 1
        assert tasks[0]['job_id'] == previous_id
        assert tasks[0]['status'] == 'error'
        assert tasks[0]['failure_boundary'] == 'source_scope'
        assert tasks[0]['latest_progress'][0]['text'] == 'validating the generated preview'
        assert 'private-path' not in str(tasks)


@pytest.mark.parametrize('kind', ['maintenance', 'presentation'])
def test_delegated_context_is_task_local_and_retains_relevant_design_requirements(tmp_path, kind):
    import subprocess
    from site_agent.hands.opencode_runner import install_agent_files

    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    class MemoryMustNotBeInjected:
        def recent_observations(self, **kwargs):
            raise AssertionError('generic memory must not be loaded into a delegated task')

    install_agent_files(tmp_path, None, 'openrouter/deepseek/deepseek-v4.1-flash',
                        memory=MemoryMustNotBeInjected(), task_contract={
                            'source_kind': kind, 'source_brief': 'Improve the selected section',
                            'source_paths': ['src/components/site/presentation/Training.tsx'],
                            'acceptance_criteria': ['Preserve the mobile layout'],
                            'business_facts': ['Training takes place in Bacalar'],
                        })
    instructions = (tmp_path / '.opencode/ada-instructions.md').read_text()
    assert 'Training takes place in Bacalar' in instructions
    assert 'Preserve the mobile layout' in instructions
    assert ('DESIGN SKILL SET' in instructions) == (kind == 'presentation')
    assert 'What you have read lately' not in instructions
