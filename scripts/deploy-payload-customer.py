#!/usr/bin/env python3
"""Release a registered Payload Worker from a fresh checkout of an exact SHA."""
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
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
D1_SYSTEM_TABLES = frozenset({"_cf_KV"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def payload_migration_command(manifest: dict[str, Any]) -> list[str]:
    """Run migrations through the site's pinned, package-managed Payload entrypoint."""
    return [str(Path(manifest["npmBin"]) / "npm"), "run", "payload", "--", "migrate"]


def validate_payload_verifier(checkout: Path) -> None:
    """Require the exact site-agent verifier before any build or tenant D1 mutation."""
    template = ROOT / "src/site_agent/templates/next-payload"
    package_path = checkout / "package.json"
    lock_path = checkout / "package-lock.json"
    tsconfig_path = checkout / "tsconfig.json"
    verifier_path = checkout / "scripts/verify-payload-contract.ts"
    if not package_path.is_file() or not lock_path.is_file() or not tsconfig_path.is_file():
        raise RuntimeError("tenant source must include its package manifest, lockfile, and tsconfig")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    tsconfig = json.loads(tsconfig_path.read_text(encoding="utf-8"))
    config_targets = tsconfig.get("compilerOptions", {}).get("paths", {}).get("@payload-config")
    if not isinstance(config_targets, list) or len(config_targets) != 1 or not isinstance(config_targets[0], str):
        raise RuntimeError("tenant tsconfig must map @payload-config to one existing Payload config")
    config_path = checkout / config_targets[0]
    try:
        config_path.resolve().relative_to(checkout.resolve())
    except ValueError as error:
        raise RuntimeError("tenant @payload-config target must stay inside the source checkout") from error
    if not config_path.is_file():
        raise RuntimeError("tenant tsconfig @payload-config target does not exist")
    expected_package = json.loads((template / "package.json").read_text(encoding="utf-8"))
    expected_script = expected_package["scripts"]["verify:payload"]
    expected_tsx = expected_package["devDependencies"]["tsx"]
    if package.get("scripts", {}).get("verify:payload") != expected_script:
        raise RuntimeError("tenant Payload verifier command must match the site-agent template")
    if package.get("devDependencies", {}).get("tsx") != expected_tsx:
        raise RuntimeError("tenant Payload verifier must declare the template's exact tsx version")
    if lock.get("packages", {}).get("", {}).get("devDependencies", {}).get("tsx") != expected_tsx:
        raise RuntimeError("tenant lockfile does not pin the template's exact Payload verifier runtime")
    expected_source = (template / "scripts/verify-payload-contract.ts").read_bytes()
    if not verifier_path.is_file() or verifier_path.read_bytes() != expected_source:
        raise RuntimeError("tenant Payload verifier source must match the site-agent template exactly")


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


def migration_ledger_head(applied: list[str]) -> str:
    """Stable identity for one ordered Payload migration ledger."""
    return hashlib.sha256(json.dumps(applied, separators=(",", ":")).encode()).hexdigest()


def uploaded_version_id(output: str) -> str:
    versions = re.findall(r"Worker Version ID:\s*([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})", output)
    if len(versions) != 1:
        raise RuntimeError("upload did not identify exactly one immutable Worker version")
    return versions[0]


def validate_target(customer: dict[str, Any], tenant: str, sha: str, release_id: str) -> None:
    if not SHA_RE.fullmatch(sha) or not ID_RE.fullmatch(release_id):
        raise ValueError("release requires a full commit SHA and a safe release ID")
    if not ID_RE.fullmatch(tenant) or customer["adminPath"] != "/api/helloada":
        raise ValueError("invalid tenant or noncanonical workspace API")
    if not re.fullmatch(r"https://github\.com/weareheadless/[a-zA-Z0-9_.-]+\.git", customer["repository"]):
        raise ValueError("customer repository must be in the official weareheadless account")
    for field in ("payloadAdmin", "payloadCore"):
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(customer.get(field) or "")):
            raise ValueError(f"registered customer has no exact {field} version")
    if not re.fullmatch(r"helloada-content-v\d+", str(customer.get("contentContract") or "")):
        raise ValueError("registered customer has no exact content contract")
    if not isinstance(customer.get("schemaRevision"), int) or customer["schemaRevision"] < 1:
        raise ValueError("registered customer has no exact Payload schema revision")
    if not re.fullmatch(r"[0-9a-f]{64}", str(customer.get("schemaIdentity") or "")):
        raise ValueError("registered customer has no normalized Payload schema identity")
    if not SHA256_RE.fullmatch(str(customer.get("migrationHead") or "")):
        raise ValueError("registered customer has no verified Payload migration-chain identity")
    if not UUID_RE.fullmatch(str(customer.get("d1DatabaseId") or "")):
        raise ValueError("registered customer has no exact tenant D1 identity")
    if customer["d1DatabaseId"].replace("-", "") == "0" * 32:
        raise ValueError("registered customer cannot use the template D1 identity")
    if not re.fullmatch(r"[a-z0-9-]{1,63}", str(customer.get("d1DatabaseName") or "")):
        raise ValueError("registered customer has no exact tenant D1 name")
    if not re.fullmatch(r"[a-z0-9-]{3,63}", str(customer.get("r2BucketName") or "")):
        raise ValueError("registered customer has no exact tenant R2 bucket")


def validate_toolchain_manifest(manifest: dict[str, Any]) -> None:
    for field in ("nodeBin", "npmBin"):
        value = str(manifest.get(field) or "")
        if not value or not Path(value).is_absolute():
            raise ValueError(f"release toolchain requires an absolute {field}")
    for field in ("nodeVersion", "npmVersion"):
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get(field) or "")):
            raise ValueError(f"release toolchain requires an exact {field}")


