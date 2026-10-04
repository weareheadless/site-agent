#!/usr/bin/env python3
"""VPS GitOps queue: fetch trusted main and execute each requested release once."""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from site_agent.credentials import github_ssh_command

API_DEPLOYMENT_MODULE = Path(__file__).with_name("deploy-site-agent-api.py")
API_DEPLOYMENT_SPEC = importlib.util.spec_from_file_location("site_agent_api_deployment", API_DEPLOYMENT_MODULE)
if API_DEPLOYMENT_SPEC is None or API_DEPLOYMENT_SPEC.loader is None:
    raise RuntimeError("API deployment contract is unavailable")
API_DEPLOYMENT = importlib.util.module_from_spec(API_DEPLOYMENT_SPEC)
API_DEPLOYMENT_SPEC.loader.exec_module(API_DEPLOYMENT)
validate_api_queue = API_DEPLOYMENT.validate_api_queue


def mark_interrupted_runs(root: Path) -> None:
    # The caller owns the global lock; no previous service process can still run.
    for receipt in (root / "runs").glob("*/*/receipt.json"):
        result = json.loads(receipt.read_text())
        if result.get("status") != "running":
            continue
        result.update({"status": "interrupted", "error": "systemd job ended before a terminal receipt",
                       "finishedAt": datetime.now(timezone.utc).isoformat()})
        temporary = receipt.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(receipt)


def validate_queue(queue: dict, registry: dict) -> None:
    if queue.get("schema") != 1 or not isinstance(queue.get("releases"), dict):
        raise ValueError("invalid release queue schema")
    for tenant, request in queue["releases"].items():
        if tenant not in registry["customers"] or not isinstance(request, dict):
            raise ValueError("unregistered tenant in release queue")
        permitted = (
            {"id", "sha"},
            {"id", "sha", "approvalId"},
            {"id", "sha", "initializeSchema"},
            {"id", "sha", "schemaMigration"},
        )
        if set(request) not in permitted:
            raise ValueError("release must be an owner approval, a schema initialization, or an exact tenant schema migration")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", request["id"]):
            raise ValueError("unsafe release ID")
        if not re.fullmatch(r"[0-9a-f]{40}", request["sha"]):
            raise ValueError("release queue requires full immutable commit SHAs")
        if "approvalId" in request and (
            isinstance(request["approvalId"], bool)
            or not isinstance(request["approvalId"], int)
            or request["approvalId"] < 1
        ):
            raise ValueError("approval identity must be a positive integer")
        if "initializeSchema" in request:
            initialization = request["initializeSchema"]
            expected_head = registry["customers"][tenant].get("migrationHead")
            if (
                not isinstance(initialization, dict)
                or set(initialization) != {"migrationHead"}
                or not re.fullmatch(r"[0-9a-f]{64}", str(initialization.get("migrationHead") or ""))
                or initialization["migrationHead"] != expected_head
            ):
                raise ValueError("new-tenant schema initialization must match the registered migration chain")
        if "schemaMigration" in request:
            migration = request["schemaMigration"]
            expected_head = registry["customers"][tenant].get("migrationHead")
            if (
                not isinstance(migration, dict)
                or set(migration) != {"fromLedgerIdentity", "targetMigrationHead"}
                or not re.fullmatch(r"[0-9a-f]{64}", str(migration.get("fromLedgerIdentity") or ""))
                or not re.fullmatch(r"[0-9a-f]{64}", str(migration.get("targetMigrationHead") or ""))
                or migration["targetMigrationHead"] != expected_head
                or migration["fromLedgerIdentity"] == migration["targetMigrationHead"]
            ):
                raise ValueError("tenant schema migration must identify one prior ledger and the registered target head")


def snapshot_api_source(mirror: Path, root: Path, source_sha: str) -> Path:
    snapshot = root / "api-sources" / source_sha
    marker = snapshot / ".site-agent-source-sha"
    if snapshot.exists():
        if not marker.is_file() or marker.read_text(encoding="ascii").strip() != source_sha:
            raise RuntimeError("cached API source snapshot identity mismatch")
        return snapshot
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="api-source-", dir=snapshot.parent))
    try:
        with subprocess.Popen(["git", "-C", str(mirror), "archive", source_sha], stdout=subprocess.PIPE) as archive:
            subprocess.run(["tar", "-x", "-C", str(staging)], stdin=archive.stdout, check=True)
            if archive.wait():
                raise RuntimeError("could not snapshot API source commit")
        (staging / ".site-agent-source-sha").write_text(source_sha + "\n", encoding="ascii")
        staging.rename(snapshot)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return snapshot


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
        mark_interrupted_runs(args.root)
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
        api_request = validate_api_queue(document("deploy/desired-api-release.json"))
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
        if api_request:
            ancestry = subprocess.run(
                ["git", "-C", str(mirror), "merge-base", "--is-ancestor",
                 api_request["sha"], "refs/heads/main"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if ancestry.returncode:
                raise ValueError("API source SHA is not an ancestor of official main")
            api_source = snapshot_api_source(mirror, args.root, api_request["sha"])
            api_tool = snapshot / "scripts" / "deploy-site-agent-api.py"
            if not api_tool.is_file():
                raise RuntimeError("control snapshot does not contain the API deployment contract")
            print(f"[queue] API release={api_request['id']} source={api_request['sha']}", flush=True)
            code = subprocess.run(
                [sys.executable, str(api_tool), "--source-dir", str(api_source),
                 "--source-sha", api_request["sha"], "--release-id", api_request["id"],
                 "--root", str(args.root), "--python", sys.executable],
                env={**environment, "HELLOADA_PIPELINE_SHA": sha},
            ).returncode
            failures += int(code != 0)
            if code:
                print("[queue] API release failed; customer releases are held", flush=True)
                return 1
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
                if result["status"] not in ("deployed", "verified"):
                    failures += 1
                continue
            print(f"[queue] release={tenant}/{request['id']} source={request['sha']} pipeline={sha}", flush=True)
            command = [sys.executable, str(snapshot / "scripts/deploy-payload-customer.py"),
                "--tenant", tenant, "--ref", request["sha"], "--release-id", request["id"]]
            if "approvalId" in request:
                command.extend(["--approval-id", str(request["approvalId"])])
            if "initializeSchema" in request:
                command.extend(["--initialize-schema-head", request["initializeSchema"]["migrationHead"]])
            if "schemaMigration" in request:
                command.extend(["--schema-migration-from-ledger-identity",
                                request["schemaMigration"]["fromLedgerIdentity"]])
            code = subprocess.run(command,
                env={**environment, "HELLOADA_PIPELINE_SHA": sha}).returncode
            failures += int(code != 0)
        return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
