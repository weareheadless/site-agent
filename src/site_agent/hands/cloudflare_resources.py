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


@dataclass(frozen=True)
class CloudflareWorkerReceipt:
    worker_id: str
    name: str
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {"worker_id": self.worker_id, "name": self.name, "created": self.created}


@dataclass(frozen=True)
class QueueReceipt:
    queue_id: str
    name: str
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {"queue_id": self.queue_id, "name": self.name, "created": self.created}


class CloudflareResourceProvisioner:
    """Small idempotent client for account-level Cloudflare resources."""

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

    def ensure_worker(self, name: str) -> CloudflareWorkerReceipt:
        worker_name = str(name or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker_name):
            raise CloudflareResourceError("Worker name is invalid")
        existing = self._find_worker(worker_name)
        if existing is not None:
            return existing
        status, created = self._request(
            "POST",
            f"/accounts/{self.account_id}/workers/workers",
            payload={"name": worker_name},
        )
        if status in {200, 201} and created.get("success"):
            result = created.get("result") or {}
            worker_id = str(result.get("id") or "").strip()
            returned_name = str(result.get("name") or "").strip()
            if worker_id and returned_name == worker_name:
                return CloudflareWorkerReceipt(worker_id, worker_name, True)
            raise CloudflareResourceError("Cloudflare created a Worker without the expected identity")
        if status in {400, 409, 422}:
            existing = self._find_worker(worker_name)
            if existing is not None:
                return existing
            raise CloudflareResourceError("Worker creation raced another owner and could not be reconciled")
        raise CloudflareResourceError(self._error(created))

    def workers_dev_url(self, worker_name: str) -> str:
        """Return the Worker URL using the subdomain configured on this account."""
        worker = str(worker_name or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
            raise CloudflareResourceError("Worker name is invalid")
        status, body = self._request(
            "GET",
            f"/accounts/{self.account_id}/workers/subdomain",
        )
        result = body.get("result")
        subdomain = str(result.get("subdomain") or "").strip().lower() if isinstance(result, Mapping) else ""
        if status != 200 or not body.get("success") or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", subdomain,
        ):
            raise CloudflareResourceError("Cloudflare account workers.dev subdomain is not configured")
        return f"https://{worker}.{subdomain}.workers.dev"

    def ensure_workers_dev_route(self, worker_name: str) -> None:
        """Enable this script's production workers.dev route, preserving preview settings."""
        worker = str(worker_name or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
            raise CloudflareResourceError("Worker name is invalid")
        path = (
            f"/accounts/{self.account_id}/workers/scripts/"
            f"{urllib.parse.quote(worker, safe='')}/subdomain"
        )
        status, body = self._request("GET", path)
        current = body.get("result")
        if status != 200 or not body.get("success") or not isinstance(current, Mapping):
            raise CloudflareResourceError(self._error(body))
        if not isinstance(current.get("enabled"), bool):
            raise CloudflareResourceError("Cloudflare Worker subdomain response is invalid")
        if current["enabled"]:
            return
        status, updated = self._request("POST", path, payload={"enabled": True})
        result = updated.get("result")
        if status != 200 or not updated.get("success") or not isinstance(result, Mapping) or result.get("enabled") is not True:
            raise CloudflareResourceError(self._error(updated))

    def _find_worker(self, worker_name: str) -> CloudflareWorkerReceipt | None:
        page = 1
        per_page = 100
        while True:
            query = urllib.parse.urlencode({"page": page, "per_page": per_page})
            status, body = self._request(
                "GET",
                f"/accounts/{self.account_id}/workers/workers?{query}",
            )
            if status != 200 or not body.get("success"):
                raise CloudflareResourceError(self._error(body))
            rows = body.get("result")
            if not isinstance(rows, list):
                raise CloudflareResourceError("Cloudflare Worker list response is invalid")
            for row in rows:
                if not isinstance(row, Mapping) or str(row.get("name") or "") != worker_name:
                    continue
                worker_id = str(row.get("id") or "").strip()
                if not worker_id:
                    raise CloudflareResourceError("Cloudflare Worker identity is missing its ID")
                return CloudflareWorkerReceipt(worker_id, worker_name, False)
            info = body.get("result_info")
            total_pages = info.get("total_pages") if isinstance(info, Mapping) else None
            if total_pages is not None:
                try:
                    if page >= int(total_pages):
                        return None
                except (TypeError, ValueError) as exc:
                    raise CloudflareResourceError("Cloudflare Worker pagination metadata is invalid") from exc
            elif len(rows) < per_page:
                return None
            else:
                raise CloudflareResourceError("Cloudflare Worker list omitted pagination metadata")
            page += 1

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

    def ensure_queue(self, name: str) -> QueueReceipt:
        queue_name = str(name or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", queue_name):
            raise CloudflareResourceError("Queue name is invalid")
        existing = self._find_queue(queue_name)
        if existing is not None:
            return existing
        status, created = self._request(
            "POST", f"/accounts/{self.account_id}/queues", payload={"queue_name": queue_name},
        )
        if status in {200, 201} and created.get("success"):
            row = created.get("result") or {}
            queue_id = str(row.get("queue_id") or row.get("id") or "").strip()
            if queue_id:
                return QueueReceipt(queue_id, queue_name, True)
        if status in {400, 409, 422}:
            existing = self._find_queue(queue_name)
            if existing is not None:
                return existing
            raise CloudflareResourceError("Queue creation raced another owner and could not be reconciled")
        raise CloudflareResourceError(self._error(created))

    def _find_queue(self, queue_name: str) -> QueueReceipt | None:
        page = 1
        per_page = 100
        while True:
            query = urllib.parse.urlencode({"page": page, "per_page": per_page})
            status, body = self._request(
                "GET",
                f"/accounts/{self.account_id}/queues?{query}",
            )
            if status != 200 or not body.get("success"):
                raise CloudflareResourceError(self._error(body))
            rows = body.get("result")
            if not isinstance(rows, list):
                raise CloudflareResourceError("Cloudflare Queue list response is invalid")
            for row in rows:
                if not isinstance(row, Mapping) or str(row.get("queue_name") or "") != queue_name:
                    continue
                queue_id = str(row.get("queue_id") or "").strip()
                if not queue_id:
                    raise CloudflareResourceError("Cloudflare Queue identity is missing its ID")
                return QueueReceipt(queue_id, queue_name, False)
            info = body.get("result_info")
            total_pages = info.get("total_pages") if isinstance(info, Mapping) else None
            if total_pages is not None:
                try:
                    if page >= int(total_pages):
                        return None
                except (TypeError, ValueError) as exc:
                    raise CloudflareResourceError("Cloudflare Queue pagination metadata is invalid") from exc
            elif len(rows) < per_page:
                return None
            else:
                raise CloudflareResourceError("Cloudflare Queue list omitted pagination metadata")
            page += 1

__all__ = [
    "CloudflareResourceError",
    "CloudflareResourceProvisioner",
    "CloudflareWorkerReceipt",
    "D1DatabaseReceipt",
    "QueueReceipt",
]