def validate_worker_contract(worker_config: dict[str, Any], customer: dict[str, Any], tenant: str) -> None:
    if worker_config.get("d1Count") != 1 or worker_config.get("r2Count") != 1:
        raise RuntimeError("Worker must have exactly one canonical tenant D1 and R2 binding")
    if worker_config.get("name") != customer["worker"] or worker_config.get("tenant") != tenant:
        raise RuntimeError("Worker name or tenant binding does not match the registry")
    if worker_config.get("admin") != customer["payloadAdmin"]:
        raise RuntimeError("Worker admin version does not match the registry")
    if (worker_config.get("core") != customer["payloadCore"]
            or worker_config.get("contract") != customer["contentContract"]
            or worker_config.get("schemaRevision") != customer["schemaRevision"]
            or worker_config.get("schemaIdentity") != customer["schemaIdentity"]):
        raise RuntimeError("Worker shared Payload contract does not match the registry")
    if (worker_config.get("migrationHead") != customer["migrationHead"]
            or worker_config.get("d1DatabaseId") != customer["d1DatabaseId"]
            or worker_config.get("d1DatabaseName") != customer["d1DatabaseName"]
            or worker_config.get("r2BucketName") != customer["r2BucketName"]):
        raise RuntimeError("Worker migration chain or tenant data-resource identity does not match the registry")


def d1_query(customer: dict[str, Any], sql: str, env: dict[str, str]) -> list[dict[str, Any]]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
           + "/d1/database/" + urllib.parse.quote(customer["d1DatabaseId"], safe="") + "/query")
    request = urllib.request.Request(
        url,
        data=json.dumps({"sql": sql}).encode(),
        method="POST",
        headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"tenant D1 schema inspection failed: {type(error).__name__}") from error
    if body.get("success") is not True or not isinstance(body.get("result"), list) or len(body["result"]) != 1:
        raise RuntimeError("Cloudflare did not return one successful tenant D1 query result")
    result = body["result"][0]
    if result.get("success") is not True or not isinstance(result.get("results"), list):
        raise RuntimeError("Cloudflare tenant D1 query did not complete successfully")
    return result["results"]


