from types import SimpleNamespace
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml
import pytest

from site_agent.application.growth import growth_snapshot
from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
import site_agent.application.workspace as workspace_module
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
    memory.kv_set('next_run:growth_initial', 1791000000)
    scheduler = SimpleNamespace(jobs=[('growth_initial', {'every': 'week'}, object())])
    before = memory.list_drafts()
    result = growth_snapshot(memory, {}, {'scheduler': scheduler})
    assert result['articles'][0]['title'] == 'Owner article'
    assert 'weeklyReports' not in result
    assert 'monthlyReports' not in result
    assert result['latestInsight']['headline'] == 'Improve local search'
    assert result['keywordMetrics'][0]['search_volume'] == 20
    assert result['sources'][0]['status'] == 'collecting'
    assert result['sources'][1]['status'] == 'verification_required'
    assert result['sources'][2]['status'] == 'not_configured'
    assert result['activities'][0]['enabled'] is True
    assert result['activities'][0]['nextRun']
    assert result['activities'][1]['enabled'] is False
    assert result['activities'][1]['nextRun'] is None
    assert 'private-never-return' not in json.dumps(result)
    assert 'credential_token' not in json.dumps(result)
    assert 'Existing report' not in json.dumps(result)
    assert 'Existing SEO report' not in json.dumps(result)
    assert memory.list_drafts() == before
    assert result['approvalRequired'] is True


def test_disabled_schedules_do_not_promise_a_future_cycle(tmp_path):
    memory = Memory(tmp_path / 'memory.db')
    memory.kv_set('next_run:growth_reconciler', 1791000000)
    result = growth_snapshot(memory, {}, {'scheduler': SimpleNamespace(jobs=[])})
    assert 'work' not in result
    assert all(row['nextRun'] is None for row in result['activities'])
    memory.close()


def test_area_model_and_ada_context_share_ids_without_read_side_effects(tmp_path):
    from site_agent.application.growth import growth_chat_context

    memory = Memory(tmp_path / 'memory.db')
    context = {'scheduler': SimpleNamespace(jobs=[])}
    before = memory.conn.total_changes
    try:
        snapshot = growth_snapshot(memory, {'site': {'website_present': True}}, context)
        chat = growth_chat_context(memory, {'site': {'website_present': True}}, context)
        assert chat['serviceModel']['decisionIds'] == snapshot['serviceModel']['decisionIds']
        assert [row['id'] for row in chat['serviceModel']['areas']] == [row['id'] for row in snapshot['serviceModel']['areas']]
        for owner_area, ada_area in zip(snapshot['serviceModel']['areas'], chat['serviceModel']['areas']):
            for key in ('state', 'decisionIds', 'workIds', 'evidenceState', 'lastAssessedAt', 'nextAssessment'):
                assert ada_area[key] == owner_area[key]
        assert chat['serviceModel']['recentResults'] == []
        assert memory.conn.total_changes == before
    finally:
        memory.close()


