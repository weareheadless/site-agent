import pytest
from contextlib import closing

from site_agent.brain.editor import _validate_website_change_plan
from site_agent.hands.repo_changes import source_path_allowed, source_authoring_contract


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
    assert source_path_allowed(config(), 'src/app/(frontend)/oceanic.css')
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


@pytest.mark.parametrize(
    ("payload_effects", "expected_reply"),
    [
        ([{
            "kind": "collection",
            "operation": "update",
            "target": "posts",
            "document_id": "7",
            "revision": "sha256:" + "b" * 64,
            "fields": ["body", "seo"],
            "locale": "en",
            "summary": "Updated the requested draft fields",
        }], "I've updated the page draft with the requested fields. It remains unpublished."),
        ([], "To be clear, I haven't built or previewed this yet. These are directions only. "
             "Choose a direction, then ask me to build it when you're ready."),
        ([{"kind": "collection", "operation": "update"}],
         "To be clear, I haven't built or previewed this yet. These are directions only. "
         "Choose a direction, then ask me to build it when you're ready."),
        (None, "To be clear, I haven't built or previewed this yet. These are directions only. "
              "Choose a direction, then ask me to build it when you're ready."),
    ],
)
def test_chat_job_uses_payload_receipt_for_reply_safety_without_weakening_build_guard(
    tmp_path, monkeypatch, payload_effects, expected_reply
):
    from site_agent.brain import editor
    from site_agent.core.chat_jobs import run_job
    from site_agent.core.memory import Memory

    model_reply = "I've updated the page draft with the requested fields. It remains unpublished."

    def handle_message(context, *args, **kwargs):
        if payload_effects is not None:
            context["_completed_payload_effects"] = payload_effects
        return {"reply": model_reply, "proposal_id": None, "merge_draft_id": None}

    monkeypatch.setattr(editor, "handle_message", handle_message)
    with closing(Memory(tmp_path / "memory.db")) as memory:
        conversation = memory.create_conversation()
        job_id = memory.enqueue_chat_job(conversation, "Update the selected post draft")
        memory.claim_chat_job("test-worker")
        job = memory.get_chat_job(job_id)
        context = {
            "memory": memory,
            "config": {"site": {}},
            "env": {},
            "_completed_payload_effects": [{
                "kind": "collection", "operation": "update", "target": "posts",
                "document_id": "old-job", "revision": "sha256:" + "c" * 64,
                "fields": ["body"], "locale": "en", "summary": "Prior job receipt",
            }],
        }

        result = run_job(context, job, "test-worker", adapter_factory=lambda: object())

        assert result["reply"] == expected_reply


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


def test_editor_requests_sequential_tool_calls(monkeypatch):
    from site_agent.application import growth
    from site_agent.brain import editor, prompts, task_context

    class ToolsLLM:
        def __init__(self):
            self.kwargs = None

        def chat_tools(self, messages, tools, **kwargs):
            self.kwargs = kwargs
            return {"content": "I checked the request.", "tool_calls": None}

    llm = ToolsLLM()
    memory = object()
    monkeypatch.setattr(editor, "_payload_gateway", lambda context: None)
    monkeypatch.setattr(editor, "_writable_patterns", lambda context: [])
    monkeypatch.setattr(editor, "inner_life_context", lambda memory: "")
    monkeypatch.setattr(editor, "configured_site_profile_prompt", lambda config: "")
    monkeypatch.setattr(editor, "_workspace_language", lambda message: None)
    monkeypatch.setattr(editor, "_tweakmap_block", lambda context: "")
    monkeypatch.setattr(editor, "_template_tokens_block", lambda context: "")
    monkeypatch.setattr(editor, "_decision_ledger_block", lambda context: "")
    monkeypatch.setattr(editor, "_looks_like_design_request", lambda message: False)
    monkeypatch.setattr(editor, "_tools_spec", lambda *args, **kwargs: [])
    monkeypatch.setattr(editor, "_max_work_steps", lambda context: 1)
    monkeypatch.setattr(task_context, "conversation_tasks", lambda context: [])
    monkeypatch.setattr(growth, "growth_chat_context", lambda *args: {})
    monkeypatch.setattr(prompts, "memory_context", lambda *args, **kwargs: "")

    editor._handle_message_tools(
        {"llm": llm, "memory": memory, "config": config()},
        adapter=None,
        message="Check the current draft status",
        history=[],
        progress=None,
        persona="",
    )

    assert llm.kwargs["parallel_tool_calls"] is False


