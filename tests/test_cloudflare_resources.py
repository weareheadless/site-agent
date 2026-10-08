from __future__ import annotations

import pytest

from site_agent.hands.cloudflare_resources import (
    CloudflareResourceError,
    CloudflareResourceProvisioner,
)


ACCOUNT_ID = "a" * 32


def test_queue_provisioner_reuses_existing_queue(monkeypatch):
    provisioner = CloudflareResourceProvisioner(ACCOUNT_ID, "test-token")
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        assert method == "GET"
        assert path == f"/accounts/{ACCOUNT_ID}/queues?page=1&per_page=100"
        assert payload is None
        return 200, {
            "success": True,
            "result": [{"queue_id": "queue-123", "queue_name": "messages-demo"}],
            "result_info": {"total_pages": 1},
        }

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_queue("messages-demo")

    assert receipt.to_dict() == {
        "queue_id": "queue-123",
        "name": "messages-demo",
        "created": False,
    }
    assert len(calls) == 1


def test_queue_provisioner_creates_a_missing_queue(monkeypatch):
    provisioner = CloudflareResourceProvisioner(ACCOUNT_ID, "test-token")
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        if method == "GET":
            return 200, {"success": True, "result": [], "result_info": {"total_pages": 1}}
        assert method == "POST"
        assert path == f"/accounts/{ACCOUNT_ID}/queues"
        assert payload == {"queue_name": "messages-demo"}
        return 200, {
            "success": True,
            "result": {"queue_id": "queue-123", "queue_name": "messages-demo"},
        }

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_queue("messages-demo")

    assert receipt.to_dict() == {
        "queue_id": "queue-123",
        "name": "messages-demo",
        "created": True,
    }
    assert [call[0] for call in calls] == ["GET", "POST"]


def test_queue_provisioner_reconciles_a_concurrent_creation(monkeypatch):
    provisioner = CloudflareResourceProvisioner(ACCOUNT_ID, "test-token")
    list_calls = 0

    def fake_request(method, _path, *, payload=None):
        nonlocal list_calls
        if method == "GET":
            list_calls += 1
            rows = [] if list_calls == 1 else [
                {"queue_id": "queue-123", "queue_name": "messages-demo"},
            ]
            return 200, {"success": True, "result": rows, "result_info": {"total_pages": 1}}
        assert method == "POST"
        assert payload == {"queue_name": "messages-demo"}
        return 409, {"success": False, "errors": [{"message": "already exists"}]}

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_queue("messages-demo")

    assert receipt.queue_id == "queue-123"
    assert receipt.created is False
    assert list_calls == 2


def test_queue_provisioner_searches_all_pages(monkeypatch):
    provisioner = CloudflareResourceProvisioner(ACCOUNT_ID, "test-token")
    paths = []

    def fake_request(method, path, *, payload=None):
        assert method == "GET"
        assert payload is None
        paths.append(path)
        page = int(path.split("page=", 1)[1].split("&", 1)[0])
        if page == 1:
            return 200, {
                "success": True,
                "result": [
                    {"queue_id": str(index), "queue_name": f"queue-{index}"}
                    for index in range(100)
                ],
                "result_info": {"total_pages": 2},
            }
        return 200, {
            "success": True,
            "result": [{"queue_id": "queue-123", "queue_name": "messages-demo"}],
            "result_info": {"total_pages": 2},
        }

    monkeypatch.setattr(provisioner, "_request", fake_request)
    receipt = provisioner.ensure_queue("messages-demo")

    assert receipt.queue_id == "queue-123"
    assert len(paths) == 2


def test_queue_provisioner_fails_closed_on_incomplete_pagination(monkeypatch):
    provisioner = CloudflareResourceProvisioner(ACCOUNT_ID, "test-token")

    def fake_request(_method, _path, *, payload=None):
        assert payload is None
        return 200, {
            "success": True,
            "result": [
                {"queue_id": str(index), "queue_name": f"queue-{index}"}
                for index in range(100)
            ],
        }

    monkeypatch.setattr(provisioner, "_request", fake_request)
    with pytest.raises(CloudflareResourceError, match="omitted pagination metadata"):
        provisioner.ensure_queue("messages-demo")


def test_queue_provisioner_rejects_invalid_names_without_api_calls(monkeypatch):
    provisioner = CloudflareResourceProvisioner(ACCOUNT_ID, "test-token")
    monkeypatch.setattr(
        provisioner,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("invalid queue name must not make API calls"),
    )

    with pytest.raises(CloudflareResourceError, match="Queue name is invalid"):
        provisioner.ensure_queue("Messages Demo")
