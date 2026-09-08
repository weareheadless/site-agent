"""Small typed HTTP client for Cicero's versioned agent API."""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..core.contracts import safe_provider_message


class CiceroConfigurationError(ValueError):
    pass


class CiceroClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str = "provider_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class CiceroResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class CiceroTransport(Protocol):
    def request(self, method: str, path: str, headers: Mapping[str, str], body: bytes | None = None) -> CiceroResponse:
        ...


class UrllibTransport:
    """Default transport with one bounded timeout for connect/read operations."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0, max_response_bytes: int = 50 * 1024 * 1024) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_response_bytes = max(1, int(max_response_bytes))

    def request(self, method: str, path: str, headers: Mapping[str, str], body: bytes | None = None) -> CiceroResponse:
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=dict(headers), method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return CiceroResponse(
                    response.status,
                    dict(response.headers.items()),
                    _bounded_read(response, self.max_response_bytes),
                )
        except urllib.error.HTTPError as exc:
            return CiceroResponse(
                exc.code,
                dict(exc.headers.items()) if exc.headers else {},
                _bounded_read(exc, self.max_response_bytes),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CiceroClientError(
                "Cicero did not respond", code="provider_unreachable"
            ) from exc


def _bounded_read(response: Any, maximum: int) -> bytes:
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise CiceroClientError("Cicero response exceeded the configured size limit", code="response_too_large")
    return body


def _positive_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text.isdigit() or int(text) <= 0:
        raise CiceroClientError(f"Cicero returned an invalid {field}", code="invalid_provider_response")
    return text


def _asset_name(value: Any) -> str:
    name = str(value or "")
    if not name or os.path.basename(name) != name or "/" in name or "\\" in name or ".." in name:
        raise CiceroClientError("asset name is invalid", code="invalid_asset_name")
    return name


@dataclass(frozen=True)
class CiceroOperation:
    operation_id: str
    status: str
    created_at: str | None = None
    artifact: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CiceroOperation":
        if not isinstance(payload, Mapping):
            raise CiceroClientError("Cicero returned an invalid operation", code="invalid_provider_response")
        operation_id = _positive_id(payload.get("operation_id"), "operation id")
        status = str(payload.get("status") or "").strip()
        if status not in {"queued", "running", "completed", "failed", "interrupted"}:
            raise CiceroClientError("Cicero returned an invalid operation status", code="invalid_provider_response")
        artifact = payload.get("artifact")
        if artifact is not None and not isinstance(artifact, dict):
            raise CiceroClientError("Cicero returned an invalid artifact", code="invalid_provider_response")
        error = payload.get("error")
        if error is not None and not isinstance(error, dict):
            error = {"message": safe_provider_message(str(error))}
        return cls(
            operation_id=operation_id,
            status=status,
            created_at=str(payload["created_at"]) if payload.get("created_at") else None,
            artifact=artifact,
            error=error,
        )


def configured(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    provider = ((config.get("providers") or {}).get("cicero") or {})
    token_env = str(provider.get("token_env") or "CICERO_SERVICE_TOKEN")
    return bool(provider.get("enabled")) and bool(str(provider.get("base_url") or "").strip()) and bool(env.get(token_env, "").strip())


class CiceroClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: CiceroTransport | None = None,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        base_url = str(base_url or "").strip().rstrip("/")
        token = str(token or "").strip()
        if not base_url or not token:
            raise CiceroConfigurationError("Cicero base_url and service token are required")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CiceroConfigurationError("Cicero base_url must be an HTTP(S) URL")
        self._base_url = base_url
        self._token = token
        self._max_response_bytes = max(1, int(max_response_bytes))
        self._transport = transport or UrllibTransport(base_url, timeout_seconds, self._max_response_bytes)

    @classmethod
    def from_config(cls, config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> "CiceroClient | None":
        env = os.environ if env is None else env
        provider = ((config.get("providers") or {}).get("cicero") or {})
        if not provider.get("enabled"):
            return None
        token_env = str(provider.get("token_env") or "CICERO_SERVICE_TOKEN")
        token = env.get(token_env, "")
        if not str(provider.get("base_url") or "").strip() or not token.strip():
            return None
        return cls(
            str(provider["base_url"]),
            token,
            timeout_seconds=float(provider.get("timeout_seconds", 30)),
            max_response_bytes=int(provider.get("max_response_bytes", 50 * 1024 * 1024)),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    def _request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        accept: str = "application/json",
        extra_headers: Mapping[str, str] | None = None,
    ) -> CiceroResponse:
        encoded = None
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "site-agent-cicero/1",
        }
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self._transport.request(method, path, headers, encoded)
        except CiceroClientError:
            raise
        except Exception as exc:  # noqa: BLE001 — transport details stay behind a safe error
            raise CiceroClientError("Cicero request failed", code="provider_unreachable") from exc
        if response.status_code >= 400:
            raise self._error(response)
        return response

    @staticmethod
    def _json(response: CiceroResponse) -> Any:
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CiceroClientError("Cicero returned invalid JSON", code="invalid_provider_response") from exc
        return value

    def _error(self, response: CiceroResponse) -> CiceroClientError:
        code = "provider_error"
        message = f"Cicero request failed ({response.status_code})"
        try:
            payload = json.loads(response.body.decode("utf-8"))
            if isinstance(payload, dict):
                detail = payload.get("detail")
                error = payload.get("error")
                if isinstance(error, dict):
                    code = str(error.get("code") or code)
                    detail = error.get("message") or detail
                if detail:
                    message = safe_provider_message(str(detail))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return CiceroClientError(message, status_code=response.status_code, code=code)

    def brand(self) -> dict[str, Any]:
        value = self._json(self._request("GET", "/api/v1/brand"))
        if not isinstance(value, dict):
            raise CiceroClientError("Cicero returned an invalid brand", code="invalid_provider_response")
        return value

    def media(self) -> list[dict[str, Any]]:
        payload = self._json(self._request("GET", "/api/v1/media"))
        # The endpoint intentionally returns a list, so retain a small typed
        # validation boundary rather than passing arbitrary JSON to callers.
        if not isinstance(payload, list):
            raise CiceroClientError("Cicero returned an invalid media list", code="invalid_provider_response")
        return payload

    def prepare(self, payload: Mapping[str, Any], idempotency_key: str) -> CiceroOperation:
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 255:
            raise CiceroClientError("a valid idempotency key is required", code="invalid_request")
        response = self._request(
            "POST",
            "/api/v1/post-preparations",
            dict(payload),
            extra_headers={"Idempotency-Key": key},
        )
        return CiceroOperation.from_payload(self._json(response))

    def operation(self, operation_id: str | int) -> CiceroOperation:
        operation = _positive_id(operation_id, "operation id")
        response = self._request("GET", f"/api/v1/operations/{urllib.parse.quote(operation, safe='')}")
        return CiceroOperation.from_payload(self._json(response))

    def wait_operation(
        self,
        operation_id: str | int,
        *,
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 600.0,
        sleep=time.sleep,
    ) -> CiceroOperation:
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        interval = max(0.05, float(poll_interval_seconds))
        while True:
            operation = self.operation(operation_id)
            if operation.status in {"completed", "failed", "interrupted"}:
                return operation
            if time.monotonic() >= deadline:
                raise CiceroClientError("Cicero preparation timed out", code="provider_timeout")
            sleep(interval)

    def post(self, post_id: str | int) -> dict[str, Any]:
        post = _positive_id(post_id, "post id")
        value = self._json(self._request("GET", f"/api/v1/posts/{urllib.parse.quote(post, safe='')}"))
        if not isinstance(value, dict):
            raise CiceroClientError("Cicero returned an invalid post", code="invalid_provider_response")
        return value

    def asset(self, post_id: str | int, filename: str) -> tuple[bytes, str]:
        post = _positive_id(post_id, "post id")
        name = _asset_name(filename)
        response = self._request(
            "GET",
            f"/api/v1/posts/{urllib.parse.quote(post, safe='')}/assets/{urllib.parse.quote(name, safe='')}",
            accept="*/*",
        )
        content_type = response.headers.get("Content-Type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return response.body, content_type.split(";", 1)[0].strip()


__all__ = [
    "CiceroClient",
    "CiceroClientError",
    "CiceroConfigurationError",
    "CiceroOperation",
    "CiceroResponse",
    "CiceroTransport",
    "configured",
]
