from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dispatch_payload_releases", ROOT / "scripts/dispatch-payload-releases.py"
)
dispatcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatcher)
API_SPEC = importlib.util.spec_from_file_location(
    "deploy_site_agent_api_template_bundle_test", ROOT / "scripts/deploy-site-agent-api.py"
)
api_deploy = importlib.util.module_from_spec(API_SPEC)
API_SPEC.loader.exec_module(api_deploy)


def test_api_health_check_uses_extended_window_and_exact_contract(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, _size): return b'{"ok": true}'
    monkeypatch.setattr(api_deploy.urllib.request, "urlopen", lambda *_a, **_k: Response())
    assert api_deploy._health_check("http://health") == 1
    assert api_deploy._health_check.__defaults__ == (180,)


def test_api_health_failure_log_capture_is_best_effort_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(api_deploy.urllib.request, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(api_deploy.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="did not pass"):
        api_deploy._health_check("http://health", attempts=2)
    monkeypatch.setattr(api_deploy.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    assert api_deploy._capture_failed_unit_log(tmp_path / "failed-unit.log") is None


def test_api_deploy_failure_receipt_has_health_diagnostics(tmp_path, monkeypatch):
    source = tmp_path / "snapshot"
    (source / "src/site_agent").mkdir(parents=True)
    (source / "deploy").mkdir()
    (source / "pyproject.toml").write_text("[project]\n")
    (source / "src/site_agent/__init__.py").write_text("")
    (source / ".site-agent-source-sha").write_text("a" * 40)
    (source / "deploy/site-agent-api.service").write_text("[Service]\n")
    (source / "deploy/api-runtime.json").write_text(json.dumps({"schema": 1, "requiredExtras": ["crawlseo", "design-lab", "ga"]}))
    root = tmp_path / "root"
    prior = root / "api/releases/prior"
    prior.mkdir(parents=True)
    (root / "api/current").symlink_to(prior)
    real_is_file, real_read_bytes = Path.is_file, Path.read_bytes
    host = Path("/etc/systemd/system/site-agent-api.service")
    monkeypatch.setattr(Path, "is_file", lambda path: True if path == host else real_is_file(path))
    monkeypatch.setattr(Path, "read_bytes", lambda path: b"[Service]\n" if path == host else real_read_bytes(path))
    monkeypatch.setattr(api_deploy, "_runtime_config_preflight", lambda *_a: None)
    monkeypatch.setattr(api_deploy, "_verify_wheel_runtime_dependencies", lambda *_a, **_k: None)
    monkeypatch.setattr(api_deploy, "_verify_payload_template_bundle", lambda *_a: None)
    def run(command, **kwargs):
        if command[:2] == ["systemd-analyze", "verify"]: return subprocess.CompletedProcess(command, 0, "", "")
        if "wheel" in command:
            Path(command[command.index("--wheel-dir") + 1], "site_agent-1.whl").write_bytes(b"wheel")
        elif "install" in command:
            Path(command[command.index("--target") + 1], "site_agent").mkdir(parents=True)
        elif "-c" in command:
            target = Path(kwargs["env"]["PYTHONPATH"])
            return subprocess.CompletedProcess(command, 0, json.dumps({"path": str(target / "site_agent/__init__.py"), "version": "1"}), "")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(api_deploy, "_run", run)
    monkeypatch.setattr(api_deploy, "_restart_api", lambda: None)
    def unhealthy(_url): raise RuntimeError("API /healthz did not pass after restart")
    monkeypatch.setattr(api_deploy, "_health_check", unhealthy)
    monkeypatch.setattr(api_deploy, "_capture_failed_unit_log", lambda path: str(path))
    with pytest.raises(RuntimeError, match="did not pass"):
        api_deploy.deploy(source, "a" * 40, "candidate", root, "/venv/python", "http://health")
    receipt = json.loads((root / "runs/api/candidate/receipt.json").read_text())
    assert receipt["healthCheck"]["attempts"] == 180
    assert receipt["healthCheck"]["secondsWaited"] >= 0
    assert receipt["failedUnitLogPath"].endswith("failed-unit.log")


def test_interrupted_api_rollback_records_failed_health_and_keeps_previous_selected(tmp_path, monkeypatch):
    releases = tmp_path / "api/releases"
    previous = releases / "previous"
    previous.mkdir(parents=True)
    current = tmp_path / "api/current"
    receipt_path = tmp_path / "receipt.json"
    receipt = {"stage": "activated", "previousRelease": "previous"}
    monkeypatch.setattr(api_deploy, "_restart_api", lambda: None)
    monkeypatch.setattr(api_deploy, "_health_check", lambda *_args: (_ for _ in ()).throw(RuntimeError("unhealthy")))

    with pytest.raises(RuntimeError, match="health check failed"):
        api_deploy._recover_interrupted(receipt_path, receipt, current, releases, "http://health")

    assert current.resolve() == previous.resolve()
    persisted = json.loads(receipt_path.read_text())
    assert persisted["status"] == "failed"
    assert persisted["stage"] == "recovery-rollback-failed"
    assert persisted["rollbackRelease"] == "previous"
    assert persisted["rollbackHealth"] is False


@pytest.mark.parametrize("rollback_healthy", [True, False])
def test_api_deploy_rolls_back_candidate_health_failure(tmp_path, monkeypatch, rollback_healthy):
    source = tmp_path / "snapshot"
    (source / "src/site_agent").mkdir(parents=True)
    (source / "deploy").mkdir()
    (source / "pyproject.toml").write_text("[project]\n")
    (source / "src/site_agent/__init__.py").write_text("")
    (source / ".site-agent-source-sha").write_text("a" * 40)
    (source / "deploy/site-agent-api.service").write_text("[Service]\n")
    (source / "deploy/api-runtime.json").write_text(
        json.dumps({"schema": 1, "requiredExtras": ["crawlseo", "design-lab", "ga"]})
    )
    root = tmp_path / "payload-releases"
    previous = root / "api/releases/prior"
    previous.mkdir(parents=True)
    current = root / "api/current"
    current.symlink_to(previous)

    calls = []
    selected_during_health = []
    real_is_file, real_read_bytes = Path.is_file, Path.read_bytes
    host_unit = Path("/etc/systemd/system/site-agent-api.service")

    def host_contract_is_file(path):
        if path == host_unit:
            return True
        return real_is_file(path)

    def host_contract_read_bytes(path):
        if path == host_unit:
            return b"[Service]\n"
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "is_file", host_contract_is_file)
    monkeypatch.setattr(Path, "read_bytes", host_contract_read_bytes)
    monkeypatch.setattr(api_deploy, "_runtime_config_preflight", lambda *_args: None)
    monkeypatch.setattr(api_deploy, "_verify_wheel_runtime_dependencies", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_deploy, "_verify_payload_template_bundle", lambda *_args: None)

    def fake_run(command, *, cwd=None, env=None, **_kwargs):
        calls.append(command)
        if command[:2] == ["systemd-analyze", "verify"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["/venv/python", "-m", "pytest"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == ["/venv/python", "-m", "pip", "wheel"]:
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            (wheel_dir / "site_agent-1.0-py3-none-any.whl").write_bytes(b"fixture wheel")
        elif command[:4] == ["/venv/python", "-m", "pip", "install"]:
            target = Path(command[command.index("--target") + 1])
            (target / "site_agent").mkdir(parents=True)
            (target / "site_agent/__init__.py").write_text("")
        elif command[:2] == ["/venv/python", "-c"]:
            target = Path(env["PYTHONPATH"])
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "path": str(target / "site_agent/__init__.py"), "version": "1.0",
            }), "")
        else:
            raise AssertionError(f"unexpected external command: {command!r}")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(api_deploy, "_run", fake_run)
    monkeypatch.setattr(api_deploy, "_restart_api", lambda: calls.append(["restart-broker"]))

    def health(_url):
        selected = current.resolve()
        selected_during_health.append(selected.name)
        if selected.name != "prior" or not rollback_healthy:
            raise RuntimeError("unhealthy")

    monkeypatch.setattr(api_deploy, "_health_check", health)
    with pytest.raises(RuntimeError, match="unhealthy"):
        api_deploy.deploy(source, "a" * 40, "candidate", root, "/venv/python", "http://health")

    receipt = json.loads((root / "runs/api/candidate/receipt.json").read_text())
    assert current.resolve() == previous.resolve()
    assert receipt["rollbackRelease"] == "prior"
    assert receipt["rollbackHealth"] is rollback_healthy
    assert receipt["status"] == ("rolled-back" if rollback_healthy else "failed")
    assert selected_during_health == ["candidate", "prior"]
    assert calls.count(["restart-broker"]) == 2
    assert all(command[0] in ("/venv/python", "systemd-analyze") or command == ["restart-broker"]
               for command in calls)
    assert not any("/SOCIAL/site-agent/.venv" in str(command) for command in calls)


