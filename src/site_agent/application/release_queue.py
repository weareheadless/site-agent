"""One source-controlled request path for all managed Payload deployments."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..credentials import credential_environment, github_api_token
from ..hands.github_release_queue import GitHubReleaseQueue, GitHubReleaseQueueError
from ..payload_contract import PayloadContractError, validate_payload_migrations


class ReleaseQueueError(RuntimeError):
    """A tenant release is not safe or could not be recorded in GitHub."""


def _managed_repository_url(value: Any) -> str:
    """Convert the canonical owner/repository setting to the release URL form."""
    repository = str(value or "").strip()
    if not re.fullmatch(r"weareheadless/[A-Za-z0-9_.-]+", repository):
        raise ReleaseQueueError("managed tenant repository must use its official owner/repository identity")
    return f"https://github.com/{repository}.git"


def customer_release_identity(config: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Read tenant and package identity from the canonical managed checkout."""
    tenant = str(config.get("instance_name") or "").strip().lower()
    site = config.get("site") if isinstance(config.get("site"), Mapping) else {}
    deployment = site.get("source_deployment") if isinstance(site.get("source_deployment"), Mapping) else {}
    repository = _managed_repository_url(site.get("repository"))
    worker = str(deployment.get("worker_name") or "").strip()
    public_url = str(site.get("public_url") or "").strip().rstrip("/")
    root = Path(str(deployment.get("clone_path") or site.get("clone_path") or "")).expanduser().resolve()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", tenant):
        raise ReleaseQueueError("managed tenant identity is missing")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
        raise ReleaseQueueError("managed Worker identity is missing")
    origin = urlsplit(public_url)
    if origin.scheme != "https" or not origin.netloc or origin.path or origin.query or origin.fragment:
        raise ReleaseQueueError("managed public origin must be an HTTPS origin")
    try:
        manifest = validate_payload_migrations(root)
        wrangler = json.loads((root / "wrangler.jsonc").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, PayloadContractError) as exc:
        raise ReleaseQueueError("canonical template manifest is missing or invalid") from exc
    if not isinstance(manifest, dict):
        raise ReleaseQueueError("canonical template manifest is invalid")
    if not isinstance(wrangler, dict) or wrangler.get("name") != worker:
        raise ReleaseQueueError("canonical Worker configuration does not match tenant identity")
    databases = wrangler.get("d1_databases")
    buckets = wrangler.get("r2_buckets")
    if not isinstance(databases, list) or len(databases) != 1 or not isinstance(databases[0], Mapping):
        raise ReleaseQueueError("canonical Worker must have exactly one tenant D1 database")
    if not isinstance(buckets, list) or len(buckets) != 1 or not isinstance(buckets[0], Mapping):
        raise ReleaseQueueError("canonical Worker must have exactly one tenant R2 bucket")
    database = databases[0]
    bucket = buckets[0]
    if database.get("binding") != "D1" or bucket.get("binding") != "R2":
        raise ReleaseQueueError("canonical D1 and R2 bindings are missing")
    database_id = str(database.get("database_id") or "")
    database_name = str(database.get("database_name") or "")
    bucket_name = str(bucket.get("bucket_name") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", database_id) or database_id == "00000000-0000-0000-0000-000000000000":
        raise ReleaseQueueError("canonical tenant D1 database identity is invalid")
    if not re.fullmatch(r"[a-z0-9-]{1,63}", database_name) or not re.fullmatch(r"[a-z0-9-]{3,63}", bucket_name):
        raise ReleaseQueueError("canonical tenant D1/R2 resource names are invalid")
    contract = {
        "repository": repository,
        "worker": worker,
        "health": public_url + "/api/health",
        "adminPath": "/api/helloada",
        "payloadAdmin": manifest.get("payloadAdmin"),
        "payloadCore": manifest.get("payloadCore"),
        "contentContract": manifest.get("contentContract"),
        "schemaRevision": manifest.get("schemaRevision"),
        "schemaIdentity": manifest.get("schemaIdentity"),
        "migrationHead": manifest.get("migrationHead"),
        "d1DatabaseId": database_id.lower(),
        "d1DatabaseName": database_name,
        "r2BucketName": bucket_name,
    }
    payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
    payload_contract = payload.get("contract") if isinstance(payload.get("contract"), Mapping) else {}
    for key in ("payloadAdmin", "payloadCore", "contentContract", "schemaRevision", "schemaIdentity", "migrationHead"):
        if payload_contract.get({
            "payloadAdmin": "adminVersion",
            "payloadCore": "coreVersion",
            "contentContract": "contract",
            "schemaRevision": "schemaRevision",
            "schemaIdentity": "schemaIdentity",
            "migrationHead": "migrationHead",
        }[key]) != contract[key]:
            raise ReleaseQueueError("tenant config and canonical template identities do not agree")
    return tenant, contract


def request_release(
    config: Mapping[str, Any],
    env: Mapping[str, str],
    source_sha: str,
    *,
    approval_id: int | str | None = None,
    initialize_schema: bool = False,
    new_attempt: bool = False,
) -> dict[str, str]:
    """Commit a release request to the only production queue in site-agent."""
    root = release_root(config)
    if not root.is_dir():
        raise ReleaseQueueError("canonical VPS release receipts are not mounted on this service")
    token = github_api_token(config, credential_environment(config, env))
    tenant, customer = customer_release_identity(config)
    try:
        return GitHubReleaseQueue(token).request(
            tenant,
            source_sha,
            customer,
            approval_id=approval_id,
            initialize_schema=initialize_schema,
            new_attempt=new_attempt,
        )
    except GitHubReleaseQueueError as exc:
        raise ReleaseQueueError(str(exc)) from exc


def release_root(config: Mapping[str, Any]) -> Path:
    pipeline = config.get("deployment_pipeline")
    if not isinstance(pipeline, Mapping):
        raise ReleaseQueueError("the canonical VPS deployment pipeline is not configured")
    value = str(pipeline.get("release_root") or "").strip()
    if not value:
        raise ReleaseQueueError("the canonical VPS release receipt root is not configured")
    root = Path(value).expanduser().resolve()
    if root == Path(root.anchor):
        raise ReleaseQueueError("the canonical VPS release receipt root is unsafe")
    return root


__all__ = ["ReleaseQueueError", "customer_release_identity", "release_root", "request_release"]
