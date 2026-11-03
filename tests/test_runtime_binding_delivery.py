import json
from pathlib import Path

import pytest
import yaml

from site_agent.application.runtime_binding_delivery import deliver_runtime_bindings, RuntimeBindingError, binding_hashes
from site_agent.core.memory import Memory


def fixture(tmp_path):
    tenant = 'demo-site'
    directory = tmp_path / 'tenants' / tenant
    directory.mkdir(parents=True)
    config_path = directory / 'config.yaml'
    activation = dict(schema=1, tenant_id=tenant, release_id='initial-release', source_sha='a'*40,
                      control_sha='b'*40, shared_runtime_fingerprint='c'*64, uploaded_version='version-one')
    config = {'instance_name': tenant, 'data_dir': str(directory / 'data'),
              'deployment_pipeline': {'release_root': str(tmp_path / 'releases')},
              'site': {'payload': {'runtime_activation': activation}}}
    config_path.write_text(yaml.safe_dump(config))
    (directory / 'tenant.env').write_text('PAYLOAD_SECRET=preserved\n')
    (directory.parent / 'tenants.json').write_text(json.dumps({tenant: {'config_path': str(config_path)}}))
    memory = Memory(directory / 'data/memory.db')
    receipt = {'tenant': tenant, 'releaseId': 'initial-release', 'sourceSha': 'a'*40, 'uploadedVersion': 'version-one',
               'status': 'deployed', 'connectionVerifiedAt': '2026-11-03T00:00:00Z',
               'deployment': {'versions': [{'version_id': 'version-one', 'percentage': 100}]}}
    def save(value):
        path = tmp_path / 'releases/runs' / tenant / value['releaseId'] / 'receipt.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    save(receipt)
    return config, config_path, memory, receipt, save


def test_stage_preserves_env_and_queues_exact_active_source_once(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    calls = []
    monkeypatch.setattr(module, 'request_release', lambda *args, **kwargs: calls.append((args, kwargs)) or {'release_id': kwargs['release_id']})
    try:
        first = deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        second = deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert first['state'] == second['state'] == 'awaiting_release'
        assert len(calls) == 1 and calls[0][0][2] == 'a'*40
        assert 'PAYLOAD_SECRET=preserved' in path.with_name('tenant.env').read_text()
        assert path.with_name('tenant.env').stat().st_mode & 0o777 == 0o600
        assert 'G-ONE' not in json.dumps(memory.kv_get('runtime_binding_delivery'))
    finally:
        memory.close()


def test_running_bootstrap_never_gets_overwritten_or_claimed_delivered(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    receipt['status'] = 'running'
    save(receipt)
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: pytest.fail('cannot replace active bootstrap'))
    try:
        result = deliver_runtime_bindings(config, {}, memory, path, {'GOOGLE_SITE_VERIFICATION': 'tag'})
        assert result['state'] == 'awaiting_active_release'
    finally:
        memory.close()


def test_only_exact_active_delivered_bindings_can_complete(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    receipt['runtimeBindings'] = binding_hashes({'GA_MEASUREMENT_ID': 'G-ONE'})
    save(receipt)
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: pytest.fail('already delivered'))
    try:
        assert deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})['state'] == 'delivered'
        receipt['deployment']['versions'][0]['percentage'] = 50
        save(receipt)
        with pytest.raises(RuntimeBindingError, match='100%'):
            deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
    finally:
        memory.close()


def test_failed_delivery_is_not_retried_with_another_release_id(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    memory.kv_set('runtime_binding_delivery', {'release_id': 'failed-release', 'source_sha': 'a'*40,
                                              'activation_release_id': 'initial-release', 'queued': True})
    save({**receipt, 'releaseId': 'failed-release', 'status': 'failed'})
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: pytest.fail('failed IDs are terminal'))
    try:
        with pytest.raises(RuntimeBindingError, match='failed'):
            deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
    finally:
        memory.close()


def test_ambiguous_queue_outcome_keeps_the_same_intent(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs['release_id'])
        if len(calls) == 1:
            raise module.ReleaseQueueError('queue response lost')
        return {'release_id': kwargs['release_id']}
    monkeypatch.setattr(module, 'request_release', request)
    try:
        with pytest.raises(RuntimeBindingError):
            deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        result = deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert calls[0] == calls[1] == result['release_id']
    finally:
        memory.close()