def test_api_deploy_smoke_failure_never_promotes_or_restarts(tmp_path, monkeypatch):
    source = tmp_path / "snapshot"
    (source / "src/site_agent").mkdir(parents=True)
    (source / "deploy").mkdir()
    (source / "pyproject.toml").write_text("[project]\n")
    (source / "src/site_agent/__init__.py").write_text("")
    (source / ".site-agent-source-sha").write_text("a" * 40)
    (source / "deploy/site-agent-api.service").write_text("[Service]\n")
    (source / "deploy/api-runtime.json").write_text(
        json.dumps({"schema": 1, "requiredExtras": ["crawlseo", "design-lab", "ga"]})
    )
    root = tmp_path / "payload-releases"
    previous = root / "api/releases/prior"
    previous.mkdir(parents=True)
    current = root / "api/current"
    current.symlink_to(previous)
    real_is_file, real_read_bytes = Path.is_file, Path.read_bytes
    unit = Path("/etc/systemd/system/site-agent-api.service")
    monkeypatch.setattr(Path, "is_file", lambda p: True if p == unit else real_is_file(p))
    monkeypatch.setattr(Path, "read_bytes", lambda p: b"[Service]\n" if p == unit else real_read_bytes(p))
    monkeypatch.setattr(api_deploy, "_runtime_config_preflight", lambda *_args: None)
    monkeypatch.setattr(api_deploy, "_verify_wheel_runtime_dependencies", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_deploy, "_verify_payload_template_bundle", lambda *_args: None)
    calls = []

    def fail_smoke(command, **_kwargs):
        calls.append(command)
        if command[:2] == ["/venv/python", "-c"] and "from site_agent.hands.crawlseo" in command[2]:
            raise RuntimeError("smoke import failed")
        if command[0] == "systemd-analyze":
            return subprocess.CompletedProcess(command, 0, "", "")
        if "pytest" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if "wheel" in command:
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            (wheel_dir / "site_agent-1.0-py3-none-any.whl").write_bytes(b"fixture wheel")
        elif "install" in command:
            target = Path(command[command.index("--target") + 1])
            (target / "site_agent").mkdir(parents=True)
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(api_deploy, "_run", fail_smoke)
    monkeypatch.setattr(api_deploy, "_restart_api", lambda: pytest.fail("candidate restart occurred"))
    with pytest.raises(RuntimeError, match="smoke import failed"):
        api_deploy.deploy(source, "a" * 40, "candidate-smoke-failure", root,
                          "/venv/python", "http://health")
    assert current.resolve() == previous.resolve()
    assert not (root / "api/releases/candidate-smoke-failure").exists()
    assert any(command[:2] == ["/venv/python", "-c"] for command in calls)
    assert all(command[0] in ("/venv/python", "systemd-analyze") for command in calls)
    assert all("/SOCIAL/site-agent/.venv" not in str(command) for command in calls)