def applied_payload_migrations(customer: dict[str, Any], env: dict[str, str]) -> tuple[list[str], list[str]]:
    tables = d1_query(customer,
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name", env)
    # Cloudflare creates _cf_KV in every D1 database; it is provider-owned,
    # reserved, and not application data. Ignore this exact system table only.
    table_names = []
    for row in tables:
        name = str(row.get("name") or "")
        if name not in D1_SYSTEM_TABLES:
            table_names.append(name)
    if "payload_migrations" not in table_names:
        return table_names, []
    rows = d1_query(customer, "SELECT name FROM payload_migrations ORDER BY batch ASC, id ASC", env)
    return table_names, [str(row.get("name") or "") for row in rows]


def enforce_payload_migrations(checkout: Path, customer: dict[str, Any], env: dict[str, str],
                               initialization_head: str | None, migration_from_ledger: str | None,
                               base: dict[str, str],
                               manifest: dict[str, Any], tenant: str, stage: Any) -> list[str]:
    from site_agent.payload_contract import PayloadContractError, validate_payload_migrations

    try:
        template = validate_payload_migrations(checkout)
    except PayloadContractError as error:
        raise RuntimeError(str(error)) from error
    if template["migrationHead"] != customer["migrationHead"]:
        raise RuntimeError("checked-out Payload migration chain differs from the registered tenant contract")
    expected = [str(entry["name"]) for entry in template["migrations"]]
    if initialization_head is not None and migration_from_ledger is not None:
        raise RuntimeError("schema initialization and an existing-tenant migration are mutually exclusive")
    tables, applied = applied_payload_migrations(customer, env)
    if not tables:
        if migration_from_ledger is not None:
            raise RuntimeError("an existing-tenant migration cannot initialize an empty D1")
        if initialization_head != template["migrationHead"]:
            raise RuntimeError("empty tenant D1 requires the explicit bootstrap initialization receipt")
        stage("initialize-schema")
        runtime = tenant_runtime_secrets(manifest, tenant)
        migration_env = {**base, **env, **runtime, "NODE_ENV": "production", "PAYLOAD_CLI": "1"}
        run(payload_migration_command(manifest), checkout, migration_env)
        tables, applied = applied_payload_migrations(customer, env)
    elif "payload_migrations" not in tables:
        raise RuntimeError("non-empty tenant D1 has no Payload migration ledger")
    elif initialization_head is not None and applied != expected:
        raise RuntimeError("bootstrap retry found a non-empty D1 without the exact completed initial migration chain")
    elif applied != expected:
        is_prefix = bool(applied) and len(applied) < len(expected) and expected[:len(applied)] == applied
        if not is_prefix or migration_from_ledger is None:
            raise RuntimeError("existing tenant D1 differs from the committed chain; an explicit exact schema-migration request is required")
        if migration_ledger_head(applied) != migration_from_ledger:
            raise RuntimeError("tenant D1 migration ledger changed after the schema-migration request was approved")
        stage("migrate-schema")
        runtime = tenant_runtime_secrets(manifest, tenant)
        migration_env = {**base, **env, **runtime, "NODE_ENV": "production", "PAYLOAD_CLI": "1"}
        run(payload_migration_command(manifest), checkout, migration_env)
        tables, applied = applied_payload_migrations(customer, env)
    elif migration_from_ledger is not None:
        prefix_heads = {
            migration_ledger_head(expected[:length])
            for length in range(1, len(expected))
        }
        if migration_from_ledger not in prefix_heads:
            raise RuntimeError("schema-migration request does not identify a strict prefix of the committed chain")
    if "payload_migrations" not in tables or applied != expected:
        raise RuntimeError("applied Payload migration ledger differs from the exact committed migration chain")
    return applied


def cloudflare_deployment(customer: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + env["CLOUDFLARE_ACCOUNT_ID"]
           + "/workers/scripts/" + customer["worker"] + "/deployments")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}
        raise RuntimeError(f"Cloudflare deployment inspection failed with HTTP {error.code}") from error
    if body.get("success") is not True:
        raise RuntimeError("Cloudflare deployment inspection failed")
    deployments = body["result"]["deployments"]
    if not deployments:
        return {}
    return max(deployments, key=lambda item: item["created_on"])


