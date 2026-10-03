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


def test_interrupted_receipts_are_terminal_even_after_the_queue_moves_on(tmp_path):
    interrupted = tmp_path / "runs/oceanicvibes/old-request/receipt.json"
    interrupted.parent.mkdir(parents=True)
    interrupted.write_text(json.dumps({"status": "running", "sourceSha": SHA, "stage": "build"}))
    completed = tmp_path / "runs/oceanicvibes/completed/receipt.json"
    completed.parent.mkdir(parents=True)
    completed.write_text(json.dumps({"status": "deployed", "sourceSha": SHA}))
    queue.mark_interrupted_runs(tmp_path)
    result = json.loads(interrupted.read_text())
    assert result["status"] == "interrupted" and result["finishedAt"]
    assert json.loads(completed.read_text())["status"] == "deployed"
    first = interrupted.read_bytes()
    queue.mark_interrupted_runs(tmp_path)
    assert interrupted.read_bytes() == first


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


@pytest.mark.parametrize("field", ["payloadAdmin", "payloadCore", "contentContract"])
def test_release_registry_requires_exact_shared_payload_versions(field):
    customer = {**REGISTRY["customers"]["oceanicvibes"], field: ""}
    with pytest.raises(ValueError, match="version|contract"):
        release.validate_target(customer, "oceanicvibes", SHA, "release-1")


def test_worker_contract_requires_the_registered_tenant_and_all_shared_versions():
    customer = REGISTRY["customers"]["oceanicvibes"]
    release.validate_worker_contract({"name": "oceanicvibes", "tenant": "oceanicvibes",
        "admin": customer["payloadAdmin"], "core": customer["payloadCore"],
        "contract": customer["contentContract"]}, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="shared Payload contract"):
        release.validate_worker_contract({"name": "oceanicvibes", "tenant": "oceanicvibes",
            "admin": customer["payloadAdmin"], "core": "0.0.9",
            "contract": customer["contentContract"]}, customer, "oceanicvibes")


def test_promotion_uses_the_uploaded_version_and_rejects_ambiguous_output():
    version = "12345678-1234-1234-1234-123456789abc"
    output = f"Uploaded Worker\nWorker Version ID: {version}\n"
    assert release.uploaded_version_id(output) == version
    for invalid in ("Upload failed", output + output):
        with pytest.raises(RuntimeError, match="exactly one"):
            release.uploaded_version_id(invalid)


def test_same_admin_version_does_not_prove_new_source(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"ok": True, "tenant": "oceanicvibes", "payloadAdmin": "0.8.6",
                               "payloadCore": "0.1.0", "contentContract": "helloada-content-v1",
                               "releaseSha": "b" * 40}).encode()

    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="release SHA"):
        release.check_health("https://oceanicvibes.com/api/health", "oceanicvibes",
                             REGISTRY["customers"]["oceanicvibes"], SHA)


@pytest.mark.parametrize("key,value", [
    ("payloadAdmin", "0.8.5"),
    ("payloadCore", "0.0.9"),
    ("contentContract", "helloada-content-v0"),
])
def test_live_health_requires_the_exact_shared_payload_contract(monkeypatch, key, value):
    body = {"ok": True, "tenant": "oceanicvibes", "payloadAdmin": "0.8.6",
            "payloadCore": "0.1.0", "contentContract": "helloada-content-v1", "releaseSha": SHA}
    body[key] = value

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(body).encode()

    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="shared Payload contract"):
        release.check_health("https://oceanicvibes.com/api/health", "oceanicvibes",
                             REGISTRY["customers"]["oceanicvibes"], SHA)


def artifact(tmp_path):
    customer = REGISTRY["customers"]["oceanicvibes"]
    files = {
        ".open-next/worker.js": "import './server-functions/default/handler.mjs'",
        ".open-next/server-functions/default/handler.mjs": "route('/growth/contract')",
        ".next/server/app-paths-manifest.json": json.dumps({"/api/helloada/[...path]/route": "helloada.js", "/api/content/route": "content.js", "/api/health/route": "health.js"}),
        "node_modules/@weareheadless/helloada-payload-admin/package.json": json.dumps({"version": customer["payloadAdmin"]}),
        "node_modules/@weareheadless/helloada-payload-core/package.json": json.dumps({"version": customer["payloadCore"]}),
        "helloada-content-contract.json": json.dumps({"contract": customer["contentContract"]}),
        ".open-next/assets/helloada-release.json": json.dumps({"sourceSha": SHA,
            "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
            "contentContract": customer["contentContract"]}),
    }
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return tmp_path


