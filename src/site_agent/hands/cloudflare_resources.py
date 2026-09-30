"""Cloudflare account resources used by the HelloAda bootstrap saga."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


CF_API = "https://api.cloudflare.com/client/v4"


class CloudflareResourceError(RuntimeError):
    """A required Cloudflare resource could not be created or read."""


@dataclass(frozen=True)
class D1DatabaseReceipt:
    database_id: str
    name: str
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {"database_id": self.database_id, "name": self.name, "created": self.created}


class CloudflareResourceProvisioner:
    """Small idempotent client for account-level D1 resources."""

    def __init__(self, account_id: str, api_token: str, *, timeout_seconds: float = 30.0) -> None:
        self.account_id = str(account_id or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{32}", self.account_id):
            raise CloudflareResourceError("Cloudflare account ID is invalid")
        self.api_token = str(api_token or "").strip()
        if not self.api_token:
            raise CloudflareResourceError("Cloudflare API token is missing")
        self.timeout_seconds = float(timeout_seconds)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = json.dumps(dict(payload)).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{CF_API}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "helloada-bootstrap",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024)
                body = json.loads(raw.decode("utf-8") or "{}")
                return int(response.status), body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(32 * 1024)
                body = json.loads(raw.decode("utf-8") or "{}")
            except (OSError, UnicodeError, ValueError):
                body = {}
            return int(exc.code), body if isinstance(body, dict) else {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudflareResourceError(
                f"Cloudflare API request failed: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _error(body: Mapping[str, Any]) -> str:
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, Mapping):
                return str(first.get("message") or "Cloudflare API error")[:300]
        return "Cloudflare API error"

    def ensure_d1(self, name: str, *, location: str | None = None) -> D1DatabaseReceipt:
        database_name = str(name or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", database_name):
            raise CloudflareResourceError("D1 database name is invalid")
        existing = self._find_d1(database_name)
        if existing is not None:
            return existing
        payload: dict[str, Any] = {"name": database_name}
        if location:
            payload["primary_location_hint"] = str(location).strip().lower()
        status, created = self._request(
            "POST",
            f"/accounts/{self.account_id}/d1/database",
            payload=payload,
        )
        if status in {200, 201} and created.get("success"):
            result = created.get("result") or {}
            database_id = str(result.get("uuid") or result.get("id") or "").strip()
            if database_id:
                return D1DatabaseReceipt(database_id, database_name, True)
        if status in {400, 409, 422}:
            existing = self._find_d1(database_name)
            if existing is not None:
                return existing
            raise CloudflareResourceError("D1 database creation raced another owner and could not be reconciled")
        raise CloudflareResourceError(self._error(created))

    def _find_d1(self, database_name: str) -> D1DatabaseReceipt | None:
        query = urllib.parse.urlencode({"name": database_name})
        status, body = self._request("GET", f"/accounts/{self.account_id}/d1/database?{query}")
        if status != 200 or not body.get("success"):
            if status not in {200, 404}:
                raise CloudflareResourceError(self._error(body))
            return None
        rows = body.get("result") or []
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, Mapping) and str(row.get("name") or "") == database_name:
                database_id = str(row.get("uuid") or row.get("id") or "").strip()
                if database_id:
                    return D1DatabaseReceipt(database_id, database_name, False)
        return None


__all__ = ["CloudflareResourceError", "CloudflareResourceProvisioner", "D1DatabaseReceipt"]
