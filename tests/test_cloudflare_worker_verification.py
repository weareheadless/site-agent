"""Focused, read-only proof for the extracted Worker verifier."""
import builtins
import json
import os
import urllib.error
from pathlib import Path

import pytest

from site_agent.hands import cloudflare_worker_verification as verifier


CUSTOMER = {"worker": "customer-worker"}
ENV = {"CLOUDFLARE_ACCOUNT_ID": "account-1", "CLOUDFLARE_API_TOKEN": "test-token"}


def deployment(version="uploaded", *, annotations=None, versions=None, deployment_id="deploy-1"):
    return {
        "id": deployment_id,
        "created_on": "2026-01-01T00:00:00Z",
        "annotations": annotations or {},
        "versions": versions if versions is not None else [{"version_id": version, "percentage": 100}],
    }


def version(version_id, *, etag="script-etag", bindings=None):
    return {
        "id": version_id,
        "resources": {
            "script": {"etag": etag},
            "bindings": bindings if bindings is not None else [
                {"name": "DB", "type": "d1", "id": "database-1"},
                {"name": "TOKEN", "type": "secret_text", "text": "secret-value"},
            ],
        },
    }


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def http_error(code):
    return urllib.error.HTTPError("https://api.cloudflare.com/", code, "failure", {}, None)


@pytest.mark.parametrize("inspector, expected", [
    ("deployment", deployment()),
    ("version", {"script_etag": "script-etag", "binding_identity": verifier.worker_version_identity(version("uploaded"))["binding_identity"]}),
])
def test_http_inspectors_parse_successful_real_shaped_responses(monkeypatch, inspector, expected):
    calls = []

    def transport(request, **kwargs):
        calls.append((request.get_method(), request.full_url))
        if inspector == "deployment":
            return Response({"success": True, "result": {"deployments": [deployment()]}})
        return Response({"success": True, "result": version("uploaded")})

    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    actual = (verifier.cloudflare_deployment(CUSTOMER, ENV) if inspector == "deployment" else
              verifier.cloudflare_worker_version_identity(CUSTOMER, "uploaded", ENV))
    assert actual == expected
    assert len(calls) == 1
    assert calls[0][0] == "GET"


@pytest.mark.parametrize("code, expected", [(404, {}), (401, RuntimeError), (500, RuntimeError)])
def test_deployment_inspector_http_errors_are_handled_as_contract(code, expected, monkeypatch):
    def transport(*_, **__):
        raise http_error(code)

    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    if expected is RuntimeError:
        with pytest.raises(RuntimeError, match=f"HTTP {code}"):
            verifier.cloudflare_deployment(CUSTOMER, ENV)
    else:
        assert verifier.cloudflare_deployment(CUSTOMER, ENV) == expected


@pytest.mark.parametrize("inspector", ["deployment", "version"])
@pytest.mark.parametrize("payload", [b"{not-json", b'{"success":false,"errors":[{"message":"denied"}]}'])
def test_http_inspectors_fail_closed_on_malformed_json_or_unsuccessful_result(monkeypatch, inspector, payload):
    class RawResponse(Response):
        def read(self):
            return payload

    monkeypatch.setattr(verifier.urllib.request, "urlopen", lambda *_args, **_kwargs: RawResponse(None))
    with pytest.raises((RuntimeError, ValueError, json.JSONDecodeError, KeyError)):
        if inspector == "deployment":
            verifier.cloudflare_deployment(CUSTOMER, ENV)
        else:
            verifier.cloudflare_worker_version_identity(CUSTOMER, "uploaded", ENV)


@pytest.mark.parametrize("code", [401, 404, 500])
def test_version_inspector_http_errors_fail_closed(monkeypatch, code):
    monkeypatch.setattr(verifier.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error(code)))
    with pytest.raises(RuntimeError, match=f"HTTP {code}"):
        verifier.cloudflare_worker_version_identity(CUSTOMER, "uploaded", ENV)


def test_version_inspector_rejects_wrong_requested_version(monkeypatch):
    monkeypatch.setattr(verifier.urllib.request, "urlopen", lambda *_args, **_kwargs:
                        Response({"success": True, "result": version("different-version")}))
    with pytest.raises(RuntimeError, match="does not match the requested version"):
        verifier.cloudflare_worker_version_identity(CUSTOMER, "uploaded", ENV)


