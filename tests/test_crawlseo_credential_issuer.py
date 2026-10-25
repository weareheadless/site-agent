import importlib.util
import io
from pathlib import Path
from unittest import mock

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "issue-crawlseo-migration-read-credential.py"
SPEC = importlib.util.spec_from_file_location("crawlseo_credential_issuer", SCRIPT)
ISSUER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ISSUER)


def test_credential_issuer_appends_internal_route_under_application_mount(tmp_path):
    response = io.BytesIO(
        b'{"scopes":["connector:read"],"reused":false,'
        b'"token":"cseo_12345678901234567890","credentialId":"cred-1","expiresInDays":30}'
    )
    response.status = 200
    output = tmp_path / "credential.env"
    opener = mock.Mock()
    opener.open.return_value = response
    with mock.patch.object(ISSUER.urllib.request, "build_opener", return_value=opener):
        result = ISSUER.issue_credential(
            "https://crawlseo.helloada.app/crawlseo", "site / 1", "key-1", "control-secret", output
        )
    request = opener.open.call_args.args[0]
    assert request.full_url == (
        "https://crawlseo.helloada.app/crawlseo/api/internal/sites/site%20%2F%201/connector-credentials"
    )
    assert request.get_header("User-agent") == "HelloAda/migration-credential-issuer"
    assert result["credentialId"] == "cred-1"
    assert output.read_text() == "CRAWLSEO_CONNECTOR_READ_TOKEN=cseo_12345678901234567890\n"


def test_credential_issuer_never_follows_redirect_with_control_token(tmp_path):
    request = ISSUER.urllib.request.Request("https://crawlseo.example", headers={"Authorization": "Bearer secret"})
    with pytest.raises(ValueError, match="redirects"):
        ISSUER._NoCredentialRedirect().redirect_request(request, None, 307, "redirect", {}, "https://other.example")
    opener = mock.Mock()
    opener.open.side_effect = ValueError("credential endpoint redirects are not permitted")
    output = tmp_path / "credential.env"
    with mock.patch.object(ISSUER.urllib.request, "build_opener", return_value=opener):
        with pytest.raises(ValueError, match="redirects"):
            ISSUER.issue_credential("https://crawlseo.example", "site-1", "key-1", "secret", output)
    assert not output.exists()


@pytest.mark.parametrize("url", [
    "http://crawlseo.example/crawlseo",
    "https://user:pass@crawlseo.example/crawlseo",
    "https://crawlseo.example/crawlseo?token=x",
    "https://crawlseo.example/crawlseo#frag",
    "https://crawlseo.example/crawlseo/../other",
    "https://crawlseo.example/crawlseo/%2e%2e/other",
    "https://crawlseo.example/crawlseo/%252e%252e/other",
    "https://crawlseo.example/crawlseo%5cother",
    "https://crawlseo.example/crawlseo//other",
    "https://crawlseo.example/crawlseo/",
    "https://crawlseo.example/crawlseo//",
    "https://crawlseo.example/crawlseo mount",
    "https://crawlseo.example/crawlseo%2fother",
    "https://crawlseo.example:99999/crawlseo",
    "https://crawlseo.example:/crawlseo",
    "https://crawlseo.example/crawlseo/api/connector/v1",
    "https://crawlseo.example/crawlseo./other",
])
def test_credential_issuer_rejects_unsafe_base_urls_without_creating_output(tmp_path, url):
    output = tmp_path / "credential.env"
    with pytest.raises(ValueError, match="HTTPS"):
        ISSUER.issue_credential(url, "site-1", "key-1", "control-secret", output)
    assert not output.exists()