def test_real_scheduler_specs_are_json_safe_for_growth_and_chat(tmp_path):
    import datetime
    from site_agent.core.scheduler import normalize_schedule
    from site_agent.application.growth import growth_chat_context

    memory = Memory(tmp_path / 'memory.db')
    spec = normalize_schedule({'every': 'weekly', 'weekday': 'monday', 'at': '08:00'})
    context = {'scheduler': SimpleNamespace(jobs=[('growth_weekly', spec, object())])}
    try:
        for result in (growth_snapshot(memory, {}, context), growth_chat_context(memory, {}, context)):
            decoded = json.loads(json.dumps(result))
            activity = next(row for row in decoded['activities'] if row['id'] == 'growth_weekly')
            assert activity['schedule']['at_time'] == '08:00:00'
            assert activity['schedule']['weekday'] == 0
        assert spec['at_time'] == datetime.time(8, 0)
    finally:
        memory.close()


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
        assert client.get('/api/workspace/intelligence').status_code == 401
        assert client.get('/api/workspace/intelligence', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        for name in tenants:
            headers = {'Authorization': f'Bearer {name}-token'}
            connection = client.get('/api/workspace/connection', headers=headers).json()
            assert connection == {'tenant': name, 'connected': True, 'ready': name == 'alpha'}
            # Existing growth records are still readable when the AI is unconfigured.
            growth = client.get('/api/workspace/growth', headers=headers).json()
            assert growth['tenant'] == name
            assert [article['title'] for article in growth['articles']] == [f'{name} article']
            assert 'token' not in json.dumps(connection)


def test_intelligence_requires_registry_authorized_tenant_and_reports_unavailable(tmp_path):
    tenants = {}
    for name in ('alpha', 'beta'):
        memory = Memory(tmp_path / f'{name}.db')
        tenants[name] = Tenant(name, {}, memory, None,
            {'crawlseo_service': object(), 'connector_site_id': name,
             'seo_provisioning_state': {'crawlseo': {'site_id': name}}}, f'{name}-token')
    registry = TenantRegistry(tenants)
    service = ChatService(registry=registry)
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=service, registry=registry)
    with TestClient(app) as client:
        response = client.get('/api/workspace/intelligence', headers={'Authorization': 'Bearer alpha-token'})
        assert response.status_code == 503
        assert response.json()['state'] == 'unavailable'
        assert 'businessProfile' not in response.json()


def test_control_plane_intelligence_is_tenant_scoped_and_keeps_unavailable_contract(tmp_path):
    tenants = {}
    for name in ('alpha', 'beta'):
        memory = Memory(tmp_path / f'{name}.db')
        tenants[name] = Tenant(name, {}, memory, None,
            {'crawlseo_service': object(), 'connector_site_id': name,
             'seo_provisioning_state': {'crawlseo': {'site_id': name}}}, f'{name}-token')
    registry = TenantRegistry(tenants)
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=ChatService(registry=registry),
        registry=registry, control_prefix='/v1/control-plane/websites', control_token='control-secret')
    with TestClient(app) as client:
        url = '/v1/control-plane/websites/alpha/intelligence'
        assert client.get(url).status_code == 401
        assert client.get(url, headers={'Authorization': 'Bearer invalid'}).status_code == 401
        missing = client.get('/v1/control-plane/websites/missing/intelligence',
            headers={'Authorization': 'Bearer control-secret'})
        assert missing.status_code == 200
        assert missing.json() == {'state': 'not_started', 'reason': 'tenant is not registered yet'}
        response = client.get(url, headers={'Authorization': 'Bearer control-secret'})
        assert response.status_code == 503
        assert response.json()['state'] == 'unavailable'
        assert response.json().get('reason')
        assert response.headers['Cache-Control'] == 'no-store'
        assert client.get('/api/workspace/intelligence',
            headers={'Authorization': 'Bearer alpha-token'}).status_code == 503
        assert client.get('/api/workspace/intelligence',
            headers={'Authorization': 'Bearer control-secret'}).status_code == 401


def test_control_plane_intelligence_without_recorded_knowledge_is_not_started(tmp_path):
    tenant = Tenant('empty', {}, Memory(tmp_path / 'empty.db'), None,
                    {'crawlseo_service': None}, 'empty-token')
    registry = TenantRegistry({'empty': tenant})
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=ChatService(registry=registry),
        registry=registry, control_prefix='/v1/control-plane/websites', control_token='control-secret')
    with TestClient(app) as client:
        response = client.get('/v1/control-plane/websites/empty/intelligence',
                              headers={'Authorization': 'Bearer control-secret'})
        assert response.status_code == 200
        assert response.json() == {'state': 'not_started',
                                   'reason': 'no intelligence has been recorded for this tenant yet'}


