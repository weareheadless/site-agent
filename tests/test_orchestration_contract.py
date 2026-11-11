import pytest
from contextlib import closing

from site_agent.brain.editor import _validate_website_change_plan
from site_agent.hands.repo_changes import source_path_allowed, source_authoring_contract


def config():
    """A registered source-authored tenant, as the API actually loads it.

    The shipped defaults fill ``site.writable_patterns`` with the scaffold's
    presentation files, so a tenant that never configured one still arrives
    here with that list. The ownership boundary cannot depend on it.
    """
    return {'design_engine': {'build_profile': 'next_react'}, 'site': {
        'writable_patterns': [
            'src/app/(frontend)/site.css', 'src/components/site/presentation/**',
            'src/components/site/TenantChrome.tsx', 'public/site/**', 'public/fonts/**',
        ]}}


BESPOKE_FILES = [
    'src/app/(frontend)/page.tsx',
    'src/app/(frontend)/courses/page.tsx',
    'src/app/(frontend)/courses/[slug]/page.tsx',
    'src/app/(frontend)/excursions/page.tsx',
    'src/app/(frontend)/excursions/[slug]/page.tsx',
    'src/app/(frontend)/depth/page.tsx',
    'src/app/(frontend)/site.css',
    'src/content/site.ts',
    'src/components/dive/DiveScene.tsx',
    'src/components/site/presentation/Training.tsx',
    'public/site/excursion-cenote.webp',
    'public/robots.txt',
    'src/app/robots.ts',
]

PLATFORM_FILES = [
    'package.json', 'package-lock.json', 'next.config.mjs', 'tsconfig.json',
    'payload.config.ts', 'wrangler.jsonc', 'worker.ts', 'open-next.config.ts',
    'src/middleware.ts', 'src/helloada.config.ts', 'src/payload-types.ts',
    'src/app/(frontend)/layout.tsx', 'src/app/(frontend)/[[...slug]]/page.tsx',
    'src/app/(payload)/admin/importMap.js',
    'src/app/api/helloada/[...path]/route.ts', 'src/app/api/workspace/content/route.ts',
    'src/collections/Pages.ts', 'src/globals/SiteSettings.ts', 'src/migrations/index.ts',
    'src/lib/content.ts', 'src/lib/content-routes.ts', 'src/lib/helloada-auth.ts',
    'src/lib/runtime-env.ts', 'src/lib/service-auth.ts',
    'src/components/admin/HelloAdaNav.tsx', 'src/components/PublicDocument.tsx',
    'src/components/site/TenantSections.tsx', 'public/brand/helloada-logo.svg',
    'helloada-content-contract.json', 'template-manifest.json',
    '.helloada-managed.json', '.gitignore', '.env', '.github/workflows/ci.yml',
]


def _plan(*paths):
    return {
        'content_effects': [], 'source_brief': 'Add the courses and excursions',
        'source_paths': list(paths),
        'acceptance_criteria': ['Every course has a page'], 'response_only': False,
    }


def test_a_source_authored_site_can_author_its_own_composition():
    for path in BESPOKE_FILES:
        assert source_path_allowed(config(), path), path
    # The plan validator and the build sandbox are one decision.
    accepted = _validate_website_change_plan(
        _plan('src/app/(frontend)/excursions/page.tsx', 'src/content/site.ts'),
        None, config(),
    )
    assert accepted['source_paths'] == [
        'src/app/(frontend)/excursions/page.tsx', 'src/content/site.ts',
    ]


def test_platform_source_stays_outside_the_tenant_boundary():
    for path in PLATFORM_FILES:
        assert not source_path_allowed(config(), path), path
        with pytest.raises(ValueError, match='outside tenant ownership'):
            _validate_website_change_plan(_plan(path), None, config())


def test_the_ownership_statement_and_the_gate_are_the_same_decision():
    ownership = source_authoring_contract(config())
    assert ownership['frontend_only'] is True
    # A replaced composition cannot be described by a pattern list; the
    # protected paths are the boundary the prompt and the sandbox share.
    assert ownership['configured_patterns'] == ['**']
    assert 'except protected_paths' in ownership['rule']
    protected = ownership['protected_paths']
    for path in BESPOKE_FILES + PLATFORM_FILES:
        declared_protected = any(
            path == entry or path.startswith(entry.rstrip('/') + '/') for entry in protected
        )
        assert source_path_allowed(config(), path) is not declared_protected, path


