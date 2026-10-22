import pytest

from site_agent.brain.editor import _execute_tool, _validate_website_change_plan, handle_message
from site_agent.core.memory import Memory
from site_agent.hands.base import SiteAdapter


def contract():
    return {'locales': ['en'], 'defaultLocale': 'en', 'enabled': {'collections': ['posts']},
        'authoring': {'collections': {'posts': [
            {'name': 'slug', 'type': 'text', 'required': True},
            {'name': 'title', 'type': 'text', 'required': True},
            {'name': 'summary', 'type': 'text'},
        ]}}}


def plan(fields):
    return {'content_effects': [{'kind': 'collection', 'operation': 'create',
        'collection': 'posts', 'identifier': 'new-article', 'identifier_kind': 'slug',
        'fields': fields, 'summary': 'Prepare the requested article'}], 'source_brief': ''}


def test_create_plan_cannot_freeze_an_impossible_required_field_set():
    with pytest.raises(ValueError, match='required.*title'):
        _validate_website_change_plan(plan(['slug']), contract())
    assert _validate_website_change_plan(plan(['slug', 'title']), contract())


def test_payload_refusal_is_logged_with_job_identity_not_arguments(caplog):
    context = {'config': {}, 'memory': object(), 'tenant_id': 'test-tenant', '_chat_job_id': 65,
        'payload_gateway': object(), '_authoring_contract': contract(),
        '_website_change_plan': _validate_website_change_plan(plan(['slug', 'title']), contract())}
    result = _execute_tool(context, None, 'create_payload_draft',
        {'collection': 'posts', 'data': {'slug': 'new-article'}}, lambda _: None)
    assert result.startswith('REFUSED:')
    assert 'job=65' in caplog.text
    assert 'tool=create_payload_draft' in caplog.text
    assert 'exactly match the validated plan' in caplog.text
    assert 'new-article' not in caplog.text


def test_tool_budget_exhaustion_is_not_reported_as_a_connection_failure(tmp_path):
    class LLM:
        def chat_tools(self, *args, **kwargs):
            return {'content': None, 'tool_calls': [{'id': 'call-1', 'type': 'function',
                'function': {'name': 'get_growth', 'arguments': '{}'}}]}
    class Adapter(SiteAdapter):
        name = 'test'
        site = {}
        def commit_file(self, *args, **kwargs):
            raise AssertionError('No website mutation is permitted')
    memory = Memory(tmp_path / 'memory.db')
    try:
        context = {'memory': memory, 'llm': LLM(), 'config': {
            'persona': {'name': 'Ada'}, 'llm': {'tool_calling': True, 'max_work_steps': 1},
            'site': {'adapter': 'github_static', 'repository': 'acme/site'}}}
        with pytest.raises(RuntimeError, match='tool-step limit'):
            handle_message(context, Adapter(), 'Check the saved growth status without changing anything')
    finally:
        memory.close()
