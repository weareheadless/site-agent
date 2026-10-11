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

HELLOADA_APP_DEPLOYMENT_MODULE = Path(__file__).with_name("deploy-helloada-app.py")
HELLOADA_APP_DEPLOYMENT_SPEC = importlib.util.spec_from_file_location(
    "helloada_app_deployment", HELLOADA_APP_DEPLOYMENT_MODULE,
)
if HELLOADA_APP_DEPLOYMENT_SPEC is None or HELLOADA_APP_DEPLOYMENT_SPEC.loader is None:
    raise RuntimeError("HelloAda app deployment contract is unavailable")
HELLOADA_APP_DEPLOYMENT = importlib.util.module_from_spec(HELLOADA_APP_DEPLOYMENT_SPEC)
HELLOADA_APP_DEPLOYMENT_SPEC.loader.exec_module(HELLOADA_APP_DEPLOYMENT)
validate_helloada_app_queue = HELLOADA_APP_DEPLOYMENT.validate_helloada_app_queue


def mark_interrupted_runs(root: Path) -> None:
    # The caller owns the global lock; systemd has stopped the prior process group.
    for receipt in (root / "runs").glob("*/*/receipt.json"):
        result = json.loads(receipt.read_text())
        if result.get("status") != "running":
            continue
        result.update({"status": "interrupted", "error": "systemd job ended before a terminal receipt",
                       "finishedAt": datetime.now(timezone.utc).isoformat()})
        if result.get("tenant") and result.get("worker"):
            for name in ("source", "temporary", "open-next.tar.gz"):
                path = receipt.parent / name
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path)
            result["workspaceCleanupStatus"] = "interrupted-cleaned"
        temporary = receipt.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(receipt)


def cleanup_stale_release_workspaces(root: Path) -> None:
    work_root = root / "work"
    if work_root.is_symlink():
        raise RuntimeError("release workspace root must not be a symlink")
    if not work_root.exists():
        return
    if not work_root.is_dir():
        raise RuntimeError("release workspace root is not a real directory")
    # The caller owns reconcile.lock, so no canonical build can still be using it.
    for workspace in work_root.iterdir():
        if workspace.is_symlink() or workspace.is_file():
            workspace.unlink()
        elif workspace.is_dir():
            shutil.rmtree(workspace)
        else:
            raise RuntimeError("unexpected object in release workspace root")


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
        request_shape = set(request)
        runtime_fingerprint = request.get("sharedRuntimeFingerprint")
        if runtime_fingerprint is not None:
            request_shape.remove("sharedRuntimeFingerprint")
            if not re.fullmatch(r"[0-9a-f]{64}", str(runtime_fingerprint)):
                raise ValueError("shared-runtime release requires a full SHA-256 fingerprint")
        if request_shape not in permitted:
            raise ValueError("release must be an owner approval, a schema initialization, an exact schema migration, or a shared-runtime release")
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
    policies = {
        tenant: customer.get("sharedRuntimeUpdate", "automatic")
        for tenant, customer in registry["customers"].items()
        if isinstance(customer, dict)
    }
    if any(policy not in {"manual", "canary", "automatic"} for policy in policies.values()):
        raise ValueError("tenant shared-runtime rollout policy is invalid")
    if any(policy == "automatic" for policy in policies.values()) and sum(
        policy == "canary" for policy in policies.values()
    ) != 1:
        raise ValueError("automatic shared-runtime fan-out requires exactly one canary")


def release_purpose_for_request(request: dict) -> str:
    """Map one validated queue operation to its exact Payload content gate."""
    return "workspace-bootstrap" if "initializeSchema" in request else "website"


