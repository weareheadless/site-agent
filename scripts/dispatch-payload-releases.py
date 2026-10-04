#!/usr/bin/env python3
"""Run the release controller from an immutable snapshot of official main."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


REMOTE = "git@github.com:weareheadless/site-agent.git"
PROFILE_FILE = Path("/SOCIAL/configs/host-credentials.yaml")
DEFAULT_GITHUB_KEY = Path("/home/admin/.ssh/github_weareheadless_ed25519")
MANIFEST_NAME = "dispatcher.json"
SOURCE_MARKER = ".site-agent-control-sha"
SHA_RE = re.compile(r"[0-9a-f]{40}")
DISPATCHER_ENTRYPOINT = "/SOCIAL/site-agent/.venv/bin/python /SOCIAL/payload-releases/bin/current/dispatch-payload-releases.py"


def validate_service_contract(unit_path: Path) -> None:
    lines = [line.strip() for line in unit_path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    expected = {
        "WorkingDirectory": "/SOCIAL/payload-releases",
        "ExecStart": DISPATCHER_ENTRYPOINT,
        "NoNewPrivileges": "true",
        "KillMode": "control-group",
    }
    for key, value in expected.items():
        found = [line.partition("=")[2] for line in lines if line.partition("=")[0] == key]
        if found != [value]:
            raise RuntimeError(f"official release service unit violates {key} contract")


def github_ssh_command(profile_path: Path = PROFILE_FILE) -> str:
    """Resolve only the host GitHub SSH identity; never load API tokens."""
    try:
        document = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeError("host credential profile is unavailable or invalid") from exc
    if not isinstance(document, dict):
        raise RuntimeError("host credential profile must be a mapping")
    profiles = document.get("credentials", document)
    if not isinstance(profiles, dict):
        raise RuntimeError("host credential profiles must be a mapping")
    profile = profiles.get("github", {})
    if not isinstance(profile, dict):
        raise RuntimeError("GitHub credential profile must be a mapping")

    configured = str(profile.get("ssh_command") or "").strip()
    if configured:
        if "\n" in configured or "\r" in configured or len(configured) > 500:
            raise RuntimeError("GitHub SSH command is invalid")
        return configured

    key_path = Path(str(profile.get("ssh_key_path") or profile.get("key_path") or DEFAULT_GITHUB_KEY)).expanduser().resolve()
    if not key_path.is_file():
        raise RuntimeError("configured GitHub SSH identity is unavailable")
    return f"ssh -i {shlex.quote(str(key_path))} -o IdentitiesOnly=yes"


def _run(command: list[str], *, env: dict[str, str], capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def snapshot_main(mirror: Path, root: Path, source_sha: str, env: dict[str, str]) -> Path:
    if not SHA_RE.fullmatch(source_sha):
        raise ValueError("official main did not resolve to a full commit SHA")
    snapshots = root / "dispatch-control"
    destination = snapshots / source_sha
    marker = destination / SOURCE_MARKER
    if destination.exists():
        if (destination.is_symlink() or marker.is_symlink() or not marker.is_file()
                or marker.read_text(encoding="ascii").strip() != source_sha):
            raise RuntimeError("cached dispatcher snapshot identity mismatch")
        return destination

    snapshots.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix="dispatch-", dir=snapshots))
    try:
        with subprocess.Popen(
            ["git", "-C", str(mirror), "archive", source_sha],
            stdout=subprocess.PIPE,
            env=env,
        ) as archive:
            subprocess.run(["tar", "-x", "-C", str(staging)], stdin=archive.stdout, check=True)
            if archive.stdout:
                archive.stdout.close()
            if archive.wait():
                raise RuntimeError("could not archive the official-main dispatcher snapshot")
        if not (staging / "scripts/reconcile-payload-releases.py").is_file():
            raise RuntimeError("official-main snapshot has no release controller")
        (staging / SOURCE_MARKER).write_text(source_sha + "\n", encoding="ascii")
        os.chmod(staging, 0o700)
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def installed_identity(script_path: Path) -> dict[str, Any]:
    manifest_path = script_path.with_name(MANIFEST_NAME)
    if script_path.is_symlink() or manifest_path.is_symlink():
        raise RuntimeError("release dispatcher slot cannot contain symbolic links")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("release dispatcher installation manifest is unavailable") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("release dispatcher installation manifest is invalid")
    expected = manifest.get("dispatcherSha256")
    digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
    if manifest.get("schema") != 1 or not isinstance(expected, str) or digest != expected:
        raise RuntimeError("installed release dispatcher does not match its installation manifest")
    if not SHA_RE.fullmatch(str(manifest.get("sourceSha") or "")):
        raise RuntimeError("release dispatcher manifest has no immutable source identity")
    return manifest


def ensure_dispatcher_slot(snapshot: Path, source_sha: str, bin_root: Path) -> Path:
    if not SHA_RE.fullmatch(source_sha):
        raise ValueError("dispatcher slot requires a full immutable commit SHA")
    candidate_script = snapshot / "scripts/dispatch-payload-releases.py"
    candidate_unit = snapshot / "deploy/helloada-release.service"
    if not candidate_script.is_file() or not candidate_unit.is_file():
        raise RuntimeError("official-main snapshot is missing the release dispatcher contract")
    validate_service_contract(candidate_unit)
    script_hash = hashlib.sha256(candidate_script.read_bytes()).hexdigest()
    unit_hash = hashlib.sha256(candidate_unit.read_bytes()).hexdigest()
    bin_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    releases = bin_root / "releases"
    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = releases / source_sha
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise RuntimeError("immutable dispatcher release slot is not a directory")
        manifest = installed_identity(destination / "dispatch-payload-releases.py")
        if (manifest.get("sourceSha") != source_sha
                or manifest.get("dispatcherSha256") != script_hash
                or manifest.get("unitSha256") != unit_hash):
            raise RuntimeError("immutable dispatcher release slot does not match official main")
    else:
        staging = Path(tempfile.mkdtemp(prefix="dispatcher-", dir=releases))
        try:
            shutil.copyfile(candidate_script, staging / "dispatch-payload-releases.py")
            os.chmod(staging / "dispatch-payload-releases.py", 0o750)
            manifest = {
                "schema": 1,
                "sourceSha": source_sha,
                "dispatcherSha256": script_hash,
                "unitSha256": unit_hash,
            }
            (staging / MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.chmod(staging / MANIFEST_NAME, 0o600)
            os.chmod(staging, 0o700)
            staging.rename(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    current = bin_root / "current"
    if current.exists() and not current.is_symlink():
        raise RuntimeError("dispatcher current path is not a managed symlink")
    if not current.is_symlink() or current.resolve() != destination.resolve():
        temporary_link = bin_root / f".current.{os.getpid()}"
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(Path("releases") / source_sha)
        os.replace(temporary_link, current)
    return destination


def verify_host_service_unit(
    snapshot: Path,
    installed_path: Path = Path("/etc/systemd/system/helloada-release.service"),
) -> None:
    candidate_unit = snapshot / "deploy/helloada-release.service"
    if not candidate_unit.is_file():
        raise RuntimeError("official-main snapshot is missing the release service unit")
    validate_service_contract(candidate_unit)
    if not installed_path.is_file() or installed_path.read_bytes() != candidate_unit.read_bytes():
        raise RuntimeError("host release service unit differs from official main; run the reviewed host bootstrap")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/SOCIAL/payload-releases"))
    args = parser.parse_args()

    script_path = Path(__file__)
    installed = installed_identity(script_path)
    args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    environment = {**os.environ, "GIT_SSH_COMMAND": github_ssh_command()}
    mirror = args.root / "control.git"
    if not mirror.exists():
        _run(["git", "clone", "--bare", REMOTE, str(mirror)], env=environment)
    actual_remote = _run(
        ["git", "-C", str(mirror), "remote", "get-url", "origin"],
        env=environment,
        capture=True,
    )
    if actual_remote != REMOTE:
        raise RuntimeError("release control mirror does not point to the official repository")
    _run(["git", "-C", str(mirror), "fetch", "origin", "+refs/heads/main:refs/heads/main"], env=environment)
    source_sha = _run(["git", "-C", str(mirror), "rev-parse", "refs/heads/main"], env=environment, capture=True)
    ancestry = subprocess.run(
        ["git", "-C", str(mirror), "merge-base", "--is-ancestor", installed["sourceSha"], "refs/heads/main"],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ancestry.returncode:
        raise RuntimeError("installed dispatcher source is not an ancestor of official main")
    snapshot = snapshot_main(mirror, args.root, source_sha, environment)
    verify_host_service_unit(snapshot)
    target_script = snapshot / "scripts/dispatch-payload-releases.py"
    target_unit = snapshot / "deploy/helloada-release.service"
    if (hashlib.sha256(target_script.read_bytes()).hexdigest() != installed.get("dispatcherSha256")
            or hashlib.sha256(target_unit.read_bytes()).hexdigest() != installed.get("unitSha256")):
        ensure_dispatcher_slot(snapshot, source_sha, args.root / "bin")
        print(f"[dispatcher] activated immutable runtime from official main {source_sha}", flush=True)

    controller = snapshot / "scripts/reconcile-payload-releases.py"
    return subprocess.run(
        [sys.executable, str(controller), "--root", str(args.root)],
        env=environment,
        check=False,
    ).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - do not disclose protected host configuration
        print(f"[dispatcher] failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
