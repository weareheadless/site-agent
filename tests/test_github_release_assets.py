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