def test_intelligence_composes_real_project_contract_and_isolates_canonical_identities(tmp_path):
    from site_agent.application.crawlseo import CrawlSEOApplicationService

    class FaithfulProvider:
        def __init__(self, project_id, workspace_id):
            self.project_id = project_id
            self.workspace_id = workspace_id
            self.reads = []

        def project(self):
            # This is the canonical seo_get_project shape, not the reader's
            # desired camelCase view.
            return {
                'project_id': self.project_id,
                'workspace_id': self.workspace_id,
                'site': {'domain': f'{self.project_id}.example', 'url': f'https://{self.project_id}.example/'},
                'connections': {'gsc': {'status': 'active', 'property': 'url'},
                                'ga4': {'status': 'active', 'property': 'property'}},
            }

        def business_knowledge_document(self, workspace_id, project_id, document_id):
            self.reads.append(('business', workspace_id, project_id, document_id))
            return {'name': project_id, 'documentId': document_id}

        def latest_research_report(self):
            self.reads.append(('research',))
            return {'status': 'completed'}

        def connector_capabilities(self, *, site_id):
            return {'schemaVersion': '1.0', 'siteId': site_id, 'projectId': self.project_id,
                    'capabilities': ['findings.read']}

        def connector_findings(self, **kwargs):
            self.reads.append(('findings', kwargs['site_id']))
            return {'schemaVersion': '1.0', 'siteId': kwargs['site_id'], 'projectId': self.project_id,
                    'findings': [], 'nextCursor': None}

        def connector_actions(self, **kwargs):
            self.reads.append(('actions', kwargs['site_id']))
            return {'schemaVersion': '1.0', 'siteId': kwargs['site_id'], 'actions': [], 'nextCursor': None}

    tenants = {}
    providers = {}
    for tenant_id, project_id, workspace_id in (
        ('alpha', 'project-alpha-exact', 'workspace-alpha-exact'),
        ('beta', 'project-beta-exact', 'workspace-beta-exact'),
    ):
        memory = Memory(tmp_path / f'{tenant_id}.db')
        provider = FaithfulProvider(project_id, workspace_id)
        providers[tenant_id] = provider
        tenants[tenant_id] = Tenant(tenant_id, {}, memory, None, {
            'crawlseo_service': CrawlSEOApplicationService(provider),
            'connector_site_id': f'site-{tenant_id}',
        }, f'{tenant_id}-token')
    registry = TenantRegistry(tenants)
    service = ChatService(registry=registry)
    for tenant_id, project_id, workspace_id in (
        ('alpha', 'project-alpha-exact', 'workspace-alpha-exact'),
        ('beta', 'project-beta-exact', 'workspace-beta-exact'),
    ):
        normalized = tenants[tenant_id].context['crawlseo_service'].project()
        assert normalized['project_id'] == project_id
        assert normalized['workspace_id'] == workspace_id
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=service, registry=registry)
    with TestClient(app) as client:
        for tenant_id, project_id, workspace_id in (
            ('alpha', 'project-alpha-exact', 'workspace-alpha-exact'),
            ('beta', 'project-beta-exact', 'workspace-beta-exact'),
        ):
            response = client.get('/api/workspace/intelligence',
                headers={'Authorization': f'Bearer {tenant_id}-token'})
            assert response.status_code == 200
            assert response.json()['state'] == 'available'
            assert response.json()['businessProfile']['name'] == project_id
            assert providers[tenant_id].reads[0] == ('business', workspace_id, project_id, 'business-profile')
        assert providers['alpha'].reads[0][1:] != providers['beta'].reads[0][1:]


