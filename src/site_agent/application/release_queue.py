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
    journey = config.get("ada_journey") or config.get("journey") or {}
    journey = journey if isinstance(journey, Mapping) else {}
    website_present = journey.get("website_present") if "website_present" in journey else site.get("website_present")
    if not isinstance(website_present, bool):
        raise ReleaseQueueError("managed website-present state must be explicit")
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
    if not isinstance(buckets, list) or len(buckets) != 2 or any(not isinstance(item, Mapping) for item in buckets):
        raise ReleaseQueueError("canonical Worker must have exactly one public-media and one private-email R2 bucket")
    database = databases[0]
    buckets_by_binding = {str(item.get("binding") or ""): item for item in buckets}
    if database.get("binding") != "D1" or set(buckets_by_binding) != {"R2", "PRIVATE_EMAIL"}:
        raise ReleaseQueueError("canonical D1, public-media and private-email bindings are missing or duplicated")
    database_id = str(database.get("database_id") or "")
    database_name = str(database.get("database_name") or "")
    bucket_name = str(buckets_by_binding["R2"].get("bucket_name") or "")
    private_email_bucket_name = str(buckets_by_binding["PRIVATE_EMAIL"].get("bucket_name") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", database_id) or database_id == "00000000-0000-0000-0000-000000000000":
        raise ReleaseQueueError("canonical tenant D1 database identity is invalid")
    if (
        not re.fullmatch(r"[a-z0-9-]{1,63}", database_name)
        or not re.fullmatch(r"[a-z0-9-]{3,63}", bucket_name)
        or not re.fullmatch(r"[a-z0-9-]{3,63}", private_email_bucket_name)
        or private_email_bucket_name == bucket_name
    ):
        raise ReleaseQueueError("canonical tenant D1/R2 resource names are invalid")
    queues = wrangler.get("queues")
    producers = queues.get("producers") if isinstance(queues, Mapping) else None
    consumers = queues.get("consumers") if isinstance(queues, Mapping) else None
    if (
        not isinstance(producers, list) or len(producers) != 1 or not isinstance(producers[0], Mapping)
        or producers[0].get("binding") != "HELLOADA_MESSAGES_QUEUE"
        or not isinstance(consumers, list) or len(consumers) != 2
        or any(not isinstance(item, Mapping) for item in consumers)
    ):
        raise ReleaseQueueError("canonical Worker must declare one Messages producer and both Queue consumers")
    messages_queue_name = str(producers[0].get("queue") or "")
    consumer_names = {str(item.get("queue") or ""): item for item in consumers}
    message_dlq_name = str(
        consumer_names.get(messages_queue_name, {}).get("dead_letter_queue") or ""
    )
    if (
        len(consumer_names) != 2
        or not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", messages_queue_name)
        or not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", message_dlq_name)
        or messages_queue_name == message_dlq_name
        or set(consumer_names) != {messages_queue_name, message_dlq_name}
    ):
        raise ReleaseQueueError("canonical Messages and dead-letter Queue identities are invalid")
    contract = {
        "repository": repository,
        "worker": worker,
        "health": public_url + "/api/health",
        "adminPath": "/api/helloada",
        "websitePresent": website_present,
        "payloadAdmin": manifest.get("payloadAdmin"),
        "payloadCore": manifest.get("payloadCore"),
        "contentContract": manifest.get("contentContract"),
        "schemaRevision": manifest.get("schemaRevision"),
        "schemaIdentity": manifest.get("schemaIdentity"),
        "migrationHead": manifest.get("migrationHead"),
        "d1DatabaseId": database_id.lower(),
        "d1DatabaseName": database_name,
        "r2BucketName": bucket_name,
        "privateEmailR2BucketName": private_email_bucket_name,
        "messagesQueueName": messages_queue_name,
        "messagesDlqName": message_dlq_name,
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
    release_id: str | None = None,
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
            release_id=release_id,
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