def test_mixed_side_effect_batch_remains_fail_closed(monkeypatch):
    from site_agent.application import growth
    from site_agent.brain import editor, prompts, task_context

    calls = [
        {"id": "plan-1", "type": "function", "function": {"name": "plan_website_change", "arguments": "{}"}},
        {"id": "plan-2", "type": "function", "function": {"name": "plan_website_change", "arguments": "{}"}},
    ]

    class ToolsLLM:
        def __init__(self):
            self.responses = [
                {"content": None, "tool_calls": calls},
                {"content": "The batch was refused; no change was made.", "tool_calls": None},
            ]
            self.requests = []

        def chat_tools(self, messages, tools, **kwargs):
            self.requests.append((messages, kwargs))
            return self.responses.pop(0)

    llm = ToolsLLM()
    memory = object()
    monkeypatch.setattr(editor, "_payload_gateway", lambda context: None)
    monkeypatch.setattr(editor, "_writable_patterns", lambda context: [])
    monkeypatch.setattr(editor, "inner_life_context", lambda memory: "")
    monkeypatch.setattr(editor, "configured_site_profile_prompt", lambda config: "")
    monkeypatch.setattr(editor, "_workspace_language", lambda message: None)
    monkeypatch.setattr(editor, "_tweakmap_block", lambda context: "")
    monkeypatch.setattr(editor, "_template_tokens_block", lambda context: "")
    monkeypatch.setattr(editor, "_decision_ledger_block", lambda context: "")
    monkeypatch.setattr(editor, "_looks_like_design_request", lambda message: False)
    monkeypatch.setattr(
        editor, "_tools_spec",
        lambda *args, **kwargs: [{"function": {"name": "plan_website_change"}}],
    )
    monkeypatch.setattr(editor, "_execute_tool", lambda *args, **kwargs: pytest.fail("batch executed"))
    monkeypatch.setattr(editor, "_max_work_steps", lambda context: 2)
    monkeypatch.setattr(task_context, "conversation_tasks", lambda context: [])
    monkeypatch.setattr(growth, "growth_chat_context", lambda *args: {})
    monkeypatch.setattr(prompts, "memory_context", lambda *args, **kwargs: "")

    result = editor._handle_message_tools(
        {"llm": llm, "memory": memory, "config": config()},
        adapter=None,
        message="Check the draft",
        history=[],
        progress=None,
        persona="",
    )

    assert result["reply"] == "The batch was refused; no change was made."
    assert len(llm.requests) == 2
    assert all(kwargs["parallel_tool_calls"] is False for _, kwargs in llm.requests)
    tool_results = [message for message in llm.requests[1][0] if message["role"] == "tool"]
    assert len(tool_results) == 2
    assert all(message["content"].startswith("REFUSED:") for message in tool_results)


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
                            'ownership': source_authoring_contract(config()),
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


def test_delegated_permissions_allow_only_planned_files_and_no_shell(tmp_path):
    import json
    import subprocess
    from site_agent.hands.opencode_runner import install_agent_files
    from site_agent.hands.repo_changes import source_authoring_contract

    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    planned = 'src/app/(frontend)/site.css'
    install_agent_files(tmp_path, None, None, task_contract={
        'source_kind': 'maintenance', 'source_paths': [planned],
        'ownership': source_authoring_contract(config()),
    })
    installed = json.loads((tmp_path / 'opencode.json').read_text())
    permissions = installed['permission']
    assert permissions['edit']['*'] == 'deny'
    assert permissions['edit'][planned] == 'allow'
    assert permissions['edit'][str(tmp_path / planned)] == 'allow'
    assert 'src/app/(frontend)/oceanic.css' not in permissions['edit']
    assert permissions['bash'] == permissions['shell'] == 'deny'
    assert permissions['external_directory'] == 'deny'
    assert permissions['task'] == 'deny'
    assert installed['agent']['build']['permission'] == permissions


def test_delegated_permissions_refuse_unowned_paths_before_install(tmp_path):
    from site_agent.hands.opencode_runner import _delegated_permissions, RunnerError
    from site_agent.hands.repo_changes import source_authoring_contract

    for path in ['src/app/(frontend)/layout.tsx', '../outside.css', 'src/components/site/presentation/*']:
        with pytest.raises(RunnerError, match='delegated source'):
            _delegated_permissions(tmp_path, {
                'source_paths': [path], 'ownership': source_authoring_contract(config()),
            })
