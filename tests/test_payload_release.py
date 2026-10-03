"""Release safety boundaries: provenance, canonical routes and immutable requests."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script("deploy-payload-customer")
queue = load_script("reconcile-payload-releases")
SHA = "a" * 40
REGISTRY = json.loads((ROOT / "deploy/payload-customers.json").read_text())


def test_committed_queue_is_valid():
    queue.validate_queue(json.loads((ROOT / "deploy/desired-releases.json").read_text()), REGISTRY)


@pytest.mark.parametrize("tenant,release_request", [
    ("unknown", {"id": "release-1", "sha": SHA}),
    ("oceanicvibes", {"id": "../escape", "sha": SHA}),
    ("oceanicvibes", {"id": "release-1", "sha": "main"}),
    ("oceanicvibes", {"id": "release-1", "sha": SHA, "command": "arbitrary"}),
])
def test_invalid_requests_never_execute(tenant, release_request):
    with pytest.raises(ValueError):
        queue.validate_queue({"schema": 1, "releases": {tenant: release_request}}, REGISTRY)


def test_external_customer_repository_is_rejected():
    customer = {**REGISTRY["customers"]["oceanicvibes"], "repository": "https://github.com/stranger/site.git"}
    with pytest.raises(ValueError, match="official"):
        release.validate_target(customer, "oceanicvibes", SHA, "release-1")


def test_same_admin_version_does_not_prove_new_source(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"ok": True, "tenant": "oceanicvibes", "payloadAdmin": "0.8.4", "releaseSha": "b" * 40}).encode()

    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="release SHA"):
        release.check_health("https://oceanicvibes.com/api/health", "oceanicvibes", "0.8.4", SHA)


def artifact(tmp_path):
    files = {
        ".open-next/worker.js": "import './server-functions/default/handler.mjs'",
        ".open-next/server-functions/default/handler.mjs": "route('/growth/contract')",
        ".next/server/app-paths-manifest.json": json.dumps({"/api/helloada/[...path]/route": "helloada.js", "/api/health/route": "health.js"}),
        "node_modules/@weareheadless/helloada-payload-admin/package.json": json.dumps({"version": "0.8.4"}),
        ".open-next/assets/helloada-release.json": json.dumps({"sourceSha": SHA, "payloadAdmin": "0.8.4"}),
    }
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return tmp_path


def test_checks_compiled_server_instead_of_thin_worker_entry(tmp_path):
    checkout = artifact(tmp_path)
    hashes = release.inspect_artifact(checkout, "0.8.4", SHA)
    assert "server-functions/default/handler.mjs" in hashes


def test_stale_release_marker_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / ".open-next/assets/helloada-release.json").write_text(json.dumps({"sourceSha": "b" * 40, "payloadAdmin": "0.8.4"}))
    with pytest.raises(RuntimeError, match="marker"):
        release.inspect_artifact(checkout, "0.8.4", SHA)


def test_obsolete_route_in_built_manifest_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    routes["/api/atelier/ada/route"] = "old.js"
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="obsolete"):
        release.inspect_artifact(checkout, "0.8.4", SHA)
