#!/usr/bin/env python3
"""Build and atomically release the HelloAda project selector from one exact SHA."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SHA_RE = re.compile(r"[0-9a-f]{40}")
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
KEY_RE = re.compile(r"[A-Za-z0-9_-]{300,4096}")
HELLOADA_APP_CONFIG = {
    "schema": 1,
    "repository": "git@github.com:weareheadless/helloada.git",
    "worker": "helloada",
    "siteUrl": "https://helloada.app",
    "healthUrl": "https://helloada.app/api/health",
    "siteAgentUrl": "https://api.helloada.app/v1",
    "d1": {"name": "helloada", "id": "54955f1d-7470-46eb-8760-693891dab001"},
    "r2Bucket": "helloada-media",
    "privateKeyName": "HELLOADA_HANDOFF_PRIVATE_KEY",
    "privateKeyFile": "/SOCIAL/configs/helloada-app/secrets.json",
    "publicKeyName": "HELLOADA_HANDOFF_PUBLIC_KEY",
    "apiEnvFile": "/SOCIAL/configs/site-agent-api/.env",
}

_CUSTOMER_DEPLOY_PATH = ROOT / "scripts/deploy-payload-customer.py"
_CUSTOMER_DEPLOY_SPEC = importlib.util.spec_from_file_location("site_agent_worker_release", _CUSTOMER_DEPLOY_PATH)
if _CUSTOMER_DEPLOY_SPEC is None or _CUSTOMER_DEPLOY_SPEC.loader is None:
    raise RuntimeError("shared Worker release helpers are unavailable")
_WORKER_RELEASE = importlib.util.module_from_spec(_CUSTOMER_DEPLOY_SPEC)
_CUSTOMER_DEPLOY_SPEC.loader.exec_module(_WORKER_RELEASE)


def validate_helloada_app_queue(queue: Any) -> dict[str, str] | None:
    if (not isinstance(queue, dict) or set(queue) != {"schema", "release"}
            or isinstance(queue.get("schema"), bool) or queue.get("schema") != 1):
        raise ValueError("invalid HelloAda app release queue schema")
    request = queue["release"]
    if request is None:
        return None
    if not isinstance(request, dict) or set(request) != {"id", "sha"}:
        raise ValueError("HelloAda app release must contain only an ID and full source SHA")
    if not isinstance(request["id"], str) or not ID_RE.fullmatch(request["id"]):
        raise ValueError("unsafe HelloAda app release ID")
    if not isinstance(request["sha"], str) or not SHA_RE.fullmatch(request["sha"]):
        raise ValueError("HelloAda app release requires a full immutable source SHA")
    return request


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _run(command: list[str], cwd: Path, env: dict[str, str], *, capture: bool = True) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, check=False,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None)
    if result.returncode:
        if capture and result.stdout:
            print(result.stdout, end="", flush=True)
        raise RuntimeError(f"{Path(command[0]).name} failed with exit code {result.returncode}")
    return result.stdout or ""


def _source_tree_hash(source: Path) -> str:
    digest = hashlib.sha256()
    generated = {".git", "node_modules", ".next", ".open-next", ".wrangler"}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if generated.intersection(relative.parts) or path.name.endswith(".tsbuildinfo"):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _env_file(path: Path) -> dict[str, str]:
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("the declared site-agent environment file is unavailable") from error
    values: dict[str, str] = {}
    for line in rows:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("the declared site-agent environment file is malformed")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            raise RuntimeError("the declared site-agent environment file has invalid or duplicate names")
        values[key] = value.strip()
    return values


def _load_handoff_secret(config: dict[str, Any], directory: Path) -> str:
    secret_path = Path(str(config.get("privateKeyFile") or ""))
    expected_key = str(config.get("privateKeyName") or "")
    try:
        if secret_path.is_symlink() or stat.S_IMODE(secret_path.stat().st_mode) != 0o600:
            raise RuntimeError("the HelloAda handoff secret file must be a regular mode-0600 file")
        document = json.loads(secret_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError("the HelloAda handoff secret file is unavailable or invalid") from error
    if not isinstance(document, dict) or set(document) != {expected_key}:
        raise RuntimeError("the HelloAda handoff secret file has an unexpected key set")
    private_key = str(document.get(expected_key) or "")
    if not KEY_RE.fullmatch(private_key):
        raise RuntimeError("the HelloAda owner-handoff private key is missing or malformed")
    try:
        private_der = base64.urlsafe_b64decode(private_key + "=" * ((4 - len(private_key) % 4) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise RuntimeError("the HelloAda owner-handoff private key is not valid base64url") from error
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("OpenSSL is required to verify the HelloAda handoff key pair")
    descriptor, filename = tempfile.mkstemp(prefix=".handoff-key-", dir=directory)
    private_path = Path(filename)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(private_der)
        result = subprocess.run([openssl, "pkey", "-inform", "DER", "-in", str(private_path),
                                 "-pubout", "-outform", "DER"], capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError("the HelloAda owner-handoff key is not a supported RSA PKCS#8 key")
        from site_agent.application.bootstrap import _validate_rsa_spki
        try:
            _validate_rsa_spki(result.stdout)
        except ValueError as error:
            raise RuntimeError("the HelloAda owner-handoff key is not a supported RSA PKCS#8 key") from error
    finally:
        private_path.unlink(missing_ok=True)
    public_value = base64.urlsafe_b64encode(result.stdout).decode("ascii").rstrip("=")
    api_values = _env_file(Path(str(config.get("apiEnvFile") or "")))
    if api_values.get(str(config.get("publicKeyName") or "")) != public_value:
        raise RuntimeError("HelloAda and site-agent owner-handoff keys do not match")
    return private_key


def _validate_app_config(source: Path, config: dict[str, Any], node: str, env: dict[str, str],
                         npm_version: str) -> dict[str, Any]:
    command = [node, "-e", "const fs=require('node:fs');const ts=require('typescript');"
               "const r=ts.parseConfigFileTextToJson('wrangler.jsonc',fs.readFileSync('wrangler.jsonc','utf8'));"
               "if(r.error)throw Error('Invalid Wrangler JSONC');const c=r.config;"
               "const v=c.vars||{};const d=c.d1_databases||[];const b=c.r2_buckets||[];"
               "process.stdout.write(JSON.stringify({name:c.name,main:c.main,site:v.NEXT_PUBLIC_SITE_URL,"
               "api:v.SITE_AGENT_URL,d1:d.map(x=>({name:x.database_name,id:x.database_id})),"
               "r2:b.map(x=>x.bucket_name),required:c.secrets?.required||[]}));"]
    try:
        raw = _run(command, source, env)
        worker = json.loads(raw)
    except (RuntimeError, json.JSONDecodeError) as error:
        raise RuntimeError("HelloAda Worker configuration could not be parsed") from error
    expected = {
        "name": config["worker"],
        "main": ".open-next/worker.js",
        "site": config["siteUrl"],
        "api": config["siteAgentUrl"],
        "d1": [config["d1"]],
        "r2": [config["r2Bucket"]],
        "required": [config["privateKeyName"]],
    }
    if worker != expected:
        raise RuntimeError("HelloAda source Worker, site-agent API, D1, R2 or required-secret contract differs from the release registry")
    package = json.loads((source / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((source / "package-lock.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts") or {}
    if package.get("packageManager") != f"npm@{npm_version}":
        raise RuntimeError("HelloAda package manager does not match the central release toolchain")
    if not all(scripts.get(name) for name in ("test", "lint", "typecheck", "build")):
        raise RuntimeError("HelloAda app must declare test, lint, typecheck and build checks")
    if package.get("dependencies") != lock.get("packages", {}).get("", {}).get("dependencies"):
        raise RuntimeError("HelloAda package manifest and lockfile dependencies differ")
    if not (source / "src/app/api/health/route.ts").is_file():
        raise RuntimeError("HelloAda app does not expose the exact-release health route")
    return worker


def _health(url: str, expected_sha: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache",
                                                   "User-Agent": "HelloAda-Release/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.load(response)
    if response.status != 200 or body.get("ok") is not True or body.get("releaseSha") != expected_sha:
        raise RuntimeError("HelloAda live health or release SHA did not match the uploaded source")
    return body


def _deployment_version(deployment: dict[str, Any]) -> str | None:
    versions = deployment.get("versions")
    if not isinstance(versions, list) or len(versions) != 1 or versions[0].get("percentage") != 100:
        return None
    version_id = versions[0].get("version_id")
    return version_id if isinstance(version_id, str) and version_id else None


def deploy(source_dir: Path, source_sha: str, release_id: str, root: Path,
           config: dict[str, Any], toolchain: dict[str, Any]) -> dict[str, Any]:
    if not SHA_RE.fullmatch(source_sha) or not ID_RE.fullmatch(release_id):
        raise ValueError("HelloAda app deployment requires a safe release ID and full source SHA")
    source_dir = source_dir.resolve()
    marker = source_dir / ".helloada-source-sha"
    if not source_dir.is_dir() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != source_sha:
        raise ValueError("HelloAda source snapshot does not match the requested SHA")
    directory = root / "runs" / "helloada-app" / release_id
    receipt_path = directory / "receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("sourceSha") != source_sha or receipt.get("releaseId") != release_id:
            raise RuntimeError("HelloAda app release ID was reused for different source")
        return receipt
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    receipt: dict[str, Any] = {
        "schema": 1, "releaseId": release_id, "sourceSha": source_sha,
        "repository": config["repository"], "worker": config["worker"],
        "status": "running", "stage": "started", "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    def stage(name: str) -> None:
        receipt["stage"] = name
        receipt["updatedAt"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(receipt_path, receipt)
        print(f"[helloada-app] stage={name} release={release_id}", flush=True)

    try:
        private_key = _load_handoff_secret(config, source_dir.parent)
        profile = {"credentials": {"profile_file": str(toolchain["credentialProfile"] )}}
        sys.path.insert(0, str(ROOT / "src"))
        from site_agent.credentials import credential_environment, credential_profile, github_ssh_command
        cloudflare_profile = dict(credential_profile(profile, "cloudflare"))
        if not cloudflare_profile.get("env_file") or not Path(cloudflare_profile["env_file"]).is_file():
            raise RuntimeError("declared Cloudflare credential file is missing")
        safe_base = {key: value for key, value in os.environ.items() if key in ("HOME", "USER", "LANG", "TZ")}
        safe_base.update({"PATH": str(toolchain["npmBin"]) + ":" + str(toolchain["nodeBin"]) + ":/usr/local/bin:/usr/bin:/bin",
                          "CI": "1", "npm_config_cache": str(source_dir.parent / "npm-cache")})
        temporary = source_dir.parent / "temporary"
        temporary.mkdir(mode=0o700)
        safe_base["TMPDIR"] = str(temporary)
        build_env = {**safe_base, "PAYLOAD_LOCAL_BUILD": "1", "CLOUDFLARE_REMOTE_BINDINGS": "0",
                     "PAYLOAD_SECRET": "helloada-local-build-only-secret-never-used-for-production"}
        deploy_env = credential_environment({"credentials": {"cloudflare": cloudflare_profile}}, safe_base)
        if not deploy_env.get("CLOUDFLARE_API_TOKEN") or not deploy_env.get("CLOUDFLARE_ACCOUNT_ID"):
            raise RuntimeError("declared Cloudflare profile is incomplete")
        for executable in (Path(toolchain["nodeBin"]) / "node", Path(toolchain["npmBin"]) / "npm"):
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise RuntimeError(f"configured release executable is unavailable: {executable.name}")
        node = str(Path(toolchain["nodeBin"]) / "node")
        npm = str(Path(toolchain["npmBin"]) / "npm")
        if _run([node, "--version"], source_dir, safe_base).strip().removeprefix("v") != toolchain["nodeVersion"]:
            raise RuntimeError("HelloAda release Node version differs from the central toolchain")
        if _run([npm, "--version"], source_dir, safe_base).strip() != toolchain["npmVersion"]:
            raise RuntimeError("HelloAda release npm version differs from the central toolchain")
        public = _WORKER_RELEASE.cloudflare_deployment(config, deploy_env)
        if not public:
            raise RuntimeError("the registered HelloAda production Worker has no existing deployment")
        receipt["previousDeployment"] = public

        stage("source-verified")
        source_hash = _source_tree_hash(source_dir)
        receipt["lockfileSha256"] = hashlib.sha256((source_dir / "package-lock.json").read_bytes()).hexdigest()
        stage("dependencies")
        _run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"], source_dir, safe_base)
        worker_config = _validate_app_config(source_dir, config, node, build_env, toolchain["npmVersion"])
        receipt["workerConfig"] = worker_config
        for command in ([npm, "test"], [npm, "run", "lint"], [npm, "run", "typecheck"], [npm, "run", "build"]):
            _run(list(command), source_dir, build_env)
        if _source_tree_hash(source_dir) != source_hash:
            raise RuntimeError("HelloAda checks changed tracked source")

        stage("build")
        _run([str(source_dir / "node_modules/.bin/opennextjs-cloudflare"), "build"], source_dir, build_env)
        artifact = source_dir / ".open-next"
        worker = artifact / "worker.js"
        assets = artifact / "assets"
        if not worker.is_file() or not assets.is_dir():
            raise RuntimeError("OpenNext did not produce the registered HelloAda Worker artifact")
        artifact_files = _WORKER_RELEASE.file_hashes(artifact)
        if not artifact_files:
            raise RuntimeError("HelloAda release artifact is empty")
        if _source_tree_hash(source_dir) != source_hash:
            raise RuntimeError("OpenNext changed tracked HelloAda source")
        receipt["artifactSha256"] = hashlib.sha256(json.dumps(artifact_files, sort_keys=True).encode()).hexdigest()
        stage("upload")
        if _WORKER_RELEASE.cloudflare_deployment(config, deploy_env).get("id") != public.get("id"):
            raise RuntimeError("HelloAda production changed during the build; inspect it before retrying")
        receipt["uploadedVersion"] = _WORKER_RELEASE.upload_worker_version(
            source_dir, source_sha, release_id, source_dir.parent,
            {config["privateKeyName"]: private_key}, deploy_env,
        )
        if _WORKER_RELEASE.file_hashes(artifact) != artifact_files:
            raise RuntimeError("HelloAda upload changed the inspected artifact")

        stage("promote")
        if _WORKER_RELEASE.cloudflare_deployment(config, deploy_env).get("id") != public.get("id"):
            raise RuntimeError("HelloAda production changed during upload; inspect it before promotion")
        _WORKER_RELEASE.run([str(source_dir / "node_modules/.bin/wrangler"), "versions", "deploy",
                             receipt["uploadedVersion"] + "@100%", "--name", config["worker"], "--yes"],
                            source_dir, deploy_env)
        stage("verify")
        last_error: Exception | None = None
        for attempt in range(12):
            deployment = _WORKER_RELEASE.cloudflare_deployment(config, deploy_env)
            if _deployment_version(deployment) != receipt["uploadedVersion"]:
                last_error = RuntimeError("the exact uploaded HelloAda version does not receive 100% of traffic")
            else:
                try:
                    receipt["health"] = _health(config["healthUrl"], source_sha)
                    receipt["deployment"] = deployment
                    break
                except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as error:
                    last_error = error
            receipt.setdefault("gateAttempts", []).append({"attempt": attempt + 1, "error": str(last_error)[:200]})
            _atomic_json(receipt_path, receipt)
            if attempt < 11:
                time.sleep(5)
        else:
            previous_version = _deployment_version(public)
            if not previous_version:
                raise RuntimeError("HelloAda health gate failed and no exact previous version is available") from last_error
            _WORKER_RELEASE.run([str(source_dir / "node_modules/.bin/wrangler"), "versions", "deploy",
                                 previous_version + "@100%", "--name", config["worker"], "--yes"],
                                source_dir, deploy_env)
            raise RuntimeError("HelloAda health gate failed; the exact previous Worker version was restored") from last_error
        receipt.update({"status": "deployed", "stage": "deployed", "finishedAt": datetime.now(timezone.utc).isoformat()})
        _atomic_json(receipt_path, receipt)
        print(f"[helloada-app] DEPLOYED receipt={receipt_path}", flush=True)
        return receipt
    except Exception as error:
        receipt.update({"status": "failed", "error": str(error)[:500],
                        "finishedAt": datetime.now(timezone.utc).isoformat()})
        _atomic_json(receipt_path, receipt)
        print(f"[helloada-app] FAILED stage={receipt['stage']}: {receipt['error']}", file=sys.stderr, flush=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--root", type=Path, default=Path("/SOCIAL/payload-releases"))
    parser.add_argument("--app-config", type=Path, default=ROOT / "deploy/helloada-app.json")
    parser.add_argument("--toolchain-config", type=Path, default=ROOT / "deploy/payload-customers.json")
    args = parser.parse_args()
    config = json.loads(args.app_config.read_text(encoding="utf-8"))
    toolchain = json.loads(args.toolchain_config.read_text(encoding="utf-8"))
    if config.get("schema") != 1 or toolchain.get("schema") != 1:
        raise ValueError("HelloAda app release manifests have an unsupported schema")
    if config != HELLOADA_APP_CONFIG:
        raise ValueError("HelloAda release target differs from the fixed production app contract")
    _WORKER_RELEASE.validate_toolchain_manifest(toolchain)
    if Path(toolchain["releaseRoot"]).resolve() != args.root.resolve():
        raise ValueError("HelloAda app release root differs from the installed VPS release root")
    result = deploy(args.source_dir, args.source_sha, args.release_id, args.root, config, toolchain)
    return 0 if result.get("status") == "deployed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
