from __future__ import annotations

import base64
import json

import pytest

from site_agent.hands.github_release_queue import GitHubReleaseQueue, GitHubReleaseQueueError


SHA = "a" * 40
CUSTOMER = {
    "repository": "https://github.com/weareheadless/demo.git",
    "worker": "helloada-demo",
    "health": "https://demo.example/api/health",
    "adminPath": "/api/helloada",
    "payloadAdmin": "0.8.7",
    "payloadCore": "0.2.0",
    "contentContract": "helloada-content-v2",
    "schemaRevision": 2,
    "schemaIdentity": "b" * 64,
    "migrationHead": "c" * 64,
    "d1DatabaseId": "12345678-1234-1234-1234-123456789abc",
    "d1DatabaseName": "helloada-demo",
    "r2BucketName": "helloada-demo-media",
}


def test_release_request_commits_registry_and_exact_approval_together(monkeypatch):
    queue = GitHubReleaseQueue("token")
    documents = {
        "payload-customers.json": {"schema": 1, "releaseRoot": "/SOCIAL/payload-releases", "customers": {}},
        "desired-releases.json": {"schema": 1, "releases": {}},
    }
    calls = []
    blob_contents = {}

    def request(method, path, *, payload=None):
        calls.append((method, path, payload))
        if method == "GET" and path.endswith("git/ref/heads/main"):
            return 200, {"object": {"sha": "1" * 40}}
        if method == "GET" and path.endswith("git/commits/" + "1" * 40):
            return 200, {"tree": {"sha": "2" * 40}}
        if method == "GET" and "/contents/deploy/" in path:
            name = path.split("/contents/deploy/", 1)[1].split("?", 1)[0]
            return 200, {
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(documents[name]).encode()).decode(),
            }
        if method == "POST" and path.endswith("/git/blobs"):
            sha = f"{len(blob_contents) + 1:040x}"
            blob_contents[sha] = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
            return 201, {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            assert payload["base_tree"] == "2" * 40
            assert {row["path"] for row in payload["tree"]} == {
                "deploy/payload-customers.json", "deploy/desired-releases.json",
            }
            return 201, {"sha": "3" * 40}
        if method == "POST" and path.endswith("/git/commits"):
            assert payload["parents"] == ["1" * 40]
            return 201, {"sha": "4" * 40}
        if method == "PATCH" and path.endswith("/git/refs/heads/main"):
            assert payload == {"sha": "4" * 40, "force": False}
            return 200, {"object": {"sha": "4" * 40}}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(queue, "_request", request)
    result = queue.request("demo", SHA, CUSTOMER, approval_id=42)

    assert result["source_sha"] == SHA
    assert result["control_sha"] == "4" * 40
    assert result["release_id"].startswith("rel-")
    tree = next(payload for method, path, payload in calls if method == "POST" and path.endswith("/git/trees"))
    written = {row["path"].rsplit("/", 1)[1]: blob_contents[row["sha"]] for row in tree["tree"]}
    assert written["payload-customers.json"]["customers"]["demo"] == CUSTOMER
    assert written["desired-releases.json"]["releases"]["demo"] == {
        "id": result["release_id"], "sha": SHA, "approvalId": 42,
    }
    assert sum(method == "POST" and path.endswith("/git/commits") for method, path, _ in calls) == 1


def test_bootstrap_queues_only_the_exact_registered_migration_chain(monkeypatch):
    queue = GitHubReleaseQueue("token")
    documents = {
        "payload-customers.json": {"schema": 1, "releaseRoot": "/SOCIAL/payload-releases", "customers": {}},
        "desired-releases.json": {"schema": 1, "releases": {}},
    }

    calls = []
    blob_contents = {}

    def request(method, path, *, payload=None):
        calls.append((method, path, payload))
        if method == "GET" and path.endswith("git/ref/heads/main"):
            return 200, {"object": {"sha": "1" * 40}}
        if method == "GET" and path.endswith("git/commits/" + "1" * 40):
            return 200, {"tree": {"sha": "2" * 40}}
        if method == "GET" and "/contents/deploy/" in path:
            name = path.split("/contents/deploy/", 1)[1].split("?", 1)[0]
            return 200, {"encoding": "base64", "content": base64.b64encode(json.dumps(documents[name]).encode()).decode()}
        if method == "POST" and path.endswith("/git/blobs"):
            sha = f"{len(blob_contents) + 1:040x}"
            blob_contents[sha] = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
            return 201, {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            return 201, {"sha": "3" * 40}
        if method == "POST" and path.endswith("/git/commits"):
            return 201, {"sha": "4" * 40}
        if method == "PATCH" and path.endswith("/git/refs/heads/main"):
            return 200, {"object": {"sha": "4" * 40}}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(queue, "_request", request)
    result = queue.request("demo", SHA, CUSTOMER, initialize_schema=True)
    tree = next(payload for method, path, payload in calls if method == "POST" and path.endswith("/git/trees"))
    written = {row["path"].rsplit("/", 1)[1]: blob_contents[row["sha"]] for row in tree["tree"]}
    assert written["desired-releases.json"]["releases"]["demo"] == {
        "id": result["release_id"],
        "sha": SHA,
        "initializeSchema": {"migrationHead": CUSTOMER["migrationHead"]},
    }
    assert written["payload-customers.json"]["customers"]["demo"] == CUSTOMER


def test_matching_request_is_idempotent(monkeypatch):
    queue = GitHubReleaseQueue("token")
    documents = {
        "payload-customers.json": {"schema": 1, "customers": {"demo": CUSTOMER}},
        "desired-releases.json": {"schema": 1, "releases": {
            "demo": {"id": "rel-20261003000000-abcd1234", "sha": SHA, "approvalId": 42},
        }},
    }
    writes = []

    def request(method, path, *, payload=None):
        if method == "GET" and path.endswith("git/ref/heads/main"):
            return 200, {"object": {"sha": "1" * 40}}
        if method == "GET" and path.endswith("git/commits/" + "1" * 40):
            return 200, {"tree": {"sha": "2" * 40}}
        if method == "GET" and "/contents/deploy/" in path:
            name = path.split("/contents/deploy/", 1)[1].split("?", 1)[0]
            return 200, {"encoding": "base64", "content": base64.b64encode(json.dumps(documents[name]).encode()).decode()}
        writes.append((method, path))
        raise AssertionError("idempotent request must not create a second control commit")

    monkeypatch.setattr(queue, "_request", request)
    result = queue.request("demo", SHA, CUSTOMER, approval_id=42)
    assert result == {"release_id": "rel-20261003000000-abcd1234", "source_sha": SHA, "control_sha": "1" * 40}
    assert writes == []


def test_verified_failed_release_retry_creates_a_new_attempt(monkeypatch):
    queue = GitHubReleaseQueue("token")
    documents = {
        "payload-customers.json": {"schema": 1, "customers": {"demo": CUSTOMER}},
        "desired-releases.json": {"schema": 1, "releases": {
            "demo": {"id": "rel-20261003000000-abcd1234", "sha": SHA, "initializeSchema": {
                "migrationHead": CUSTOMER["migrationHead"],
            }},
        }},
    }
    writes = []
    blob_contents = {}

    def request(method, path, *, payload=None):
        if method == "GET" and path.endswith("git/ref/heads/main"):
            return 200, {"object": {"sha": "1" * 40}}
        if method == "GET" and path.endswith("git/commits/" + "1" * 40):
            return 200, {"tree": {"sha": "2" * 40}}
        if method == "GET" and "/contents/deploy/" in path:
            name = path.split("/contents/deploy/", 1)[1].split("?", 1)[0]
            return 200, {"encoding": "base64", "content": base64.b64encode(json.dumps(documents[name]).encode()).decode()}
        writes.append((method, path, payload))
        if method == "POST" and path.endswith("/git/blobs"):
            blob_sha = f"{len(blob_contents) + 1:040x}"
            blob_contents[blob_sha] = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
            return 201, {"sha": blob_sha}
        if method == "POST" and path.endswith("/git/trees"):
            return 201, {"sha": "3" * 40}
        if method == "POST" and path.endswith("/git/commits"):
            return 201, {"sha": "4" * 40}
        if method == "PATCH" and path.endswith("/git/refs/heads/main"):
            return 200, {"object": {"sha": "4" * 40}}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(queue, "_request", request)
    result = queue.request("demo", SHA, CUSTOMER, initialize_schema=True, new_attempt=True)

    assert result["release_id"] != "rel-20261003000000-abcd1234"
    tree = next(payload for method, path, payload in writes if method == "POST" and path.endswith("/git/trees"))
    written = {row["path"].rsplit("/", 1)[1]: blob_contents[row["sha"]] for row in tree["tree"]}
    assert written["desired-releases.json"]["releases"]["demo"] == {
        "id": result["release_id"],
        "sha": SHA,
        "initializeSchema": {"migrationHead": CUSTOMER["migrationHead"]},
    }
    assert sum(method == "POST" and path.endswith("/git/commits") for method, path, _ in writes) == 1


def test_release_request_rejects_noncanonical_or_unversioned_customer():
    queue = GitHubReleaseQueue("token")
    with pytest.raises(GitHubReleaseQueueError, match="official"):
        queue.request("demo", SHA, {**CUSTOMER, "repository": "https://github.com/other/demo.git"})
    with pytest.raises(GitHubReleaseQueueError, match="approval"):
        queue.request("demo", SHA, CUSTOMER, approval_id=0)
