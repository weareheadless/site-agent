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

    snapshot = dispatcher.snapshot_main(bare, tmp_path / "releases", first_sha, {})
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


def test_api_restart_policy_is_scoped_and_release_scripts_do_not_use_sudo():
    policy = (ROOT / "deploy/helloada-api-restart.rules").read_text()
    assert 'action.id === "org.freedesktop.systemd1.manage-units"' in policy
    assert 'subject.user === "admin"' in policy
    assert 'action.lookup("unit") === "site-agent-api.service"' in policy
    assert 'action.lookup("verb") === "restart"' in policy
    assert "sudo" not in (ROOT / "scripts/dispatch-payload-releases.py").read_text()
    assert "sudo" not in (ROOT / "scripts/deploy-site-agent-api.py").read_text()
