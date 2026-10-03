#!/usr/bin/env python3
"""Build and deploy one Payload customer from one exact Git SHA.

This is the only supported customer Worker release command. It deliberately
does not infer a branch, reuse an artifact, load a bootstrap credential, or
repair a legacy bridge. A failed gate stops the release and writes a receipt.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "deploy" / "payload-customers.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    printable = " ".join(command)
    print(f"[release] {printable}", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    return completed.stdout


def normalized_remote(value: str) -> str:
    value = value.strip().removesuffix("/").removesuffix(".git")
    value = re.sub(r"^https?://github\.com/", "", value)
    value = re.sub(r"^git@github\.com:", "", value)
    return value


def artifact_hashes(root: Path) -> dict[str, str]:
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    if not files:
        raise RuntimeError("OpenNext produced no files")
    result: dict[str, str] = {}
    for path in files:
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def write_receipt(directory: Path, receipt: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"{receipt['tenant']}-{stamp}-{receipt['sourceSha'][:12]}.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    temporary.replace(destination)
    return destination


def health(url: str, expected_tenant: str, expected_admin: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"release": expected_admin})
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(f"{url}{separator}{query}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"health returned HTTP {response.status}")
        body = json.loads(response.read().decode("utf-8"))
    if body.get("tenant") != expected_tenant:
        raise RuntimeError(f"health tenant mismatch: {body.get('tenant')!r}")
    if str(body.get("payloadAdmin")) != expected_admin:
        raise RuntimeError(f"live Payload admin is {body.get('payloadAdmin')!r}, expected {expected_admin!r}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--ref", required=True, help="Full 40-character customer repository commit SHA")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    if not SHA_RE.fullmatch(args.ref):
        parser.error("--ref must be a full 40-character commit SHA")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    customer = manifest.get("customers", {}).get(args.tenant)
    if not isinstance(customer, dict):
        parser.error(f"unknown tenant: {args.tenant}")
    checkout = Path(str(customer["checkout"]))
    expected_remote = normalized_remote(str(customer["repository"]))
    receipt: dict[str, Any] = {
        "schema": 1,
        "tenant": args.tenant,
        "sourceSha": args.ref,
        "worker": customer["worker"],
        "startedAt": utc_now(),
        "status": "failed",
        "stage": "preflight",
        "legacyBridgePolicy": "reject",
    }
    receipt_dir = Path(str(manifest["receiptDir"]))
    lock_path = Path(str(manifest["lockFile"]))
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        profile = {"credentials": {"profile_file": str(manifest["credentialProfile"])}}
        sys.path.insert(0, str(ROOT / "src"))
        from site_agent.credentials import cloudflare_env_names, credential_environment

        # Ambient shell credentials are deliberately excluded.  The declared
        # host profile must win so a runner cannot silently reuse a bootstrap
        # token or a prior customer's environment.
        token_name, account_name = cloudflare_env_names(profile)
        base_environment = dict(os.environ)
        base_environment.pop(token_name, None)
        base_environment.pop(account_name, None)
        environment = credential_environment(profile, base_environment)
        if not environment.get("CLOUDFLARE_API_TOKEN") or not environment.get("CLOUDFLARE_ACCOUNT_ID"):
            raise RuntimeError("the declared Cloudflare profile is missing CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID")
        node_bin = Path(str(manifest["nodeBin"]))
        if not (node_bin / "node").is_file():
            raise RuntimeError(f"Node 22 runtime is missing: {node_bin}")
        environment["PATH"] = f"{node_bin}:{environment.get('PATH', '')}"
        environment["PAYLOAD_LOCAL_BUILD"] = "1"
        environment["CI"] = "1"

        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            receipt["stage"] = "checkout"
            if not checkout.is_dir():
                raise RuntimeError(f"configured checkout does not exist: {checkout}")
            current_remote = normalized_remote(run(["git", "remote", "get-url", "origin"], cwd=checkout, env=environment).strip())
            if current_remote != expected_remote:
                raise RuntimeError(f"origin mismatch: {current_remote!r} != {expected_remote!r}")
            if run(["git", "status", "--porcelain"], cwd=checkout, env=environment).strip():
                raise RuntimeError("customer checkout is dirty")
            run(["git", "fetch", "origin", "main", "--prune"], cwd=checkout, env=environment)
            resolved = run(["git", "rev-parse", f"{args.ref}^{{commit}}"], cwd=checkout, env=environment).strip()
            if resolved != args.ref:
                raise RuntimeError(f"requested SHA is not present: {args.ref}")
            run(["git", "checkout", "--detach", args.ref], cwd=checkout, env=environment)
            if run(["git", "status", "--porcelain"], cwd=checkout, env=environment).strip():
                raise RuntimeError("checkout became dirty after pinning the release")
            receipt["repository"] = expected_remote
            receipt["checkout"] = str(checkout)

            receipt["stage"] = "cloudflare-auth"
            run(["npx", "wrangler", "whoami"], cwd=checkout, env=environment)
            previous = run(["npx", "wrangler", "deployments", "list", "--name", str(customer["worker"])], cwd=checkout, env=environment)
            receipt["previousDeployments"] = previous[-4000:]

            receipt["stage"] = "dependencies"
            run(["npm", "ci", "--ignore-scripts"], cwd=checkout, env=environment)
            run(["npm", "run", "typecheck"], cwd=checkout, env=environment)

            receipt["stage"] = "artifact"
            run(["npx", "opennextjs-cloudflare", "build"], cwd=checkout, env=environment)
            artifact = checkout / ".open-next"
            worker = artifact / "worker.js"
            if not worker.is_file() or worker.stat().st_size == 0:
                raise RuntimeError("OpenNext worker artifact is missing")
            legacy_check = subprocess.run(
                ["git", "grep", "-n", "api/atelier", "--", "src", "package.json", "wrangler.jsonc"],
                cwd=checkout,
                env=environment,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if legacy_check.returncode not in (0, 1):
                raise RuntimeError(f"legacy API scan failed with exit {legacy_check.returncode}: {legacy_check.stdout.strip()}")
            if legacy_check.stdout.strip():
                raise RuntimeError("legacy /api/atelier bridge is present; migrate the source before deployment")
            worker_text = worker.read_text(encoding="utf-8", errors="ignore")
            if "growth/contract" not in worker_text:
                raise RuntimeError("artifact is missing the managed Growth contract")
            if str(customer["payloadAdmin"]) not in worker_text:
                raise RuntimeError("artifact is missing the expected Payload admin release marker")
            receipt["artifact"] = {"root": str(artifact), "files": artifact_hashes(artifact), "workerSha256": hashlib.sha256(worker.read_bytes()).hexdigest()}

            receipt["stage"] = "deploy"
            deployment = run(["npx", "opennextjs-cloudflare", "deploy"], cwd=checkout, env=environment)
            receipt["deploymentOutput"] = deployment[-4000:]
            receipt["stage"] = "live-verification"
            receipt["health"] = health(str(customer["health"]), args.tenant, str(customer["payloadAdmin"]))
            receipt["status"] = "passed"
            receipt["stage"] = "complete"
            receipt["finishedAt"] = utc_now()
            destination = write_receipt(receipt_dir, receipt)
            print(f"[release] PASS receipt={destination}", flush=True)
            return 0
    except Exception as error:
        receipt["error"] = str(error)
        receipt["finishedAt"] = utc_now()
        destination = write_receipt(receipt_dir, receipt)
        print(f"[release] FAIL receipt={destination}: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
