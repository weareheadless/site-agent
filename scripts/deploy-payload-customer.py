#!/usr/bin/env python3
"""Release a registered Payload Worker from a fresh checkout of an exact SHA."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def run(command: list[str], cwd: Path, env: dict[str, str]) -> str:
    print("[release] " + " ".join(command), flush=True)
    output: list[str] = []
    with subprocess.Popen(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            output.append(line)
        if process.wait():
            raise RuntimeError(f"command failed ({process.returncode}): {command[0]}")
    return "".join(output)


def file_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def validate_target(customer: dict[str, Any], tenant: str, sha: str, release_id: str) -> None:
    if not SHA_RE.fullmatch(sha) or not ID_RE.fullmatch(release_id):
        raise ValueError("release requires a full commit SHA and a safe release ID")
    if not ID_RE.fullmatch(tenant) or customer["adminPath"] != "/api/helloada":
        raise ValueError("invalid tenant or noncanonical workspace API")
    if not re.fullmatch(r"https://github\.com/weareheadless/[a-zA-Z0-9_.-]+\.git", customer["repository"]):
        raise ValueError("customer repository must be in the official weareheadless account")


def cloudflare_deployment(customer: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + env["CLOUDFLARE_ACCOUNT_ID"]
           + "/workers/scripts/" + customer["worker"] + "/deployments")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]})
    with urllib.request.urlopen(req, timeout=30) as response:
        body = json.load(response)
    if body.get("success") is not True:
        raise RuntimeError("Cloudflare deployment inspection failed")
    deployments = body["result"]["deployments"]
    if not deployments:
        raise RuntimeError("Worker has no production deployment to verify or roll back to")
    return max(deployments, key=lambda item: item["created_on"])


def check_health(url: str, tenant: str, version: str, sha: str) -> dict[str, Any]:
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(url + separator + urllib.parse.urlencode({"release": sha}),
                                     headers={"Accept": "application/json", "Cache-Control": "no-cache",
                                              "User-Agent": "HelloAda-Release/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        body = json.load(response)
    if body.get("ok") is not True or body.get("tenant") != tenant:
        raise RuntimeError("live tenant health mismatch")
    if body.get("payloadAdmin") != version or body.get("releaseSha") != sha:
        raise RuntimeError("live release SHA or installed admin version does not match the release")
    return body


def inspect_artifact(checkout: Path, expected_admin: str, sha: str) -> dict[str, str]:
    artifact = checkout / ".open-next"
    if not (artifact / "worker.js").is_file():
        raise RuntimeError("OpenNext produced no Worker")
    routes = json.loads((checkout / ".next/server/app-paths-manifest.json").read_text())
    if "/api/helloada/[...path]/route" not in routes or "/api/health/route" not in routes:
        raise RuntimeError("artifact has no canonical workspace or release health route")
    if any("/api/atelier" in route for route in routes):
        raise RuntimeError("artifact still contains the obsolete Atelier API")
    package = json.loads((checkout / "node_modules/@weareheadless/helloada-payload-admin/package.json").read_text())
    if package["version"] != expected_admin:
        raise RuntimeError("installed Payload admin version does not match the registry")
    javascript = list((artifact / "server-functions").rglob("*.mjs")) + list((artifact / "server-functions").rglob("*.js"))
    if not any("/growth/contract" in path.read_text(errors="replace") for path in javascript):
        raise RuntimeError("compiled server is missing the Growth contract")
    marker = json.loads((artifact / "assets/helloada-release.json").read_text())
    if marker["sourceSha"] != sha or marker["payloadAdmin"] != expected_admin:
        raise RuntimeError("built release marker does not match the pinned source")
    return file_hashes(artifact)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "deploy/payload-customers.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    customer = manifest["customers"].get(args.tenant)
    if customer is None:
        parser.error("tenant is not registered")
    validate_target(customer, args.tenant, args.ref, args.release_id)
    directory = Path(manifest["releaseRoot"]) / "runs" / args.tenant / args.release_id
    directory.mkdir(parents=True, exist_ok=False)
    receipt_path = directory / "receipt.json"
    checkout = directory / "source"
    receipt: dict[str, Any] = {"schema": 2, "tenant": args.tenant, "releaseId": args.release_id,
        "sourceSha": args.ref, "pipelineSha": os.environ.get("HELLOADA_PIPELINE_SHA"),
        "worker": customer["worker"], "repository": customer["repository"],
        "startedAt": utc_now(), "status": "running", "stage": "preflight",
        "browserVerification": "pending"}

    def stage(name: str) -> None:
        receipt["stage"] = name
        atomic_json(receipt_path, receipt)
        print(f"[release] stage={name} tenant={args.tenant}", flush=True)

    try:
        stage("credentials")
        sys.path.insert(0, str(ROOT / "src"))
        from site_agent.credentials import credential_environment, credential_profile, github_remote, github_ssh_command
        profile = {"credentials": {"profile_file": manifest["credentialProfile"]}}
        cloudflare = dict(credential_profile(profile, "cloudflare"))
        if not cloudflare.get("env_file") or not Path(cloudflare["env_file"]).is_file():
            raise RuntimeError("declared Cloudflare credential file is missing")
        base = {k: os.environ[k] for k in ("HOME", "USER", "LANG", "TZ", "TMPDIR") if k in os.environ}
        base.update({"PATH": manifest["nodeBin"] + ":/usr/local/bin:/usr/bin:/bin", "CI": "1",
                     "npm_config_cache": str(Path(manifest["releaseRoot"]) / "npm-cache")})
        deploy_env = credential_environment({"credentials": {"cloudflare": cloudflare}}, base)
        if not deploy_env.get("CLOUDFLARE_API_TOKEN") or not deploy_env.get("CLOUDFLARE_ACCOUNT_ID"):
            raise RuntimeError("declared Cloudflare profile is incomplete")
        if not Path(manifest["nodeBin"], "node").is_file():
            raise RuntimeError("configured Node runtime is missing")
        if run(["node", "--version"], directory, base).strip().split(".")[0] != "v22":
            raise RuntimeError("release requires Node 22")
        receipt["previousDeployment"] = cloudflare_deployment(customer, deploy_env)

        stage("checkout")
        git_env = {**base, "GIT_SSH_COMMAND": github_ssh_command(profile, base)}
        if not git_env["GIT_SSH_COMMAND"]:
            raise RuntimeError("declared GitHub SSH identity is missing")
        remote = github_remote(customer["repository"], profile, base)
        run(["git", "clone", "--no-checkout", remote, str(checkout)], directory, git_env)
        run(["git", "merge-base", "--is-ancestor", args.ref, "origin/main"], checkout, git_env)
        run(["git", "checkout", "--detach", args.ref], checkout, git_env)
        if run(["git", "rev-parse", "HEAD"], checkout, base).strip() != args.ref:
            raise RuntimeError("checkout SHA mismatch")
        if run(["git", "status", "--porcelain"], checkout, base).strip():
            raise RuntimeError("fresh release checkout is dirty")
        source = list((checkout / "src").rglob("*.ts")) + list((checkout / "src").rglob("*.tsx"))
        if any("/api/atelier" in p.read_text() for p in source):
            raise RuntimeError("obsolete /api/atelier source must be removed")
        receipt["lockfileSha256"] = hashlib.sha256((checkout / "package-lock.json").read_bytes()).hexdigest()

        stage("dependencies")
        run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], checkout, base)
        # TypeScript's pinned JSONC parser accepts comments and trailing commas.
        parsed = run(["node", "-e", "const fs=require('node:fs');const ts=require('typescript');"
                      "const r=ts.parseConfigFileTextToJson('wrangler.jsonc',fs.readFileSync('wrangler.jsonc','utf8'));"
                      "if(r.error)throw Error('Invalid Wrangler JSONC');const c=r.config;"
                      "process.stdout.write(JSON.stringify({name:c.name,tenant:c.vars?.HELLOADA_TENANT_ID,admin:c.vars?.HELLOADA_PAYLOAD_ADMIN_VERSION}));"], checkout, base)
        wrangler = json.loads(parsed)
        if wrangler["name"] != customer["worker"] or wrangler["tenant"] != args.tenant:
            raise RuntimeError("Worker name or tenant binding does not match the registry")
        if wrangler["admin"] != customer["payloadAdmin"]:
            raise RuntimeError("Worker admin version does not match the registry")
        run(["npm", "run", "typecheck"], checkout, base)
        if run(["git", "status", "--porcelain"], checkout, base).strip():
            raise RuntimeError("dependency/type checks changed tracked source")

        stage("build")
        marker = {"sourceSha": args.ref, "pipelineSha": receipt["pipelineSha"],
                  "tenant": args.tenant, "payloadAdmin": customer["payloadAdmin"]}
        atomic_json(checkout / "public/helloada-release.json", marker)
        build_env = {**base, "PAYLOAD_LOCAL_BUILD": "1", "HELLOADA_RELEASE_SHA": args.ref}
        run([str(checkout / "node_modules/.bin/opennextjs-cloudflare"), "build"], checkout, build_env)
        receipt["artifactHashes"] = inspect_artifact(checkout, customer["payloadAdmin"], args.ref)
        changed = run(["git", "diff", "--name-only"], checkout, base).strip()
        if changed:
            raise RuntimeError("build changed tracked source: " + changed)
        stage("artifact-verified")
        run(["tar", "-czf", str(directory / "open-next.tar.gz"), "-C", str(checkout), ".open-next"], directory, base)
        receipt["archiveSha256"] = hashlib.sha256((directory / "open-next.tar.gz").read_bytes()).hexdigest()

        stage("deploy")
        before_deploy = cloudflare_deployment(customer, deploy_env)
        if before_deploy["id"] != receipt["previousDeployment"]["id"]:
            raise RuntimeError("production changed during the build; reconcile that deployment before retrying")
        run([str(checkout / "node_modules/.bin/opennextjs-cloudflare"), "deploy", "--var",
             "HELLOADA_RELEASE_SHA:" + args.ref], checkout, deploy_env)
        if file_hashes(checkout / ".open-next") != receipt["artifactHashes"]:
            raise RuntimeError("deployment changed the inspected artifact")

        stage("verify-deployment")
        deployment = cloudflare_deployment(customer, deploy_env)
        if deployment["id"] == before_deploy["id"]:
            raise RuntimeError("Cloudflare did not create a new deployment")
        versions = deployment["versions"]
        if len(versions) != 1 or versions[0]["percentage"] != 100:
            raise RuntimeError("new Worker version does not receive 100% of production traffic")
        receipt["deployment"] = deployment
        for attempt in range(12):
            try:
                receipt["health"] = check_health(customer["health"], args.tenant, customer["payloadAdmin"], args.ref)
                break
            except (OSError, ValueError, RuntimeError):
                if attempt == 11:
                    raise
                time.sleep(5)

        stage("verify-connection")
        gate = manifest["connectionGate"]
        run([sys.executable, str(ROOT / "scripts/check-helloada-connections.py"),
             "--config", gate["config"], "--env-file", gate["envFile"],
             "--api-url", gate["apiUrl"], "--tenant", args.tenant], ROOT,
             {**base, "PYTHONPATH": str(ROOT / "src")})
        receipt.update({"status": "deployed", "stage": "awaiting-browser-verification", "finishedAt": utc_now()})
        atomic_json(receipt_path, receipt)
        print(f"[release] DEPLOYED receipt={receipt_path}", flush=True)
        return 0
    except Exception as error:
        receipt.update({"status": "failed", "error": str(error), "finishedAt": utc_now()})
        atomic_json(receipt_path, receipt)
        print(f"[release] FAILED stage={receipt['stage']}: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
