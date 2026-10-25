from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import importlib.util

SPEC = importlib.util.spec_from_file_location(
    "migration_credential_issuer",
    Path(__file__).parents[1] / "scripts" / "issue-crawlseo-migration-read-credential.py",
)
assert SPEC and SPEC.loader
issuer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(issuer)


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_issues_exact_read_scope_and_stores_token_privately(monkeypatch, tmp_path):
    token = "cseo_" + "a" * 43
    result_body = {"credentialId": "credential-1", "token": token, "scopes": ["connector:read"],
                   "reused": False, "expiresInDays": 30}

    def open_request(request, timeout):
        assert request.full_url == "https://crawlseo.example/api/internal/sites/site%2F1/connector-credentials"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer provisioning-secret"
        assert json.loads(request.data) == {"idempotencyKey": "inventory-run-1"}
        assert timeout == 30
        return Response(json.dumps(result_body).encode())

    monkeypatch.setattr(issuer.urllib.request, "urlopen", open_request)
    output = tmp_path / "private" / "connector.env"
    result = issuer.issue_credential("https://crawlseo.example", "site/1", "inventory-run-1",
                                     "provisioning-secret", output)
    assert result == {"credentialId": "credential-1", "expiresInDays": 30, "output": str(output)}
    assert output.read_text() == f"CRAWLSEO_CONNECTOR_READ_TOKEN={token}\n"
    assert output.stat().st_mode & 0o777 == 0o600
    assert token not in json.dumps(result)
    with pytest.raises(FileExistsError):
        issuer.issue_credential("https://crawlseo.example", "site/1", "inventory-run-1",
                                "provisioning-secret", output)


def test_rejects_write_capabilities_and_cleans_reserved_output(monkeypatch, tmp_path):
    response = {"credentialId": "credential-1", "token": "cseo_" + "b" * 43,
                "scopes": ["connector:read", "connector:write"], "reused": False, "expiresInDays": 30}
    monkeypatch.setattr(issuer.urllib.request, "urlopen", lambda *args, **kwargs: Response(json.dumps(response).encode()))
    output = tmp_path / "connector.env"
    with pytest.raises(ValueError, match="read-only scope"):
        issuer.issue_credential("https://crawlseo.example", "site-1", "inventory-run-2", "control", output)
    assert not output.exists()


def test_requires_https_and_valid_generated_token(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        issuer.issue_credential("http://crawlseo.example", "site-1", "key", "control", tmp_path / "x.env")

    response = {"credentialId": "credential-1", "token": "cseo_good\nINJECTED=value",
                "scopes": ["connector:read"], "reused": False, "expiresInDays": 30}
    monkeypatch.setattr(issuer.urllib.request, "urlopen", lambda *args, **kwargs: Response(json.dumps(response).encode()))
    with pytest.raises(ValueError, match="credential was not newly issued"):
        issuer.issue_credential("https://crawlseo.example", "site-1", "key", "control", tmp_path / "x.env")
    assert not (tmp_path / "x.env").exists()