def test_two_producers_preserve_all_settings_and_share_one_pending_release(tmp_path, monkeypatch):
    import concurrent.futures
    import site_agent.application.runtime_binding_delivery as module
    from site_agent.application.tenant_environment import read_tenant_environment
    config, path, memory, receipt, save = fixture(tmp_path)
    memory.close()
    calls = []
    monkeypatch.setattr(module, 'request_release', lambda *args, **kwargs: calls.append(kwargs['release_id']) or {'release_id': kwargs['release_id']})
    def reconcile(values):
        local = Memory(Path(config['data_dir']) / 'memory.db')
        try:
            return deliver_runtime_bindings(config, {}, local, path, values)
        finally:
            local.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reconcile, [{'GA_MEASUREMENT_ID': 'G-ONE'}, {'GOOGLE_SITE_VERIFICATION': 'public-tag'}]))
    assert results[0]['release_id'] == results[1]['release_id']
    assert len(calls) == 1
    values = read_tenant_environment(path.with_name('tenant.env'))
    assert values['GA_MEASUREMENT_ID'] == 'G-ONE' and values['GOOGLE_SITE_VERIFICATION'] == 'public-tag'
    assert values['PAYLOAD_SECRET'] == 'preserved'


def test_unregistered_or_cross_tenant_delivery_is_rejected_before_writing(tmp_path, monkeypatch):
    config, path, memory, receipt, save = fixture(tmp_path)
    (path.parent.parent / 'tenants.json').write_text('{}')
    try:
        with pytest.raises(RuntimeBindingError):
            deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert 'GA_MEASUREMENT_ID' not in path.with_name('tenant.env').read_text()
    finally:
        memory.close()


def test_a_failed_intent_recovers_only_after_an_operator_promotes_a_new_release(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    save({**receipt, 'releaseId': 'failed-release', 'status': 'failed'})
    memory.kv_set('runtime_binding_delivery', {
        'release_id': 'failed-release', 'source_sha': 'a'*40,
        'activation_release_id': 'initial-release', 'queued': True,
    })
    calls = []
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: calls.append(kw['release_id']) or {'release_id': kw['release_id']})
    try:
        with pytest.raises(RuntimeBindingError, match='failed'):
            deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert calls == []
        # An operator promoted a new verified release: activation advances.
        new_activation = dict(schema=1, tenant_id='demo-site', release_id='operator-release',
                              source_sha='a'*40, control_sha='b'*40,
                              shared_runtime_fingerprint='c'*64, uploaded_version='version-two')
        save({**receipt, 'releaseId': 'operator-release', 'uploadedVersion': 'version-two',
              'deployment': {'versions': [{'version_id': 'version-two', 'percentage': 100}]}})
        current = yaml.safe_load(path.with_name('config.yaml').read_text())
        current['site']['payload']['runtime_activation'] = new_activation
        path.with_name('config.yaml').write_text(yaml.safe_dump(current))
        result = deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert result['state'] == 'awaiting_release' and len(calls) == 1
        assert result['release_id'] != 'failed-release'
    finally:
        memory.close()


def test_a_completed_release_without_the_staged_bindings_stops_after_one_retry(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    staged = module.binding_hashes({'GA_MEASUREMENT_ID': 'G-ONE'})
    save({**receipt, 'releaseId': 'completed-release', 'runtimeBindings': {}})
    memory.kv_set('runtime_binding_delivery', {
        'release_id': 'completed-release', 'source_sha': 'a'*40,
        'activation_release_id': 'initial-release', 'queued': True,
        'staged': staged, 'completed_retries': 1,
    })
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: pytest.fail('must not loop releases'))
    try:
        with pytest.raises(RuntimeBindingError, match='without attaching'):
            deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
    finally:
        memory.close()


def test_one_retry_is_allowed_for_a_binding_staged_during_the_build(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    save({**receipt, 'releaseId': 'raced-release', 'runtimeBindings': {}})
    memory.kv_set('runtime_binding_delivery', {
        'release_id': 'raced-release', 'source_sha': 'a'*40,
        'activation_release_id': 'initial-release', 'queued': True, 'completed_retries': 0,
    })
    calls = []
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: calls.append(kw['release_id']) or {'release_id': kw['release_id']})
    try:
        result = deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert result['state'] == 'awaiting_release' and len(calls) == 1
        assert result['release_id'] != 'raced-release'
        assert memory.kv_get('runtime_binding_delivery')['completed_retries'] == 1
    finally:
        memory.close()


def test_a_tenant_without_verified_activation_stages_nothing(tmp_path, monkeypatch):
    import site_agent.application.runtime_binding_delivery as module
    config, path, memory, receipt, save = fixture(tmp_path)
    current = yaml.safe_load(path.with_name('config.yaml').read_text())
    current['site']['payload'].pop('runtime_activation')
    path.with_name('config.yaml').write_text(yaml.safe_dump(current))
    monkeypatch.setattr(module, 'request_release', lambda *a, **kw: pytest.fail('nothing to release against'))
    try:
        result = deliver_runtime_bindings(config, {}, memory, path, {'GA_MEASUREMENT_ID': 'G-ONE'})
        assert result['state'] == 'awaiting_runtime_release'
        assert 'GA_MEASUREMENT_ID' not in path.with_name('tenant.env').read_text()
    finally:
        memory.close()
