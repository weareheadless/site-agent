#!/usr/bin/env python3
"""Release a registered Payload Worker from a fresh checkout of an exact SHA."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if TYPE_CHECKING:
    from site_agent.hands.cloudflare_resources import CloudflareResourceProvisioner

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
D1_SYSTEM_TABLES = frozenset({"_cf_KV"})
MINIMUM_BUILD_FREE_BYTES = 8 * 1024 ** 3
NPM_INSTALL_ARGUMENTS = ("ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline", "--maxsockets=1")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_build_capacity(path: Path) -> None:
    free_bytes = shutil.disk_usage(path).free
    if free_bytes < MINIMUM_BUILD_FREE_BYTES:
        free_gib = free_bytes / (1024 ** 3)
        minimum_gib = MINIMUM_BUILD_FREE_BYTES // (1024 ** 3)
        raise RuntimeError(
            f"Payload build requires at least {minimum_gib} GiB free; "
            f"only {free_gib:.1f} GiB is available"
        )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def payload_migration_command(manifest: dict[str, Any]) -> list[str]:
    """Run migrations through the site's pinned, package-managed Payload entrypoint."""
    return [str(Path(manifest["npmBin"]) / "npm"), "run", "payload", "--", "migrate"]


def payload_remote_bindings_config_file(temporary_directory: Path, customer: dict[str, Any],
                                  worker_config: dict[str, Any]) -> Path:
    """Build a private Wrangler config that explicitly targets this tenant's remote bindings."""
    compatibility_date = str(worker_config.get("compatibilityDate") or "")
    try:
        datetime.strptime(compatibility_date, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("Payload migration requires the exact Worker compatibility date") from error
    flags = worker_config.get("compatibilityFlags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) or not flag for flag in flags):
        raise ValueError("Payload migration requires the exact Worker compatibility flags")
    config = {
        "name": customer["worker"],
        "compatibility_date": compatibility_date,
        "compatibility_flags": flags,
        "d1_databases": [{
            "binding": "D1",
            "database_id": customer["d1DatabaseId"],
            "database_name": customer["d1DatabaseName"],
            "remote": True,
        }],
        "r2_buckets": [{
            "binding": "R2",
            "bucket_name": customer["r2BucketName"],
            "remote": True,
        }],
    }
    temporary_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(
        prefix=".helloada-payload-migration-", suffix=".jsonc", dir=temporary_directory,
    )
    path = Path(filename)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(config, stream, indent=2, sort_keys=True)
            stream.write("\n")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def require_release_purpose(
    release_purpose: str,
    initialization_head: str | None,
) -> None:
    """Bind the verifier contract to the exact operation recorded in GitHub."""
    expected_purpose = "workspace-bootstrap" if initialization_head is not None else "website"
    if release_purpose != expected_purpose:
        raise ValueError("release purpose does not match the exact queued operation")
    if initialization_head is not None and not SHA256_RE.fullmatch(initialization_head):
        raise ValueError("workspace bootstrap requires the exact committed Payload migration head")


def verify_workspace_bootstrap_contract(
    checkout: Path,
    receipt: dict[str, Any],
    customer: dict[str, Any],
    initialization_head: str | None,
) -> None:
    """Require the exact initialized schema before making a new admin available."""
    manifest = json.loads((checkout / "template-manifest.json").read_text(encoding="utf-8"))
    expected_migrations = [str(item["name"]) for item in manifest["migrations"]]
    if (
        initialization_head != customer["migrationHead"]
        or manifest.get("migrationHead") != customer["migrationHead"]
        or receipt.get("verifiedMigrationHead") != customer["migrationHead"]
        or receipt.get("appliedMigrations") != expected_migrations
    ):
        raise RuntimeError("workspace bootstrap does not match the exact registered Payload schema and migration chain")


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


def worker_artifact_hashes(checkout: Path, custom_worker_bundle: Path | None = None) -> dict[str, str]:
    """Hash the generated app plus every source/config input OpenNext uploads."""
    generated = {f".open-next/{path}": digest for path, digest in file_hashes(checkout / ".open-next").items()}
    for relative in ("worker.ts", "wrangler.jsonc", "package.json", "package-lock.json"):
        path = checkout / relative
        if not path.is_file():
            raise RuntimeError(f"custom Worker release input is missing: {relative}")
        generated[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    mailflare_output = checkout / ".mailflare"
    if not (mailflare_output / "provenance.json").is_file():
        raise RuntimeError("Mailflare Worker output is missing its source receipt")
    generated.update({
        f".mailflare/{path}": digest
        for path, digest in file_hashes(mailflare_output).items()
    })
    if custom_worker_bundle is not None:
        if not (custom_worker_bundle / "worker.js").is_file():
            raise RuntimeError("Wrangler dry-run produced no compiled custom Worker")
        generated.update({
            f"custom-worker/{path}": digest
            for path, digest in file_hashes(custom_worker_bundle).items()
        })
    return generated


def worker_handlers(source: str) -> set[str]:
    handlers = {name for name, pattern in {
        "fetch": r"\bfetch\s*:", "email": r"\basync\s+email\s*\(",
        "queue": r"\basync\s+queue\s*\(", "scheduled": r"\bscheduled\s*\(",
    }.items() if re.search(pattern, source)}
    if "composeTenantWorker({" in source and all(token in source for token in (
        "site: siteAgentHandlers", "mailflare,", "mailflareQueueNames:", "basePath: \"/mail\"",
    )):
        return {"fetch", "email", "queue", "scheduled"}
    return handlers


def migration_ledger_head(applied: list[str]) -> str:
    """Stable identity for one ordered Payload migration ledger."""
    return hashlib.sha256(json.dumps(applied, separators=(",", ":")).encode()).hexdigest()


def uploaded_version_id(output: str) -> str:
    versions = re.findall(r"Worker Version ID:\s*([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})", output)
    if len(versions) != 1:
        raise RuntimeError("upload did not identify exactly one immutable Worker version")
    return versions[0]


def durable_object_migration_identity(migrations: Any) -> str | None:
    if not isinstance(migrations, list):
        raise RuntimeError("Worker Durable Object migrations are not an ordered list")
    if not migrations:
        return None
    if any(not isinstance(item, dict) or not isinstance(item.get("tag"), str) or not item["tag"]
           for item in migrations):
        raise RuntimeError("Worker Durable Object migrations have no exact tags")
    canonical = json.dumps(migrations, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def select_worker_rollout_mode(tenant_runs: Path,
                               migration_identity: str | None) -> tuple[str, str | None]:
    if migration_identity is None:
        return "versioned", None
    proven_release = None
    for path in sorted(tenant_runs.glob("*/receipt.json")):
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"cannot establish Durable Object lifecycle history from {path.parent.name}") from error
        lifecycle = prior.get("durableObjectLifecycle")
        if lifecycle is None:
            continue
        if not isinstance(lifecycle, dict):
            raise RuntimeError(f"invalid Durable Object lifecycle receipt: {path.parent.name}")
        if lifecycle.get("identity") != migration_identity:
            continue
        state = lifecycle.get("state")
        if state in {"applying", "outcome-unknown"}:
            if prior.get("releaseId") != path.parent.name:
                raise RuntimeError(f"Durable Object receipt identity is invalid: {path.parent.name}")
            from site_agent.application.durable_object_reconciliation import (
                LifecycleReconciliationError,
                read_lifecycle_reconciliation,
            )
            try:
                evidence = read_lifecycle_reconciliation(
                    tenant_runs.parent.parent, tenant_runs.name, prior,
                )
            except LifecycleReconciliationError as error:
                raise RuntimeError(
                    f"Durable Object lifecycle evidence is invalid in release {path.parent.name}"
                ) from error
            if evidence is None:
                raise RuntimeError(
                    f"Durable Object lifecycle outcome is unresolved in release {prior.get('releaseId')}; "
                    "the coordinator must prove the exact live deployment before queueing another release"
                )
            if evidence["migrationIdentity"] != migration_identity:
                raise RuntimeError(f"Durable Object reconciliation identity changed: {path.parent.name}")
            proven_release = prior["releaseId"]
            continue
        if state == "planned":
            continue
        if state == "applied":
            if lifecycle.get("strategy") != "atomic" or not prior.get("releaseId"):
                raise RuntimeError(f"Durable Object lifecycle proof is incomplete: {path.parent.name}")
            proven_release = prior["releaseId"]
            continue
        if state == "reused":
            source_release = lifecycle.get("appliedByReleaseId")
            if not isinstance(source_release, str) or not source_release:
                raise RuntimeError(f"Durable Object lifecycle reuse proof is incomplete: {path.parent.name}")
            proven_release = source_release
            continue
        raise RuntimeError(f"unknown Durable Object lifecycle state in receipt: {path.parent.name}")
    if proven_release:
        return "versioned", proven_release
    return "atomic", None


def deployed_worker_version_id(deployment: Any, previous_deployment: Any) -> str:
    if not isinstance(deployment, dict) or not deployment.get("id"):
        raise RuntimeError("atomic Worker deploy created no Cloudflare deployment identity")
    if isinstance(previous_deployment, dict) and deployment.get("id") == previous_deployment.get("id"):
        raise RuntimeError("atomic Worker deploy did not create a new Cloudflare deployment")
    versions = deployment.get("versions")
    if (not isinstance(versions, list) or len(versions) != 1
            or versions[0].get("percentage") != 100):
        raise RuntimeError("atomic Durable Object lifecycle deploy is not serving one version at 100%")
    version_id = versions[0].get("version_id")
    if not isinstance(version_id, str) or not UUID_RE.fullmatch(version_id):
        raise RuntimeError("atomic Worker deployment has no exact immutable version identity")
    return version_id




def wait_for_atomic_worker_version(customer: dict[str, Any], env: dict[str, str],
                                  previous_deployment: dict[str, Any]) -> tuple[dict[str, Any], str]:
    last_error: Exception = RuntimeError("Cloudflare has not recorded the atomic deployment yet")
    for attempt in range(12):
        try:
            deployment = cloudflare_deployment(customer, env)
        except OSError as error:
            last_error = error
        else:
            if deployment and deployment.get("id") != previous_deployment.get("id"):
                try:
                    version_id = deployed_worker_version_id(deployment, previous_deployment)
                except RuntimeError as error:
                    last_error = error
                else:
                    return deployment, version_id
        if attempt < 11:
            time.sleep(5)
    raise RuntimeError("Cloudflare did not expose the exact atomic 100% Worker deployment after 12 checks") from last_error


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
    if not UUID_RE.fullmatch(str(customer.get("mailflareD1DatabaseId") or "")) or customer["mailflareD1DatabaseId"].replace("-", "") == "0" * 32:
        raise ValueError("registered customer has no exact Mailflare D1 identity")
    if not re.fullmatch(r"[a-z0-9-]{1,63}", str(customer.get("mailflareD1DatabaseName") or "")):
        raise ValueError("registered customer has no exact Mailflare D1 name")
    if not re.fullmatch(r"[a-z0-9-]{3,63}", str(customer.get("r2BucketName") or "")):
        raise ValueError("registered customer has no exact tenant R2 bucket")
    for field in ("privateEmailR2BucketName", "mailflareR2BucketName", "mailflareInboundQueueName",
                  "mailflareOutboundQueueName", "mailflareAgentQueueName"):
        if not re.fullmatch(r"[a-z0-9-]{3,63}", str(customer.get(field) or "")):
            raise ValueError(f"registered customer has no exact {field} resource name")
    if len({customer["d1DatabaseName"], customer["mailflareD1DatabaseName"]}) != 2:
        raise ValueError("Payload and Mailflare databases must be tenant-isolated")
    if len({customer["r2BucketName"], customer["privateEmailR2BucketName"], customer["mailflareR2BucketName"]}) != 3:
        raise ValueError("public media, private email, and Mailflare files must use separate tenant buckets")


def validate_toolchain_manifest(manifest: dict[str, Any]) -> None:
    for field in ("nodeBin", "npmBin"):
        value = str(manifest.get(field) or "")
        if not value or not Path(value).is_absolute():
            raise ValueError(f"release toolchain requires an absolute {field}")
    for field in ("nodeVersion", "npmVersion"):
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get(field) or "")):
            raise ValueError(f"release toolchain requires an exact {field}")



def validate_worker_contract(worker_config: dict[str, Any], customer: dict[str, Any], tenant: str) -> None:
    if worker_config.get("d1Count") != 2:
        raise RuntimeError("Worker must have isolated Payload and Mailflare D1 databases")
    if worker_config.get("r2Count") != 3:
        raise RuntimeError("Worker must have exactly three canonical R2 bindings")
    if worker_config.get("d1Binding") != "D1":
        raise RuntimeError("Worker must use the canonical D1 binding name")
    d1_bindings = worker_config.get("d1Bindings")
    if (not isinstance(d1_bindings, list) or len(d1_bindings) != 2
            or {item.get("binding") for item in d1_bindings if isinstance(item, dict)} != {"D1", "MAILFLARE_DB"}):
        raise RuntimeError("Worker must declare separate Payload and Mailflare D1 bindings")
    if (worker_config.get("mailflareD1DatabaseId") != customer["mailflareD1DatabaseId"]
            or worker_config.get("mailflareD1DatabaseName") != customer["mailflareD1DatabaseName"]):
        raise RuntimeError("Worker Mailflare D1 identity differs from the exact registered tenant database")
    if worker_config.get("mailflareMigrationsDir") != ".mailflare/migrations":
        raise RuntimeError("Worker Mailflare D1 migration directory differs from the canonical source path")
    r2_bindings = worker_config.get("r2Bindings")
    if not isinstance(r2_bindings, list) or len(r2_bindings) != 3:
        raise RuntimeError("Worker must declare exactly the public, private-email and Mailflare R2 bindings")
    buckets = {
        str(item.get("binding") or ""): str(item.get("bucketName") or "")
        for item in r2_bindings if isinstance(item, dict)
    }
    if buckets != {"R2": customer["r2BucketName"], "PRIVATE_EMAIL": customer["privateEmailR2BucketName"],
                   "MAILFLARE_BUCKET": customer["mailflareR2BucketName"]}:
        raise RuntimeError("Worker R2 bindings differ from the exact registered tenant buckets")
    if worker_config.get("r2Binding") != "R2" or worker_config.get("r2BucketName") != customer["r2BucketName"]:
        raise RuntimeError("Worker must use the canonical public R2 binding")
    try:
        datetime.strptime(str(worker_config.get("compatibilityDate") or ""), "%Y-%m-%d")
    except ValueError as error:
        raise RuntimeError("Worker compatibility date is missing or invalid") from error
    flags = worker_config.get("compatibilityFlags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) or not flag for flag in flags):
        raise RuntimeError("Worker compatibility flags are missing or invalid")
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
            or worker_config.get("d1DatabaseName") != customer["d1DatabaseName"]):
        raise RuntimeError("Worker migration chain or tenant D1 identity does not match the registry")
    queues = worker_config.get("queues")
    consumers = queues.get("consumers") if isinstance(queues, dict) else None
    if not isinstance(consumers, list) or len(consumers) != 3 or any(not isinstance(item, dict) for item in consumers):
        raise RuntimeError("Worker must declare exactly the three Mailflare Queue consumers")
    by_queue = {item.get("queue"): item for item in consumers}
    expected_queue_names = {
        "MAILFLARE_INBOUND_QUEUE": customer["mailflareInboundQueueName"],
        "MAILFLARE_OUTBOUND_QUEUE": customer["mailflareOutboundQueueName"],
        "MAILFLARE_AGENT_QUEUE": customer["mailflareAgentQueueName"],
    }
    expected_queues = set(expected_queue_names.values())
    if set(by_queue) != expected_queues or any(item.get("dead_letter_queue") for item in consumers):
        raise RuntimeError("Worker Queue consumers must match the three registered Mailflare queues exactly")
    if worker_config.get("queueProducerCount") != 3 or worker_config.get("queueConsumerCount") != 3:
        raise RuntimeError("Worker must bind exactly three Mailflare queue producers and consumers")
    if worker_config.get("mailflareQueueNames") != expected_queue_names:
        raise RuntimeError("Worker Mailflare producer names differ from the registered tenant Queues")
    for config in consumers:
        worker_queue_consumer_settings(config)
    if (worker_config.get("main") != "worker.ts" or worker_config.get("sendEmailBinding") is not True
            or worker_config.get("sendEmailBindingCount") != 1):
        raise RuntimeError("Worker must upload the canonical custom entrypoint and exactly one Cloudflare email binding")
    if worker_config.get("turnstileSiteKey"):
        raise RuntimeError("Turnstile sitekeys must be provisioned by the release pipeline, not committed in tenant source")
    if worker_config.get("turnstileSecretInVars"):
        raise RuntimeError("Turnstile secrets must be supplied through the protected Worker secret file")
    limits = worker_config.get("rateLimitBindings")
    if not isinstance(limits, list) or len(limits) != 4:
        raise RuntimeError("Worker must define all four canonical site and Mailflare rate-limit bindings")
    limits_by_name = {str(item.get("name") or ""): str(item.get("namespaceId") or "")
                      for item in limits if isinstance(item, dict)}
    if set(limits_by_name) != {"HELLOADA_FORM_RATE_LIMIT", "MAILFLARE_BOOKING_RATE_LIMIT",
                               "MAILFLARE_LOGIN_RATE_LIMIT", "MAILFLARE_AGENT_RATE_LIMIT"}:
        raise RuntimeError("Worker rate-limit binding names do not match the site-agent and Mailflare contracts")
    namespace_ids = list(limits_by_name.values())
    if any(not value.isdigit() or int(value) < 1 for value in namespace_ids) or len(set(namespace_ids)) != 4:
        raise RuntimeError("Worker rate-limit namespaces must be distinct positive Cloudflare account identifiers")
    required_handlers = {"fetch", "email", "queue", "scheduled"}
    if not required_handlers.issubset(set(worker_config.get("handlers") or [])):
        raise RuntimeError("Worker custom entrypoint is missing a required event handler")
    crons = worker_config.get("crons")
    if crons != ["*/5 * * * *", "0 2 * * *"]:
        raise RuntimeError("Worker must declare Mailflare's canonical maintenance schedules")
    if worker_config.get("durableObjectBindings") != [{"name": "MAILFLARE_REALTIME", "className": "RealtimeHub"}]:
        raise RuntimeError("Worker must bind Mailflare RealtimeHub exactly once")
    if worker_config.get("durableObjectMigrations") != [{"tag": "v1", "newSqliteClasses": ["RealtimeHub"]}]:
        raise RuntimeError("Worker must declare Mailflare RealtimeHub's SQLite migration exactly once")
    if worker_config.get("aiBinding") != "MAILFLARE_AI":
        raise RuntimeError("Worker must bind Mailflare to tenant Workers AI")


def worker_cron_schedules(customer: dict[str, Any], env: dict[str, str]) -> list[str]:
    """Read the exact active Cloudflare schedules for this registered Worker."""
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
        + "/workers/scripts/"
        + urllib.parse.quote(customer["worker"], safe="")
        + "/schedules"
    )
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Cloudflare Worker schedule inspection failed with HTTP {error.code}") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Cloudflare Worker schedule inspection returned no valid response") from error
    if payload.get("success") is not True:
        raise RuntimeError("Cloudflare Worker schedule inspection failed")
    result = payload.get("result")
    schedules = result.get("schedules") if isinstance(result, dict) else None
    if not isinstance(schedules, list):
        raise RuntimeError("Cloudflare Worker schedule response has no schedules list")
    crons = [item.get("cron") for item in schedules if isinstance(item, dict)]
    if len(crons) != len(schedules) or any(not isinstance(cron, str) or not cron.strip() for cron in crons):
        raise RuntimeError("Cloudflare Worker schedule response contains an invalid schedule")
    if len(crons) != len(set(crons)):
        raise RuntimeError("Cloudflare Worker schedule response contains duplicate cron expressions")
    return sorted(crons)


