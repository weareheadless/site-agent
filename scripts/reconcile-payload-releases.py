#!/usr/bin/env python3
"""VPS GitOps queue: fetch trusted main and execute each requested release once."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from site_agent.credentials import github_ssh_command


def validate_queue(queue: dict, registry: dict) -> None:
    if queue.get("schema") != 1 or not isinstance(queue.get("releases"), dict):
        raise ValueError("invalid release queue schema")
    for tenant, request in queue["releases"].items():
        if tenant not in registry["customers"] or not isinstance(request, dict):
            raise ValueError("unregistered tenant in release queue")
        if set(request) != {"id", "sha"}:
            raise ValueError("each release must contain only id and sha")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", request["id"]):
            raise ValueError("unsafe release ID")
        if not re.fullmatch(r"[0-9a-f]{40}", request["sha"]):
            raise ValueError("release queue requires full immutable commit SHAs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/SOCIAL/payload-releases"))
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / "reconcile.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        profile = {"credentials": {"profile_file": "/SOCIAL/configs/host-credentials.yaml"}}
        ssh_command = github_ssh_command(profile, {})
        if not ssh_command:
            raise RuntimeError("GitHub SSH identity missing")
        environment = {**os.environ, "GIT_SSH_COMMAND": ssh_command}
        mirror = args.root / "control.git"
        remote = "git@github.com:weareheadless/site-agent.git"
        if not mirror.exists():
            subprocess.run(["git", "clone", "--bare", remote, str(mirror)], env=environment, check=True)
        actual = subprocess.check_output(["git", "-C", str(mirror), "remote", "get-url", "origin"], text=True).strip()
        if actual != remote:
            raise RuntimeError("control repository remote mismatch")
        subprocess.run(["git", "-C", str(mirror), "fetch", "origin", "+refs/heads/main:refs/heads/main"], env=environment, check=True)
        sha = subprocess.check_output(["git", "-C", str(mirror), "rev-parse", "refs/heads/main"], text=True).strip()

        def document(path: str) -> dict:
            return json.loads(subprocess.check_output(["git", "-C", str(mirror), "show", f"{sha}:{path}"], text=True))

        registry = document("deploy/payload-customers.json")
        queue = document("deploy/desired-releases.json")
        validate_queue(queue, registry)
        if Path(registry["releaseRoot"]) != args.root:
            raise RuntimeError("release root differs from installed systemd configuration")
        snapshot = args.root / "control" / sha
        if not snapshot.exists():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix="snapshot-", dir=snapshot.parent))
            with subprocess.Popen(["git", "-C", str(mirror), "archive", sha], stdout=subprocess.PIPE) as archive:
                subprocess.run(["tar", "-x", "-C", str(staging)], stdin=archive.stdout, check=True)
                if archive.wait():
                    raise RuntimeError("could not snapshot control commit")
            staging.rename(snapshot)
        failures = 0
        pending = any(not (args.root / "runs" / tenant / request["id"]).exists()
                      for tenant, request in queue["releases"].items())
        if pending:
            subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_payload_release.py"],
                           cwd=snapshot, env={**environment, "PYTHONPATH": str(snapshot / "src")}, check=True)
        for tenant, request in queue["releases"].items():
            directory = args.root / "runs" / tenant / request["id"]
            receipt = directory / "receipt.json"
            if directory.exists():
                if not receipt.exists():
                    print(f"[queue] {tenant}/{request['id']} interrupted before receipt; commit a new release ID", flush=True)
                    failures += 1
                    continue
                result = json.loads(receipt.read_text())
                if result["sourceSha"] != request["sha"]:
                    raise RuntimeError("release ID was reused for a different SHA")
                if result["status"] == "running":
                    result.update({"status": "interrupted", "error": "systemd job ended before a terminal receipt"})
                    temporary = receipt.with_suffix(".tmp")
                    temporary.write_text(json.dumps(result, indent=2) + "\n")
                    temporary.replace(receipt)
                if result["status"] not in ("deployed", "verified"):
                    failures += 1
                continue
            print(f"[queue] release={tenant}/{request['id']} source={request['sha']} pipeline={sha}", flush=True)
            code = subprocess.run([sys.executable, str(snapshot / "scripts/deploy-payload-customer.py"),
                "--tenant", tenant, "--ref", request["sha"], "--release-id", request["id"]],
                env={**environment, "HELLOADA_PIPELINE_SHA": sha}).returncode
            failures += int(code != 0)
        return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