def block_mutation_paths(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("read-only verifier attempted a filesystem mutation")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    for name in ("write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "replace"):
        monkeypatch.setattr(Path, name, forbidden)
    for name in ("remove", "replace", "mkdir", "makedirs", "rename", "unlink"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, forbidden)


def transport_for(active_version, *, trigger=None):
    calls = []
    active = deployment(active_version, annotations={"workers/triggered_by": trigger} if trigger else {})

    def transport(request, **kwargs):
        method, url = request.get_method(), request.full_url
        calls.append((method, url))
        assert method == "GET", f"unexpected non-GET request: {method} {url}"
        if url.endswith("/deployments"):
            payload = {"success": True, "result": {"deployments": [active]}}
        elif "/versions/" in url:
            requested = url.rsplit("/", 1)[-1]
            # Secret rotation changes the secret value but not the normalized identity.
            payload = {"success": True, "result": version(requested, bindings=[
                {"name": "DB", "type": "d1", "id": "database-1"},
                {"name": "TOKEN", "type": "secret_text", "text": "rotated-secret" if requested == active_version else "secret-value"},
            ])}
        else:
            raise AssertionError(f"unexpected verifier request (including activation/receipt APIs): {url}")
        return Response(payload)

    return calls, transport


@pytest.mark.parametrize("active_version, trigger", [("uploaded", None), ("rotated", "secret")])
def test_package_resolver_uses_real_http_defaults_read_only(monkeypatch, active_version, trigger):
    block_mutation_paths(monkeypatch)
    calls, transport = transport_for(active_version, trigger=trigger)
    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    result = verifier.resolve_verified_active_worker(CUSTOMER, ENV, "uploaded")
    assert result[1] == active_version
    assert result[0]["id"] == "deploy-1"
    assert result[2] == result[3]
    assert calls and all(method == "GET" for method, _ in calls)
    # The final deployment read is the resolver's required stability snapshot.
    assert len(calls) == (3 if active_version == "uploaded" else 4)


@pytest.mark.parametrize("active_version, trigger, active_identity", [
    ("rotated", "secret", {"etag": "changed", "binding": "same"}),
    ("rotated", "secret", {"etag": "same", "binding": "changed"}),
    ("rotated", "deployment", {"etag": "same", "binding": "same"}),
])
def test_rejects_changed_code_nonsecret_bindings_or_nonsecret_trigger(active_version, trigger, active_identity):
    dep = deployment(active_version, annotations={"workers/triggered_by": trigger})

    def inspect(_, version_id, __):
        return {"script_etag": "same", "binding_identity": "same"} if version_id == "uploaded" else {
            "script_etag": active_identity["etag"], "binding_identity": active_identity["binding"]}

    with pytest.raises(RuntimeError):
        verifier.resolve_verified_active_worker(CUSTOMER, ENV, "uploaded", inspect_deployment=lambda *_: dep,
                                                inspect_version=inspect, sleep=lambda _: None)


@pytest.mark.parametrize("versions", [[], [{"version_id": "a", "percentage": 50}, {"version_id": "b", "percentage": 50}],
                                          [{"version_id": "a", "percentage": 99}]])
def test_rejects_split_or_missing_traffic(versions):
    with pytest.raises(RuntimeError, match="exactly one 100%-traffic"):
        verifier.resolve_verified_active_worker(CUSTOMER, ENV, "a", inspect_deployment=lambda *_: deployment(versions=versions))


def test_retries_drift_once_then_succeeds():
    sleeps, observations = [], []

    def snapshot(*_):
        observations.append(None)
        if len(observations) == 1:
            raise RuntimeError("the active Worker version changed during readiness verification")

    result = verifier.resolve_verified_active_worker(CUSTOMER, ENV, "v", inspect_deployment=lambda *_: deployment("v"),
        inspect_version=lambda *_: {"identity": "same"}, require_snapshot=snapshot, sleep=sleeps.append)
    assert result[1] == "v"
    assert len(observations) == 2
    assert sleeps == [0.25]


def test_retries_drift_eight_times_then_exhausts():
    sleeps = []
    drift = lambda *_: (_ for _ in ()).throw(RuntimeError("the active Worker version changed during readiness verification"))
    with pytest.raises(RuntimeError, match="active Worker version changed"):
        verifier.resolve_verified_active_worker(CUSTOMER, ENV, "v", inspect_deployment=lambda *_: deployment("v"),
            inspect_version=lambda *_: {}, require_snapshot=drift, sleep=sleeps.append)
    assert sleeps == [0.25] * 7
