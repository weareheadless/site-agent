"""Commit exact, approved Payload releases to the canonical GitHub queue."""

from __future__ import annotations

import base64
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping


_REPOSITORY = "weareheadless/site-agent"
_GITHUB_API = "https://api.github.com"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TENANT = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_RELEASE_ID = re.compile(r"^rel-\d{14}-[0-9a-f]{8}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_CONTRACT = re.compile(r"^helloada-content-v\d+$")


class GitHubReleaseQueueError(RuntimeError):
    """A canonical production release request could not be recorded."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class GitHubReleaseQueue:
    """Atomically register a consumer and queue its exact source revision.

    A single GitHub tree/commit updates both control-plane documents. A compare-
    and-swap ref update prevents concurrent tenants from losing each other's
    release requests. The GitHub commit is the durable queue receipt.
    """

    def __init__(self, token: str, *, timeout_seconds: float = 30.0) -> None:
        self._token = str(token or "").strip()
        if not self._token:
            raise GitHubReleaseQueueError("GitHub release-queue credentials are unavailable")
        self._timeout = float(timeout_seconds)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = json.dumps(dict(payload)).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{_GITHUB_API}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "HelloAda-Release-Queue/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read(2 * 1024 * 1024).decode("utf-8") or "{}")
                return int(response.status), body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read(32 * 1024).decode("utf-8") or "{}")
            except (OSError, UnicodeError, ValueError):
                body = {}
            return int(exc.code), body if isinstance(body, dict) else {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubReleaseQueueError(f"GitHub release queue is unavailable: {type(exc).__name__}") from exc

    @staticmethod
    def _required_customer(customer: Mapping[str, Any]) -> dict[str, Any]:
        result = {key: customer.get(key) for key in (
            "repository", "worker", "health", "adminPath", "websitePresent", "payloadAdmin", "payloadCore",
            "contentContract", "schemaRevision", "schemaIdentity", "migrationHead",
            "d1DatabaseId", "d1DatabaseName", "mailflareD1DatabaseId", "mailflareD1DatabaseName",
            "r2BucketName", "privateEmailR2BucketName", "mailflareR2BucketName",
            "mailflareInboundQueueName",
            "mailflareOutboundQueueName", "mailflareAgentQueueName",
        )}
        if not re.fullmatch(r"https://github\.com/weareheadless/[A-Za-z0-9_.-]+\.git", str(result["repository"] or "")):
            raise GitHubReleaseQueueError("release source must be an official weareheadless repository")
        if not _TENANT.fullmatch(str(result["worker"] or "")):
            raise GitHubReleaseQueueError("registered Worker name is invalid")
        if not re.fullmatch(r"https://[^/?#]+/api/health", str(result["health"] or "")):
            raise GitHubReleaseQueueError("registered health endpoint is invalid")
        if result["adminPath"] != "/api/helloada":
            raise GitHubReleaseQueueError("release does not use the canonical HelloAda API")
        if not isinstance(result["websitePresent"], bool):
            raise GitHubReleaseQueueError("explicit website-present state is required")
        if not _VERSION.fullmatch(str(result["payloadAdmin"] or "")) or not _VERSION.fullmatch(str(result["payloadCore"] or "")):
            raise GitHubReleaseQueueError("exact shared Payload package versions are required")
        if not _CONTRACT.fullmatch(str(result["contentContract"] or "")):
            raise GitHubReleaseQueueError("exact shared Payload contract is required")
        if isinstance(result["schemaRevision"], bool) or not isinstance(result["schemaRevision"], int) or result["schemaRevision"] < 1:
            raise GitHubReleaseQueueError("exact Payload schema revision is required")
        if not re.fullmatch(r"[0-9a-f]{64}", str(result["schemaIdentity"] or "")):
            raise GitHubReleaseQueueError("exact Payload schema identity is required")
        if not re.fullmatch(r"[0-9a-f]{64}", str(result["migrationHead"] or "")):
            raise GitHubReleaseQueueError("exact Payload migration-chain identity is required")
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(result["d1DatabaseId"] or "")):
            raise GitHubReleaseQueueError("exact tenant D1 database identity is required")
        if str(result["d1DatabaseId"]).replace("-", "") == "0" * 32:
            raise GitHubReleaseQueueError("template D1 database identity cannot be registered")
        if not re.fullmatch(r"[a-z0-9-]{1,63}", str(result["d1DatabaseName"] or "")):
            raise GitHubReleaseQueueError("tenant D1 database name is invalid")
        if (not re.fullmatch(r"[0-9a-fA-F-]{36}", str(result["mailflareD1DatabaseId"] or ""))
                or str(result["mailflareD1DatabaseId"]).replace("-", "") == "0" * 32):
            raise GitHubReleaseQueueError("exact tenant Mailflare D1 database identity is required")
        if not re.fullmatch(r"[a-z0-9-]{1,63}", str(result["mailflareD1DatabaseName"] or "")):
            raise GitHubReleaseQueueError("tenant Mailflare D1 database name is invalid")
        if result["mailflareD1DatabaseName"] == result["d1DatabaseName"]:
            raise GitHubReleaseQueueError("Payload and Mailflare databases must be isolated")
        if not re.fullmatch(r"[a-z0-9-]{3,63}", str(result["r2BucketName"] or "")):
            raise GitHubReleaseQueueError("tenant R2 bucket name is invalid")
        for field in ("privateEmailR2BucketName", "mailflareR2BucketName", "mailflareInboundQueueName",
                      "mailflareOutboundQueueName", "mailflareAgentQueueName"):
            if not re.fullmatch(r"[a-z0-9-]{3,63}", str(result[field] or "")):
                raise GitHubReleaseQueueError(f"tenant {field} resource name is invalid")
        if len({result["r2BucketName"], result["privateEmailR2BucketName"], result["mailflareR2BucketName"]}) != 3:
            raise GitHubReleaseQueueError("public media, private email and Mailflare objects must be isolated")
        if len({result["mailflareInboundQueueName"], result["mailflareOutboundQueueName"],
                result["mailflareAgentQueueName"]}) != 3:
            raise GitHubReleaseQueueError("tenant Mailflare queues must be isolated")
        return result

    def request(
        self,
        tenant: str,
        source_sha: str,
        customer: Mapping[str, Any],
        *,
        approval_id: int | str | None = None,
        initialize_schema: bool = False,
        release_id: str | None = None,
    ) -> dict[str, str]:
        tenant = str(tenant or "").strip().lower()
        source_sha = str(source_sha or "").strip().lower()
        if not _TENANT.fullmatch(tenant) or not _SHA.fullmatch(source_sha):
            raise GitHubReleaseQueueError("release requires a tenant and full immutable source SHA")
        normalized_customer = self._required_customer(customer)
        if approval_id is not None and (isinstance(approval_id, bool) or not str(approval_id).isdigit() or int(approval_id) < 1):
            raise GitHubReleaseQueueError("approval identity must be a positive integer")
        if initialize_schema and approval_id is not None:
            raise GitHubReleaseQueueError("schema initialization is reserved for new-tenant bootstrap")
        requested_release_id = str(release_id or "").strip().lower() or None
        if requested_release_id is not None and not _RELEASE_ID.fullmatch(requested_release_id):
            raise GitHubReleaseQueueError("release attempt identity is invalid")

        for attempt in range(4):
            status, ref = self._request("GET", f"/repos/{_REPOSITORY}/git/ref/heads/main")
            if status != 200:
                raise GitHubReleaseQueueError("could not read the canonical release-control branch")
            parent_sha = str((ref.get("object") or {}).get("sha") or "")
            if not _SHA.fullmatch(parent_sha):
                raise GitHubReleaseQueueError("GitHub returned an invalid release-control revision")
            status, parent = self._request("GET", f"/repos/{_REPOSITORY}/git/commits/{parent_sha}")
            if status != 200:
                raise GitHubReleaseQueueError("could not read the release-control tree")
            base_tree = str((parent.get("tree") or {}).get("sha") or "")
            if not _SHA.fullmatch(base_tree):
                raise GitHubReleaseQueueError("GitHub returned an invalid release-control tree")
            documents: dict[str, dict[str, Any]] = {}
            for name in ("payload-customers.json", "desired-releases.json"):
                status, blob = self._request(
                    "GET",
                    f"/repos/{_REPOSITORY}/contents/deploy/{name}?ref={parent_sha}",
                )
                if status != 200 or blob.get("encoding") != "base64":
                    raise GitHubReleaseQueueError(f"canonical deploy/{name} is unavailable")
                try:
                    documents[name] = json.loads(base64.b64decode(blob["content"], validate=False).decode("utf-8"))
                except (ValueError, UnicodeError, TypeError) as exc:
                    raise GitHubReleaseQueueError(f"canonical deploy/{name} is invalid JSON") from exc

            registry = documents["payload-customers.json"]
            queue = documents["desired-releases.json"]
            customers = registry.get("customers")
            releases = queue.get("releases")
            if registry.get("schema") != 1 or not isinstance(customers, dict):
                raise GitHubReleaseQueueError("canonical customer registry schema is invalid")
            if queue.get("schema") != 1 or not isinstance(releases, dict):
                raise GitHubReleaseQueueError("canonical release queue schema is invalid")
            existing = customers.get(tenant)
            if existing is None:
                customers[tenant] = {**normalized_customer, "sharedRuntimeUpdate": "automatic"}
            elif not isinstance(existing, dict):
                raise GitHubReleaseQueueError("registered tenant contract is not an object")
            else:
                for key, value in normalized_customer.items():
                    if key not in existing:
                        # A source-derived exact identity may add newly required
                        # resource bindings to an older registration atomically
                        # with its release request. Existing values never drift.
                        existing[key] = value
                    elif existing[key] != value:
                        raise GitHubReleaseQueueError(
                            "registered tenant contract differs from the approved source; reconcile the registry first"
                        )

            current = releases.get(tenant)
            expected_approval = int(approval_id) if approval_id is not None else None
            same_request = (
                isinstance(current, Mapping)
                and current.get("sha") == source_sha
                and current.get("approvalId") == expected_approval
                and current.get("initializeSchema") == (
                    {"migrationHead": normalized_customer["migrationHead"]} if initialize_schema else None
                )
            )
            if isinstance(current, Mapping) and current.get("id") == requested_release_id and requested_release_id:
                if not same_request:
                    raise GitHubReleaseQueueError("release attempt identity is already bound to a different request")
                return {
                    "release_id": requested_release_id,
                    "source_sha": source_sha,
                    "control_sha": parent_sha,
                }
            if requested_release_id is None and same_request and isinstance(current.get("id"), str):
                return {
                    "release_id": current["id"],
                    "source_sha": source_sha,
                    "control_sha": parent_sha,
                }

            release_id = requested_release_id or datetime.now(timezone.utc).strftime("rel-%Y%m%d%H%M%S-") + secrets.token_hex(4)
            request: dict[str, Any] = {"id": release_id, "sha": source_sha}
            if approval_id is not None:
                request["approvalId"] = int(approval_id)
            if initialize_schema:
                request["initializeSchema"] = {"migrationHead": normalized_customer["migrationHead"]}
            releases[tenant] = request

            tree_entries = []
            for name, value in documents.items():
                path = f"deploy/{name}"
                content = _json_bytes(value).decode("utf-8")
                status, blob = self._request("POST", f"/repos/{_REPOSITORY}/git/blobs", payload={
                    "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                })
                blob_sha = str(blob.get("sha") or "")
                if status != 201 or not _SHA.fullmatch(blob_sha):
                    raise GitHubReleaseQueueError(f"could not create the canonical {path} revision")
                tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})
            status, tree = self._request("POST", f"/repos/{_REPOSITORY}/git/trees", payload={
                "base_tree": base_tree,
                "tree": tree_entries,
            })
            tree_sha = str(tree.get("sha") or "")
            if status != 201 or not _SHA.fullmatch(tree_sha):
                raise GitHubReleaseQueueError("could not create the atomic release-control tree")
            message = f"chore(release): queue {tenant} {source_sha[:12]}"
            status, commit = self._request("POST", f"/repos/{_REPOSITORY}/git/commits", payload={
                "message": message,
                "tree": tree_sha,
                "parents": [parent_sha],
            })
            commit_sha = str(commit.get("sha") or "")
            if status != 201 or not _SHA.fullmatch(commit_sha):
                raise GitHubReleaseQueueError("could not create the release request commit")
            status, updated = self._request("PATCH", f"/repos/{_REPOSITORY}/git/refs/heads/main", payload={
                "sha": commit_sha,
                "force": False,
            })
            if status in (200, 201) and str((updated.get("object") or {}).get("sha") or "") == commit_sha:
                return {"release_id": release_id, "source_sha": source_sha, "control_sha": commit_sha}
            if status not in (409, 422) or attempt == 3:
                raise GitHubReleaseQueueError("GitHub rejected the release request; no deployment was started")

        raise GitHubReleaseQueueError("release request could not be committed after concurrent updates")


__all__ = ["GitHubReleaseQueue", "GitHubReleaseQueueError"]
