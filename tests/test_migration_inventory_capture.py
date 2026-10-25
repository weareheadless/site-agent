from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import importlib.util

SPEC = importlib.util.spec_from_file_location(
    "migration_inventory_capture",
    Path(__file__).parents[1] / "scripts" / "capture-crawlseo-migration-plan.py",
)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def test_fetch_plan_checks_tenant_and_keeps_blockers(monkeypatch):
    body = {"tenant": "oceanic", "snapshotHash": "sha256:abc", "readOnly": True,
            "blockers": ["pending approvals require review"], "migrationApplied": False}

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def open_request(request, timeout):
        assert request.full_url == "https://helloada.example/v1/control-plane/websites/oceanic/growth/migration-plan"
        assert request.get_header("Authorization") == "Bearer secret-value"
        assert timeout == 30
        return Response(json.dumps(body).encode())

    monkeypatch.setattr(capture.urllib.request, "urlopen", open_request)
    result = capture.fetch_plan("https://helloada.example", "oceanic", "secret-value")
    assert result["blockers"] == body["blockers"]
    assert result["migrationApplied"] is False


def test_fetch_plan_rejects_wrong_tenant_and_http_remote(monkeypatch):
    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(capture.urllib.request, "urlopen", lambda *args, **kwargs:
        Response(b'{"tenant":"other","snapshotHash":"hash"}'))
    with pytest.raises(ValueError, match="identity"):
        capture.fetch_plan("https://helloada.example", "oceanic", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        capture.fetch_plan("http://helloada.example", "oceanic", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        capture.fetch_plan("http://localhost.attacker.example", "oceanic", "secret")
    with pytest.raises(ValueError, match="origin"):
        capture.fetch_plan("https://helloada.example/private-path", "oceanic", "secret")


def test_write_exclusive_preserves_prior_inventory(tmp_path):
    target = tmp_path / "nested" / "inventory.json"
    capture.write_exclusive(target, {"snapshotHash": "first"})
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
    assert json.loads(target.read_text())["snapshotHash"] == "first"
    with pytest.raises(FileExistsError):
        capture.write_exclusive(target, {"snapshotHash": "replacement"})
    assert json.loads(target.read_text())["snapshotHash"] == "first"
