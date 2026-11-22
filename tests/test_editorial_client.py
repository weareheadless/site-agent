"""The editorial client: one connection, many tenants, honest outcomes.

Three behaviours are load-bearing:

- The tenant is named in the brief, not proved by a token of its own. A token
  per tenant is the shape that strands each new customer on an unconfigured
  host, and the tenant is already an authenticated field.
- `held` is an editorial outcome with a reason. It is surfaced, not retried.
- `failed` is a real failure and is raised.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from site_agent.hands.editorial import (
    EditorialClient,
    EditorialError,
    EditorialRejectedError,
    EditorialTimeout,
    EditorialUnavailableError,
    build_editorial_client,
)

BRIEF = {
    "tenant": "site-ff8e9af06f56201f",
    "mode": "brief",
    "topic": {"question": "What did people wear?"},
    "evidence": {"min_sources": 2},
}


class FakeResponse:
    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self._raw = json.dumps(body).encode("utf-8")

    def read(self, limit: int = -1) -> bytes:
        return self._raw if limit < 0 else self._raw[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(monkeypatch, responses: list, calls: list | None = None) -> EditorialClient:
    queue = list(responses)

    def fake_urlopen(request, timeout=None):
        if calls is not None:
            calls.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return EditorialClient(base_url="http://127.0.0.1:8790", token="host-token", poll_seconds=0)


def test_a_brief_is_submitted_and_its_post_id_returned(monkeypatch):
    calls: list = []
    client = _client(monkeypatch, [FakeResponse(202, {"post_id": "post_1", "state": "queued"})], calls)

    assert client.submit(BRIEF) == "post_1"
    body = json.loads(calls[0].data.decode("utf-8"))
    assert body["tenant"] == "site-ff8e9af06f56201f"
    assert calls[0].headers["Authorization"] == "Bearer host-token"


def test_wait_returns_a_ready_post_with_its_artifact(monkeypatch):
    client = _client(
        monkeypatch,
        [
            FakeResponse(200, {"id": "post_1", "state": "researching", "artifacts": {}}),
            FakeResponse(
                200,
                {
                    "id": "post_1",
                    "state": "ready",
                    "artifacts": {"es": {"title": "Un título", "body_markdown": "Cuerpo"}},
                },
            ),
        ],
    )

    post = client.wait("post_1", deadline_seconds=10)

    assert post.ready
    assert post.artifact("es")["title"] == "Un título"


def test_a_missing_locale_is_named_not_silently_empty():
    from site_agent.hands.editorial import EditorialPost

    post = EditorialPost(post_id="post_1", state="ready", artifacts={})

    with pytest.raises(EditorialError, match="no 'es' artifact"):
        post.artifact("es")


def test_held_is_an_outcome_with_its_reason_not_an_outage(monkeypatch):
    client = _client(
        monkeypatch,
        [
            FakeResponse(
                200,
                {"id": "post_1", "state": "held", "error": "only 1 readable source", "artifacts": {}},
            )
        ],
    )

    post = client.wait("post_1", deadline_seconds=10)

    assert post.held
    assert post.error == "only 1 readable source"


def test_failed_is_raised_because_it_is_not_an_editorial_judgement(monkeypatch):
    client = _client(
        monkeypatch,
        [FakeResponse(200, {"id": "post_1", "state": "failed", "error": "writer exploded"})],
    )

    with pytest.raises(EditorialError, match="writer exploded"):
        client.wait("post_1", deadline_seconds=10)


def test_running_out_of_budget_names_the_post_and_leaves_it_pollable(monkeypatch):
    client = _client(
        monkeypatch,
        [FakeResponse(200, {"id": "post_1", "state": "drafting"})] * 50,
    )

    with pytest.raises(EditorialTimeout, match="post_1"):
        client.wait("post_1", deadline_seconds=0.05)


def test_a_bad_brief_is_rejected_and_not_retried_as_an_outage(monkeypatch):
    client = _client(
        monkeypatch,
        [urllib.error.HTTPError("u", 422, "no", {}, None)],
    )

    with pytest.raises(EditorialRejectedError):
        client.submit(BRIEF)


def test_a_dead_service_is_unavailable_so_the_caller_does_not_blame_the_brief(monkeypatch):
    client = _client(monkeypatch, [urllib.error.URLError("connection refused")])

    with pytest.raises(EditorialUnavailableError, match="could not be reached"):
        client.submit(BRIEF)


def test_an_unconfigured_connection_says_which_setting_is_missing():
    client = EditorialClient(base_url="", token="")

    with pytest.raises(EditorialUnavailableError, match="providers.editorial"):
        client.submit(BRIEF)


def test_the_host_profile_resolves_one_connection_for_every_tenant(tmp_path):
    env_file = tmp_path / "editorial.env"
    env_file.write_text("EDITORIAL_TOKEN=host-token\n", encoding="utf-8")
    config = {
        "credentials": {
            "editorial": {
                "url": "http://127.0.0.1:8790",
                "api_token_env": "EDITORIAL_TOKEN",
                "env_file": str(env_file),
            }
        }
    }

    client = build_editorial_client(config)

    assert client.base_url == "http://127.0.0.1:8790"
    assert client.token == "host-token"
    assert client.configured()
