from types import SimpleNamespace
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application.growth import growth_snapshot
from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
from site_agent.core.memory import Memory
from site_agent.web.workspace import register_workspace_routes


def test_growth_is_readonly_and_does_not_invent_provider_data(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    memory.save_draft('Owner article', 'Existing draft', kind='article')
    memory.save_draft('Weekly progress', 'Existing report', kind='report')
    memory.save_seo_insight(period='2026-10', headline='Improve local search', summary_md='Grounded recommendation')
    idea = memory.create_article_idea('article:2026-W40', 'idea-hash', {'working_title': 'Useful local guide', 'thesis': 'Answer a real question'})
    memory.update_article_idea(idea['id'], research_result_json=[{'keyword': 'local service', 'search_volume': 20, 'competition': 0.2, 'credential_token': 'private-never-return'}])
    report = memory.create_seo_site_report('2026-10')
    memory.update_seo_site_report(report['id'], summary='Existing SEO report', status='completed')
    memory.kv_set('seo_provisioning_state', {'ga4_property_id': 'properties/123', 'gsc_property': 'https://example.test', 'gsc_pending': True, 'credential_token': 'private-never-return'})
    memory.kv_set('next_run:article', 1791000000)
    scheduler = SimpleNamespace(jobs=[('article', {'every': 'week'}, object())])
    before = memory.list_drafts()
    result = growth_snapshot(memory, {}, {'scheduler': scheduler})
    assert result['articles'][0]['title'] == 'Owner article'
    assert result['weeklyReports'][0]['body'] == 'Existing report'
    assert result['latestInsight']['headline'] == 'Improve local search'
    assert result['keywordMetrics'][0]['search_volume'] == 20
    assert result['monthlyReports'][0]['body_md'] == 'Existing SEO report'
    assert result['sources'][0]['status'] == 'collecting'
    assert result['sources'][1]['status'] == 'verification_required'
    assert result['sources'][2]['status'] == 'not_configured'
    assert result['activities'][0]['enabled'] is True
    assert result['activities'][0]['nextRun']
    assert result['activities'][1]['enabled'] is False
    assert 'private-never-return' not in json.dumps(result)
    assert 'credential_token' not in json.dumps(result)
    assert memory.list_drafts() == before
    assert result['approvalRequired'] is True


def test_connection_and_growth_are_authenticated_and_tenant_isolated(tmp_path):
    tenants = {}
    for name in ('alpha', 'beta'):
        memory = Memory(tmp_path / f'{name}.db')
        memory.save_draft(f'{name} article', f'{name} only')
        tenants[name] = Tenant(name, {}, memory, None, {'llm': SimpleNamespace(api_key='configured') if name == 'alpha' else None}, f'{name}-token')
    registry = TenantRegistry(tenants)
    service = ChatService(registry=registry)
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=service, registry=registry)
    with TestClient(app) as client:
        for path in ('connection', 'growth'):
            assert client.get(f'/api/workspace/{path}').status_code == 401
            assert client.get(f'/api/workspace/{path}', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        for name in tenants:
            headers = {'Authorization': f'Bearer {name}-token'}
            connection = client.get('/api/workspace/connection', headers=headers).json()
            assert connection == {'tenant': name, 'connected': True, 'ready': name == 'alpha'}
            # Existing growth records are still readable when the AI is unconfigured.
            growth = client.get('/api/workspace/growth', headers=headers).json()
            assert growth['tenant'] == name
            assert [article['title'] for article in growth['articles']] == [f'{name} article']
            assert 'token' not in json.dumps(connection)
