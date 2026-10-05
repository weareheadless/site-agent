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