def queue_shared_runtime_fanout(
    mirror: Path,
    remote: str,
    environment: dict[str, str],
    release_root: Path,
    expected_control_sha: str,
    fingerprint: str,
    *,
    batch_size: int = 5,
) -> dict:
    """Queue one canary or bounded automatic tenant batch in an atomic Git commit."""
    from site_agent.application.shared_runtime_rollout import plan_shared_runtime_rollout

    subprocess.run(
        ["git", "-C", str(mirror), "fetch", "origin", "+refs/heads/main:refs/heads/main"],
        env=environment, check=True,
    )
    actual_sha = subprocess.check_output(
        ["git", "-C", str(mirror), "rev-parse", "refs/heads/main"], text=True,
    ).strip()
    if actual_sha != expected_control_sha:
        print("[runtime-rollout] control branch changed during this run; next timer pass will plan from its new snapshot",
              flush=True)
        return {"state": "deferred-control-branch-changed", "queued": {}}

    def document(path: str) -> dict:
        return json.loads(subprocess.check_output(
            ["git", "-C", str(mirror), "show", f"{actual_sha}:{path}"], text=True,
        ))

    registry = document("deploy/payload-customers.json")
    queue = document("deploy/desired-releases.json")
    plan = plan_shared_runtime_rollout(
        registry, queue, release_root, fingerprint, batch_size=batch_size,
    )
    print(
        f"[runtime-rollout] state={plan['state']} canary={plan.get('canaryTenant')} "
        f"blocked={','.join(plan.get('blocked', [])) or 'none'}",
        flush=True,
    )
    if not plan["queued"]:
        return plan

    for tenant, request in plan["queued"].items():
        queue["releases"][tenant] = request
    validate_queue(queue, registry)

    work_root = release_root / "work"
    work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="runtime-rollout-", dir=work_root) as workspace:
        checkout = Path(workspace) / "control"
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(mirror), str(checkout)],
            env=environment, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "checkout", "--detach", actual_sha],
            env=environment, check=True, stdout=subprocess.DEVNULL,
        )
        queue_path = checkout / "deploy/desired-releases.json"
        queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(checkout), "add", "--", "deploy/desired-releases.json"],
                       env=environment, check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.name", "Site-Agent Release Automation"],
                       env=environment, check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.email", "site-agent-release@users.noreply.github.com"],
                       env=environment, check=True)
        subprocess.run(
            ["git", "-C", str(checkout), "commit", "-m",
             f"chore(release): fan out shared runtime {fingerprint[:12]}"],
            env=environment, check=True, stdout=subprocess.DEVNULL,
        )
        commit_sha = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True,
        ).strip()
        subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin", remote],
                       env=environment, check=True)
        pushed = subprocess.run(
            ["git", "-C", str(checkout), "push", "origin", "HEAD:refs/heads/main"],
            env=environment, text=True, capture_output=True,
        )
        if pushed.returncode:
            subprocess.run(
                ["git", "-C", str(mirror), "fetch", "origin", "+refs/heads/main:refs/heads/main"],
                env=environment, check=True,
            )
            latest_sha = subprocess.check_output(
                ["git", "-C", str(mirror), "rev-parse", "refs/heads/main"], text=True,
            ).strip()
            if latest_sha != commit_sha:
                if latest_sha != expected_control_sha:
                    print("[runtime-rollout] concurrent control commit won; fan-out will be recalculated next timer pass",
                          flush=True)
                    return {"state": "deferred-control-branch-changed", "queued": {}}
                raise RuntimeError("could not commit the shared-runtime release fan-out")
        subprocess.run(
            ["git", "-C", str(mirror), "fetch", "origin", "+refs/heads/main:refs/heads/main"],
            env=environment, check=True,
        )
    print(
        f"[runtime-rollout] committed {plan['state']}: "
        + ", ".join(f"{tenant}/{request['id']}" for tenant, request in plan["queued"].items()),
        flush=True,
    )
    return plan


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


def snapshot_helloada_source(mirror: Path, destination: Path, source_sha: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("HelloAda source snapshot requires a full immutable SHA")
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("HelloAda source destination must be a new workspace path")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix="helloada-source-", dir=destination.parent))
    try:
        with subprocess.Popen(
            ["git", "-C", str(mirror), "archive", source_sha],
            stdout=subprocess.PIPE,
        ) as archive:
            subprocess.run(["tar", "-x", "-C", str(staging)], stdin=archive.stdout, check=True)
            if archive.stdout:
                archive.stdout.close()
            if archive.wait():
                raise RuntimeError("could not snapshot HelloAda source commit")
        marker_path = staging / ".helloada-source-sha"
        marker_path.write_text(source_sha + "\n", encoding="ascii")
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def cleanup_legacy_helloada_build_caches(root: Path) -> None:
    for name in ("helloada-sources", "npm-cache"):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(f"legacy HelloAda build cache is not a real directory: {name}")
        shutil.rmtree(path)


