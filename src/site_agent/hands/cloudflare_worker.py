"""Small Cloudflare Workers secrets client used by tenant bootstrap.

The site-agent already owns the Cloudflare deployment credential.  Keeping the
secret write here means a provisioned Google verification token (and the public
GA measurement id) can be delivered to the Worker without asking an operator to
copy values between systems.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

CF_API = "https://api.cloudflare.com/client/v4"
USER_AGENT = "site-agent/0.1 (+https://helloada.app)"


class CloudflareWorkerError(RuntimeError):
    """A safe, customer-readable Worker configuration failure."""


def _error_message(payload: Mapping[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, Mapping):
            return str(first.get("message") or "Cloudflare API error")[:300]
    return "Cloudflare API error"


class CloudflareWorkerSecretsClient:
    """Write individual encrypted Worker secrets for one script."""

    def __init__(
        self,
        api_token: str,
        account_id: str,
        worker_name: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        token = str(api_token or "").strip()
        account = str(account_id or "").strip()
        worker = str(worker_name or "").strip()
        if not token:
            raise CloudflareWorkerError("Cloudflare Worker API token is missing")
        if not account:
            raise CloudflareWorkerError("Cloudflare account id is missing")
        if not worker:
            raise CloudflareWorkerError("Cloudflare Worker name is missing")
        self._token = token
        self._account_id = account
        self._worker_name = worker
        self._timeout = float(timeout_seconds)

    @property
    def endpoint(self) -> str:
        return (
            f"{CF_API}/accounts/{urllib.parse.quote(self._account_id, safe='')}/workers/scripts/"
            f"{urllib.parse.quote(self._worker_name, safe='')}/secrets"
        )

    def put_secret(self, name: str, value: str) -> dict[str, str]:
        secret_name = str(name or "").strip()
        secret_value = str(value or "")
        if not secret_name or not secret_name.replace("_", "").isalnum():
            raise CloudflareWorkerError("Worker secret name is invalid")
        if not secret_value:
            raise CloudflareWorkerError("Worker secret value is missing")
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps({"name": secret_name, "text": secret_value, "type": "secret_text"}).encode(),
            method="PUT",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode() or "{}")
            except (ValueError, UnicodeError):
                payload = {}
            raise CloudflareWorkerError(_error_message(payload)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudflareWorkerError(f"Cloudflare Worker request failed: {type(exc).__name__}") from exc
        if not isinstance(payload, Mapping) or not payload.get("success"):
            raise CloudflareWorkerError(_error_message(payload if isinstance(payload, Mapping) else {}))
        return {"name": secret_name, "status": "written"}


__all__ = ["CloudflareWorkerError", "CloudflareWorkerSecretsClient"]