def test_every_file_the_shared_runtime_release_touches_is_platform_owned():
    import json
    from pathlib import Path

    from site_agent.frontend_ownership import is_frontend_owned_path

    overlay = json.loads(
        (Path(__file__).resolve().parents[1] / 'deploy/shared-runtime-overlay.json').read_text()
    )
    touched = [
        *overlay['copy'], *overlay['remove'], *overlay['copyTrees'], *overlay['fingerprintTrees'],
    ]
    assert touched
    for path in touched:
        assert not is_frontend_owned_path(path), path


def test_non_next_config_keeps_its_configured_allowlist():
    standard_site = {
        'site': {'writable_patterns': ['src/app/(frontend)/**', 'public/**']},
    }
    assert source_path_allowed(standard_site, 'src/app/(frontend)/site.css')
    assert not source_path_allowed(standard_site, 'src/app/robots.ts')
    assert source_authoring_contract(standard_site)['configured_patterns'] == [
        'src/app/(frontend)/**', 'public/**',
    ]


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


def test_stale_job_moves_its_linked_owner_action_to_waiting(tmp_path):
    """The watchdog must close linked actions itself; the old helper is gone."""
    from site_agent.core.contracts import (
        ActionPriority,
        ActionRequirement,
        ActionState,
        OwnerAction,
    )
    from site_agent.core.memory import Memory

    with closing(Memory(tmp_path / 'memory.db')) as memory:
        conversation = memory.create_conversation()
        job_id = memory.enqueue_chat_job(conversation, 'Review the requested changes')
        memory.claim_chat_job('test-worker')
        action = memory.create_owner_action(OwnerAction(
            capability_id='review.site_change',
            provider_id='site-agent',
            title='Review the requested changes',
            summary='A pending change is waiting for review.',
            action_label='Review',
            priority=ActionPriority.NORMAL,
            requirement=ActionRequirement.OWNER_DECISION,
            source_ref=f'chat-job:{job_id}',
            dedupe_key=f'chat-job:{job_id}',
            state=ActionState.STARTED,
        ))
        memory.link_owner_action(action.id, conversation_id=conversation, job_id=job_id)

        assert memory.fail_stale_chat_jobs(cut=10**12) == [job_id]

        assert memory.get_chat_job(job_id)['status'] == 'error'
        assert memory.get_owner_action(action.id).state is ActionState.WAITING


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
        ([], "I haven't built or previewed this yet, so nothing has changed. "
             "Choose a direction, then ask me to build it when you're ready."),
        ([{"kind": "collection", "operation": "update"}],
         "I haven't built or previewed this yet, so nothing has changed. "
         "Choose a direction, then ask me to build it when you're ready."),
        (None, "I haven't built or previewed this yet, so nothing has changed. "
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
    # The brief requires the gitignored builder artifact; denying it failed a
    # completed build on its final write.
    assert permissions['edit']['.opencode/tweak-map.json'] == 'allow'
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


def test_an_offer_to_build_later_does_not_erase_the_answer_around_it():
    """A plan that ends "I'll build it when you confirm" is not a false claim.

    Replacing the whole message with one canned sentence also replaced the
    assistant turn in the conversation, so the owner's next "state the plan
    again" had nothing left to restate.
    """
    from site_agent.brain.owner_copy import owner_message_without_unstarted_build

    plan = (
        "A page is the right shape. A section alone cannot rank for his name, cannot hold "
        "the credentials without bloating the homepage, and gives you nothing to link to "
        "from course pages.\n\n"
        "1. A page at /about/peter-abaji with the credential strip and competition record.\n"
        "2. A homepage band with a portrait and three facts, linking to the page.\n"
        "3. A byline on every course page that links to it.\n\n"
        "I'll build it once you confirm the portrait and the bio are ready."
    )
    assert owner_message_without_unstarted_build(plan, action_started=False) == plan


def test_a_false_completion_claim_is_removed_without_discarding_the_rest():
    from site_agent.brain.owner_copy import owner_message_without_unstarted_build

    message = (
        "I've built the profile page and the preview is ready. "
        "It uses the journal type scale and the same footer as the homepage."
    )
    kept = owner_message_without_unstarted_build(message, action_started=False)
    assert "I've built" not in kept
    assert "preview is ready" not in kept
    assert "journal type scale" in kept


def test_a_message_that_is_only_a_false_completion_claim_states_the_truth():
    from site_agent.brain.owner_copy import owner_message_without_unstarted_build

    kept = owner_message_without_unstarted_build("I've built the page.", action_started=False)
    assert "haven't built or previewed" in kept