def test_checks_compiled_server_instead_of_thin_worker_entry(tmp_path):
    checkout = artifact(tmp_path)
    hashes = release.inspect_artifact(checkout, REGISTRY["customers"]["oceanicvibes"], SHA)
    assert "server-functions/default/handler.mjs" in hashes


def test_stale_release_marker_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / ".open-next/assets/helloada-release.json").write_text(json.dumps({"sourceSha": "b" * 40}))
    with pytest.raises(RuntimeError, match="marker"):
        release.inspect_artifact(checkout, REGISTRY["customers"]["oceanicvibes"], SHA)


def test_shared_core_version_must_match_release_registry(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / "node_modules/@weareheadless/helloada-payload-core/package.json").write_text(json.dumps({"version": "0.0.9"}))
    with pytest.raises(RuntimeError, match="core version"):
        release.inspect_artifact(checkout, REGISTRY["customers"]["oceanicvibes"], SHA)


def test_browser_bridge_does_not_substitute_for_service_content_gateway(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    del routes["/api/content/route"]
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="service content"):
        release.inspect_artifact(checkout, REGISTRY["customers"]["oceanicvibes"], SHA)


def test_obsolete_route_in_built_manifest_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    routes["/api/atelier/ada/route"] = "old.js"
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="obsolete"):
        release.inspect_artifact(checkout, REGISTRY["customers"]["oceanicvibes"], SHA)


def promoted_receipt(tmp_path):
    customer = REGISTRY["customers"]["oceanicvibes"]
    archive = tmp_path / "open-next.tar.gz"
    archive.write_bytes(b"immutable-artifact")
    result = {"tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
              "worker": customer["worker"], "repository": customer["repository"],
              "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
              "contentContract": customer["contentContract"],
              "status": "failed", "stage": "verify-connection", "error": "connection failed",
              "deployment": {"id": "deployment-1"}, "uploadedVersion": "version-1",
              "archiveSha256": release.hashlib.sha256(archive.read_bytes()).hexdigest()}
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    return result, customer


def test_read_only_continuation_preserves_prior_failure(tmp_path):
    _, customer = promoted_receipt(tmp_path)
    result = release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer)
    assert result["status"] == "running" and "error" not in result
    assert result["verificationHistory"][-1]["error"] == "connection failed"


@pytest.mark.parametrize("changed", ["identity", "unpromoted", "artifact"])
def test_read_only_continuation_rejects_unproven_release(tmp_path, changed):
    result, customer = promoted_receipt(tmp_path)
    if changed == "identity":
        result["sourceSha"] = "b" * 40
    elif changed == "unpromoted":
        result["stage"] = "upload"
    else:
        (tmp_path / "open-next.tar.gz").write_bytes(b"changed")
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    with pytest.raises(ValueError):
        release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer)


def test_edge_convergence_repeats_identical_checks_without_deploying(monkeypatch):
    result = {"tenant": "oceanicvibes", "sourceSha": SHA, "uploadedVersion": "version-1"}
    customer = REGISTRY["customers"]["oceanicvibes"]
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: {"ok": True})
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    commands = []

    def run(command, *args):
        commands.append(command)
        if len(commands) == 1:
            raise RuntimeError("connection gate failed")

    monkeypatch.setattr(release, "run", run)
    release.verify_live(result, customer, REGISTRY, {}, {}, lambda name: result.update(stage=name))
    assert commands[0] == commands[1] and len(commands) == 2
    assert commands[0][1].endswith("check-helloada-connections.py")
    assert result["connectionVerifiedAt"] and len(result["gateAttempts"]) == 1


def test_read_only_gate_rejects_a_different_production_version(monkeypatch):
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "other-version"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: pytest.fail("must reject before health"))
    with pytest.raises(RuntimeError, match="exact uploaded"):
        release.verify_live({"uploadedVersion": "version-1"}, {}, {}, {}, {}, lambda _: None)


def test_failed_connection_gate_is_bounded_and_remains_failed(monkeypatch):
    result = {"tenant": "oceanicvibes", "sourceSha": SHA, "uploadedVersion": "version-1"}
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: {"ok": True})
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    monkeypatch.setattr(release, "run", lambda *args: (_ for _ in ()).throw(RuntimeError("gate failed")))
    with pytest.raises(RuntimeError, match="gate failed"):
        release.verify_live(result, REGISTRY["customers"]["oceanicvibes"], REGISTRY,
                            {}, {}, lambda name: result.update(stage=name))
    assert len(result["gateAttempts"]) == 12 and "connectionVerifiedAt" not in result