def test_api_release_requires_the_complete_payload_template_bundle(tmp_path):
    template = tmp_path / "site_agent/templates/next-payload"
    template.mkdir(parents=True)
    for name in ("template-manifest.json", "helloada-content-contract.json", "wrangler.jsonc"):
        (template / name).write_text("{}\n", encoding="utf-8")
    (template / ".gitignore").write_text("node_modules/\n*.tsbuildinfo\n", encoding="utf-8")

    api_deploy._verify_payload_template_bundle(tmp_path)

    (template / ".gitignore").unlink()
    with pytest.raises(RuntimeError, match="missing canonical Payload template files"):
        api_deploy._verify_payload_template_bundle(tmp_path)


def test_dispatcher_resolves_only_the_configured_github_ssh_identity(tmp_path):
    identity = tmp_path / "github_ed25519"
    identity.write_text("private-key-placeholder")
    profile = tmp_path / "host-credentials.yaml"
    profile.write_text(f"credentials:\n  github:\n    ssh_key_path: {identity}\n")

    command = dispatcher.github_ssh_command(profile)

    assert str(identity) in command
    assert "IdentitiesOnly=yes" in command
    assert "TOKEN" not in command


def test_dispatcher_rejects_missing_or_invalid_host_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatcher, "DEFAULT_GITHUB_KEY", tmp_path / "missing-key")
    profile = tmp_path / "host-credentials.yaml"
    profile.write_text("credentials:\n  github: {}\n")
    with pytest.raises(RuntimeError, match="identity is unavailable"):
        dispatcher.github_ssh_command(profile)

    profile.write_text("credentials:\n  github: [\n")
    with pytest.raises(RuntimeError, match="profile is unavailable or invalid"):
        dispatcher.github_ssh_command(profile)