@pytest.mark.parametrize('project_payload', [
    {'workspace_id': 'valid-workspace'},
    {'project_id': None, 'workspace_id': 'valid-workspace'},
    {'project_id': 17, 'workspace_id': 'valid-workspace'},
    {'project_id': 'valid-project'},
    {'project_id': 'valid-project', 'workspace_id': None},
    {'project_id': 'valid-project', 'workspace_id': ['not', 'text']},
    {'project_id': 'valid-project', 'workspace_id': '   '},
])
def test_intelligence_rejects_malformed_canonical_identity_before_downstream_reads(tmp_path, project_payload):
    from site_agent.application.crawlseo import CrawlSEOApplicationService

    class MalformedProvider:
        def __init__(self):
            self.reads = []

        def project(self):
            return {
                **project_payload,
                'site': {'domain': 'tenant.example', 'url': 'https://tenant.example/'},
                'connections': {},
                # Valid aliases must not rescue an invalid canonical value.
                'id': 'alias-project', 'projectId': 'alias-project',
                'workspaceId': 'alias-workspace',
            }

        def business_knowledge_document(self, *args):
            self.reads.append(('business', args))
            return {}

        def latest_research_report(self):
            self.reads.append(('research',))
            return {}

        def connector_findings(self, **kwargs):
            self.reads.append(('findings', kwargs))
            return {}

        def connector_actions(self, **kwargs):
            self.reads.append(('actions', kwargs))
            return {}

    provider = MalformedProvider()
    tenant = Tenant('alpha', {}, Memory(tmp_path / 'malformed.db'), None, {
        'crawlseo_service': CrawlSEOApplicationService(provider), 'connector_site_id': 'site-alpha',
    }, 'alpha-token')
    registry = TenantRegistry({'alpha': tenant})
    result = ChatService(registry=registry).intelligence_summary(tenant=tenant)
    assert result['state'] == 'unavailable'
    assert provider.reads == []


def test_intelligence_aliases_apply_only_when_canonical_keys_are_absent(tmp_path):
    tenant = Tenant('alpha', {}, Memory(tmp_path / 'aliases.db'), None, {
        'crawlseo_service': SimpleNamespace(
            project=lambda: {'workspaceId': 'workspace-alias', 'projectId': 'project-alias'},
            intelligence_snapshot=lambda **kwargs: {'businessProfile': {}, 'research': {'status': 'completed'},
                'coverage': {}, 'actions': []},
        ),
        'connector_site_id': 'site-alpha',
    }, 'alpha-token')
    registry = TenantRegistry({'alpha': tenant})
    calls = []
    tenant.context['crawlseo_service'].intelligence_snapshot = lambda **kwargs: (
        calls.append(kwargs) or {'businessProfile': {}, 'research': {'status': 'completed'}, 'coverage': {}, 'actions': []}
    )
    result = ChatService(registry=registry).intelligence_summary(tenant=tenant)
    assert result['state'] == 'available'
    assert calls == [{'site_id': 'site-alpha', 'workspace_id': 'workspace-alias', 'project_id': 'project-alias'}]


def test_migrated_tenant_keeps_its_existing_provider_credential_file(tmp_path):
    credential_file = tmp_path / 'tenant.env'
    credential_file.write_text('CRAWLSEO_SERVICE_TOKEN=tenant-research-fixture\nPROVISIONED_DEMO_TOKEN=old-fixture\n')
    config = {'data_dir': str(tmp_path / 'data'), 'credentials': {'env_file': str(credential_file)}}
    env = load_tenant_environment(config, {'PROVISIONED_DEMO_TOKEN': 'canonical-fixture'})
    assert env['CRAWLSEO_SERVICE_TOKEN'] == 'tenant-research-fixture'
    assert env['PROVISIONED_DEMO_TOKEN'] == 'canonical-fixture'


