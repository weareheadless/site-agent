"""Cloudflare R2 provisioning for one isolated site-agent instance.

The provisioner creates one private bucket and one bucket-scoped R2 API token.
The token secret is returned by Cloudflare only once, so callers must write it
to the instance environment file immediately.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class R2ProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class R2ProvisioningResult:
    account_id: str
    bucket: str
    jurisdiction: str
    access_key_id: str
    secret_access_key: str
    token_name: str
    bucket_created: bool
    token_created: bool


def _safe_slug(value: str, label: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value):
        raise R2ProvisioningError(f"{label} must contain 3-64 lowercase letters, numbers, or hyphens")
    return value


class CloudflareR2Provisioner:
    """Small stdlib Cloudflare API client for customer-scoped R2 setup."""

    def __init__(self, account_id: str, api_token: str, timeout: float = 30) -> None:
        self.account_id = account_id.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{32}", self.account_id):
            raise R2ProvisioningError("account_id must be a 32-character Cloudflare account ID")
        self.api_token = api_token.strip()
        if not self.api_token:
            raise R2ProvisioningError("Cloudflare API token is required")
        self.timeout = timeout
        self.base_url = "https://api.cloudflare.com/client/v4"

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", "replace")
            raise R2ProvisioningError(f"Cloudflare API request failed ({exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise R2ProvisioningError(f"Cloudflare API request failed: {exc}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise R2ProvisioningError("Cloudflare API returned invalid JSON") from exc
        if not isinstance(result, dict) or not result.get("success"):
            errors = result.get("errors") if isinstance(result, dict) else None
            raise R2ProvisioningError(f"Cloudflare API rejected the request: {str(errors)[:500]}")
        return result

    def ensure_bucket(self, bucket: str, jurisdiction: str = "default", location: str | None = None) -> bool:
        bucket = _safe_slug(bucket, "bucket")
        if jurisdiction not in {"default", "eu", "us", "fedramp"}:
            raise R2ProvisioningError("jurisdiction must be default, eu, us, or fedramp")
        body: dict[str, Any] = {"name": bucket}
        if location:
            if location not in {"apac", "eeur", "enam", "weur", "wnam", "oc"}:
                raise R2ProvisioningError("location is not a supported Cloudflare R2 location")
            body["locationHint"] = location
        if jurisdiction != "default":
            # The API models jurisdiction as a request header, not JSON data.
            # urllib does not expose headers through _request's small interface,
            # so non-default jurisdictions are intentionally rejected until the
            # storage adapter supports jurisdiction-specific endpoints too.
            raise R2ProvisioningError("non-default R2 jurisdictions are not supported yet")
        try:
            self._request("POST", f"/accounts/{self.account_id}/r2/buckets", body)
            return True
        except R2ProvisioningError as exc:
            if "(409)" in str(exc) or "already exists" in str(exc).lower():
                return False
            raise

    def _permission_group(self, name: str) -> dict[str, str]:
        # Account-owned bootstrap tokens cannot access the user-scoped endpoint.
        result = self._request("GET", f"/accounts/{self.account_id}/tokens/permission_groups")
        groups = result.get("result")
        if not isinstance(groups, list):
            raise R2ProvisioningError("Cloudflare returned no token permission groups")
        for group in groups:
            if isinstance(group, dict) and group.get("name") == name and group.get("id"):
                return {"id": str(group["id"]), "name": name}
        raise R2ProvisioningError(f"Cloudflare permission group not found: {name}")

    def create_bucket_token(self, bucket: str, token_name: str) -> tuple[str, str]:
        bucket = _safe_slug(bucket, "bucket")
        token_name = token_name.strip()[:50] or f"site-agent-{bucket}"
        group = self._permission_group("Workers R2 Storage Bucket Item Write")
        resource = f"com.cloudflare.edge.r2.bucket.{self.account_id}_default_{bucket}"
        result = self._request(
            "POST",
            f"/accounts/{self.account_id}/tokens",
            {
                "name": token_name,
                "policies": [{"effect": "allow", "resources": {resource: "*"}, "permission_groups": [group]}],
            },
        )
        token = result.get("result")
        if not isinstance(token, dict) or not token.get("id") or not token.get("value"):
            raise R2ProvisioningError("Cloudflare did not return the new R2 token credentials")
        # Cloudflare documents the S3 secret as SHA-256(token.value); the token
        # value itself must never be written to an instance file or log.
        return str(token["id"]), hashlib.sha256(str(token["value"]).encode()).hexdigest()

    def provision(
        self,
        bucket: str,
        token_name: str | None = None,
        jurisdiction: str = "default",
        location: str | None = None,
        existing_credentials: tuple[str, str] | None = None,
    ) -> R2ProvisioningResult:
        bucket = _safe_slug(bucket, "bucket")
        created = self.ensure_bucket(bucket, jurisdiction=jurisdiction, location=location)
        if existing_credentials and all(str(value).strip() for value in existing_credentials):
            return R2ProvisioningResult(
                account_id=self.account_id,
                bucket=bucket,
                jurisdiction=jurisdiction,
                access_key_id=existing_credentials[0],
                secret_access_key=existing_credentials[1],
                token_name=token_name or "existing",
                bucket_created=created,
                token_created=False,
            )
        name = token_name or f"site-agent-{bucket}-{secrets.token_hex(4)}"
        access_key, secret = self.create_bucket_token(bucket, name)
        return R2ProvisioningResult(
            account_id=self.account_id,
            bucket=bucket,
            jurisdiction=jurisdiction,
            access_key_id=access_key,
            secret_access_key=secret,
            token_name=name,
            bucket_created=created,
            token_created=True,
        )


def write_instance_r2_config(
    config_path: str | Path,
    env_path: str | Path,
    result: R2ProvisioningResult,
) -> None:
    """Write only R2 fields while preserving other instance settings."""
    import yaml

    config_path = Path(config_path)
    env_path = Path(env_path)
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise R2ProvisioningError("instance config root must be a mapping")
    site = config.setdefault("site", {})
    if not isinstance(site, dict):
        raise R2ProvisioningError("site config must be a mapping")
    media = site.setdefault("media", {})
    if not isinstance(media, dict):
        raise R2ProvisioningError("site.media config must be a mapping")
    media.update({"enabled": True, "account_id": result.account_id, "bucket": result.bucket, "private": True})
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))

    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value
    for key, value in {
        "R2_ACCESS_KEY_ID": result.access_key_id,
        "R2_SECRET_ACCESS_KEY": result.secret_access_key,
    }.items():
        existing[key] = value
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("".join(f"{key}={value}\n" for key, value in sorted(existing.items())))
    os.chmod(env_path, 0o600)


__all__ = ["CloudflareR2Provisioner", "R2ProvisioningError", "R2ProvisioningResult", "write_instance_r2_config"]
