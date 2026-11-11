import base64
import hashlib
import json
from pathlib import Path
import urllib.request

import pytest

from site_agent.application import release_dependencies as module


def test_artifact_must_match_exact_locked_integrity():
    data = b'approved immutable artifact'
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    module.verify_integrity(data, integrity, '@weareheadless/example')
    with pytest.raises(RuntimeError, match='@weareheadless/example.*SHA-512'):
        module.verify_integrity(b'different artifact', integrity, '@weareheadless/example')


def test_verify_release_dependencies_checks_published_artifact_bytes(tmp_path, monkeypatch):
    import json

    names = ('@weareheadless/helloada-payload-core',)
    packages = {}
    locked = {}
    release_assets = {}
    artifact_bytes = {}
    for index, name in enumerate(names, start=1):
        tag = f'test-release-{index}'
        filename = f'{name.rsplit("/", 1)[-1]}.tgz'
        url = f'https://github.com/weareheadless/site-agent/releases/download/{tag}/{filename}'
        data = f'published bytes for {name}'.encode()
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
        packages[name] = url
        locked['node_modules/' + name] = {'resolved': url, 'integrity': integrity}
        release_assets[tag] = {'tag_name': tag, 'draft': False, 'assets': [
            {'id': index, 'name': filename, 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
        ]}
        artifact_bytes[str(index)] = data

    (tmp_path / 'package.json').write_text(json.dumps({'dependencies': packages}))
    (tmp_path / 'package-lock.json').write_text(json.dumps({'packages': locked}))

    fetched_releases = []

    def fake_fetch(path, token, binary=False):
        if '/releases/tags/' in path:
            tag = path.rsplit('/', 1)[-1]
            fetched_releases.append(tag)
            return release_assets[tag]
        asset_id = path.rsplit('/', 1)[-1]
        return artifact_bytes[asset_id]

    monkeypatch.setattr(module, 'github_fetch', fake_fetch)
    evidence = module.verify_release_dependencies(tmp_path, 'test-token')

    assert [item['package'] for item in evidence] == list(names)
    assert all(item['integrity'].startswith('sha512-') for item in evidence)
    assert len(evidence) == 1
    fetched_releases.clear()
    core_only = module.verify_release_dependencies(tmp_path, 'test-token', package_names=(names[0],))
    assert [item['package'] for item in core_only] == [names[0]]
    assert fetched_releases == ['test-release-1']
    with pytest.raises(ValueError, match='Only platform release packages'):
        module.verify_release_dependencies(tmp_path, 'test-token', package_names=('@other/package',))


    original_package = (tmp_path / 'package.json').read_bytes()
    original_lock = (tmp_path / 'package-lock.json').read_bytes()
    staged_paths = []
    cached_bytes = []

    def seed(command, cwd):
        assert cwd == tmp_path
        assert command[1:3] == ['cache', 'add']
        assert command[4] == '--ignore-scripts'
        asset_path = Path(command[3])
        staged_paths.append(asset_path)
        cached_bytes.append(asset_path.read_bytes())

    cached_evidence = module.prepare_release_dependencies(
        tmp_path, 'test-token', 'npm', tmp_path, seed,
    )
    assert cached_evidence == evidence
    assert cached_bytes == [artifact_bytes['1']]
    assert all(not path.exists() for path in staged_paths)
    assert (tmp_path / 'package.json').read_bytes() == original_package
    assert (tmp_path / 'package-lock.json').read_bytes() == original_lock

    def fail_cache(_command, _cwd):
        raise RuntimeError('npm cache add failed')

    with pytest.raises(RuntimeError, match='npm cache add failed'):
        module.prepare_release_dependencies(tmp_path, 'test-token', 'npm', tmp_path, fail_cache)
    assert (tmp_path / 'package.json').read_bytes() == original_package
    assert (tmp_path / 'package-lock.json').read_bytes() == original_lock
def test_a_stale_platform_package_name_is_verified_not_refused(tmp_path, monkeypatch):
    """The checkout's declaration is the contract, not a catalogue in this repo.

    `inmersion` still pinned `@weareheadless/helloada-payload-admin`, which the
    platform had shipped and the release pipeline had deployed, but which a
    hardcoded name list no longer carried. Its preview build failed as
    "Undeclared private release package" while production ran that exact source.
    """
    import json

    names = ('@weareheadless/helloada-payload-admin', '@weareheadless/helloada-payload-core')
    packages, locked, release_assets, artifact_bytes = {}, {}, {}, {}
    for index, name in enumerate(sorted(names), start=1):
        tag = f'platform-v{index}'
        filename = f'{name.rsplit("/", 1)[-1]}.tgz'
        url = f'https://github.com/weareheadless/site-agent/releases/download/{tag}/{filename}'
        data = f'published bytes for {name}'.encode()
        packages[name] = url
        locked['node_modules/' + name] = {
            'resolved': url,
            'integrity': 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        }
        release_assets[tag] = {'tag_name': tag, 'draft': False, 'assets': [
            {'id': index, 'name': filename, 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()},
        ]}
        artifact_bytes[str(index)] = data
    (tmp_path / 'package.json').write_text(json.dumps({'dependencies': packages}))
    (tmp_path / 'package-lock.json').write_text(json.dumps({'packages': locked}))

    def fake_fetch(path, token, binary=False):
        if '/releases/tags/' in path:
            return release_assets[path.rsplit('/', 1)[-1]]
        return artifact_bytes[path.rsplit('/', 1)[-1]]

    monkeypatch.setattr(module, 'github_fetch', fake_fetch)
    evidence = module.verify_release_dependencies(tmp_path, 'test-token')

    assert [item['package'] for item in evidence] == sorted(names)


def test_a_platform_package_outside_the_release_assets_still_fails_closed(tmp_path, monkeypatch):
    import json

    name = '@weareheadless/rogue'
    (tmp_path / 'package.json').write_text(json.dumps({'dependencies': {name: 'https://example.com/rogue.tgz'}}))
    (tmp_path / 'package-lock.json').write_text(json.dumps({'packages': {}}))

    with pytest.raises(RuntimeError, match='exact GitHub release URL'):
        module.verify_release_dependencies(tmp_path, 'test-token')


def test_signed_download_does_not_receive_api_credential():
    request = urllib.request.Request('https://api.github.com/repos/a/b/releases/assets/1', headers={'Authorization': 'Bearer private'})
    redirected = module.ReleaseRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://release-assets.githubusercontent.com/asset')
    assert redirected.get_header('Authorization') is None
    with pytest.raises(RuntimeError, match='redirect host'):
        module.ReleaseRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://other.test/asset')


def test_default_worker_and_manifest_use_the_released_shared_versions():
    import json
    import re
    root = Path(__file__).parents[1]
    template = root / 'src/site_agent/templates/next-payload'
    manifest = json.loads((template / 'template-manifest.json').read_text())
    worker = (template / 'wrangler.jsonc').read_text()
    core_version = json.loads((root / 'packages/helloada-payload-core/package.json').read_text())['version']
    assert manifest['payloadCore'] == core_version
    assert re.search('"HELLOADA_PAYLOAD_CORE_VERSION":\\s*"' + re.escape(core_version) + '"', worker)

    template_package = json.loads((template / 'package.json').read_text())
    template_lock = json.loads((template / 'package-lock.json').read_text())
    # The admin is shared runtime source now, identified by the fingerprint the
    # release runner injects, not by a pinned package version.
    assert '@weareheadless/helloada-payload-admin' not in template_package['dependencies']
    assert 'node_modules/@weareheadless/helloada-payload-admin' not in template_lock['packages']
    assert 'payloadAdmin' not in manifest
    assert re.fullmatch(r'[0-9a-f]{64}', manifest['sharedRuntimeFingerprint'])
    assert re.search('"HELLOADA_SHARED_RUNTIME_FINGERPRINT":\\s*"' + manifest['sharedRuntimeFingerprint'] + '"', worker)

    core_version = json.loads((root / 'packages/helloada-payload-core/package.json').read_text())['version']
    core_asset = (
        f"https://github.com/weareheadless/site-agent/releases/download/helloada-payload-core-v{core_version}/"
        f"weareheadless-helloada-payload-core-{core_version}.tgz"
    )
    assert template_package['dependencies']['@weareheadless/helloada-payload-core'] == core_asset
    locked_core = template_lock['packages']['node_modules/@weareheadless/helloada-payload-core']
    assert locked_core['version'] == core_version
    assert locked_core['resolved'] == core_asset
    # The lock must pin the exact bytes of the released 0.6.5 artifact.
    assert locked_core['integrity'] == (
        'sha512-T+JxWnbQh6bgGtah0aq2/rHKX5n7PSVSII2fgfLuzUfMf3f18IrolYHjEVJgk1gx782YfSyS7sNvFC51Mq0WbQ=='
    )