def tenant_runtime_secrets(manifest: dict[str, Any], tenant: str) -> dict[str, str]:
    """Load only this tenant's Worker secrets from the registered host workspace."""
    try:
        import yaml
        from site_agent.application.tenant_registration import (
            WORKER_SITE_AGENT_TOKEN_ENV,
            provisioned_root,
            tenant_token_env,
        )

        config_path = Path(manifest["connectionGate"]["config"]).resolve()
        host_config = yaml.safe_load(config_path.read_text())
        if not isinstance(host_config, dict):
            raise ValueError("host API config root is invalid")
        root = provisioned_root(host_config)
        index = json.loads((root / "tenants.json").read_text())
        entry = index.get(tenant)
        if not isinstance(entry, dict):
            raise ValueError("tenant is not registered on this VPS")
        registered_config = Path(str(entry.get("config_path") or "")).resolve()
        expected_config = (root / tenant / "config.yaml").resolve()
        if registered_config != expected_config or root not in registered_config.parents:
            raise ValueError("registered tenant config path is inconsistent")
        env_path = root / tenant / "tenant.env"
        values: dict[str, str] = {}
        for line in env_path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("tenant secret file contains a malformed line")
            key, value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
                raise ValueError("tenant secret file contains an invalid or duplicate name")
            values[key] = value.strip()
        worker_manifest_path = ROOT / "src/site_agent/templates/next-payload/template-manifest.json"
        worker_manifest = json.loads(worker_manifest_path.read_text(encoding="utf-8"))
        worker_token_env = str(worker_manifest.get("workerTokenEnv") or "").strip()
        if worker_token_env != WORKER_SITE_AGENT_TOKEN_ENV:
            raise ValueError("canonical Worker token binding differs from the tenant registration contract")
        required = {"PAYLOAD_SECRET", tenant_token_env(tenant)}
        if any(not values.get(key) for key in required):
            raise ValueError("registered tenant runtime secrets are incomplete")
        # The site-agent keeps a tenant-specific environment name in its
        # protected host file; the canonical Worker contract uses one stable
        # binding name. This is an explicit mapping, not a second token.
        return {
            "PAYLOAD_SECRET": values["PAYLOAD_SECRET"],
            worker_token_env: values[tenant_token_env(tenant)],
        }
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"tenant runtime secrets are unavailable: {str(error)[:240]}") from error


def worker_secrets_file(directory: Path, values: dict[str, str]) -> Path:
    """Create a private, short-lived file for one immutable Worker upload."""
    descriptor, filename = tempfile.mkstemp(prefix=".worker-secrets-", suffix=".json", dir=directory)
    path = Path(filename)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(values, stream, sort_keys=True)
            stream.write("\n")
        return path
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise


def upload_worker_version(checkout: Path, sha: str, release_id: str, directory: Path,
                          secrets: dict[str, str], env: dict[str, str]) -> str:
    secrets_path = worker_secrets_file(directory, secrets)
    try:
        output = run([str(checkout / "node_modules/.bin/opennextjs-cloudflare"), "upload",
                      "--secrets-file", str(secrets_path), "--var",
                      "HELLOADA_RELEASE_SHA:" + sha, "--tag", release_id], checkout, env)
        return uploaded_version_id(output)
    finally:
        secrets_path.unlink(missing_ok=True)

