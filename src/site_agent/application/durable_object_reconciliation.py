"""Fail-closed proof for an atomic Worker deploy with an ambiguous CLI outcome."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

_SHA = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_TENANT = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_LIFECYCLE_STATES = {"applying", "outcome-unknown"}


class LifecycleReconciliationError(RuntimeError):
    """An ambiguous Worker lifecycle cannot be proven from exact live state."""


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise LifecycleReconciliationError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LifecycleReconciliationError(f"{label} timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise LifecycleReconciliationError(f"{label} timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _api_json(url: str, environment: Mapping[str, str]) -> dict[str, Any]:
    token = environment.get("CLOUDFLARE_API_TOKEN")
    if not isinstance(token, str) or not token:
        raise LifecycleReconciliationError("Cloudflare API credential is unavailable")
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise LifecycleReconciliationError(f"Cloudflare API returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise LifecycleReconciliationError("Cloudflare API response could not be verified") from error
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise LifecycleReconciliationError("Cloudflare API returned an unsuccessful response")
    return payload


def _api_result(url: str, environment: Mapping[str, str]) -> Any:
    payload = _api_json(url, environment)
    if "result" not in payload:
        raise LifecycleReconciliationError("Cloudflare API response has no result")
    return payload["result"]


def _health_json(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise LifecycleReconciliationError("registered health URL must be an HTTPS origin")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise LifecycleReconciliationError("registered health endpoint did not return a direct HTTP 200")
            payload = json.load(response)
    except LifecycleReconciliationError:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise LifecycleReconciliationError("registered health endpoint could not be verified") from error
    if not isinstance(payload, dict):
        raise LifecycleReconciliationError("registered health response is not an object")
    return payload


def reconciliation_path(release_root: Path, tenant: str, release_id: str) -> Path:
    if not _TENANT.fullmatch(tenant) or not _RELEASE_ID.fullmatch(release_id):
        raise LifecycleReconciliationError("unsafe lifecycle reconciliation identity")
    return release_root / "reconciliations" / tenant / f"{release_id}.json"


def read_lifecycle_reconciliation(
    release_root: Path, tenant: str, receipt: Mapping[str, Any],
) -> dict[str, Any] | None:
    release_id = str(receipt.get("releaseId") or "")
    path = reconciliation_path(release_root, tenant, release_id)
    if path.is_symlink():
        raise LifecycleReconciliationError("lifecycle reconciliation evidence must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise LifecycleReconciliationError("lifecycle reconciliation evidence is not a regular file")
    receipt_path = release_root / "runs" / tenant / release_id / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise LifecycleReconciliationError("reconciled release receipt is missing or unsafe")
    try:
        receipt_bytes = receipt_path.read_bytes()
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LifecycleReconciliationError("lifecycle reconciliation evidence is unreadable") from error
    if not isinstance(evidence, dict):
        raise LifecycleReconciliationError("lifecycle reconciliation evidence is not an object")
    lifecycle = receipt.get("durableObjectLifecycle")
    if not isinstance(lifecycle, Mapping):
        raise LifecycleReconciliationError("reconciled receipt has no Durable Object lifecycle identity")
    expected = {
        "schema": 1,
        "tenant": tenant,
        "releaseId": release_id,
        "receiptSha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "sourceSha": receipt.get("sourceSha"),
        "sharedRuntimeFingerprint": receipt.get("sharedRuntimeFingerprint"),
        "migrationIdentity": lifecycle.get("identity"),
        "status": "verified",
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise LifecycleReconciliationError("lifecycle evidence does not match the immutable failed receipt")
    if not _SHA.fullmatch(str(evidence.get("pipelineSha") or "")):
        raise LifecycleReconciliationError("lifecycle evidence has no immutable verifier revision")
    _utc(evidence.get("verifiedAt"), "verification")
    proof = evidence.get("proof")
    if not isinstance(proof, dict):
        raise LifecycleReconciliationError("lifecycle evidence has no live deployment proof")
    deployment = proof.get("deployment")
    version = proof.get("version")
    namespace = proof.get("namespace")
    health = proof.get("health")
    if not all(isinstance(item, dict) for item in (deployment, version, namespace, health)):
        raise LifecycleReconciliationError("lifecycle evidence is incomplete")
    if (not deployment.get("id") or not version.get("id")
            or deployment.get("versionId") != version.get("id")
            or not namespace.get("id") or namespace.get("class") != "RealtimeHub"
            or health.get("tenant") != tenant or health.get("releaseSha") != receipt.get("sourceSha")
            or health.get("ok") is not True or health.get("payloadSchema") != "ready"):
        raise LifecycleReconciliationError("lifecycle evidence does not prove the exact live release")
    return evidence


def _write_lifecycle_reconciliation(path: Path, evidence: dict[str, Any]) -> None:
    parent = path.parent
    if parent.is_symlink():
        raise LifecycleReconciliationError("lifecycle reconciliation directory must not be a symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        raise LifecycleReconciliationError("lifecycle reconciliation is immutable and already exists")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            raise LifecycleReconciliationError("lifecycle reconciliation appeared concurrently")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def reconcile_lifecycle_receipt(
    release_root: Path,
    tenant: str,
    receipt: Mapping[str, Any],
    customer: Mapping[str, Any],
    environment: Mapping[str, str],
    pipeline_sha: str,
) -> dict[str, Any]:
    """Record proof only when the exact immutable release is demonstrably live."""
    receipt_path = release_root / "runs" / tenant / str(receipt.get("releaseId") or "") / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise LifecycleReconciliationError("failed release receipt is missing or unsafe")
    try:
        raw_receipt = receipt_path.read_bytes()
        immutable_receipt = json.loads(raw_receipt)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LifecycleReconciliationError("failed release receipt is unreadable") from error
    if not isinstance(immutable_receipt, dict) or dict(receipt) != immutable_receipt:
        raise LifecycleReconciliationError("release receipt changed during reconciliation")
    existing = read_lifecycle_reconciliation(release_root, tenant, immutable_receipt)
    if existing is not None:
        return existing
    if (immutable_receipt.get("tenant") != tenant
            or immutable_receipt.get("status") not in {"failed", "interrupted"}
            or immutable_receipt.get("rolloutMode") != "atomic"):
        raise LifecycleReconciliationError("release is not an interrupted atomic Worker deployment")
    lifecycle = immutable_receipt.get("durableObjectLifecycle")
    if (not isinstance(lifecycle, dict) or lifecycle.get("state") not in _LIFECYCLE_STATES
            or lifecycle.get("strategy") != "atomic"
            or not _FINGERPRINT.fullmatch(str(lifecycle.get("identity") or ""))):
        raise LifecycleReconciliationError("release has no unresolved atomic Durable Object lifecycle")
    source_sha = immutable_receipt.get("sourceSha")
    worker = immutable_receipt.get("worker")
    account_id = environment.get("CLOUDFLARE_ACCOUNT_ID")
    if (not _SHA.fullmatch(str(source_sha or "")) or not isinstance(worker, str) or not worker
            or not account_id or not _SHA.fullmatch(str(pipeline_sha or ""))):
        raise LifecycleReconciliationError("release identity or verifier revision is incomplete")
    health_url = customer.get("health")
    if not isinstance(health_url, str) or not health_url:
        raise LifecycleReconciliationError("tenant registry has no exact health endpoint")

    previous = immutable_receipt.get("previousDeployment")
    previous_id = previous.get("id") if isinstance(previous, dict) else None
    deployments_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/workers/scripts/{urllib.parse.quote(worker, safe='')}/deployments"
    )
    deployments = _api_result(deployments_url, environment)
    deployment_items = deployments.get("deployments") if isinstance(deployments, dict) else None
    if not isinstance(deployment_items, list) or not deployment_items:
        raise LifecycleReconciliationError("Worker has no deployment record to reconcile")
    deployment = max(deployment_items, key=lambda item: str(item.get("created_on") or ""))
    created = _utc(deployment.get("created_on"), "Worker deployment")
    started = _utc(immutable_receipt.get("startedAt"), "release start")
    finished = _utc(immutable_receipt.get("finishedAt"), "release finish")
    if (deployment.get("id") == previous_id or created < started or created > finished
            or deployment.get("source") != "wrangler"):
        raise LifecycleReconciliationError("active Worker deployment is not the exact atomic release window")
    versions = deployment.get("versions")
    if (not isinstance(versions, list) or len(versions) != 1
            or versions[0].get("percentage") != 100
            or not isinstance(versions[0].get("version_id"), str)):
        raise LifecycleReconciliationError("atomic Worker deployment is not one exact 100% version")
    version_id = versions[0]["version_id"]
    version_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/workers/scripts/{urllib.parse.quote(worker, safe='')}/versions/{urllib.parse.quote(version_id, safe='')}"
    )
    version = _api_result(version_url, environment)
    if version.get("id") != version_id:
        raise LifecycleReconciliationError("Cloudflare returned a different Worker version")
    metadata = version.get("metadata")
    version_created = metadata.get("created_on") if isinstance(metadata, dict) else None
    if version_created and _utc(version_created, "Worker version") != created:
        raise LifecycleReconciliationError("Worker deployment and immutable version timestamps differ")
    resources = version.get("resources")
    script = resources.get("script") if isinstance(resources, dict) else None
    bindings = resources.get("bindings") if isinstance(resources, dict) else None
    if not isinstance(script, dict) or script.get("last_deployed_from") != "wrangler" or not isinstance(bindings, list):
        raise LifecycleReconciliationError("Worker version source or bindings cannot be verified")

    def binding(name: str) -> dict[str, Any]:
        matches = [item for item in bindings if isinstance(item, dict) and item.get("name") == name]
        if len(matches) != 1:
            raise LifecycleReconciliationError(f"Worker version has no unique {name} binding")
        return matches[0]

    source_binding = binding("HELLOADA_RELEASE_SHA")
    tenant_binding = binding("HELLOADA_TENANT_ID")
    realtime_binding = binding("MAILFLARE_REALTIME")
    if source_binding.get("type") != "plain_text" or source_binding.get("text") != source_sha:
        raise LifecycleReconciliationError("Worker version source SHA differs from the immutable release")
    if tenant_binding.get("type") != "plain_text" or tenant_binding.get("text") != tenant:
        raise LifecycleReconciliationError("Worker version tenant binding differs from the registered tenant")
    namespace_id = realtime_binding.get("namespace_id")
    if realtime_binding.get("type") != "durable_object_namespace" or realtime_binding.get("class_name") != "RealtimeHub":
        raise LifecycleReconciliationError("Worker version has no exact RealtimeHub binding")
    if not isinstance(namespace_id, str) or not namespace_id:
        raise LifecycleReconciliationError("Worker version RealtimeHub binding has no namespace identity")

    namespaces_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        "/workers/durable_objects/namespaces?per_page=1000"
    )
    namespace_result = _api_result(namespaces_url, environment)
    if not isinstance(namespace_result, list):
        raise LifecycleReconciliationError("Cloudflare Durable Object namespace list is invalid")
    matches = [
        item for item in namespace_result
        if isinstance(item, dict) and item.get("id") == namespace_id
        and item.get("class") == "RealtimeHub" and item.get("name") == f"{worker}_RealtimeHub"
    ]
    if len(matches) != 1:
        raise LifecycleReconciliationError("Worker RealtimeHub namespace is not uniquely present in Cloudflare")

    health = _health_json(health_url)
    required_health = {
        "ok": True,
        "tenant": tenant,
        "releaseSha": source_sha,
        "payloadSchema": "ready",
    }
    for key in ("migrationHead", "schemaIdentity", "schemaRevision", "payloadAdmin", "payloadCore", "contentContract"):
        if immutable_receipt.get(key) is not None:
            required_health[key] = immutable_receipt[key]
    if any(health.get(key) != expected for key, expected in required_health.items()):
        raise LifecycleReconciliationError("public health does not match the failed release receipt")

    evidence = {
        "schema": 1,
        "tenant": tenant,
        "releaseId": immutable_receipt["releaseId"],
        "receiptSha256": hashlib.sha256(raw_receipt).hexdigest(),
        "sourceSha": source_sha,
        "sharedRuntimeFingerprint": immutable_receipt.get("sharedRuntimeFingerprint"),
        "migrationIdentity": lifecycle["identity"],
        "pipelineSha": pipeline_sha,
        "status": "verified",
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "proof": {
            "deployment": {
                "id": deployment["id"],
                "createdAt": deployment["created_on"],
                "versionId": version_id,
                "percentage": 100,
            },
            "version": {
                "id": version_id,
                "releaseSha": source_sha,
                "tenant": tenant,
                "createdAt": version_created,
            },
            "namespace": {
                "id": namespace_id,
                "class": "RealtimeHub",
                "name": matches[0]["name"],
                "binding": "MAILFLARE_REALTIME",
            },
            "health": {
                "url": health_url,
                "tenant": tenant,
                "releaseSha": source_sha,
                "ok": True,
                "payloadSchema": "ready",
            },
        },
    }
    path = reconciliation_path(release_root, tenant, immutable_receipt["releaseId"])
    _write_lifecycle_reconciliation(path, evidence)
    return evidence


def reconcile_unresolved_lifecycle_receipts(
    release_root: Path,
    registry: Mapping[str, Any],
    environment: Mapping[str, str],
    pipeline_sha: str,
) -> dict[str, list[dict[str, str]]]:
    """Automatically attest only exact live state; ambiguous state stays blocked."""
    customers = registry.get("customers")
    if not isinstance(customers, Mapping):
        raise LifecycleReconciliationError("tenant registry is invalid")
    verified: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for tenant, customer in customers.items():
        if not isinstance(tenant, str) or not isinstance(customer, Mapping):
            raise LifecycleReconciliationError("tenant registry contains an invalid entry")
        tenant_root = release_root / "runs" / tenant
        if tenant_root.is_symlink():
            raise LifecycleReconciliationError("tenant release directory must not be a symlink")
        if not tenant_root.exists():
            continue
        if not tenant_root.is_dir():
            raise LifecycleReconciliationError("tenant release path is not a directory")
        for run in sorted(tenant_root.iterdir()):
            if run.is_symlink() or not run.is_dir():
                raise LifecycleReconciliationError("tenant release history contains an unexpected object")
            receipt_path = run / "receipt.json"
            if receipt_path.is_symlink() or not receipt_path.is_file():
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise LifecycleReconciliationError("tenant release history contains an invalid receipt") from error
            if not isinstance(receipt, dict):
                raise LifecycleReconciliationError("tenant release receipt is not an object")
            lifecycle = receipt.get("durableObjectLifecycle")
            if not isinstance(lifecycle, dict) or lifecycle.get("state") not in _LIFECYCLE_STATES:
                continue
            try:
                evidence = read_lifecycle_reconciliation(release_root, tenant, receipt)
                if evidence is None:
                    evidence = reconcile_lifecycle_receipt(
                        release_root, tenant, receipt, customer, environment, pipeline_sha,
                    )
                verified.append({"tenant": tenant, "releaseId": str(receipt["releaseId"])})
            except LifecycleReconciliationError as error:
                unresolved.append({
                    "tenant": tenant,
                    "releaseId": str(receipt.get("releaseId") or run.name),
                    "reason": str(error),
                })
    return {"verified": verified, "unresolved": unresolved}


__all__ = [
    "LifecycleReconciliationError",
    "read_lifecycle_reconciliation",
    "reconcile_lifecycle_receipt",
    "reconcile_unresolved_lifecycle_receipts",
]