def reconcile_worker_cron_schedules(
    customer: dict[str, Any], desired: list[str], env: dict[str, str],
) -> dict[str, Any]:
    """Reconcile schedules to the committed Wrangler contract and verify Cloudflare's result."""
    if desired != ["*/5 * * * *", "0 2 * * *"]:
        raise ValueError("release requires the exact canonical Mailflare schedules")
    before = worker_cron_schedules(customer, env)
    changed = before != desired
    if changed:
        url = (
            "https://api.cloudflare.com/client/v4/accounts/"
            + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
            + "/workers/scripts/"
            + urllib.parse.quote(customer["worker"], safe="")
            + "/schedules"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps([{"cron": cron} for cron in desired]).encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Cloudflare Worker schedule update failed with HTTP {error.code}") from error
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("Cloudflare Worker schedule update returned no valid response") from error
        if payload.get("success") is not True:
            raise RuntimeError("Cloudflare Worker schedule update failed")
    after = worker_cron_schedules(customer, env)
    if after != desired:
        raise RuntimeError("Cloudflare Worker schedules differ from the committed deployment contract")
    return {"before": before, "desired": desired, "after": after, "changed": changed, "verifiedAt": utc_now()}


def worker_queue_consumer_detail(
    queue_id: str, consumer_id: str, env: dict[str, str],
) -> dict[str, Any]:
    """Read one consumer's authoritative Worker identity and normalize its API field."""
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
        + "/queues/" + urllib.parse.quote(queue_id, safe="") + "/consumers"
        + "/" + urllib.parse.quote(consumer_id, safe="")
    )
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Cloudflare Queue consumer inspection failed with HTTP {error.code}") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Cloudflare Queue consumer inspection returned no valid response") from error
    consumer = payload.get("result")
    if (payload.get("success") is not True or not isinstance(consumer, dict)
            or consumer.get("consumer_id") != consumer_id):
        raise RuntimeError("Cloudflare Queue consumer detail did not match the requested identity")
    # Cloudflare's list endpoint currently returns script_name as null while
    # the detail endpoint returns the actual Worker under `script`. Normalize
    # that provider response to one internal contract before comparing it.
    if consumer.get("script_name") is None and isinstance(consumer.get("script"), str):
        consumer["script_name"] = consumer["script"]
    return consumer


def worker_queue_consumers(queue_id: str, env: dict[str, str]) -> list[dict[str, Any]]:
    """Read the live consumer registrations for one provisioned Cloudflare Queue."""
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
        + "/queues/" + urllib.parse.quote(queue_id, safe="") + "/consumers"
    )
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Cloudflare Queue consumer inspection failed with HTTP {error.code}") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Cloudflare Queue consumer inspection returned no valid response") from error
    consumers = payload.get("result")
    if payload.get("success") is not True or not isinstance(consumers, list):
        raise RuntimeError("Cloudflare Queue consumer inspection failed")
    if any(not isinstance(item, dict) or not isinstance(item.get("consumer_id"), str)
           or not item["consumer_id"] for item in consumers):
        raise RuntimeError("Cloudflare Queue consumer response contains an invalid consumer")
    return [worker_queue_consumer_detail(queue_id, item["consumer_id"], env) for item in consumers]


def worker_queue_consumer_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Translate the committed Wrangler consumer settings to Cloudflare's API shape."""
    settings = {
        "batch_size": config.get("max_batch_size"),
        "max_concurrency": config.get("max_concurrency"),
        "max_retries": config.get("max_retries"),
        "max_wait_time_ms": config.get("max_batch_timeout", 5) * 1000,
        "retry_delay": config.get("retry_delay", 0),
    }
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in settings.values()):
        raise RuntimeError("committed Worker Queue consumer settings are invalid")
    if settings["batch_size"] < 1 or settings["max_concurrency"] < 1:
        raise RuntimeError("committed Worker Queue consumer limits must be positive")
    return settings