def cleanup_stale_control_snapshots(root: Path, source_sha: str) -> None:
    snapshots = root / "control"
    if snapshots.is_symlink():
        raise RuntimeError("control snapshot root must not be a symlink")
    if not snapshots.exists():
        return
    if not snapshots.is_dir():
        raise RuntimeError("control snapshot root is not a real directory")
    for stale in snapshots.iterdir():
        if stale.name == source_sha:
            continue
        if stale.is_symlink() or not stale.is_dir():
            raise RuntimeError("unexpected object in control snapshot root")
        shutil.rmtree(stale)


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
        cleanup_stale_release_workspaces(args.root)
        cleanup_legacy_helloada_build_caches(args.root)
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
        cleanup_stale_control_snapshots(args.root, sha)

        def document(path: str) -> dict:
            return json.loads(subprocess.check_output(["git", "-C", str(mirror), "show", f"{sha}:{path}"], text=True))

        registry = document("deploy/payload-customers.json")
        queue = document("deploy/desired-releases.json")
        api_request = validate_api_queue(document("deploy/desired-api-release.json"))
        app_request = validate_helloada_app_queue(document("deploy/desired-helloada-app-release.json"))
        app_config = document("deploy/helloada-app.json")
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
        from site_agent.application.shared_runtime import shared_runtime_fingerprint
        shared_fingerprint = shared_runtime_fingerprint(snapshot)
        from site_agent.application.shared_runtime_rollout import plan_shared_runtime_rollout
        initial_rollout = plan_shared_runtime_rollout(
            registry, queue, args.root, shared_fingerprint,
        )
        automatic_rollout = any(
            customer.get("sharedRuntimeUpdate") == "automatic"
            for customer in registry["customers"].values()
        )
        canary_passed = not automatic_rollout or initial_rollout["state"] not in {
            "canary-queued", "canary-pending", "canary-failed", "canary-contract-mismatch", "canary-needs-first-release",
        }
        print(
            f"[runtime-rollout] target={shared_fingerprint[:12]} state={initial_rollout['state']} "
            f"canary={initial_rollout.get('canaryTenant')} passed={str(canary_passed).lower()}",
            flush=True,
        )
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
        if app_request:
            app_repository = str(app_config.get("repository") or "")
            expected_repository = "git@github.com:weareheadless/helloada.git"
            if app_config.get("schema") != 1 or app_repository != expected_repository:
                raise ValueError("HelloAda app release registry must identify the official immutable source")
            app_mirror = args.root / "helloada-control.git"
            if not app_mirror.exists():
                subprocess.run(["git", "clone", "--bare", app_repository, str(app_mirror)],
                               env=environment, check=True)
            actual_app_remote = subprocess.check_output(
                ["git", "-C", str(app_mirror), "remote", "get-url", "origin"], text=True,
            ).strip()
            if actual_app_remote != app_repository:
                raise RuntimeError("HelloAda source mirror remote mismatch")
            subprocess.run(["git", "-C", str(app_mirror), "fetch", "origin",
                            "+refs/heads/main:refs/heads/main"], env=environment, check=True)
            ancestry = subprocess.run(
                ["git", "-C", str(app_mirror), "merge-base", "--is-ancestor",
                 app_request["sha"], "refs/heads/main"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if ancestry.returncode:
                raise ValueError("HelloAda app release SHA is not an ancestor of official main")
            app_tool = snapshot / "scripts" / "deploy-helloada-app.py"
            if not app_tool.is_file():
                raise RuntimeError("control snapshot does not contain the HelloAda app release contract")
            app_run = args.root / "runs" / "helloada-app" / app_request["id"]
            app_receipt = app_run / "receipt.json"
            if app_run.exists() or app_run.is_symlink():
                if app_run.is_symlink() or not app_run.is_dir() or not app_receipt.is_file():
                    print(f"[queue] HelloAda app {app_request['id']} has no terminal receipt; commit a new release ID",
                          flush=True)
                    failures += 1
                else:
                    result = json.loads(app_receipt.read_text(encoding="utf-8"))
                    if result.get("sourceSha") != app_request["sha"] or result.get("releaseId") != app_request["id"]:
                        raise RuntimeError("HelloAda app release ID was reused for different source")
                    failures += int(result.get("status") != "deployed")
            else:
                work_root = args.root / "work"
                work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                print(f"[queue] HelloAda app release={app_request['id']} source={app_request['sha']}", flush=True)
                with tempfile.TemporaryDirectory(prefix="helloada-app-", dir=work_root) as workspace:
                    app_source = snapshot_helloada_source(app_mirror, Path(workspace) / "source",
                                                          app_request["sha"])
                    code = subprocess.run(
                        [sys.executable, str(app_tool), "--source-dir", str(app_source),
                         "--source-sha", app_request["sha"], "--release-id", app_request["id"],
                         "--root", str(args.root)],
                        env={**environment, "HELLOADA_PIPELINE_SHA": sha},
                    ).returncode
                failures += int(code != 0)
                if app_receipt.is_file():
                    result = json.loads(app_receipt.read_text(encoding="utf-8"))
                    result["workspaceCleanupStatus"] = "complete"
                    temporary_receipt = app_receipt.with_suffix(".tmp")
                    temporary_receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                    temporary_receipt.chmod(0o600)
                    temporary_receipt.replace(app_receipt)
        pending = any(not (args.root / "runs" / tenant / request["id"]).exists()
                      for tenant, request in queue["releases"].items())
        if pending:
            subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_payload_release.py"],
                           cwd=snapshot, env={**environment, "PYTHONPATH": str(snapshot / "src")}, check=True)
        for tenant, request in queue["releases"].items():
            policy = registry["customers"][tenant].get("sharedRuntimeUpdate", "automatic")
            if automatic_rollout and not canary_passed and policy != "canary":
                print(f"[queue] {tenant}/{request['id']} held until the shared-runtime canary passes", flush=True)
                continue
            requested_fingerprint = request.get("sharedRuntimeFingerprint")
            if requested_fingerprint and requested_fingerprint != shared_fingerprint:
                print(f"[queue] {tenant}/{request['id']} held because its runtime fingerprint is stale", flush=True)
                continue
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
                if (result["status"] not in ("deployed", "verified")
                        or result.get("workspaceCleanupStatus") == "failed"):
                    failures += 1
                continue
            print(f"[queue] release={tenant}/{request['id']} source={request['sha']} pipeline={sha}", flush=True)
            command = [sys.executable, str(snapshot / "scripts/deploy-payload-customer.py"),
                "--tenant", tenant, "--ref", request["sha"], "--release-id", request["id"]]
            command.extend(["--release-purpose", release_purpose_for_request(request)])
            if "approvalId" in request:
                command.extend(["--approval-id", str(request["approvalId"])])
            if "initializeSchema" in request:
                command.extend(["--initialize-schema-head", request["initializeSchema"]["migrationHead"]])
            if "schemaMigration" in request:
                command.extend(["--schema-migration-from-ledger-identity",
                                request["schemaMigration"]["fromLedgerIdentity"]])
            if requested_fingerprint:
                command.extend(["--shared-runtime-fingerprint", requested_fingerprint])
            code = subprocess.run(command,
                env={**environment, "HELLOADA_PIPELINE_SHA": sha}).returncode
            failures += int(code != 0)
        try:
            queue_shared_runtime_fanout(
                mirror, remote, environment, args.root, sha, shared_fingerprint,
            )
        except Exception as error:
            print(f"[runtime-rollout] planning or queue commit failed: {type(error).__name__}: {error}", flush=True)
            failures += 1
        return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
