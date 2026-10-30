"""Focused, read-only proof for the extracted Worker verifier."""
import urllib.error

import pytest

from site_agent.hands import cloudflare_worker_verification as verifier


def deployment(version="uploaded", *, annotations=None, versions=None, identity="same"):
    return {"id": "deploy-1", "annotations": annotations or {},
            "versions": versions if versions is not None else [{"version_id": version, "percentage": 100}],
            "_identity": identity}


def test_exact_version_and_secret_only_replacement():
    current = deployment("uploaded")
    identity = {"script_etag": "etag", "binding_identity": "bindings"}
    result = verifier.resolve_verified_active_worker(
        {}, {}, "uploaded", inspect_deployment=lambda *_: current,
        inspect_version=lambda *_: identity, require_snapshot=lambda *_: None,
        sleep=lambda _: pytest.fail("unexpected retry"))
    assert result == (current, "uploaded", identity, identity)
    rotated = deployment("rotated", annotations={"workers/triggered_by": "secret"})
    versions = iter([rotated])
    assert verifier.resolve_verified_active_worker(
        {}, {}, "uploaded", inspect_deployment=lambda *_: next(versions),
        inspect_version=lambda *_: identity, require_snapshot=lambda *_: None,
        sleep=lambda _: None)[1] == "rotated"


@pytest.mark.parametrize("active,trigger,active_id", [
    ("other", "secret", {"script_etag": "different", "binding_identity": "bindings"}),
    ("other", "secret", {"script_etag": "etag", "binding_identity": "different"}),
    ("other", "deployment", {"script_etag": "etag", "binding_identity": "bindings"}),
])
def test_rejects_changed_code_bindings_or_nonsecret_trigger(active, trigger, active_id):
    dep = deployment(active, annotations={"workers/triggered_by": trigger})
    def inspect(_, version, __):
        return {"script_etag": "etag", "binding_identity": "bindings"} if version == "uploaded" else active_id
    with pytest.raises(RuntimeError):
        verifier.resolve_verified_active_worker({}, {}, "uploaded", inspect_deployment=lambda *_: dep,
                                                inspect_version=inspect, sleep=lambda _: None)


@pytest.mark.parametrize("versions", [[], [{"version_id": "a", "percentage": 50}, {"version_id": "b", "percentage": 50}],
                                         [{"version_id": "a", "percentage": 99}]])
def test_rejects_split_or_missing_traffic(versions):
    with pytest.raises(RuntimeError, match="exactly one 100%-traffic"):
        verifier.resolve_verified_active_worker({}, {}, "a", inspect_deployment=lambda *_: deployment(versions=versions))


def test_retries_drift_eight_times_then_exhausts():
    sleeps = []
    drift = lambda *_: (_ for _ in ()).throw(RuntimeError("the active Worker version changed during readiness verification"))
    with pytest.raises(RuntimeError, match="active Worker version changed"):
        verifier.resolve_verified_active_worker({}, {}, "v", inspect_deployment=lambda *_: deployment("v"),
            inspect_version=lambda *_: {}, require_snapshot=drift, sleep=sleeps.append)
    assert sleeps == [0.25] * 7


def test_version_inspection_is_get_only_and_rejects_http_or_malformed(monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"success":true,"result":{"id":"v","resources":{"script":{"etag":"e"},"bindings":[]}}}'
    def transport(request, **kwargs):
        calls.append(request.get_method())
        assert request.get_method() == "GET"
        return Response()
    monkeypatch.setattr(verifier.urllib.request, "urlopen", transport)
    assert verifier.cloudflare_worker_version_identity({"worker": "w"}, "v", {"CLOUDFLARE_ACCOUNT_ID":"a", "CLOUDFLARE_API_TOKEN":"t"})["script_etag"] == "e"
    assert calls == ["GET"]
