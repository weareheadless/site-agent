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
    "websitePresent": False,
    "payloadAdmin": "0.8.7",
    "payloadCore": "0.2.0",
    "contentContract": "helloada-content-v2",
    "schemaRevision": 2,
    "schemaIdentity": "b" * 64,
    "migrationHead": "c" * 64,
    "d1DatabaseId": "12345678-1234-1234-1234-123456789abc",
    "d1DatabaseName": "helloada-demo",
    "mailflareD1DatabaseId": "22345678-1234-1234-1234-123456789abc",
    "mailflareD1DatabaseName": "helloada-demo-mail",
    "r2BucketName": "helloada-demo-media",
    "privateEmailR2BucketName": "helloada-demo-email",
    "mailflareR2BucketName": "helloada-demo-mail-files",
    "mailflareInboundQueueName": "helloada-demo-mail-inbound",
    "mailflareOutboundQueueName": "helloada-demo-mail-outbound",
    "mailflareAgentQueueName": "helloada-demo-mail-agent",
}


@pytest.mark.parametrize('registered_only', [False, True])
def test_release_request_commits_registry_and_exact_approval_together(monkeypatch, registered_only):
    queue = GitHubReleaseQueue("token")
    legacy_customer = {key: value for key, value in CUSTOMER.items() if key not in {
        "privateEmailR2BucketName",
        "mailflareD1DatabaseId", "mailflareD1DatabaseName", "mailflareR2BucketName",
        "mailflareInboundQueueName", "mailflareOutboundQueueName", "mailflareAgentQueueName",
    }}
    documents = {
        "payload-customers.json": {
            "schema": 1, "releaseRoot": "/SOCIAL/payload-releases", "customers": {"demo": CUSTOMER if registered_only else legacy_customer},
        },
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
    result = queue.request("demo", SHA, None if registered_only else CUSTOMER, approval_id=42,
                           **({'expected_identity': {key: CUSTOMER[key] for key in ('repository', 'worker')}} if registered_only else {}))

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


@pytest.mark.parametrize('registered,expected', [
    (False, {'repository': CUSTOMER['repository'], 'worker': CUSTOMER['worker']}),
    (True, {'repository': 'https://github.com/weareheadless/wrong.git', 'worker': CUSTOMER['worker']}),
])
def test_registered_only_release_rejects_missing_or_mismatched_identity(monkeypatch, registered, expected):
    queue = GitHubReleaseQueue('token')
    documents = {
        'payload-customers.json': {'schema': 1, 'customers': {'demo': CUSTOMER} if registered else {}},
        'desired-releases.json': {'schema': 1, 'releases': {}},
    }
    def request(method, path, **kwargs):
        assert method == 'GET', 'invalid identity must never write the queue'
        if path.endswith('git/ref/heads/main'):
            return 200, {'object': {'sha': '1' * 40}}
        if '/git/commits/' in path:
            return 200, {'tree': {'sha': '2' * 40}}
        name = path.split('/contents/deploy/')[1].split('?')[0]
        return 200, {'encoding': 'base64', 'content': base64.b64encode(json.dumps(documents[name]).encode()).decode()}
    monkeypatch.setattr(queue, '_request', request)
    with pytest.raises(GitHubReleaseQueueError, match='registered'):
        queue.request('demo', SHA, approval_id=42, expected_identity=expected)


def test_ordinary_release_does_not_read_an_authoring_checkout(monkeypatch, tmp_path):
    from site_agent.application import release_queue
    observed = {}
    class Queue:
        def __init__(self, token):
            assert token == 'token'
        def request(self, tenant, source_sha, customer, **kwargs):
            observed.update(tenant=tenant, source_sha=source_sha, customer=customer, **kwargs)
            return {'release_id': 'queued'}
    def prohibited(*args, **kwargs):
        raise AssertionError('ordinary release tried to read a mutable customer checkout')
    monkeypatch.setattr(release_queue, 'customer_release_identity', prohibited)
    monkeypatch.setattr(release_queue, 'credential_environment', lambda *args: {})
    monkeypatch.setattr(release_queue, 'github_api_token', lambda *args: 'token')
    monkeypatch.setattr(release_queue, 'GitHubReleaseQueue', Queue)
    result = release_queue.request_release({
        'instance_name': 'demo', 'deployment_pipeline': {'release_root': str(tmp_path)},
        'site': {'repository': 'weareheadless/demo', 'clone_path': '/does-not-exist', 'source_deployment': {'worker_name': 'helloada-demo'}},
    }, {}, SHA, approval_id=42)
    assert result == {'release_id': 'queued'}
    assert observed['customer'] is None
    assert observed['expected_identity'] == {'repository': CUSTOMER['repository'], 'worker': CUSTOMER['worker']}


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
    assert written["payload-customers.json"]["customers"]["demo"] == {**CUSTOMER, "sharedRuntimeUpdate": "automatic"}


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
    retry_result = queue.request(
        "demo",
        SHA,
        CUSTOMER,
        approval_id=42,
        release_id="rel-20261003000000-abcd1234",
    )
    assert retry_result == result
    assert writes == []
    with pytest.raises(GitHubReleaseQueueError, match="already bound"):
        queue.request(
            "demo",
            "b" * 40,
            CUSTOMER,
            approval_id=42,
            release_id="rel-20261003000000-abcd1234",
        )


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
    retry_release_id = "rel-20261006000000-1234abcd"
    result = queue.request("demo", SHA, CUSTOMER, initialize_schema=True, release_id=retry_release_id)

    assert result["release_id"] == retry_release_id
    tree = next(payload for method, path, payload in writes if method == "POST" and path.endswith("/git/trees"))
    written = {row["path"].rsplit("/", 1)[1]: blob_contents[row["sha"]] for row in tree["tree"]}
    assert written["desired-releases.json"]["releases"]["demo"] == {
        "id": result["release_id"],
        "sha": SHA,
        "initializeSchema": {"migrationHead": CUSTOMER["migrationHead"]},
    }
    assert sum(method == "POST" and path.endswith("/git/commits") for method, path, _ in writes) == 1


@pytest.mark.parametrize("website_present", [None, "false", 1])
def test_release_request_requires_boolean_website_presence(website_present):
    customer = dict(CUSTOMER)
    if website_present is None:
        customer.pop("websitePresent")
    else:
        customer["websitePresent"] = website_present
    with pytest.raises(GitHubReleaseQueueError, match="website-present"):
        GitHubReleaseQueue("token").request("demo", SHA, customer)


def test_release_request_rejects_noncanonical_or_unversioned_customer():
    queue = GitHubReleaseQueue("token")
    with pytest.raises(GitHubReleaseQueueError, match="official"):
        queue.request("demo", SHA, {**CUSTOMER, "repository": "https://github.com/other/demo.git"})
    with pytest.raises(GitHubReleaseQueueError, match="approval"):
        queue.request("demo", SHA, CUSTOMER, approval_id=0)