def worker_queue_consumer_matches(actual: dict[str, Any], desired: dict[str, Any]) -> bool:
    settings = actual.get("settings")
    if not isinstance(settings, dict):
        return False
    return (
        actual.get("type") == desired["type"]
        and actual.get("script_name") == desired["script_name"]
        and (actual.get("dead_letter_queue") or "") == desired.get("dead_letter_queue", "")
        and all(settings.get(key) == value for key, value in desired["settings"].items())
    )


def reconcile_worker_queue_consumer(
    queue_id: str, queue_name: str, desired: dict[str, Any], env: dict[str, str],
) -> dict[str, Any]:
    """Idempotently attach one registered Worker and fail closed on competing consumers."""
    before = worker_queue_consumers(queue_id, env)
    if len(before) > 1:
        raise RuntimeError(f"Cloudflare Queue {queue_name} has multiple consumers; refusing ambiguous ownership")
    if before:
        existing = before[0]
        if existing.get("type") != "worker" or existing.get("script_name") != desired["script_name"]:
            raise RuntimeError(f"Cloudflare Queue {queue_name} is attached to an unexpected consumer")
        changed = not worker_queue_consumer_matches(existing, desired)
        method = "PUT"
        url = (
            "https://api.cloudflare.com/client/v4/accounts/"
            + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
            + "/queues/" + urllib.parse.quote(queue_id, safe="")
            + "/consumers/" + urllib.parse.quote(existing["consumer_id"], safe="")
        )
    else:
        changed = True
        method = "POST"
        url = (
            "https://api.cloudflare.com/client/v4/accounts/"
            + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
            + "/queues/" + urllib.parse.quote(queue_id, safe="") + "/consumers"
        )
    if changed:
        request = urllib.request.Request(
            url,
            data=json.dumps(desired).encode("utf-8"),
            method=method,
            headers={
                "Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Cloudflare Queue consumer reconciliation failed with HTTP {error.code}") from error
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("Cloudflare Queue consumer reconciliation returned no valid response") from error
        if payload.get("success") is not True:
            raise RuntimeError("Cloudflare Queue consumer reconciliation failed")
    after = worker_queue_consumers(queue_id, env)
    if len(after) != 1 or not worker_queue_consumer_matches(after[0], desired):
        raise RuntimeError(f"Cloudflare Queue {queue_name} differs from the committed consumer contract")
    return {
        "queue": queue_name,
        "queueId": queue_id,
        "consumerId": after[0]["consumer_id"],
        "desired": desired,
        "verified": True,
        "changed": changed,
        "verifiedAt": utc_now(),
    }


def reconcile_worker_queue_consumers(
    customer: dict[str, Any], worker_config: dict[str, Any], resources: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    """Apply and verify all three Mailflare Queue consumers for one tenant."""
    queue_config = worker_config.get("queues")
    configured = queue_config.get("consumers") if isinstance(queue_config, dict) else None
    expected_names = {
        customer["mailflareInboundQueueName"], customer["mailflareOutboundQueueName"],
        customer["mailflareAgentQueueName"],
    }
    if not isinstance(configured, list) or len(configured) != len(expected_names):
        raise RuntimeError("committed Worker must define all three Mailflare Queue consumers")
    if any(not isinstance(item, dict) for item in configured):
        raise RuntimeError("committed Worker Queue consumer contract is invalid")
    if {item.get("queue") for item in configured} != expected_names:
        raise RuntimeError("committed Worker Queue consumers do not match the registered tenant Queues")
    by_name = {item["queue"]: item for item in configured}
    if any(item.get("dead_letter_queue") for item in configured):
        raise RuntimeError("Mailflare Queue consumers must not reference a second legacy dead-letter path")
    mailflare_queues = resources.get("mailflareQueues")
    mailflare_queues = mailflare_queues if isinstance(mailflare_queues, dict) else {}
    provisioned = {
        customer["mailflareInboundQueueName"]: mailflare_queues.get("inbound", {}),
        customer["mailflareOutboundQueueName"]: mailflare_queues.get("outbound", {}),
        customer["mailflareAgentQueueName"]: mailflare_queues.get("agent", {}),
    }
    queue_ids = {name: item.get("queue_id") for name, item in provisioned.items() if isinstance(item, dict)}
    if (set(queue_ids) != expected_names
            or any(not isinstance(queue_id, str) or not queue_id for queue_id in queue_ids.values())
            or len(set(queue_ids.values())) != len(expected_names)):
        raise RuntimeError("all three isolated tenant Mailflare Queue IDs are required before consumer reconciliation")
    results = []
    for config in configured:
        queue_name = config["queue"]
        desired = {
            "script_name": customer["worker"],
            "type": "worker",
            "settings": worker_queue_consumer_settings(config),
        }
        if config.get("dead_letter_queue"):
            desired["dead_letter_queue"] = config["dead_letter_queue"]
        results.append(reconcile_worker_queue_consumer(
            queue_ids[queue_name], queue_name, desired, env,
        ))
    return {"consumers": results, "verified": all(item["verified"] for item in results)}

def d1_query(
    customer: dict[str, Any], sql: str, env: dict[str, str], params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
           + "/d1/database/" + urllib.parse.quote(customer["d1DatabaseId"], safe="") + "/query")
    request = urllib.request.Request(
        url,
        data=json.dumps({"sql": sql, "params": list(params)}).encode(),
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


def mailflare_d1_query(customer: dict[str, Any], sql: str, env: dict[str, str],
                       params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
           + "/d1/database/" + urllib.parse.quote(customer["mailflareD1DatabaseId"], safe="") + "/query")
    request = urllib.request.Request(
        url,
        data=json.dumps({"sql": sql, "params": list(params)}).encode(),
        method="POST",
        headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"],
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Mailflare D1 schema inspection failed: {type(error).__name__}") from error
    if body.get("success") is not True or not isinstance(body.get("result"), list) or len(body["result"]) != 1:
        raise RuntimeError("Cloudflare did not return one successful Mailflare D1 query result")
    result = body["result"][0]
    if result.get("success") is not True or not isinstance(result.get("results"), list):
        raise RuntimeError("Cloudflare Mailflare D1 query did not complete successfully")
    return result["results"]


def applied_mailflare_migrations(customer: dict[str, Any], env: dict[str, str]) -> tuple[list[str], list[str]]:
    rows = mailflare_d1_query(
        customer,
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ? ORDER BY name",
        env,
        ("table", "sqlite_%"),
    )
    tables = [str(row.get("name") or "") for row in rows
              if str(row.get("name") or "") not in D1_SYSTEM_TABLES]
    if "d1_migrations" not in tables:
        return tables, []
    applied_rows = mailflare_d1_query(customer, "SELECT name FROM d1_migrations ORDER BY id ASC", env)
    return tables, [str(row.get("name") or "") for row in applied_rows]


def mailflare_migration_head(names: list[str]) -> str:
    return hashlib.sha256(json.dumps(names, separators=(",", ":")).encode()).hexdigest()


def reconcile_mailflare_migrations(checkout: Path, customer: dict[str, Any],
                                   env: dict[str, str], base: dict[str, str]) -> dict[str, Any]:
    """Apply the pinned SQL chain using Wrangler's rollback-aware D1 migration system."""
    migration_dir = checkout / ".mailflare/migrations"
    provenance = json.loads((checkout / ".mailflare/provenance.json").read_text())
    expected = provenance.get("migrationNames")
    files = sorted(path.name for path in migration_dir.glob("*.sql") if path.is_file())
    if not isinstance(expected, list) or not expected or files != expected:
        raise RuntimeError("Mailflare migration files do not match their pinned build receipt")
    if len(set(expected)) != len(expected) or any(not re.fullmatch(r"\d{4}_[a-z0-9_-]+\.sql", name) for name in expected):
        raise RuntimeError("Mailflare migration filenames are not a unique canonical sequence")

    tables, applied = applied_mailflare_migrations(customer, env)
    if "d1_migrations" not in tables and any(name not in D1_SYSTEM_TABLES for name in tables):
        raise RuntimeError("Mailflare D1 contains application tables without its migration ledger")
    if len(set(applied)) != len(applied) or expected[:len(applied)] != applied:
        raise RuntimeError("Mailflare D1 migration ledger is not a prefix of the pinned schema")
    changed = applied != expected
    if changed:
        command = [str(checkout / "node_modules/.bin/wrangler"), "d1", "migrations", "apply",
                   "MAILFLARE_DB", "--remote", "--config", "wrangler.jsonc"]
        run(command, checkout, {**base, **env, "CI": "1"})
        tables, applied = applied_mailflare_migrations(customer, env)
    if "d1_migrations" not in tables or applied != expected:
        raise RuntimeError("Mailflare D1 migration ledger differs from the pinned schema after Wrangler apply")
    return {
        "names": expected,
        "head": mailflare_migration_head(expected),
        "sourceSha256": provenance["migrationsSha256"],
        "changed": changed,
        "verifiedAt": utc_now(),
    }


def mailflare_migration_receipt(receipt: dict[str, Any]) -> tuple[list[str], str]:
    contract = receipt.get("mailflareMigrations")
    names = contract.get("names") if isinstance(contract, dict) else None
    package = receipt.get("mailflare")
    if (not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not re.fullmatch(r"\d{4}_[a-z0-9_-]+\.sql", name) for name in names)
            or len(set(names)) != len(names)
            or contract.get("head") != mailflare_migration_head(names)
            or not SHA256_RE.fullmatch(str(contract.get("sourceSha256") or ""))
            or not isinstance(package, dict)
            or package.get("migrationNames") != names
            or package.get("migrationsSha256") != contract.get("sourceSha256")):
        raise RuntimeError("release receipt does not identify an exact Mailflare migration chain")
    return names, str(contract["sourceSha256"])


def verify_mailflare_migrations(receipt: dict[str, Any], customer: dict[str, Any],
                                env: dict[str, str]) -> None:
    names, _source_sha256 = mailflare_migration_receipt(receipt)
    tables, applied = applied_mailflare_migrations(customer, env)
    if "d1_migrations" not in tables or applied != names:
        raise RuntimeError("live Mailflare D1 migration ledger differs from the exact deployed release")


def applied_payload_migrations(customer: dict[str, Any], env: dict[str, str]) -> tuple[list[str], list[str]]:
    tables = d1_query(
        customer,
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ? ORDER BY name",
        env,
        ("table", "sqlite_%"),
    )
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


def run_payload_migration(checkout: Path, customer: dict[str, Any], worker_config: dict[str, Any],
                          env: dict[str, str], base: dict[str, str], manifest: dict[str, Any],
                          tenant: str, temporary_directory: Path) -> str:
    config_path = payload_remote_bindings_config_file(temporary_directory, customer, worker_config)
    try:
        runtime = tenant_runtime_secrets(manifest, tenant)
        migration_env = {
            **base, **env, **runtime,
            "NODE_ENV": "production",
            "PAYLOAD_CLI": "1",
            "HELLOADA_CLOUDFLARE_CONFIG_PATH": str(config_path),
        }
        return run(payload_migration_command(manifest), checkout, migration_env)
    finally:
        config_path.unlink(missing_ok=True)


def run_payload_contract_verifier(checkout: Path, customer: dict[str, Any],
                                   worker_config: dict[str, Any], env: dict[str, str],
                                   base: dict[str, str], temporary_directory: Path) -> str:
    config_path = payload_remote_bindings_config_file(temporary_directory, customer, worker_config)
    try:
        website_present = customer.get("websitePresent")
        if not isinstance(website_present, bool):
            raise RuntimeError("release manifest must explicitly declare websitePresent")
        verifier_env = {
            **base, **env,
            "HELLOADA_CLOUDFLARE_CONFIG_PATH": str(config_path),
            "HELLOADA_WEBSITE_PRESENT": "true" if website_present else "false",
        }
        return run(["npm", "run", "verify:payload"], checkout, verifier_env)
    finally:
        config_path.unlink(missing_ok=True)


def enforce_payload_migrations(checkout: Path, customer: dict[str, Any], env: dict[str, str],
                               initialization_head: str | None, migration_from_ledger: str | None,
                               base: dict[str, str],
                               manifest: dict[str, Any], tenant: str, stage: Any,
                               worker_config: dict[str, Any], temporary_directory: Path) -> list[str]:
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
        run_payload_migration(checkout, customer, worker_config, env, base, manifest, tenant, temporary_directory)
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
        run_payload_migration(checkout, customer, worker_config, env, base, manifest, tenant, temporary_directory)
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


def worker_version_identity(version: Any) -> dict[str, str]:
    """Fingerprint code and non-secret bindings without including secret values."""
    resources = version.get("resources") if isinstance(version, dict) else None
    script = resources.get("script") if isinstance(resources, dict) else None
    bindings = resources.get("bindings") if isinstance(resources, dict) else None
    etag = script.get("etag") if isinstance(script, dict) else None
    if not isinstance(etag, str) or not etag or not isinstance(bindings, list):
        raise RuntimeError("Cloudflare Worker version has incomplete code or binding identity")

    normalized_bindings = []
    names = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise RuntimeError("Cloudflare Worker version has an invalid binding")
        name = binding.get("name")
        binding_type = binding.get("type")
        if not isinstance(name, str) or not name or not isinstance(binding_type, str) or not binding_type:
            raise RuntimeError("Cloudflare Worker version has an incomplete binding identity")
        if name in names:
            raise RuntimeError("Cloudflare Worker version has duplicate binding names")
        names.add(name)
        if binding_type in {"secret_text", "secret_key"}:
            normalized = {
                key: binding[key]
                for key in ("name", "type", "algorithm", "format")
                if key in binding
            }
        else:
            normalized = binding
        normalized_bindings.append(normalized)
    normalized_bindings.sort(key=lambda item: item["name"])
    identity = hashlib.sha256(
        json.dumps(normalized_bindings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"script_etag": etag, "binding_identity": identity}


def cloudflare_worker_version_identity(
    customer: dict[str, Any], version_id: str, env: dict[str, str],
) -> dict[str, str]:
    """Read code and non-secret binding identity without returning secret values."""
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
        + "/workers/scripts/"
        + urllib.parse.quote(customer["worker"], safe="")
        + "/versions/"
        + urllib.parse.quote(version_id, safe="")
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Cloudflare Worker version inspection failed with HTTP {error.code}") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Cloudflare Worker version inspection returned no valid response") from error
    if payload.get("success") is not True:
        raise RuntimeError("Cloudflare Worker version inspection failed")
    version = payload.get("result")
    if not isinstance(version, dict) or version.get("id") != version_id:
        raise RuntimeError("Cloudflare Worker version identity does not match the requested version")
    return worker_version_identity(version)


def require_active_worker_snapshot(
    customer: dict[str, Any], deploy_env: dict[str, str], deployment_id: str, version_id: str,
) -> None:
    """Require the observed production deployment/version to remain unchanged."""
    current = cloudflare_deployment(customer, deploy_env)
    versions = current.get("versions")
    if (
        current.get("id") != deployment_id
        or not isinstance(versions, list)
        or len(versions) != 1
        or versions[0].get("version_id") != version_id
        or versions[0].get("percentage") != 100
    ):
        raise RuntimeError("the active Worker version changed during readiness verification")


def resolve_verified_active_worker(
    customer: dict[str, Any], deploy_env: dict[str, str], uploaded_version: str,
) -> tuple[dict[str, Any], str, dict[str, str], dict[str, str]]:
    """Resolve a stable active version and prove any replacement is secret-only."""
    changed_message = "the active Worker version changed during readiness verification"
    for attempt in range(8):
        deployment = cloudflare_deployment(customer, deploy_env)
        versions = deployment.get("versions")
        if not isinstance(versions, list) or len(versions) != 1 or versions[0].get("percentage") != 100:
            raise RuntimeError("Cloudflare production deployment does not have exactly one 100%-traffic Worker version")
        active_version = versions[0].get("version_id")
        deployment_id = deployment.get("id")
        if not isinstance(active_version, str) or not active_version or not isinstance(deployment_id, str) or not deployment_id:
            raise RuntimeError("Cloudflare production deployment has no active Worker identity")
        if active_version != uploaded_version:
            annotations = deployment.get("annotations")
            if not isinstance(annotations, dict) or annotations.get("workers/triggered_by") != "secret":
                raise RuntimeError("the active Worker differs from the release outside a secret-only update")
        uploaded_identity = cloudflare_worker_version_identity(customer, uploaded_version, deploy_env)
        active_identity = (
            uploaded_identity
            if active_version == uploaded_version
            else cloudflare_worker_version_identity(customer, active_version, deploy_env)
        )
        if uploaded_identity != active_identity:
            raise RuntimeError("the active Worker code or non-secret bindings differ from the exact release")
        try:
            require_active_worker_snapshot(customer, deploy_env, deployment_id, active_version)
        except RuntimeError as error:
            if str(error) != changed_message or attempt == 7:
                raise
            time.sleep(0.25)
            continue
        return deployment, active_version, uploaded_identity, active_identity
    raise RuntimeError("Cloudflare production deployment kept changing during readiness verification")


def record_current_verification(
    receipt: dict[str, Any], deployment: dict[str, Any], active_version: str,
    uploaded_identity: dict[str, str], active_identity: dict[str, str],
) -> None:
    receipt["currentVerification"] = {
        "releaseId": receipt["releaseId"],
        "sourceSha": receipt["sourceSha"],
        "uploadedVersion": receipt["uploadedVersion"],
        "workerVersion": active_version,
        "deploymentId": deployment["id"],
        "trafficPercentage": 100,
        "uploadedScriptEtag": uploaded_identity["script_etag"],
        "activeScriptEtag": active_identity["script_etag"],
        "uploadedBindingIdentity": uploaded_identity["binding_identity"],
        "activeBindingIdentity": active_identity["binding_identity"],
        "mode": "exact" if active_version == receipt["uploadedVersion"] else "secret_rotation",
        "verifiedAt": utc_now(),
    }



def tenant_environment_path(manifest: dict[str, Any], tenant: str) -> Path:
    """Resolve the exact registered tenant environment file on the protected VPS."""
    import yaml
    from site_agent.application.tenant_registration import provisioned_root

    config_path = Path(manifest["connectionGate"]["config"]).resolve()
    host_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(host_config, dict):
        raise ValueError("host API config root is invalid")
    root = provisioned_root(host_config).resolve()
    index = json.loads((root / "tenants.json").read_text(encoding="utf-8"))
    entry = index.get(tenant)
    if not isinstance(entry, dict):
        raise ValueError("tenant is not registered on this VPS")
    registered_config = Path(str(entry.get("config_path") or "")).resolve()
    expected_config = (root / tenant / "config.yaml").resolve()
    env_path = (root / tenant / "tenant.env").resolve()
    if (registered_config != expected_config or root not in registered_config.parents
            or env_path.parent != expected_config.parent or root not in env_path.parents
            or not env_path.is_file()):
        raise ValueError("registered tenant environment path is inconsistent")
    return env_path


def read_tenant_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("tenant secret file contains a malformed line")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            raise ValueError("tenant secret file contains an invalid or duplicate name")
        values[key] = value.strip()
    return values


def write_tenant_environment(manifest: dict[str, Any], tenant: str, updates: dict[str, str]) -> None:
    """Atomically persist only the pipeline-owned Turnstile pair in the registered tenant env."""
    allowed = {"HELLOADA_TURNSTILE_SITE_KEY", "HELLOADA_TURNSTILE_SECRET_KEY"}
    if set(updates) != allowed or any(not value or "\n" in value or "\r" in value for value in updates.values()):
        raise ValueError("Turnstile provisioning returned an invalid tenant credential pair")
    path = tenant_environment_path(manifest, tenant)
    lock_path = path.parent / ".tenant-env.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    temporary: Path | None = None
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        values = read_tenant_environment(path)
        values.update(updates)
        descriptor, filename = tempfile.mkstemp(prefix=".tenant-env-", suffix=".tmp", dir=path.parent)
        temporary = Path(filename)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                for key, value in sorted(values.items()):
                    stream.write(f"{key}={value}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def provision_tenant_mail_resources(customer: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """Ensure exact tenant D1, R2 and Queue resources required by Mailflare and forms."""
    from site_agent.hands.cloudflare_resources import CloudflareResourceProvisioner
    from site_agent.hands.cloudflare_r2 import CloudflareR2Provisioner

    account_id = env["CLOUDFLARE_ACCOUNT_ID"]
    token = env["CLOUDFLARE_API_TOKEN"]
    resources = CloudflareResourceProvisioner(account_id, token)
    buckets = CloudflareR2Provisioner(account_id, token)
    mailflare_database = resources.ensure_d1(customer["mailflareD1DatabaseName"])
    if mailflare_database.database_id.lower() != customer["mailflareD1DatabaseId"].lower():
        raise RuntimeError("provisioned Mailflare D1 ID differs from the registered tenant identity")
    private_bucket_created = buckets.ensure_bucket(customer["privateEmailR2BucketName"])
    mailflare_bucket_created = buckets.ensure_bucket(customer["mailflareR2BucketName"])
    inbound = resources.ensure_queue(customer["mailflareInboundQueueName"])
    outbound = resources.ensure_queue(customer["mailflareOutboundQueueName"])
    agent = resources.ensure_queue(customer["mailflareAgentQueueName"])
    return {
        "mailflareD1": mailflare_database.to_dict(),
        "privateEmailR2": {"bucket": customer["privateEmailR2BucketName"], "created": bool(private_bucket_created)},
        "mailflareR2": {"bucket": customer["mailflareR2BucketName"], "created": bool(mailflare_bucket_created)},
        "mailflareQueues": {
            "inbound": inbound.to_dict(),
            "outbound": outbound.to_dict(),
            "agent": agent.to_dict(),
        },
    }


def provision_turnstile_for_tenant(
    tenant: str,
    customer: dict[str, Any],
    worker_config: dict[str, Any],
    manifest: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    """Ensure the per-tenant Turnstile widget exactly matches registered production hostnames."""
    from site_agent.hands.cloudflare_turnstile import CloudflareTurnstileProvisioner

    domains = {str(domain).strip().lower().rstrip(".") for domain in worker_config.get("publicDomains", []) if str(domain).strip()}
    health = urllib.parse.urlsplit(str(customer.get("health") or ""))
    if health.scheme != "https" or not health.hostname:
        raise RuntimeError("registered tenant health URL cannot establish a verified Turnstile hostname")
    domains.add(health.hostname.lower().rstrip("."))
    if not domains:
        raise RuntimeError("tenant source and registry contain no production Turnstile hostname")
    tenant_env_path = tenant_environment_path(manifest, tenant)
    stored = read_tenant_environment(tenant_env_path)
    provisioner = CloudflareTurnstileProvisioner(env["CLOUDFLARE_ACCOUNT_ID"], env["CLOUDFLARE_API_TOKEN"])
    receipt = provisioner.ensure_widget(
        tenant, sorted(domains),
        sitekey=stored.get("HELLOADA_TURNSTILE_SITE_KEY"),
        secret=stored.get("HELLOADA_TURNSTILE_SECRET_KEY"),
    )
    write_tenant_environment(manifest, tenant, {
        "HELLOADA_TURNSTILE_SITE_KEY": receipt.sitekey,
        "HELLOADA_TURNSTILE_SECRET_KEY": receipt.secret,
    })
    return {"sitekey": receipt.sitekey, "domains": list(receipt.domains), "created": receipt.created}




def tenant_email_auto_provisioning_enabled(environment_path: Path) -> bool:
    """Return the registered policy that permits a first Mailflare bootstrap release."""
    import yaml

    config_path = environment_path.with_name("config.yaml")
    try:
        tenant_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError("registered tenant email provisioning policy is unavailable") from error
    if not isinstance(tenant_config, dict):
        raise ValueError("registered tenant configuration is invalid")
    messages = tenant_config.get("messages")
    email = messages.get("email") if isinstance(messages, dict) else None
    provisioning = email.get("provisioning") if isinstance(email, dict) else None
    return bool(
        isinstance(email, dict)
        and email.get("enabled") is True
        and isinstance(provisioning, dict)
        and provisioning.get("auto") is True
    )


def trigger_email_provisioning_after_worker_release(
    manifest: dict[str, Any],
    tenant: str,
) -> dict[str, str]:
    """Wake the canonical tenant scheduler after its exact Worker passes health gates."""
    import yaml
    from site_agent.core.memory import Memory

    customer = (manifest.get("customers") or {}).get(tenant)
    if not isinstance(customer, dict) or not customer.get("mailflareD1DatabaseId"):
        return {"state": "not-configured"}
    environment_path = tenant_environment_path(manifest, tenant)
    if not tenant_email_auto_provisioning_enabled(environment_path):
        return {"state": "manual"}
    runtime_names = ("MAILFLARE_ADDRESS", "MAILFLARE_ZONE_ID", "MAILFLARE_ROUTING_STATUS")
    runtime_values = {name: str(value or "").strip() for name, value in read_tenant_environment(environment_path).items()
                      if name in runtime_names}
    present = [bool(runtime_values.get(name)) for name in runtime_names]
    if any(present) and not all(present):
        raise RuntimeError("registered tenant Mailflare runtime settings are incomplete")

    config_path = environment_path.with_name("config.yaml")
    tenant_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(tenant_config, dict) or tenant_config.get("instance_name") != tenant:
        raise RuntimeError("registered tenant configuration identity does not match the release")
    data_dir_value = str(tenant_config.get("data_dir") or "").strip()
    configured_data_dir = Path(data_dir_value).expanduser() if data_dir_value else Path("/")
    if not configured_data_dir.is_absolute():
        raise RuntimeError("registered tenant memory path must be absolute")
    data_dir = configured_data_dir.resolve()
    if data_dir == Path(data_dir.anchor) or data_dir.name != "data" or data_dir.parent.name != tenant:
        raise RuntimeError("registered tenant memory path is not canonical")
    memory_path = data_dir / "memory.db"
    if not memory_path.is_file():
        raise RuntimeError("registered tenant scheduler state is unavailable")

    memory = Memory(memory_path)
    try:
        previous = memory.kv_get("email_provisioning_state", {})
        previous = previous if isinstance(previous, dict) else {}
        if all(present) and previous.get("state") == "active":
            return {"state": "active"}
        memory.kv_set("next_run:email_provisioning", round(time.time(), 3))
        previous_state = str(previous.get("state") or "uninitialized")
        return {"state": "scheduled", "previousState": previous_state}
    finally:
        memory.close()


def tenant_runtime_secrets(manifest: dict[str, Any], tenant: str) -> dict[str, str]:
    """Load only this registered tenant's explicit Worker secrets from its protected VPS env."""

    try:
        from site_agent.application.tenant_registration import (
            WORKER_SITE_AGENT_TOKEN_ENV,
            tenant_token_env,
        )

        worker_manifest_path = ROOT / "src/site_agent/templates/next-payload/template-manifest.json"
        worker_manifest = json.loads(worker_manifest_path.read_text(encoding="utf-8"))
        worker_token_env = str(worker_manifest.get("workerTokenEnv") or "").strip()
        if worker_token_env != WORKER_SITE_AGENT_TOKEN_ENV:
            raise ValueError("canonical Worker token binding differs from the tenant registration contract")
        registered_customers = manifest.get("customers")
        customer = registered_customers.get(tenant) if isinstance(registered_customers, dict) else None
        if not isinstance(customer, dict):
            raise ValueError("registered tenant release manifest entry is unavailable")
        environment_path = tenant_environment_path(manifest, tenant)
        values = read_tenant_environment(environment_path)
        required = {"PAYLOAD_SECRET", tenant_token_env(tenant)}
        if any(not values.get(key) for key in required):
            raise ValueError("registered tenant runtime secrets are incomplete")
        mailflare_names = ("MAILFLARE_ADDRESS", "MAILFLARE_ZONE_ID", "MAILFLARE_ROUTING_STATUS")
        mailflare_values = {name: str(values.get(name) or "").strip() for name in mailflare_names}
        mailflare_present = [bool(value) for value in mailflare_values.values()]
        mailflare_enabled = bool(customer.get("mailflareD1DatabaseId"))
        auto_email_setup = tenant_email_auto_provisioning_enabled(environment_path)
        if any(mailflare_present) and not all(mailflare_present):
            raise ValueError("registered tenant Mailflare runtime settings are incomplete")
        if auto_email_setup and not mailflare_enabled:
            raise ValueError("automatic email provisioning requires registered Mailflare resources")
        if mailflare_enabled and not all(mailflare_present) and not auto_email_setup:
            raise ValueError("registered Mailflare tenant runtime settings are incomplete")
        if any(mailflare_present) and not mailflare_enabled:
            raise ValueError("Mailflare runtime settings exist without registered Mailflare resources")
        result = {
            "PAYLOAD_SECRET": values["PAYLOAD_SECRET"],
            worker_token_env: values[tenant_token_env(tenant)],
        }
        if bool(values.get("RESEND_API_KEY")) != bool(values.get("RESEND_API_KEY_ID")):
            raise ValueError("registered tenant Resend sender credential is incomplete")
        if bool(values.get("RESEND_API_KEY")) != bool(values.get("RESEND_API_KEY_DOMAIN_ID")):
            raise ValueError("registered tenant Resend sender key is not bound to an exact domain")
        if values.get("RESEND_API_KEY"):
            result["RESEND_API_KEY"] = values["RESEND_API_KEY"]
        if values.get("HELLOADA_TURNSTILE_SECRET_KEY"):
            result["HELLOADA_TURNSTILE_SECRET_KEY"] = values["HELLOADA_TURNSTILE_SECRET_KEY"]
        if all(mailflare_present):
            result.update(mailflare_values)
        return result
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



def worker_deployment_command(checkout: Path, action: str, secrets_path: Path,
                               sha: str, release_id: str,
                               variables: dict[str, str]) -> list[str]:
    if action not in {"upload", "deploy"}:
        raise ValueError("Worker release action must be upload or deploy")
    if set(variables) != {"HELLOADA_TURNSTILE_SITE_KEY"}:
        raise ValueError("Worker release requires the one pipeline-provisioned Turnstile sitekey")
    if any(not value or "\n" in value or "\r" in value for value in variables.values()):
        raise ValueError("Worker release variables contain an invalid value")
    command = [
        str(checkout / "node_modules/.bin/opennextjs-cloudflare"), action,
        "--secrets-file", str(secrets_path),
    ]
    for name, value in sorted(variables.items()):
        command.extend(["--var", f"{name}:{value}"])
    command.extend(["--var", f"HELLOADA_RELEASE_SHA:{sha}", "--tag", release_id])
    return command


def run_worker_deployment(checkout: Path, action: str, sha: str, release_id: str,
                          directory: Path, secrets: dict[str, str], env: dict[str, str],
                          variables: dict[str, str]) -> str:
    secrets_path = worker_secrets_file(directory, secrets)
    try:
        command = worker_deployment_command(
            checkout, action, secrets_path, sha, release_id, variables,
        )
        return run(command, checkout, env)
    finally:
        secrets_path.unlink(missing_ok=True)


def upload_worker_version(checkout: Path, sha: str, release_id: str, directory: Path,
                          secrets: dict[str, str], env: dict[str, str],
                          variables: dict[str, str]) -> str:
    return uploaded_version_id(run_worker_deployment(
        checkout, "upload", sha, release_id, directory, secrets, env, variables,
    ))


def deploy_worker_with_lifecycle(checkout: Path, sha: str, release_id: str,
                                 directory: Path, secrets: dict[str, str],
                                 env: dict[str, str],
                                 variables: dict[str, str]) -> None:
    run_worker_deployment(
        checkout, "deploy", sha, release_id, directory, secrets, env, variables,
    )

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


def control_plane_token(env_file: str | Path, base: dict[str, str]) -> str:
    """Load the server-only activation credential from the declared API env file."""
    from site_agent.config import load_env_file

    token = str(load_env_file(env_file, base).get("HELLOADA_CONTROL_PLANE_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("the declared HelloAda control-plane credential is missing")
    return token


def activate_tenant_runtime(
    api_url: str,
    tenant: str,
    release_id: str,
    source_sha: str,
    token: str,
    verification: Mapping[str, Any] | None = None,
) -> None:
    """Mount the pending tenant after Worker health and before connection auth."""
    endpoint = (
        api_url.rstrip("/")
        + "/control-plane/websites/"
        + urllib.parse.quote(tenant, safe="")
        + "/activate-runtime"
    )
    body: dict[str, Any] = {"release_id": release_id, "source_sha": source_sha}
    if verification is not None:
        body["verification"] = dict(verification)
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HelloAda-Release/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"tenant runtime activation returned HTTP {exc.code}") from None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("tenant runtime activation did not return a valid response") from exc
    if (
        not isinstance(result, dict)
        or result.get("tenant_id") != tenant
        or result.get("release_id") != release_id
        or result.get("source_sha") != source_sha
        or result.get("runtime_active") is not True
    ):
        raise RuntimeError("tenant runtime activation identity did not match the release")


def workers_dev_provisioner(
    customer: dict[str, Any], deploy_env: dict[str, str],
) -> CloudflareResourceProvisioner | None:
    """Resolve and validate the account-qualified workers.dev health origin."""
    health = str(customer.get("health") or "")
    hostname = urllib.parse.urlsplit(health).hostname or ""
    if not hostname.endswith(".workers.dev"):
        return None
    token = str(deploy_env.get("CLOUDFLARE_API_TOKEN") or "").strip()
    account_id = str(deploy_env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not token or not account_id:
        raise RuntimeError("Cloudflare credentials are required to validate the workers.dev origin")
    from site_agent.hands.cloudflare_resources import CloudflareResourceProvisioner

    provisioner = CloudflareResourceProvisioner(account_id, token)
    expected = provisioner.workers_dev_url(str(customer.get("worker") or "")) + "/api/health"
    if health != expected:
        raise RuntimeError("registered workers.dev health endpoint does not match the Cloudflare account subdomain")
    return provisioner


def verify_worker_queue_consumers(
    receipt: dict[str, Any], customer: dict[str, Any], env: dict[str, str],
) -> None:
    """Read back all three Mailflare queue consumers and enforce exact identity/settings."""
    contract = receipt.get("queueConsumers")
    consumers = contract.get("consumers") if isinstance(contract, dict) else None
    expected_names = {
        customer["mailflareInboundQueueName"], customer["mailflareOutboundQueueName"],
        customer["mailflareAgentQueueName"],
    }
    if (not isinstance(contract, dict) or contract.get("verified") is not True or not isinstance(consumers, list)
            or len(consumers) != len(expected_names)
            or {item.get("queue") for item in consumers if isinstance(item, dict)} != expected_names):
        raise RuntimeError("release receipt has no exact Mailflare consumer contract")
    for item in consumers:
        queue_id = item.get("queueId")
        desired = item.get("desired")
        if not isinstance(queue_id, str) or not queue_id or not isinstance(desired, dict):
            raise RuntimeError("release receipt has an invalid Queue consumer identity")
        active = worker_queue_consumers(queue_id, env)
        if len(active) != 1 or not worker_queue_consumer_matches(active[0], desired):
            raise RuntimeError(f"Cloudflare Queue {item['queue']} differs from the committed consumer contract")
        item["verifiedAt"] = utc_now()

def verify_live(receipt: dict[str, Any], customer: dict[str, Any], manifest: dict[str, Any],
                deploy_env: dict[str, str], base: dict[str, str], stage: Any, *,
                verify_only: bool = False) -> None:
    rollout_mode = receipt.get("rolloutMode")
    if rollout_mode not in (None, "versioned", "atomic"):
        raise RuntimeError("release receipt has an unknown Worker rollout mode")
    if rollout_mode == "atomic":
        lifecycle = receipt.get("durableObjectLifecycle")
        deployment_proof = receipt.get("deployment")
        if (not isinstance(lifecycle, dict) or lifecycle.get("state") != "applied"
                or lifecycle.get("strategy") != "atomic"
                or lifecycle.get("versionId") != receipt.get("uploadedVersion")
                or not isinstance(deployment_proof, dict)
                or lifecycle.get("deploymentId") != deployment_proof.get("id")):
            raise RuntimeError("atomic Durable Object rollout receipt has no exact applied lifecycle proof")
    elif rollout_mode == "versioned":
        lifecycle = receipt.get("durableObjectLifecycle")
        if not isinstance(lifecycle, dict) or lifecycle.get("state") not in ("reused", "not-required"):
            raise RuntimeError("versioned rollout has no prior Durable Object lifecycle proof")
    stage("verify-deployment")
    if verify_only:
        deployment, active_version, uploaded_identity, active_identity = resolve_verified_active_worker(
            customer, deploy_env, receipt["uploadedVersion"],
        )
        record_current_verification(receipt, deployment, active_version, uploaded_identity, active_identity)
    else:
        deployment = cloudflare_deployment(customer, deploy_env)
        versions = deployment["versions"]
        if len(versions) != 1 or versions[0].get("percentage") != 100:
            raise RuntimeError("the exact uploaded Worker version does not receive 100% of production traffic")
        active_version = versions[0].get("version_id")
        if not isinstance(active_version, str) or not active_version:
            raise RuntimeError("Cloudflare production deployment has no active Worker version")
        if active_version != receipt["uploadedVersion"]:
            raise RuntimeError("the exact uploaded Worker version does not receive 100% of production traffic")
        receipt["deployment"] = deployment
    cron_contract = receipt.get("cronTriggers")
    if not isinstance(cron_contract, dict) or cron_contract.get("desired") != ["*/5 * * * *", "0 2 * * *"]:
        raise RuntimeError("release receipt has no exact message and Mailflare schedule contract")
    stage("verify-cron-triggers")
    active_crons = worker_cron_schedules(customer, deploy_env)
    if active_crons != cron_contract["desired"]:
        raise RuntimeError("active Cloudflare Worker schedules differ from the exact release contract")
    cron_contract["verifiedAt"] = utc_now()
    stage("verify-queue-consumers")
    verify_worker_queue_consumers(receipt, customer, deploy_env)
    stage("verify-mailflare-migrations")
    verify_mailflare_migrations(receipt, customer, deploy_env)
    workers_dev = workers_dev_provisioner(customer, deploy_env)
    if workers_dev is not None and not verify_only:
        stage("enable-workers-dev")
        workers_dev.ensure_workers_dev_route(str(customer["worker"]))
        stage("verify-deployment")
    gate = manifest["connectionGate"]
    # Every verified Worker version crosses the same control-plane boundary:
    # the API synchronizes its runtime contract before the authenticated
    # connection gate. Bootstrap and ordinary tenant releases differ only in
    # schema initialization policy, not in runtime activation.
    # Edge rollout is asynchronous. Repeat the same strict read-only gates;
    # never change the version, identity, endpoint or success criteria.
    for attempt in range(12):
        try:
            receipt["health"] = check_health(customer["health"], receipt["tenant"],
                                             customer, receipt["sourceSha"])
            stage("verify-connection")
            activation_token = control_plane_token(gate["envFile"], base)
            activation = (
                gate["apiUrl"], receipt["tenant"], receipt["releaseId"],
                receipt["sourceSha"], activation_token,
            )
            if verify_only:
                activate_tenant_runtime(*activation, receipt["currentVerification"])
            else:
                activate_tenant_runtime(*activation)
            run([sys.executable, str(ROOT / "scripts/check-helloada-connections.py"),
                 "--config", gate["config"], "--env-file", gate["envFile"],
                 "--api-url", gate["apiUrl"], "--tenant", receipt["tenant"]], ROOT,
                {**base, "PYTHONPATH": str(ROOT / "src")})
        except (OSError, ValueError, RuntimeError) as error:
            receipt.setdefault("gateAttempts", []).append({"at": utc_now(), "error": str(error)})
            stage(receipt["stage"])
            if attempt == 11:
                raise
            time.sleep(5)
            continue
        if verify_only:
            current_deployment, current_version, current_uploaded_identity, current_active_identity = (
                resolve_verified_active_worker(customer, deploy_env, receipt["uploadedVersion"])
            )
            if current_deployment["id"] != deployment["id"] or current_version != active_version:
                deployment = current_deployment
                active_version = current_version
                uploaded_identity = current_uploaded_identity
                active_identity = current_active_identity
                record_current_verification(
                    receipt, deployment, active_version, uploaded_identity, active_identity,
                )
                stage("verify-deployment")
                if attempt == 11:
                    raise RuntimeError("Cloudflare production deployment kept changing during readiness verification")
                continue
            record_current_verification(
                receipt, current_deployment, current_version,
                current_uploaded_identity, current_active_identity,
            )
        receipt["connectionVerifiedAt"] = utc_now()
        return


def verification_receipt(directory: Path, tenant: str, sha: str, release_id: str,
                         customer: dict[str, Any], release_purpose: str,
                         approval_id: int | None = None,
                         initialization_head: str | None = None) -> dict[str, Any]:
    receipt = json.loads((directory / "receipt.json").read_text())
    require_release_purpose(release_purpose, initialization_head)
    recorded_purpose = "workspace-bootstrap" if receipt.get("initialSchemaHead") is not None else "website"
    if recorded_purpose != release_purpose:
        raise ValueError("verification purpose differs from the exact queued release operation")
    expected = {"tenant": tenant, "sourceSha": sha, "releaseId": release_id,
                "worker": customer["worker"], "repository": customer["repository"],
                "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
                "contentContract": customer["contentContract"],
                "schemaRevision": customer["schemaRevision"], "schemaIdentity": customer["schemaIdentity"],
                "migrationHead": customer["migrationHead"], "websitePresent": customer["websitePresent"],
                "privateEmailR2BucketName": customer["privateEmailR2BucketName"],
                "mailflareD1DatabaseId": customer["mailflareD1DatabaseId"],
                "mailflareD1DatabaseName": customer["mailflareD1DatabaseName"],
                "mailflareR2BucketName": customer["mailflareR2BucketName"],
                "mailflareInboundQueueName": customer["mailflareInboundQueueName"],
                "mailflareOutboundQueueName": customer["mailflareOutboundQueueName"],
                "mailflareAgentQueueName": customer["mailflareAgentQueueName"]}
    if approval_id is not None:
        expected["approvalId"] = approval_id
    if initialization_head is not None:
        expected["initialSchemaHead"] = initialization_head
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("verification target differs from the recorded release")
    try:
        mailflare_migration_receipt(receipt)
    except RuntimeError as error:
        raise ValueError("release has no exact Mailflare migration provenance") from error
    if receipt.get("status") not in ("failed", "deployed", "verified") or receipt.get("stage") not in (
            "verify-deployment", "verify-cron-triggers", "verify-queue-consumers", "verify-mailflare-migrations", "verify-connection",
            "awaiting-browser-verification", "verified"):
        raise ValueError("only a promoted release may resume read-only verification")
    if receipt.get("cronTriggers", {}).get("desired") != ["*/5 * * * *", "0 2 * * *"]:
        raise ValueError("release has no verified message and Mailflare schedule contract")
    queue_contract = receipt.get("queueConsumers")
    queue_consumers = queue_contract.get("consumers") if isinstance(queue_contract, dict) else None
    if (not isinstance(queue_contract, dict) or queue_contract.get("verified") is not True
            or not isinstance(queue_consumers, list) or len(queue_consumers) != 3):
        raise ValueError("release has no verified Mailflare consumer contract")
    if not receipt.get("uploadedVersion") or not receipt.get("deployment"):
        raise ValueError("release has no recorded immutable production promotion")
    artifact_hashes = receipt.get("artifactHashes")
    if (not isinstance(artifact_hashes, dict) or not artifact_hashes
            or any(not isinstance(path, str) or not path or Path(path).is_absolute()
                   or ".." in Path(path).parts or not isinstance(digest, str)
                   or not SHA256_RE.fullmatch(digest)
                   for path, digest in artifact_hashes.items())):
        raise ValueError("release has no valid verified artifact manifest")
    receipt.setdefault("verificationHistory", []).append({key: receipt.get(key) for key in
        ("status", "stage", "error", "finishedAt")})
    receipt.pop("error", None)
    receipt.update({"status": "running", "browserVerification": "pending"})
    return receipt


def inspect_artifact(checkout: Path, customer: dict[str, Any], sha: str,
                     custom_worker_bundle: Path | None = None,
                     shared_runtime_fingerprint: str | None = None) -> dict[str, str]:
    artifact = checkout / ".open-next"
    if not (artifact / "worker.js").is_file():
        raise RuntimeError("OpenNext produced no Worker")
    worker_source = (checkout / "worker.ts").read_text(encoding="utf-8")
    wrangler_source = (checkout / "wrangler.jsonc").read_text(encoding="utf-8")
    if not re.search(r'"main"\s*:\s*"worker\.ts"', wrangler_source):
        raise RuntimeError("Wrangler is not configured to upload the canonical custom Worker entrypoint")
    if not {"fetch", "email", "queue", "scheduled"}.issubset(worker_handlers(worker_source)):
        raise RuntimeError("custom Worker artifact is missing an HTTP, email, Queue or scheduled handler")
    mailflare_source = json.loads((ROOT / "packages/helloada-mailflare/UPSTREAM.json").read_text())
    provenance_path = checkout / ".mailflare/provenance.json"
    if not provenance_path.is_file():
        raise RuntimeError("Mailflare Worker output is missing its source receipt")
    provenance = json.loads(provenance_path.read_text())
    for key in ("repository", "commit", "packageVersion", "packageLockSha256", "integrationPatchSet", "basePath"):
        if provenance.get(key) != mailflare_source[key]:
            raise RuntimeError(f"Mailflare Worker source provenance mismatch: {key}")
    if provenance.get("namespacedApiReferences", 0) < 1:
        raise RuntimeError("Mailflare API paths were not namespaced")
    migration_dir = checkout / ".mailflare/migrations"
    migration_files = sorted(path for path in migration_dir.glob("*.sql") if path.is_file())
    migration_digest = hashlib.sha256()
    for migration_path in migration_files:
        migration_digest.update(migration_path.name.encode())
        migration_digest.update(b"\0")
        migration_digest.update(migration_path.read_bytes())
        migration_digest.update(b"\0")
    migration_names = [path.name for path in migration_files]
    if (not migration_names or migration_names != provenance.get("migrationNames")
            or migration_digest.hexdigest() != provenance.get("migrationsSha256")):
        raise RuntimeError("Mailflare SQL migrations differ from the pinned build provenance")
    if not all((checkout / item).exists() for item in (".mailflare/server/index.js", ".mailflare/server/ssr/index.js", ".open-next/assets/mail/_next/static")):
        raise RuntimeError("Mailflare Worker or namespaced client assets are missing")
    if "composeTenantWorker" not in worker_source or ".mailflare/server/index.js" not in worker_source:
        raise RuntimeError("tenant Worker does not compose the pinned Mailflare handler")
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
    if shared_runtime_fingerprint is not None and not SHA256_RE.fullmatch(shared_runtime_fingerprint):
        raise RuntimeError("shared runtime fingerprint is invalid")
    expected_marker = {
        "sourceSha": sha,
        "payloadAdmin": customer["payloadAdmin"],
        "payloadCore": customer["payloadCore"],
        "contentContract": customer["contentContract"],
        "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"],
        "migrationHead": customer["migrationHead"],
        **({"sharedRuntimeFingerprint": shared_runtime_fingerprint}
           if shared_runtime_fingerprint is not None else {}),
        "mailflareCommit": mailflare_source["commit"],
        "mailflarePatchSet": mailflare_source["integrationPatchSet"],
    }
    if any(marker.get(key) != value for key, value in expected_marker.items()):
        raise RuntimeError("built release marker does not match the pinned source")
    return worker_artifact_hashes(checkout, custom_worker_bundle)


def tracked_changes_outside_runtime_overlay(
    checkout: Path,
    allowed_paths: list[str],
    environment: dict[str, str],
    generated_untracked_roots: tuple[str, ...] = (),
) -> list[str]:
    """Reject source mutations except the declared overlay and known build outputs."""
    output = run(["git", "status", "--porcelain", "--untracked-files=all"], checkout, environment)
    allowed = set(allowed_paths)
    generated_roots = tuple(path.rstrip("/") for path in generated_untracked_roots)

    def is_generated_output(path: str) -> bool:
        return any(path == root or path.startswith(root + "/") for root in generated_roots)

    unexpected = set()
    for line in output.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        if path in allowed:
            continue
        if status == "??" and is_generated_output(path):
            continue
        unexpected.add(path)
    return sorted(unexpected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--approval-id", type=int)
    parser.add_argument("--initialize-schema-head", help="hash of the exact Payload migration chain for an empty new tenant")
    parser.add_argument("--release-purpose", choices=("workspace-bootstrap", "website"), required=True,
                        help="explicit release contract selected by the canonical release queue")
    parser.add_argument("--shared-runtime-fingerprint",
                        help="exact central runtime fingerprint authorized by the release queue")
    parser.add_argument("--schema-migration-from-ledger-identity", help="exact identity of the current Payload ledger for an approved tenant schema migration")
    parser.add_argument("--verify-only", action="store_true",
                        help="Recheck an already promoted version; never build, upload or promote")
    parser.add_argument("--manifest", type=Path, default=ROOT / "deploy/payload-customers.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_toolchain_manifest(manifest)
    registered_customer = manifest["customers"].get(args.tenant)
    if registered_customer is None:
        parser.error("tenant is not registered")
    customer = dict(registered_customer)
    from site_agent.application.shared_runtime import shared_package_versions
    package_versions = shared_package_versions(ROOT)
    customer["payloadAdmin"] = package_versions["@weareheadless/helloada-payload-admin"]
    customer["payloadCore"] = package_versions["@weareheadless/helloada-payload-core"]
    validate_target(customer, args.tenant, args.ref, args.release_id)
    try:
        require_release_purpose(args.release_purpose, args.initialize_schema_head)
    except ValueError as error:
        parser.error(str(error))
    release_root = Path(manifest["releaseRoot"])
    directory = release_root / "runs" / args.tenant / args.release_id
    workspace = None
    workspace_path = None
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
        "sharedRuntimeFingerprint": None,
        "sharedRuntimeSourceSha": os.environ.get("HELLOADA_PIPELINE_SHA"),
        "nodeVersion": manifest["nodeVersion"], "npmVersion": manifest["npmVersion"],
        "worker": customer["worker"], "repository": customer["repository"],
        "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
        "contentContract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"],
        "websitePresent": customer["websitePresent"],
        "d1DatabaseId": customer["d1DatabaseId"], "d1DatabaseName": customer["d1DatabaseName"],
        "r2BucketName": customer["r2BucketName"],
        "privateEmailR2BucketName": customer["privateEmailR2BucketName"],
        "mailflareD1DatabaseId": customer["mailflareD1DatabaseId"],
        "mailflareD1DatabaseName": customer["mailflareD1DatabaseName"],
        "mailflareR2BucketName": customer["mailflareR2BucketName"],
        "mailflareInboundQueueName": customer["mailflareInboundQueueName"],
        "mailflareOutboundQueueName": customer["mailflareOutboundQueueName"],
        "mailflareAgentQueueName": customer["mailflareAgentQueueName"],
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
                                       args.release_purpose, args.approval_id, args.initialize_schema_head)

    def stage(name: str) -> None:
        receipt["stage"] = name
        if not args.verify_only:
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
        base.update({"PATH": manifest["npmBin"] + ":" + manifest["nodeBin"] + ":/usr/local/bin:/usr/bin:/bin",
                     "CI": "1"})
        if not args.verify_only:
            ensure_build_capacity(release_root)
            work_root = release_root / "work"
            work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            work_root.chmod(0o700)
            workspace = tempfile.TemporaryDirectory(
                prefix=f"{args.tenant}-{args.release_id}-", dir=str(work_root),
            )
            workspace_path = Path(workspace.name)
            checkout = workspace_path / "source"
            temporary_root = workspace_path / "temporary"
            temporary_root.mkdir(mode=0o700)
            base["npm_config_cache"] = str(workspace_path / "npm-cache")
            base["TMPDIR"] = str(temporary_root)
        deploy_env = credential_environment({"credentials": {"cloudflare": cloudflare}}, base)
        if not deploy_env.get("CLOUDFLARE_API_TOKEN") or not deploy_env.get("CLOUDFLARE_ACCOUNT_ID"):
            raise RuntimeError("declared Cloudflare profile is incomplete")
        workers_dev_provisioner(customer, deploy_env)
        if args.verify_only:
            verify_live(
                receipt, customer, manifest, deploy_env, base, stage,
                verify_only=True,
            )
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
        stage("shared-runtime-overlay")
        host_runtime_values = read_tenant_environment(Path(manifest["connectionGate"]["envFile"]))
        from site_agent.application.shared_runtime import apply_shared_runtime_overlay
        runtime_provenance = apply_shared_runtime_overlay(
            ROOT,
            checkout,
            {**customer, "tenantId": args.tenant},
            shared_vars={
                "HELLOADA_HANDOFF_PUBLIC_KEY": host_runtime_values.get("HELLOADA_HANDOFF_PUBLIC_KEY", ""),
            },
            expected_fingerprint=args.shared_runtime_fingerprint,
        )
        if (args.shared_runtime_fingerprint is not None and not SHA256_RE.fullmatch(args.shared_runtime_fingerprint)):
            raise RuntimeError("queued shared-runtime fingerprint is invalid")
        if (args.shared_runtime_fingerprint is not None
                and runtime_provenance["fingerprint"] != args.shared_runtime_fingerprint):
            raise RuntimeError("materialized shared runtime differs from the immutable queued fingerprint")
        if (runtime_provenance["payloadAdmin"] != customer["payloadAdmin"]
                or runtime_provenance["payloadCore"] != customer["payloadCore"]):
            raise RuntimeError("materialized shared package versions differ from the release contract")
        receipt["sharedRuntime"] = runtime_provenance
        receipt["sharedRuntimeFingerprint"] = runtime_provenance["fingerprint"]
        if args.shared_runtime_fingerprint is not None:
            receipt["expectedSharedRuntimeFingerprint"] = args.shared_runtime_fingerprint
        atomic_json(receipt_path, receipt)
        validate_payload_verifier(checkout)
        source = list((checkout / "src").rglob("*.ts")) + list((checkout / "src").rglob("*.tsx"))
        if any("/api/atelier" in p.read_text() for p in source):
            raise RuntimeError("obsolete /api/atelier source must be removed")
        receipt["lockfileSha256"] = hashlib.sha256((checkout / "package-lock.json").read_bytes()).hexdigest()

        stage("dependencies")
        npm = str(Path(manifest["npmBin"], "npm"))
        from site_agent.application.release_dependencies import prepare_release_dependencies
        receipt["sharedPackageAssets"] = prepare_release_dependencies(
            checkout,
            github_api_token(profile, base),
            npm,
            Path(base["TMPDIR"]),
            lambda command, directory: run(command, directory, base),
        )
        run([npm, *NPM_INSTALL_ARGUMENTS], checkout, base)
        # TypeScript's pinned JSONC parser accepts comments and trailing commas.
        parsed = run(["node", "-e", "const fs=require('node:fs');const ts=require('typescript');"
                      "const r=ts.parseConfigFileTextToJson('wrangler.jsonc',fs.readFileSync('wrangler.jsonc','utf8'));"
                      "if(r.error)throw Error('Invalid Wrangler JSONC');const c=r.config;"
                      "process.stdout.write(JSON.stringify({name:c.name,tenant:c.vars?.HELLOADA_TENANT_ID,"
                      "main:c.main,"
                      "admin:c.vars?.HELLOADA_PAYLOAD_ADMIN_VERSION,core:c.vars?.HELLOADA_PAYLOAD_CORE_VERSION,"
                      "contract:c.vars?.HELLOADA_CONTENT_CONTRACT_VERSION,"
                      "schemaRevision:Number(c.vars?.HELLOADA_PAYLOAD_SCHEMA_REVISION||0),"
                      "schemaIdentity:c.vars?.HELLOADA_SCHEMA_IDENTITY,"
                      "migrationHead:c.vars?.HELLOADA_PAYLOAD_MIGRATION_HEAD,"
                      "d1Count:Array.isArray(c.d1_databases)?c.d1_databases.length:0,"
                      "d1DatabaseId:c.d1_databases?.[0]?.database_id,"
                      "d1DatabaseName:c.d1_databases?.find(d=>d.binding==='D1')?.database_name,"
                      "d1Bindings:(c.d1_databases||[]).map(d=>({binding:d.binding,databaseId:d.database_id,databaseName:d.database_name})),"
                      "mailflareD1DatabaseId:c.d1_databases?.find(d=>d.binding==='MAILFLARE_DB')?.database_id,"
                      "mailflareD1DatabaseName:c.d1_databases?.find(d=>d.binding==='MAILFLARE_DB')?.database_name,"
                      "mailflareMigrationsDir:c.d1_databases?.find(d=>d.binding==='MAILFLARE_DB')?.migrations_dir,"
                      "r2Count:Array.isArray(c.r2_buckets)?c.r2_buckets.length:0,"
                      "r2Bindings:(c.r2_buckets||[]).map(b=>({binding:b.binding,bucketName:b.bucket_name})),"
                      "r2BucketName:c.r2_buckets?.find(b=>b.binding==='R2')?.bucket_name,"
                      "privateEmailR2BucketName:c.r2_buckets?.find(b=>b.binding==='PRIVATE_EMAIL')?.bucket_name,"
                      "mailflareR2BucketName:c.r2_buckets?.find(b=>b.binding==='MAILFLARE_BUCKET')?.bucket_name,"
                      "queueProducerCount:Array.isArray(c.queues?.producers)?c.queues.producers.length:0,"
                      "queueConsumerCount:Array.isArray(c.queues?.consumers)?c.queues.consumers.length:0,"
                      "mailflareQueueNames:Object.fromEntries((c.queues?.producers||[]).filter(q=>String(q.binding||'').startsWith('MAILFLARE_')).map(q=>[q.binding,q.queue])),"
                      "queues:c.queues||{},"
                      "crons:c.triggers?.crons||[],"
                      "durableObjectBindings:(c.durable_objects?.bindings||[]).map(b=>({name:b.name,className:b.class_name})),"
                      "durableObjectMigrations:(c.migrations||[]).map(m=>({tag:m.tag,newSqliteClasses:m.new_sqlite_classes||[]})),"
                      "aiBinding:c.ai?.binding,"
                      "sendEmailBinding:(c.send_email||[]).some(b=>b.name==='EMAIL'),"
                      "sendEmailBindingCount:Array.isArray(c.send_email)?c.send_email.length:0,"
                      "rateLimitBindings:(c.ratelimits||[]).map(r=>({name:r.name,namespaceId:String(r.namespace_id||'')})),"
                      "turnstileSiteKey:c.vars?.HELLOADA_TURNSTILE_SITE_KEY||null,"
                      "turnstileSecretInVars:Object.prototype.hasOwnProperty.call(c.vars||{},'HELLOADA_TURNSTILE_SECRET_KEY'),"
                      "publicDomains:(()=>{const d=new Set();const addUrl=v=>{try{const u=new URL(v);if(u.protocol==='https:'||u.protocol==='http:')d.add(u.hostname.toLowerCase())}catch{}};"
                      "addUrl(c.vars?.NEXT_PUBLIC_SITE_URL);for(const r of c.routes||[]){const p=typeof r==='string'?r:r?.pattern;if(typeof p!=='string')continue;"
                      "const h=p.split('/')[0].toLowerCase().replace(/^\\*\\./,'');if(h&&!h.includes('*'))d.add(h)}return [...d].sort()})(),"
                      "compatibilityDate:c.compatibility_date,compatibilityFlags:c.compatibility_flags||[],"
                      "d1Binding:c.d1_databases?.[0]?.binding,r2Binding:c.r2_buckets?.find(b=>b.binding==='R2')?.binding}));"], checkout, base)
        wrangler = json.loads(parsed)
        worker_entry = (checkout / "worker.ts").read_text(encoding="utf-8")
        wrangler["handlers"] = worker_handlers(worker_entry)
        validate_worker_contract(wrangler, customer, args.tenant)
        lifecycle_identity = durable_object_migration_identity(wrangler["durableObjectMigrations"])
        rollout_mode, applied_lifecycle_release = select_worker_rollout_mode(
            directory.parent, lifecycle_identity,
        )
        receipt["rolloutMode"] = rollout_mode
        if lifecycle_identity is None:
            receipt["durableObjectLifecycle"] = {"identity": None, "state": "not-required"}
        elif rollout_mode == "atomic":
            receipt["durableObjectLifecycle"] = {
                "identity": lifecycle_identity, "state": "planned", "strategy": "atomic",
            }
        else:
            receipt["durableObjectLifecycle"] = {
                "identity": lifecycle_identity, "state": "reused",
                "appliedByReleaseId": applied_lifecycle_release,
            }
        atomic_json(receipt_path, receipt)
        run(["npm", "run", "typecheck"], checkout, base)
        unexpected_changes = tracked_changes_outside_runtime_overlay(
            checkout, runtime_provenance["changedPaths"], base,
        )
        if unexpected_changes:
            raise RuntimeError("dependency/type checks changed non-runtime source: " + ", ".join(unexpected_changes))

        stage("build")
        mailflare_source = json.loads((ROOT / "packages/helloada-mailflare/UPSTREAM.json").read_text())
        marker = {"sourceSha": args.ref, "pipelineSha": receipt["pipelineSha"],
                  "tenant": args.tenant, "payloadAdmin": customer["payloadAdmin"],
                  "payloadCore": customer["payloadCore"], "contentContract": customer["contentContract"],
                  "schemaRevision": customer["schemaRevision"], "schemaIdentity": customer["schemaIdentity"],
                  "migrationHead": customer["migrationHead"],
                  "sharedRuntimeFingerprint": receipt["sharedRuntimeFingerprint"],
                  "mailflareCommit": mailflare_source["commit"],
                  "mailflarePatchSet": mailflare_source["integrationPatchSet"]}
        atomic_json(checkout / "public/helloada-release.json", marker)
        node = str(Path(manifest["nodeBin"], "node"))
        npm = str(Path(manifest["npmBin"], "npm"))
        mailflare_builder = ROOT / "packages/helloada-mailflare/scripts/build.mjs"
        build_path = os.pathsep.join((manifest["nodeBin"], str(Path(npm).parent), base.get("PATH", "")))
        build_env = {**base, "PATH": build_path, "PAYLOAD_LOCAL_BUILD": "1", "HELLOADA_RELEASE_SHA": args.ref}
        run([node, str(mailflare_builder), "--tenant-root", str(checkout), "--npm-bin", npm],
            checkout, build_env)
        mailflare_provenance = json.loads((checkout / ".mailflare/provenance.json").read_text())
        run([str(checkout / "node_modules/.bin/opennextjs-cloudflare"), "build"], checkout, build_env)
        run([node, str(mailflare_builder), "--tenant-root", str(checkout), "--compose-assets"],
            checkout, build_env)
        receipt["mailflare"] = {
            "sourceCommit": mailflare_provenance["commit"],
            "packageVersion": mailflare_provenance["packageVersion"],
            "integrationPatchSet": mailflare_provenance["integrationPatchSet"],
            "basePath": mailflare_provenance["basePath"],
            "namespacedApiReferences": mailflare_provenance["namespacedApiReferences"],
            "migrationNames": mailflare_provenance["migrationNames"],
            "migrationsSha256": mailflare_provenance["migrationsSha256"],
        }
        custom_worker_bundle = directory / "custom-worker-dry-run"
        run([str(checkout / "node_modules/.bin/wrangler"), "deploy", "--dry-run",
             "--outdir", str(custom_worker_bundle)], checkout, build_env)
        receipt["artifactHashes"] = inspect_artifact(
            checkout, customer, args.ref, custom_worker_bundle,
            receipt["sharedRuntimeFingerprint"],
        )
        unexpected_changes = tracked_changes_outside_runtime_overlay(
            checkout, runtime_provenance["changedPaths"], base,
            generated_untracked_roots=(".mailflare", "public/helloada-release.json"),
        )
        if unexpected_changes:
            raise RuntimeError("build changed non-runtime source: " + ", ".join(unexpected_changes))
        stage("artifact-verified")
        before_deploy = cloudflare_deployment(customer, deploy_env)
        if before_deploy.get("id") != receipt["previousDeployment"].get("id"):
            raise RuntimeError("production changed during the build; reconcile that deployment before retrying")
        stage("provision-mailflare-resources")
        receipt["tenantResources"] = provision_tenant_mail_resources(customer, deploy_env)
        atomic_json(receipt_path, receipt)
        stage("migrate-mailflare-schema")
        receipt["mailflareMigrations"] = reconcile_mailflare_migrations(
            checkout, customer, deploy_env, base,
        )
        atomic_json(receipt_path, receipt)
        stage("provision-turnstile")
        receipt["turnstile"] = provision_turnstile_for_tenant(
            args.tenant, customer, wrangler, manifest, deploy_env,
        )
        runtime_secrets = tenant_runtime_secrets(manifest, args.tenant)
        if not runtime_secrets.get("HELLOADA_TURNSTILE_SECRET_KEY"):
            raise RuntimeError("tenant Turnstile secret was not persisted before Worker upload")
        def verify_candidate_schema() -> None:
            # Schema changes are explicitly queued and fully verified before an
            # atomic Durable Object lifecycle deployment. Ordinary versioned
            # releases retain the previous Worker until these gates pass.
            receipt["appliedMigrations"] = enforce_payload_migrations(
                checkout, customer, deploy_env, args.initialize_schema_head,
                args.schema_migration_from_ledger_identity, base, manifest, args.tenant, stage, wrangler, temporary_root,
            )
            receipt["verifiedMigrationHead"] = customer["migrationHead"]
            if args.release_purpose == "workspace-bootstrap":
                stage("verify-workspace-bootstrap-contract")
                verify_workspace_bootstrap_contract(
                    checkout, receipt, customer, args.initialize_schema_head,
                )
            else:
                stage("verify-payload-contract")
                run_payload_contract_verifier(checkout, customer, wrangler, deploy_env, base, temporary_root)
            atomic_json(receipt_path, receipt)

        release_variables = {
            "HELLOADA_TURNSTILE_SITE_KEY": receipt["turnstile"]["sitekey"],
        }
        if receipt["rolloutMode"] == "atomic":
            if worker_artifact_hashes(checkout, custom_worker_bundle) != receipt["artifactHashes"]:
                raise RuntimeError("atomic deploy inputs differ from the verified Worker artifact")
            verify_candidate_schema()
            if cloudflare_deployment(customer, deploy_env).get("id") != before_deploy.get("id"):
                raise RuntimeError("production changed during the build; reconcile before atomic deployment")
            stage("deploy-durable-object-lifecycle")
            lifecycle = receipt["durableObjectLifecycle"]
            lifecycle.update({"state": "applying", "startedAt": utc_now()})
            atomic_json(receipt_path, receipt)
            try:
                deploy_worker_with_lifecycle(
                    checkout, args.ref, args.release_id, workspace_path, runtime_secrets,
                    deploy_env, release_variables,
                )
            except Exception as error:
                lifecycle.update({"state": "outcome-unknown", "errorType": type(error).__name__})
                atomic_json(receipt_path, receipt)
                raise
            lifecycle.update({"state": "applied", "appliedAt": utc_now()})
            atomic_json(receipt_path, receipt)
            receipt["deployment"], receipt["uploadedVersion"] = wait_for_atomic_worker_version(
                customer, deploy_env, before_deploy,
            )
            lifecycle.update({
                "versionId": receipt["uploadedVersion"],
                "deploymentId": receipt["deployment"]["id"],
            })
            atomic_json(receipt_path, receipt)
            if worker_artifact_hashes(checkout, custom_worker_bundle) != receipt["artifactHashes"]:
                raise RuntimeError("atomic deploy changed an inspected Worker release input")
        else:
            stage("upload")
            receipt["uploadedVersion"] = upload_worker_version(
                checkout, args.ref, args.release_id, workspace_path, runtime_secrets,
                deploy_env, release_variables,
            )
            if worker_artifact_hashes(checkout, custom_worker_bundle) != receipt["artifactHashes"]:
                raise RuntimeError("upload changed an inspected custom Worker release input")
            verify_candidate_schema()

            # Version upload is immutable; production must still be the snapshot
            # captured before the candidate was built when it is promoted.
            stage("promote")
            if cloudflare_deployment(customer, deploy_env).get("id") != before_deploy.get("id"):
                raise RuntimeError("production changed during upload; reconcile before promotion")
            run([str(checkout / "node_modules/.bin/wrangler"), "versions", "deploy",
                 receipt["uploadedVersion"] + "@100%", "--name", customer["worker"], "--yes"], checkout, deploy_env)

        stage("reconcile-cron-triggers")
        receipt["cronTriggers"] = reconcile_worker_cron_schedules(
            customer, wrangler["crons"], deploy_env,
        )
        atomic_json(receipt_path, receipt)

        stage("reconcile-queue-consumers")
        receipt["queueConsumers"] = reconcile_worker_queue_consumers(
            customer, wrangler, receipt["tenantResources"], deploy_env,
        )
        atomic_json(receipt_path, receipt)

        stage("verify-deployment")
        deployment = cloudflare_deployment(customer, deploy_env)
        if not deployment or deployment.get("id") == before_deploy.get("id"):
            raise RuntimeError("Cloudflare did not create a new deployment")
        receipt["deployment"] = deployment
        verify_live(receipt, customer, manifest, deploy_env, base, stage)
        stage("trigger-email-provisioning")
        receipt["emailProvisioning"] = trigger_email_provisioning_after_worker_release(
            manifest, args.tenant,
        )
        receipt.update({"status": "deployed", "stage": "awaiting-browser-verification", "finishedAt": utc_now()})
        atomic_json(receipt_path, receipt)
        print(f"[release] DEPLOYED receipt={receipt_path}", flush=True)
        return 0
    except Exception as error:
        if args.verify_only:
            print(f"[release] VERIFICATION_FAILED stage={receipt['stage']}: {error}", file=sys.stderr, flush=True)
        else:
            receipt.update({"status": "failed", "error": str(error), "finishedAt": utc_now()})
            atomic_json(receipt_path, receipt)
            print(f"[release] FAILED stage={receipt['stage']}: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        if workspace is not None and not args.verify_only:
            try:
                workspace.cleanup()
                receipt["workspaceCleanupStatus"] = "complete"
            except OSError as error:
                receipt["workspaceCleanupStatus"] = "failed"
                receipt["workspaceCleanupError"] = f"{type(error).__name__}: {error}"
                print(f"[release] WORKSPACE_CLEANUP_FAILED: {error}", file=sys.stderr, flush=True)
            atomic_json(receipt_path, receipt)


if __name__ == "__main__":
    raise SystemExit(main())
