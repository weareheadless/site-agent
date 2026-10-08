import base64
import hashlib
import importlib.util
from pathlib import Path
import urllib.request

import pytest

spec = importlib.util.spec_from_file_location('release_assets', Path(__file__).parents[1] / 'scripts/github_release_assets.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_artifact_must_match_exact_locked_integrity():
    data = b'approved immutable artifact'
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    module.verify_integrity(data, integrity)
    with pytest.raises(RuntimeError, match='integrity'):
        module.verify_integrity(b'different artifact', integrity)


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
    for package, field, variable in (
        ('helloada-payload-admin', 'payloadAdmin', 'HELLOADA_PAYLOAD_ADMIN_VERSION'),
        ('helloada-payload-core', 'payloadCore', 'HELLOADA_PAYLOAD_CORE_VERSION'),
    ):
        version = json.loads((root / 'packages' / package / 'package.json').read_text())['version']
        assert manifest[field] == version
        assert re.search('"' + variable + '":\\s*"' + re.escape(version) + '"', worker)

    admin_package = root / 'packages/helloada-payload-admin'
    admin_version = json.loads((admin_package / 'package.json').read_text())['version']
    runtime = (admin_package / 'src/version.ts').read_text()
    runtime_version = r"HELLOADA_PAYLOAD_ADMIN_VERSION\s*=\s*['\"]" + re.escape(admin_version) + r"['\"]"
    assert re.search(runtime_version, runtime)

    template_package = json.loads((template / 'package.json').read_text())
    template_lock = json.loads((template / 'package-lock.json').read_text())
    release_asset = (
        f"https://github.com/weareheadless/site-agent/releases/download/payload-admin-v{admin_version}/"
        f"weareheadless-helloada-payload-admin-{admin_version}.tgz"
    )
    assert template_package['dependencies']['@weareheadless/helloada-payload-admin'] == release_asset
    locked_admin = template_lock['packages']['node_modules/@weareheadless/helloada-payload-admin']
    assert locked_admin['version'] == admin_version
    assert locked_admin['resolved'] == release_asset
    assert locked_admin['integrity'] == (
        'sha512-emr3+N6Ol3hBcgj3SxstlabjDsR0JPGbVGPBYJhWD+IxiVE2QZlb6l6QxkdgnvJ2T9JrUcPvQT/azdmbIZaKoA=='
    )

    core_version = json.loads((root / 'packages/helloada-payload-core/package.json').read_text())['version']
    core_asset = (
        f"https://github.com/weareheadless/site-agent/releases/download/helloada-payload-core-v{core_version}/"
        f"weareheadless-helloada-payload-core-{core_version}.tgz"
    )
    assert template_package['dependencies']['@weareheadless/helloada-payload-core'] == core_asset
    locked_core = template_lock['packages']['node_modules/@weareheadless/helloada-payload-core']
    assert locked_core['version'] == core_version
    assert locked_core['resolved'] == core_asset
    assert locked_core['integrity'] == (
        'sha512-Xdqf5D302wIggpFE4xp4ZybybTFiBybQiX7h6F+SehmYntA12T98CU4F6m4+mXAwYsQ1Al6fYBZsFtXagfEOOg=='
    )