def check_health(url: str, tenant: str, customer: dict[str, Any], sha: str) -> dict[str, Any]:
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(url + separator + urllib.parse.urlencode({"release": sha}),
                                     headers={"Accept": "application/json", "Cache-Control": "no-cache",
                                              "User-Agent": "HelloAda-Release/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        body = json.load(response)
    if body.get("ok") is not True or body.get("tenant") != tenant:
        raise RuntimeError("live tenant health mismatch")
    expected = {
        "payloadAdmin": customer["payloadAdmin"],
        "payloadCore": customer["payloadCore"],
        "contentContract": customer["contentContract"],
        "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"],
        "migrationHead": customer["migrationHead"],
        "releaseSha": sha,
    }
    if any(body.get(key) != value for key, value in expected.items()):
        raise RuntimeError("live release SHA or shared Payload contract version does not match the release")
    return body


def verify_live(receipt: dict[str, Any], customer: dict[str, Any], manifest: dict[str, Any],
                deploy_env: dict[str, str], base: dict[str, str], stage: Any) -> None:
    stage("verify-deployment")
    deployment = cloudflare_deployment(customer, deploy_env)
    versions = deployment["versions"]
    if (len(versions) != 1 or versions[0]["percentage"] != 100
            or versions[0]["version_id"] != receipt["uploadedVersion"]):
        raise RuntimeError("the exact uploaded Worker version does not receive 100% of production traffic")
    receipt["deployment"] = deployment
    gate = manifest["connectionGate"]
    # Edge rollout is asynchronous. Repeat the same strict read-only gates;
    # never change the version, identity, endpoint or success criteria.
    for attempt in range(12):
        try:
            receipt["health"] = check_health(customer["health"], receipt["tenant"],
                                             customer, receipt["sourceSha"])
            stage("verify-connection")
            run([sys.executable, str(ROOT / "scripts/check-helloada-connections.py"),
                 "--config", gate["config"], "--env-file", gate["envFile"],
                 "--api-url", gate["apiUrl"], "--tenant", receipt["tenant"]], ROOT,
                {**base, "PYTHONPATH": str(ROOT / "src")})
            receipt["connectionVerifiedAt"] = utc_now()
            return
        except (OSError, ValueError, RuntimeError) as error:
            receipt.setdefault("gateAttempts", []).append({"at": utc_now(), "error": str(error)})
            stage(receipt["stage"])
            if attempt == 11:
                raise
            time.sleep(5)


def verification_receipt(directory: Path, tenant: str, sha: str, release_id: str,
                         customer: dict[str, Any], approval_id: int | None = None,
                         initialization_head: str | None = None) -> dict[str, Any]:
    receipt = json.loads((directory / "receipt.json").read_text())
    expected = {"tenant": tenant, "sourceSha": sha, "releaseId": release_id,
                "worker": customer["worker"], "repository": customer["repository"],
                "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
                "contentContract": customer["contentContract"],
                "schemaRevision": customer["schemaRevision"], "schemaIdentity": customer["schemaIdentity"],
                "migrationHead": customer["migrationHead"]}
    if approval_id is not None:
        expected["approvalId"] = approval_id
    if initialization_head is not None:
        expected["initialSchemaHead"] = initialization_head
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("verification target differs from the recorded release")
    if receipt.get("status") not in ("failed", "deployed", "verified") or receipt.get("stage") not in (
            "verify-deployment", "verify-connection", "awaiting-browser-verification", "verified"):
        raise ValueError("only a promoted release may resume read-only verification")
    if not receipt.get("uploadedVersion") or not receipt.get("deployment"):
        raise ValueError("release has no recorded immutable production promotion")
    archive = directory / "open-next.tar.gz"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != receipt.get("archiveSha256"):
        raise ValueError("recorded release artifact is missing or changed")
    receipt.setdefault("verificationHistory", []).append({key: receipt.get(key) for key in
        ("status", "stage", "error", "finishedAt")})
    receipt.pop("error", None)
    receipt.update({"status": "running", "browserVerification": "pending"})
    return receipt


def inspect_artifact(checkout: Path, customer: dict[str, Any], sha: str) -> dict[str, str]:
    artifact = checkout / ".open-next"
    if not (artifact / "worker.js").is_file():
        raise RuntimeError("OpenNext produced no Worker")
    schema_configs = [path for path in (checkout / "payload.config.ts", checkout / "src/payload.config.ts") if path.is_file()]
    if len(schema_configs) != 1:
        raise RuntimeError("site must have exactly one canonical Payload configuration")
    schema_source = schema_configs[0].read_text(encoding="utf-8")
    if (not re.search(r"from\s+['\"]@weareheadless/helloada-payload-core/schema['\"]", schema_source)
            or not re.search(r"\bcreateHelloAdaSchema\s*\(", schema_source)):
        raise RuntimeError("Payload collections and globals must be instantiated from the shared site-agent schema factory")
    routes = json.loads((checkout / ".next/server/app-paths-manifest.json").read_text())
    required = {
        "/api/helloada/[...path]/route",
        "/api/workspace/content/route",
        "/api/workspace/global/route",
        "/api/workspace/media/route",
        "/api/health/route",
    }
    if not required.issubset(routes):
        raise RuntimeError("artifact is missing a canonical workspace, service content or release health route")
    if any("/api/atelier" in route for route in routes):
        raise RuntimeError("artifact still contains the obsolete Atelier API")
    package = json.loads((checkout / "node_modules/@weareheadless/helloada-payload-admin/package.json").read_text())
    if package["version"] != customer["payloadAdmin"]:
        raise RuntimeError("installed Payload admin version does not match the registry")
    core_package = json.loads((checkout / "node_modules/@weareheadless/helloada-payload-core/package.json").read_text())
    if core_package["version"] != customer["payloadCore"]:
        raise RuntimeError("installed Payload core version does not match the registry")
    content_contract = json.loads((checkout / "helloada-content-contract.json").read_text())
    if content_contract.get("contract") != customer["contentContract"]:
        raise RuntimeError("source content contract does not match the registry")
    template_manifest = json.loads((checkout / "template-manifest.json").read_text())
    sys.path.insert(0, str(ROOT / "src"))
    from site_agent.payload_contract import PayloadContractError, validate_payload_migrations
    try:
        template_manifest = validate_payload_migrations(checkout, template_manifest)
    except PayloadContractError as error:
        raise RuntimeError(str(error)) from error
    if (template_manifest.get("schemaRevision") != customer["schemaRevision"]
            or template_manifest.get("schemaIdentity") != customer["schemaIdentity"]
            or template_manifest.get("contentContract") != customer["contentContract"]
            or template_manifest.get("migrationHead") != customer["migrationHead"]):
        raise RuntimeError("source Payload schema identity does not match the registry")
    javascript = list((artifact / "server-functions").rglob("*.mjs")) + list((artifact / "server-functions").rglob("*.js"))
    if not any("/growth/contract" in path.read_text(errors="replace") for path in javascript):
        raise RuntimeError("compiled server is missing the Growth contract")
    marker = json.loads((artifact / "assets/helloada-release.json").read_text())
    expected_marker = {
        "sourceSha": sha,
        "payloadAdmin": customer["payloadAdmin"],
        "payloadCore": customer["payloadCore"],
        "contentContract": customer["contentContract"],
        "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"],
        "migrationHead": customer["migrationHead"],
    }
    if any(marker.get(key) != value for key, value in expected_marker.items()):
        raise RuntimeError("built release marker does not match the pinned source")
    return file_hashes(artifact)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--approval-id", type=int)
    parser.add_argument("--initialize-schema-head", help="hash of the exact Payload migration chain for an empty new tenant")
    parser.add_argument("--schema-migration-from-ledger-identity", help="exact identity of the current Payload ledger for an approved tenant schema migration")
    parser.add_argument("--verify-only", action="store_true",
                        help="Recheck an already promoted version; never build, upload or promote")
    parser.add_argument("--manifest", type=Path, default=ROOT / "deploy/payload-customers.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_toolchain_manifest(manifest)
    customer = manifest["customers"].get(args.tenant)
    if customer is None:
        parser.error("tenant is not registered")
    validate_target(customer, args.tenant, args.ref, args.release_id)
    directory = Path(manifest["releaseRoot"]) / "runs" / args.tenant / args.release_id
    # Serialize read-only continuation with the queue, which owns this lock
    # during normal releases. Keep the handle alive until main returns.
    verification_lock = None
    if args.verify_only:
        verification_lock = (Path(manifest["releaseRoot"]) / "reconcile.lock").open("a+")
        fcntl.flock(verification_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        directory.mkdir(parents=True, exist_ok=False)
    receipt_path = directory / "receipt.json"
    checkout = directory / "source"
    receipt: dict[str, Any] = {"schema": 2, "tenant": args.tenant, "releaseId": args.release_id,
        "sourceSha": args.ref, "pipelineSha": os.environ.get("HELLOADA_PIPELINE_SHA"),
        "nodeVersion": manifest["nodeVersion"], "npmVersion": manifest["npmVersion"],
        "worker": customer["worker"], "repository": customer["repository"],
        "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
        "contentContract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"],
        "d1DatabaseId": customer["d1DatabaseId"], "d1DatabaseName": customer["d1DatabaseName"],
        "r2BucketName": customer["r2BucketName"],
        "startedAt": utc_now(), "status": "running", "stage": "preflight",
        "browserVerification": "pending"}
    if args.approval_id is not None:
        if args.approval_id < 1:
            parser.error("approval identity must be a positive integer")
        receipt["approvalId"] = args.approval_id
    if args.initialize_schema_head is not None:
        if (args.initialize_schema_head != customer["migrationHead"] or args.approval_id is not None
                or args.schema_migration_from_ledger_identity is not None):
            parser.error("schema initialization must match the registered migration chain and cannot be an owner approval")
        receipt["initialSchemaHead"] = args.initialize_schema_head
    if args.schema_migration_from_ledger_identity is not None:
        if (not SHA256_RE.fullmatch(args.schema_migration_from_ledger_identity)
                or args.approval_id is not None or args.initialize_schema_head is not None):
            parser.error("schema migration requires one exact ledger identity and cannot be an owner approval or initialization")
        receipt["schemaMigrationFromLedgerIdentity"] = args.schema_migration_from_ledger_identity
        receipt["schemaMigrationTargetHead"] = customer["migrationHead"]
    if args.verify_only:
        receipt = verification_receipt(directory, args.tenant, args.ref, args.release_id, customer,
                                       args.approval_id, args.initialize_schema_head)

    def stage(name: str) -> None:
        receipt["stage"] = name
        atomic_json(receipt_path, receipt)
        print(f"[release] stage={name} tenant={args.tenant}", flush=True)

    try:
        stage("credentials")
        sys.path.insert(0, str(ROOT / "src"))
        from site_agent.credentials import credential_environment, credential_profile, github_remote, github_ssh_command, github_api_token
        profile = {"credentials": {"profile_file": manifest["credentialProfile"]}}
        cloudflare = dict(credential_profile(profile, "cloudflare"))
        if not cloudflare.get("env_file") or not Path(cloudflare["env_file"]).is_file():
            raise RuntimeError("declared Cloudflare credential file is missing")
        base = {k: os.environ[k] for k in ("HOME", "USER", "LANG", "TZ", "TMPDIR") if k in os.environ}
        base.update({"PATH": manifest["npmBin"] + ":" + manifest["nodeBin"] + ":/usr/local/bin:/usr/bin:/bin", "CI": "1",
                     "npm_config_cache": str(Path(manifest["releaseRoot"]) / "npm-cache")})
        temporary_root = directory / "temporary"
        temporary_root.mkdir(mode=0o700, exist_ok=True)
        base["TMPDIR"] = str(temporary_root)
        deploy_env = credential_environment({"credentials": {"cloudflare": cloudflare}}, base)
        if not deploy_env.get("CLOUDFLARE_API_TOKEN") or not deploy_env.get("CLOUDFLARE_ACCOUNT_ID"):
            raise RuntimeError("declared Cloudflare profile is incomplete")
        if args.verify_only:
            verify_live(receipt, customer, manifest, deploy_env, base, stage)
            receipt.update({"status": "deployed", "stage": "awaiting-browser-verification", "finishedAt": utc_now()})
            atomic_json(receipt_path, receipt)
            print(f"[release] REVERIFIED receipt={receipt_path}", flush=True)
            return 0
        for executable in (Path(manifest["nodeBin"], "node"), Path(manifest["npmBin"], "npm")):
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise RuntimeError(f"configured release executable is missing or not executable: {executable.name}")
        if run(["node", "--version"], directory, base).strip().removeprefix("v") != manifest["nodeVersion"]:
            raise RuntimeError(f"release requires Node {manifest['nodeVersion']}")
        if run([str(Path(manifest["npmBin"], "npm")), "--version"], directory, base).strip() != manifest["npmVersion"]:
            raise RuntimeError(f"release requires npm {manifest['npmVersion']}")
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
        validate_payload_verifier(checkout)
        source = list((checkout / "src").rglob("*.ts")) + list((checkout / "src").rglob("*.tsx"))
        if any("/api/atelier" in p.read_text() for p in source):
            raise RuntimeError("obsolete /api/atelier source must be removed")
        receipt["lockfileSha256"] = hashlib.sha256((checkout / "package-lock.json").read_bytes()).hexdigest()

        stage("dependencies")
        npm = str(Path(manifest["npmBin"], "npm"))
        from github_release_assets import prepare_release_dependencies
        receipt["sharedPackageAssets"] = prepare_release_dependencies(checkout, github_api_token(profile, base), npm, base, run)
        run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"], checkout, base)
        # TypeScript's pinned JSONC parser accepts comments and trailing commas.
        parsed = run(["node", "-e", "const fs=require('node:fs');const ts=require('typescript');"
                      "const r=ts.parseConfigFileTextToJson('wrangler.jsonc',fs.readFileSync('wrangler.jsonc','utf8'));"
                      "if(r.error)throw Error('Invalid Wrangler JSONC');const c=r.config;"
                      "process.stdout.write(JSON.stringify({name:c.name,tenant:c.vars?.HELLOADA_TENANT_ID,"
                "admin:c.vars?.HELLOADA_PAYLOAD_ADMIN_VERSION,core:c.vars?.HELLOADA_PAYLOAD_CORE_VERSION,"
                      "contract:c.vars?.HELLOADA_CONTENT_CONTRACT_VERSION,"
                      "schemaRevision:Number(c.vars?.HELLOADA_PAYLOAD_SCHEMA_REVISION||0),"
                      "schemaIdentity:c.vars?.HELLOADA_SCHEMA_IDENTITY,"
                      "migrationHead:c.vars?.HELLOADA_PAYLOAD_MIGRATION_HEAD,"
                      "d1Count:Array.isArray(c.d1_databases)?c.d1_databases.length:0,"
                      "d1DatabaseId:c.d1_databases?.[0]?.database_id,"
                      "d1DatabaseName:c.d1_databases?.[0]?.database_name,"
                      "r2Count:Array.isArray(c.r2_buckets)?c.r2_buckets.length:0,"
                      "r2BucketName:c.r2_buckets?.[0]?.bucket_name}));"], checkout, base)
        wrangler = json.loads(parsed)
        validate_worker_contract(wrangler, customer, args.tenant)
        run(["npm", "run", "typecheck"], checkout, base)
        if run(["git", "status", "--porcelain"], checkout, base).strip():
            raise RuntimeError("dependency/type checks changed tracked source")

        stage("build")
        marker = {"sourceSha": args.ref, "pipelineSha": receipt["pipelineSha"],
                  "tenant": args.tenant, "payloadAdmin": customer["payloadAdmin"],
                  "payloadCore": customer["payloadCore"], "contentContract": customer["contentContract"],
                  "schemaRevision": customer["schemaRevision"], "schemaIdentity": customer["schemaIdentity"],
                  "migrationHead": customer["migrationHead"]}
        atomic_json(checkout / "public/helloada-release.json", marker)
        build_env = {**base, "PAYLOAD_LOCAL_BUILD": "1", "HELLOADA_RELEASE_SHA": args.ref}
        run([str(checkout / "node_modules/.bin/opennextjs-cloudflare"), "build"], checkout, build_env)
        receipt["artifactHashes"] = inspect_artifact(checkout, customer, args.ref)
        changed = run(["git", "diff", "--name-only"], checkout, base).strip()
        if changed:
            raise RuntimeError("build changed tracked source: " + changed)
        stage("artifact-verified")
        run(["tar", "-czf", str(directory / "open-next.tar.gz"), "-C", str(checkout), ".open-next"], directory, base)
        receipt["archiveSha256"] = hashlib.sha256((directory / "open-next.tar.gz").read_bytes()).hexdigest()

        stage("upload")
        before_deploy = cloudflare_deployment(customer, deploy_env)
        if before_deploy.get("id") != receipt["previousDeployment"].get("id"):
            raise RuntimeError("production changed during the build; reconcile that deployment before retrying")
        runtime_secrets = tenant_runtime_secrets(manifest, args.tenant)
        receipt["uploadedVersion"] = upload_worker_version(
            checkout, args.ref, args.release_id, directory, runtime_secrets, deploy_env,
        )
        if file_hashes(checkout / ".open-next") != receipt["artifactHashes"]:
            raise RuntimeError("upload changed the inspected artifact")

        # Keep the previous Worker serving while the exact candidate's committed
        # migration is applied and checked. Only an explicitly queued migration
        # request can advance an existing tenant ledger.
        receipt["appliedMigrations"] = enforce_payload_migrations(
            checkout, customer, deploy_env, args.initialize_schema_head,
            args.schema_migration_from_ledger_identity, base, manifest, args.tenant, stage,
        )
        receipt["verifiedMigrationHead"] = customer["migrationHead"]
        stage("verify-payload-contract")
        run(["npm", "run", "verify:payload"], checkout, {**base, **deploy_env})
        atomic_json(receipt_path, receipt)

        stage("promote")
        if cloudflare_deployment(customer, deploy_env).get("id") != before_deploy.get("id"):
            raise RuntimeError("production changed during upload; reconcile before promotion")
        run([str(checkout / "node_modules/.bin/wrangler"), "versions", "deploy",
             receipt["uploadedVersion"] + "@100%", "--name", customer["worker"], "--yes"], checkout, deploy_env)

        stage("verify-deployment")
        deployment = cloudflare_deployment(customer, deploy_env)
        if not deployment or deployment.get("id") == before_deploy.get("id"):
            raise RuntimeError("Cloudflare did not create a new deployment")
        receipt["deployment"] = deployment
        verify_live(receipt, customer, manifest, deploy_env, base, stage)
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
