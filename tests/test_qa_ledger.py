"""One live test site at a time.

The harness never guesses which site is disposable. It removes only what its own
ledger says it created, and only against a target declared non-production.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from site_agent.qa.cli import purge_ledger, record_ledger


class _Handler(http.server.BaseHTTPRequestHandler):
    deleted: list[str] = []

    def do_DELETE(self):  # noqa: N802
        identifier = self.path.rsplit("/", 1)[-1]
        type(self).deleted.append(identifier)
        if identifier == "already-gone":
            self.send_error(404)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # noqa: A003
        return


@pytest.fixture()
def target():
    _Handler.deleted = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _ledger(path: Path, *ids: str, base_url=None) -> Path:
    path.write_text(
        json.dumps([{"incubation_id": identifier, "flow": "intake-to-preview", 'base_url': base_url} for identifier in ids]),
        encoding="utf-8",
    )
    return path


def test_purge_refuses_production_even_when_asked(tmp_path, target):
    ledger = _ledger(tmp_path / "ledger.json", "intake-1")
    removed, problem = purge_ledger(
        ledger, base_url=target, environment="production", allow_destructive=True
    )
    assert removed == []
    assert "refusing" in (problem or "")
    assert _Handler.deleted == []


def test_purge_requires_an_explicit_destructive_flag(tmp_path, target):
    ledger = _ledger(tmp_path / "ledger.json", "intake-1")
    removed, problem = purge_ledger(
        ledger, base_url=target, environment="test", allow_destructive=False
    )
    assert removed == []
    assert "--allow-destructive" in (problem or "")
    assert _Handler.deleted == []


def test_purge_removes_exactly_what_the_ledger_records(tmp_path, target):
    ledger = _ledger(tmp_path / "ledger.json", "intake-1", "already-gone", base_url=target)
    removed, problem = purge_ledger(
        ledger, base_url=target, environment="test", allow_destructive=True
    )
    assert problem is None
    assert sorted(removed) == ["already-gone", "intake-1"]
    assert _Handler.deleted == ["intake-1", "already-gone"]
    assert json.loads(ledger.read_text(encoding="utf-8")) == []


def test_purge_with_no_ledger_is_a_no_op(tmp_path, target):
    removed, problem = purge_ledger(
        tmp_path / "missing.json", base_url=target, environment="test", allow_destructive=True
    )
    assert removed == []
    assert problem is None
    assert _Handler.deleted == []


def test_recording_a_run_leaves_one_entry_for_the_next_purge(tmp_path):
    ledger = tmp_path / "ledger.json"
    record_ledger(ledger, {"incubation_id": "intake-a", "flow": "intake-to-preview"})
    record_ledger(ledger, {"incubation_id": "intake-b", "flow": "intake-to-preview"})
    entries = json.loads(ledger.read_text(encoding="utf-8"))
    assert [entry["incubation_id"] for entry in entries] == ["intake-a", "intake-b"]


def test_a_corrupt_ledger_never_deletes_anything(tmp_path, target):
    ledger = tmp_path / "ledger.json"
    ledger.write_text("{not json", encoding="utf-8")
    removed, problem = purge_ledger(
        ledger, base_url=target, environment="test", allow_destructive=True
    )
    assert removed == []
    assert 'invalid cleanup ledger' in problem
    assert _Handler.deleted == []


def test_a_ledger_from_another_target_is_refused(tmp_path, target):
    ledger = _ledger(tmp_path / 'ledger.json', 'intake-1', base_url='http://localhost:9999')
    _, problem = purge_ledger(ledger, base_url=target, environment='test', allow_destructive=True)
    assert 'another or unknown target' in problem
    assert _Handler.deleted == []


def test_test_flag_does_not_authorize_remote_website_deletion(tmp_path):
    ledger = _ledger(tmp_path / 'ledger.json', 'intake-1', base_url='https://customer.example')
    _, problem = purge_ledger(ledger, base_url='https://customer.example', environment='test', allow_destructive=True)
    assert 'teardown is not qualified' in problem
