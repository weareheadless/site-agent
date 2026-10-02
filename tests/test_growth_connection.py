from types import SimpleNamespace
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml

from site_agent.application.growth import growth_snapshot
from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
from site_agent.core.memory import Memory
from site_agent.web.workspace import register_workspace_routes
from site_agent.application.seo_bootstrap import load_tenant_environment


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


def test_migrated_tenant_keeps_its_existing_provider_credential_file(tmp_path):
    credential_file = tmp_path / 'tenant.env'
    credential_file.write_text('CRAWLSEO_SERVICE_TOKEN=tenant-research-fixture\nPROVISIONED_DEMO_TOKEN=old-fixture\n')
    config = {'data_dir': str(tmp_path / 'data'), 'credentials': {'env_file': str(credential_file)}}
    env = load_tenant_environment(config, {'PROVISIONED_DEMO_TOKEN': 'canonical-fixture'})
    assert env['CRAWLSEO_SERVICE_TOKEN'] == 'tenant-research-fixture'
    assert env['PROVISIONED_DEMO_TOKEN'] == 'canonical-fixture'


def test_site_origin_change_is_persisted_before_runtime_reconciliation(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(yaml.safe_dump({
        'site': {'preview_url': 'https://demo.workers.dev/'},
        'seo': {
            'enabled': True,
            'site_url': 'https://demo.workers.dev/',
            'gsc_property': 'https://demo.workers.dev/',
            'provisioning': {'auto': True, 'gsc_property': 'https://demo.workers.dev/'},
        },
        'ga': {'enabled': True},
    }), encoding='utf-8')
    tenant = Tenant(
        tenant_id='demo',
        config={},
        memory=None,
        runtime=None,
        context={},
        api_token='demo-token',
        config_path=str(config_path),
        api_token_env='CUSTOM_DEMO_TOKEN',
    )
    registry = TenantRegistry({'demo': tenant})
    calls = []

    def reload_tenant(tenant_id, path, **kwargs):
        calls.append((tenant_id, path, kwargs))
        return tenant

    registry.reload_tenant = reload_tenant
    registry.update_site_origin('demo', 'https://www.demo.example')

    updated = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    assert updated['site']['public_url'] == 'https://www.demo.example/'
    assert updated['site']['url'] == 'https://www.demo.example/'
    assert updated['site']['custom_domain'] == 'www.demo.example'
    assert updated['seo']['site_url'] == 'https://www.demo.example/'
    assert updated['seo']['gsc_property'] == 'https://www.demo.example/'
    assert updated['seo']['provisioning']['gsc_property'] == 'https://www.demo.example/'
    assert calls[0][0] == 'demo'
    assert calls[0][2]['api_token'] == 'demo-token'
    assert calls[0][2]['api_token_env'] == 'CUSTOM_DEMO_TOKEN'
