#!/usr/bin/env python3
"""Install the current official-main release dispatcher on a prepared VPS."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = "git@github.com:weareheadless/site-agent.git"
ROOT = Path("/SOCIAL/payload-releases")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SITE_AGENT_SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SITE_AGENT_SOURCE / "src"))
from site_agent.credentials import github_ssh_command


def run(command: list[str], *, env: dict[str, str], capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def bootstrap(root: Path = ROOT, source_dir: Path | None = None) -> dict[str, str]:
    bootstrap_source = source_dir.resolve() if source_dir else SITE_AGENT_SOURCE.resolve()
    source_sha_hint = ""
    if source_dir:
        if bootstrap_source != SITE_AGENT_SOURCE.resolve():
            raise RuntimeError("bootstrap must execute from the exact supplied source snapshot")
        source_sha_hint = bootstrap_source.name
        if not SHA_RE.fullmatch(source_sha_hint) or bootstrap_source.parent != (root / "control").resolve():
            raise RuntimeError("bootstrap snapshot must be the full-SHA child of the release control root")
    else:
        local_remote = run(["git", "-C", str(bootstrap_source), "remote", "get-url", "origin"],
                           env=os.environ.copy(), capture=True)
        if local_remote != REPOSITORY:
            raise RuntimeError("bootstrap checkout does not use the official site-agent repository")
        branch = run(["git", "-C", str(bootstrap_source), "branch", "--show-current"],
                     env=os.environ.copy(), capture=True)
        if branch != "main":
            raise RuntimeError("bootstrap requires the official main branch")
        if run(["git", "-C", str(bootstrap_source), "status", "--porcelain"],
               env=os.environ.copy(), capture=True):
            raise RuntimeError("bootstrap checkout must be clean")
        source_sha_hint = run(["git", "-C", str(bootstrap_source), "rev-parse", "HEAD"],
                              env=os.environ.copy(), capture=True)

    profile = {"credentials": {"profile_file": "/SOCIAL/configs/host-credentials.yaml"}}
    ssh_command = github_ssh_command(profile, {})
    if not ssh_command:
        raise RuntimeError("configured GitHub SSH identity is unavailable")
    environment = {**os.environ, "GIT_SSH_COMMAND": ssh_command}
    mirror = root / "control.git"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not mirror.exists():
        run(["git", "clone", "--bare", REPOSITORY, str(mirror)], env=environment)
    actual_remote = run(["git", "-C", str(mirror), "remote", "get-url", "origin"], env=environment, capture=True)
    if actual_remote != REPOSITORY:
        raise RuntimeError("release control mirror does not point to the official repository")
    run(["git", "-C", str(mirror), "fetch", "origin", "+refs/heads/main:refs/heads/main"], env=environment)
    source_sha = run(["git", "-C", str(mirror), "rev-parse", "refs/heads/main"], env=environment, capture=True)
    if not SHA_RE.fullmatch(source_sha):
        raise RuntimeError("official main did not resolve to a full commit SHA")
    if source_sha_hint != source_sha:
        raise RuntimeError("bootstrap source must match the exact current official-main SHA")

    snapshot_root = root / "control"
    snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot = snapshot_root / source_sha
    if source_dir:
        if snapshot.resolve() != bootstrap_source:
            raise RuntimeError("bootstrap source is not the selected official-main snapshot")
    elif not snapshot.exists():
        staging = Path(tempfile.mkdtemp(prefix="bootstrap-", dir=snapshot_root))
        try:
            with subprocess.Popen(
                ["git", "-C", str(mirror), "archive", source_sha],
                stdout=subprocess.PIPE,
                env=environment,
            ) as archive:
                subprocess.run(["tar", "-x", "-C", str(staging)], stdin=archive.stdout, check=True)
                if archive.stdout:
                    archive.stdout.close()
                if archive.wait():
                    raise RuntimeError("could not archive the official-main release source")
            staging.rename(snapshot)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    for relative in (
        "scripts/bootstrap-release-pipeline.py",
        "scripts/dispatch-payload-releases.py",
        "scripts/reconcile-payload-releases.py",
        "deploy/site-agent-api.service",
        "deploy/helloada-release.service",
        "deploy/helloada-release.timer",
        "scripts/helloada-api-restart-helper.py",
        "deploy/helloada-api-restart.socket",
        "deploy/helloada-api-restart@.service",
    ):
        committed = subprocess.check_output(
            ["git", "-C", str(mirror), "show", f"{source_sha}:{relative}"]
        )
        if committed != (snapshot / relative).read_bytes():
            raise RuntimeError("release source snapshot does not match official main")

    dispatcher_path = snapshot / "scripts/dispatch-payload-releases.py"
    spec = importlib.util.spec_from_file_location("release_dispatcher", dispatcher_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("official-main release dispatcher cannot be loaded")
    dispatcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatcher)
    dispatcher.ensure_dispatcher_slot(snapshot, source_sha, root / "bin")

    system_unit_dir = Path("/etc/systemd/system")
    unit_names = (
        "site-agent-api.service",
        "helloada-release.service",
        "helloada-release.timer",
        "helloada-api-restart.socket",
        "helloada-api-restart@.service",
    )
    helper = snapshot / "scripts/helloada-api-restart-helper.py"
    if not helper.is_file():
        raise RuntimeError("official-main snapshot is missing the API restart broker")
    run(["sudo", "-n", "install", "-o", "root", "-g", "root", "-m", "0755",
         str(helper), "/usr/local/libexec/helloada-api-restart-helper"], env=environment)
    for name in unit_names:
        unit = snapshot / "deploy" / name
        run(["systemd-analyze", "verify", str(unit)], env=environment)
        run(["sudo", "-n", "install", "-m", "0644", str(unit),
             str(system_unit_dir / name)], env=environment)
    # Remove only the obsolete file installed by the previous reviewed bootstrap.
    run(["sudo", "-n", "rm", "-f",
         "/etc/polkit-1/rules.d/60-helloada-api-restart.rules"], env=environment)
    run(["sudo", "-n", "systemctl", "daemon-reload"], env=environment)
    run(["sudo", "-n", "systemctl", "enable", "--now",
         "helloada-api-restart.socket"], env=environment)
    run(["sudo", "-n", "systemctl", "enable", "--now",
         "helloada-release.timer"], env=environment)
    return {"sourceSha": source_sha, "mirror": str(mirror), "snapshot": str(snapshot)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-dir", type=Path,
                        help="exact official-main snapshot; for recovery on an initialized host")
    args = parser.parse_args()
    try:
        result = bootstrap(args.root, args.source_dir)
    except Exception as exc:  # noqa: BLE001 - keep credential and host details out of output
        print(f"release pipeline bootstrap failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