def test_site_origin_change_is_persisted_before_runtime_reconciliation(tmp_path, monkeypatch):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(yaml.safe_dump({
        'site': {'preview_url': 'https://demo.example/', 'source_deployment': {'worker_name': 'demo'}},
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
    monkeypatch.setattr(workspace_module, 'canonical_worker_preview_url', lambda _config, _env: 'https://demo.weareheadless.workers.dev')
    calls = []

    def reload_tenant(tenant_id, path, **kwargs):
        calls.append((tenant_id, path, kwargs))
        return tenant

    registry.reload_tenant = reload_tenant
    registry.update_site_origin('demo', 'https://www.demo.example')

    updated = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    assert updated['site']['preview_url'] == 'https://demo.weareheadless.workers.dev'
    assert updated['site']['public_url'] == 'https://www.demo.example/'
    assert updated['site']['url'] == 'https://www.demo.example/'
    assert updated['site']['custom_domain'] == 'www.demo.example'
    assert updated['seo']['site_url'] == 'https://www.demo.example/'
    assert updated['seo']['gsc_property'] == 'https://www.demo.example/'
    assert updated['seo']['provisioning']['gsc_property'] == 'https://www.demo.example/'
    assert updated['messages']['email']['enabled'] is True
    assert updated['messages']['email']['local_part'] == 'hello'
    assert updated['messages']['email']['provisioning']['auto'] is True
    assert calls[0][0] == 'demo'
    assert calls[0][2]['api_token'] == 'demo-token'
    assert calls[0][2]['api_token_env'] == 'CUSTOM_DEMO_TOKEN'


def test_managed_draft_http_decisions_require_the_saved_exact_review(tmp_path, monkeypatch):
    from tests.test_growth_delivery import GitHub
    from site_agent.application import growth_delivery
    from site_agent.core.contracts import Artifact, ArtifactKind, EffectClass
    from site_agent.application.approvals import ApprovalService
    monkeypatch.setattr(growth_delivery, '_request', GitHub())
    monkeypatch.setattr(growth_delivery, 'github_api_token', lambda *_args: 'test-token')
    memory = Memory(tmp_path / 'memory.db')
    draft = memory.save_draft('Exact change', 'Only this version', kind='payload_content', meta={'review_package_hash': 'sha256:exact'})
    config = {'site': {'repository': 'owner/customer'}}
    context = {'tenant_id': 'demo', 'config': config, 'memory': memory, 'llm': SimpleNamespace(api_key='configured')}
    artifact = memory.create_artifact(Artifact(kind=ArtifactKind.SITE_CHANGE, title='Exact change', summary='Bounded', renderer='site_change', capability_id='growth.publish', provider_id='payload', content_hash='sha256:exact'))
    approval = ApprovalService(memory).create(artifact, owner_action_label='Apply exact change', effect_class=EffectClass.SITE_MUTATION)
    cycle = memory.create_strategy_cycle('http-review', '2026-10', 'hash', {})
    memory.create_strategy_initiative(cycle['id'], kind='payload_content', title='Exact change', summary='Bounded', state='ready_for_review', draft_id=draft, approval_id=approval.approval_id)
    tenant = Tenant('demo', config, memory, None, context, 'demo-token')
    registry = TenantRegistry({'demo': tenant})
    service = ChatService(registry=registry)
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=service, registry=registry)
    headers = {'Authorization': 'Bearer demo-token'}
    with TestClient(app) as client:
        for operation in ('approve', 'discard'):
            endpoint = f'/api/workspace/drafts/{draft}/{operation}'
            for body in ({}, {'review_package_hash': 'sha256:wrong'}):
                response = client.post(endpoint, headers=headers, json=body)
                assert response.status_code == 409
                assert 'missing or stale' in response.json()['detail']
                assert memory.list_drafts()[0]['status'] == 'pending'
        # A decline carries no public effect and is allowed only for this exact package.
        response = client.post(f'/api/workspace/drafts/{draft}/discard', headers=headers, json={'review_package_hash': 'sha256:exact'})
        assert response.status_code == 409
        assert memory.get_approval_request(approval.approval_id).status.value == 'pending'
        response = client.post(f'/api/workspace/drafts/{draft}/discard', headers={**headers, 'X-HelloAda-Owner-Id': 'payload:demo:11'}, json={'review_package_hash': 'sha256:exact'})
        assert response.status_code == 200
        assert response.json()['status'] == 'discarded'
    memory.close()
