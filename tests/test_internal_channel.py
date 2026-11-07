import json

import pytest

from site_agent import internal_channel
from site_agent.hands import workspace_mcp


def _server():
    server = workspace_mcp.WorkspaceServer.__new__(workspace_mcp.WorkspaceServer)
    server.job_id = 7
    server.tenant_id = "oceanicvibes"
    return server


def test_the_tool_process_forwards_a_build_to_the_api(monkeypatch):
    server = _server()
    monkeypatch.setenv("SITE_AGENT_INTERNAL_URL", "http://127.0.0.1:3014")
    monkeypatch.setenv("SITE_AGENT_INTERNAL_TOKEN", "internal-token")
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"ok": true, "text": "I made the change and prepared the preview."}'

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = {key.lower(): value for key, value in request.header_items()}
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    text, failed = server._call_api("spawn_build", {"brief": "rebuild the about page"})

    assert (text, failed) == ("I made the change and prepared the preview.", False)
    assert seen["url"] == "http://127.0.0.1:3014/internal/workspace/tool"
    assert seen["headers"]["x-internal-token"] == "internal-token"
    assert seen["body"] == {
        "tenant": "oceanicvibes",
        "job_id": 7,
        "tool": "spawn_build",
        "arguments": {"brief": "rebuild the about page"},
    }
    # The build owns its own bounded turn; the channel must not cut it short.
    assert seen["timeout"] == 2_700


def test_a_build_is_refused_when_the_api_channel_is_missing(monkeypatch):
    server = _server()
    monkeypatch.delenv("SITE_AGENT_INTERNAL_URL", raising=False)
    monkeypatch.delenv("SITE_AGENT_INTERNAL_TOKEN", raising=False)

    text, failed = server._call_api("spawn_build", {})

    assert failed is True
    assert "not reachable" in text
    assert "nothing was started" in text


def test_a_rejected_build_reports_the_status_instead_of_a_result(monkeypatch):
    server = _server()
    monkeypatch.setenv("SITE_AGENT_INTERNAL_URL", "http://127.0.0.1:3014")
    monkeypatch.setenv("SITE_AGENT_INTERNAL_TOKEN", "internal-token")

    def fake_urlopen(request, timeout=None):
        import urllib.error

        raise urllib.error.HTTPError(request.full_url, 409, "conflict", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    text, failed = server._call_api("spawn_build", {})

    assert failed is True
    assert "409" in text


def test_the_channel_address_is_loopback_even_when_the_api_listens_on_all_interfaces():
    internal_channel.configure(host="0.0.0.0", port=3014)
    assert internal_channel.environment()["SITE_AGENT_INTERNAL_URL"] == "http://127.0.0.1:3014"
    internal_channel.configure(host="127.0.0.1", port=3015)
    assert internal_channel.environment()["SITE_AGENT_INTERNAL_URL"] == "http://127.0.0.1:3015"


def test_the_channel_token_is_stable_within_the_process():
    assert internal_channel.token()
    assert internal_channel.token() == internal_channel.token()
    assert internal_channel.environment()["SITE_AGENT_INTERNAL_TOKEN"] == internal_channel.token()


def _app(tenant=None):
    from site_agent.web.workspace import create_workspace_api_app

    class FakeRegistry:
        tenants = {}

        def start(self):
            return None

        def close(self):
            return None

        def for_tenant_id(self, tenant_id):
            return tenant if tenant is not None and tenant_id == tenant.tenant_id else None

    return create_workspace_api_app(FakeRegistry())


def _endpoint(app):
    return next(route for route in app.routes if getattr(route, "path", "") == "/internal/workspace/tool").endpoint


class _Request:
    def __init__(self, host="127.0.0.1", token=None):
        self.client = type("Client", (), {"host": host})()
        self.headers = {"x-internal-token": token or ""}


def test_the_internal_route_rejects_anything_that_is_not_loopback():
    endpoint = _endpoint(_app())
    response = endpoint(_Request(host="203.0.113.9", token=internal_channel.token()), {})
    assert response.status_code == 403


def test_the_internal_route_rejects_a_missing_or_wrong_token():
    endpoint = _endpoint(_app())
    assert endpoint(_Request(token="wrong"), {}).status_code == 401
    assert endpoint(_Request(token=""), {}).status_code == 401


def test_the_internal_route_rejects_an_unknown_tenant():
    endpoint = _endpoint(_app())
    response = endpoint(_Request(token=internal_channel.token()), {"tenant": "nope", "job_id": 1, "tool": "list_drafts"})
    assert response.status_code == 404


def test_the_internal_route_runs_a_tool_for_a_registered_tenant(tmp_path):
    from types import SimpleNamespace

    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "memory.db")
    try:
        conversation = memory.create_conversation("Owner chat")
        job_id = memory.enqueue_chat_job(conversation, "what is waiting for me?")
        tenant = SimpleNamespace(tenant_id="oceanicvibes", memory=memory, context={"memory": memory, "config": {}, "env": {}})
        endpoint = _endpoint(_app(tenant))
        result = endpoint(
            _Request(token=internal_channel.token()),
            {"tenant": "oceanicvibes", "job_id": job_id, "tool": "list_drafts", "arguments": {}},
        )
        assert result["ok"] is True
        assert "no pending drafts" in result["text"]
    finally:
        memory.close()