def test_dispatcher_archives_only_the_requested_immutable_commit(tmp_path):
    repository = tmp_path / "source"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    (repository / "scripts").mkdir()
    (repository / "scripts/reconcile-payload-releases.py").write_text("print('first')\n")
    (repository / "copy.txt").write_text("first\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "first"], check=True)
    first_sha = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    bare = tmp_path / "control.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repository), str(bare)], check=True)
    stale = tmp_path / "releases" / "dispatch-control" / ("b" * 40)
    stale.mkdir(parents=True)
    (stale / "old-checkout.txt").write_text("superseded")

    snapshot = dispatcher.snapshot_main(bare, tmp_path / "releases", first_sha, {})
    assert not stale.exists()
    assert (snapshot / dispatcher.SOURCE_MARKER).read_text().strip() == first_sha
    assert (snapshot / "copy.txt").read_text() == "first\n"
    assert dispatcher.snapshot_main(bare, tmp_path / "releases", first_sha, {}) == snapshot

    (snapshot / dispatcher.SOURCE_MARKER).write_text("b" * 40 + "\n")
    with pytest.raises(RuntimeError, match="snapshot identity mismatch"):
        dispatcher.snapshot_main(bare, tmp_path / "releases", first_sha, {})


def test_installed_dispatcher_manifest_binds_script_hash_and_source(tmp_path):
    script = tmp_path / "dispatch-payload-releases.py"
    script.write_text("trusted bootstrap\n")
    manifest = {
        "schema": 1,
        "sourceSha": "a" * 40,
        "dispatcherSha256": hashlib.sha256(script.read_bytes()).hexdigest(),
    }
    script.with_name(dispatcher.MANIFEST_NAME).write_text(json.dumps(manifest))

    assert dispatcher.installed_identity(script) == manifest
    script.write_text("modified bootstrap\n")
    with pytest.raises(RuntimeError, match="does not match"):
        dispatcher.installed_identity(script)


def test_dispatcher_activates_versioned_slot_atomically(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    (snapshot / "deploy").mkdir()
    (snapshot / "scripts/dispatch-payload-releases.py").write_text("bootstrap v1\n")
    (snapshot / "deploy/helloada-release.service").write_text(
        "[Service]\n"
        "WorkingDirectory=/SOCIAL/payload-releases\n"
        "ExecStart=/SOCIAL/site-agent/.venv/bin/python /SOCIAL/payload-releases/bin/current/dispatch-payload-releases.py\n"
        "KillMode=control-group\nNoNewPrivileges=true\n"
    )

    first = dispatcher.ensure_dispatcher_slot(snapshot, "a" * 40, tmp_path / "bin")
    current = tmp_path / "bin/current"
    assert current.is_symlink()
    assert current.resolve() == first.resolve()
    manifest = dispatcher.installed_identity(current / "dispatch-payload-releases.py")
    assert manifest["sourceSha"] == "a" * 40
    assert manifest["dispatcherSha256"] == hashlib.sha256(b"bootstrap v1\n").hexdigest()

    (snapshot / "scripts/dispatch-payload-releases.py").write_text("bootstrap v2\n")
    second = dispatcher.ensure_dispatcher_slot(snapshot, "b" * 40, tmp_path / "bin")
    assert second != first
    assert current.resolve() == second.resolve()
    assert (first / "dispatch-payload-releases.py").read_text() == "bootstrap v1\n"


def test_release_service_uses_only_the_stable_immutable_dispatcher():
    unit = (ROOT / "deploy/helloada-release.service").read_text()
    assert f"ExecStart={dispatcher.DISPATCHER_ENTRYPOINT}" in unit
    assert "/SOCIAL/site-agent/scripts/reconcile-payload-releases.py" not in unit
    assert "NoNewPrivileges=true" in unit


def test_dispatcher_requires_the_bootstrapped_service_unit_to_match_main(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "deploy").mkdir(parents=True)
    unit = (
        "[Service]\n"
        f"WorkingDirectory=/SOCIAL/payload-releases\nExecStart={dispatcher.DISPATCHER_ENTRYPOINT}\n"
        "KillMode=control-group\nNoNewPrivileges=true\n"
    )
    (snapshot / "deploy/helloada-release.service").write_text(unit)
    installed = tmp_path / "helloada-release.service"
    installed.write_text(unit)
    dispatcher.verify_host_service_unit(snapshot, installed)
    installed.write_text(unit.replace("NoNewPrivileges=true", "NoNewPrivileges=false"))
    with pytest.raises(RuntimeError, match="reviewed host bootstrap"):
        dispatcher.verify_host_service_unit(snapshot, installed)


def test_api_restart_broker_accepts_only_fixed_restart_request():
    import importlib.util
    import io
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "helloada_api_restart_helper", ROOT / "scripts/helloada-api-restart-helper.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    output = io.BytesIO()
    assert helper.serve(io.BytesIO(b"restart\n"), output, run_command=fake_run) == 0
    assert output.getvalue() == b"restarted\n"
    assert calls[0][0] == ["/usr/bin/systemctl", "restart", "site-agent-api.service"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 120


def test_api_restart_broker_rejects_arbitrary_commands_without_execution():
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location(
        "helloada_api_restart_helper_reject", ROOT / "scripts/helloada-api-restart-helper.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("untrusted request reached command runner")

    output = io.BytesIO()
    assert helper.serve(io.BytesIO(b"restart site-agent-api.service\n"), output,
                        run_command=forbidden) == 2
    assert output.getvalue() == b"invalid\n"
    assert called is False


def test_api_restart_host_policy_is_fixed_and_release_scripts_do_not_use_sudo():
    socket_unit = (ROOT / "deploy/helloada-api-restart.socket").read_text()
    service_unit = (ROOT / "deploy/helloada-api-restart@.service").read_text()
    helper = (ROOT / "scripts/helloada-api-restart-helper.py").read_text()
    assert "Accept=yes" in socket_unit
    assert "\nService=" not in socket_unit
    assert "SocketUser=admin" in socket_unit
    assert "SocketMode=0600" in socket_unit
    assert "User=root" in service_unit and "StandardInput=socket" in service_unit
    assert '"/usr/bin/systemctl", "restart", "site-agent-api.service"' in helper
    assert "shell=True" not in helper
    assert "NoNewPrivileges=true" in (ROOT / "deploy/helloada-release.service").read_text()
    assert "sudo" not in (ROOT / "scripts/dispatch-payload-releases.py").read_text()
    assert "sudo" not in (ROOT / "scripts/deploy-site-agent-api.py").read_text()


def test_api_release_client_uses_newline_framed_broker_protocol(tmp_path):
    import importlib.util
    import socket
    import threading

    spec = importlib.util.spec_from_file_location(
        "deploy_site_agent_api_broker_test", ROOT / "scripts/deploy-site-agent-api.py"
    )
    api_deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_deploy)

    import tempfile

    # AF_UNIX paths are capped at 108 bytes on Linux; a normal isolated
    # worktree can already exceed that before adding the socket filename.
    with tempfile.TemporaryDirectory(prefix=".s-") as broker_dir:
        broker_path = str(Path(broker_dir) / "restart.sock")
        received = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(broker_path)
            listener.listen(1)

            def serve_one_request():
                connection, _address = listener.accept()
                with connection:
                    request = bytearray()
                    while chunk := connection.recv(32):
                        request.extend(chunk)
                    received.append(bytes(request))
                    connection.sendall(b"restarted\n")

            worker = threading.Thread(target=serve_one_request, daemon=True)
            worker.start()
            api_deploy._restart_api(broker_path)
            worker.join(timeout=2)

        assert not worker.is_alive()
        assert received == [b"restart\n"]
 
def test_host_bootstrap_restarts_updated_socket_and_timer_units():
    bootstrap = (ROOT / "scripts/bootstrap-release-pipeline.py").read_text()
    assert "scripts/retire-legacy-tenant-schedulers.py" in bootstrap
    assert '"systemctl", "restart", "site-agent-api.service"' in bootstrap
    assert '"systemctl", "restart", "helloada-api-restart.socket"' in bootstrap
    assert '"systemctl", "restart", "helloada-release.timer"' in bootstrap
