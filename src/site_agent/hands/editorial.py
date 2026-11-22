"""The editorial writing service, as one host connection.

Site-agent decides *what* gets written and *where* it lands. Editorial decides
*how* it is written, and — for a subject nobody has read yet — researches it
first. That split is why this client exists at all instead of another prompt.

Two rules shape it:

- One connection for every tenant. The brief names the tenant; editorial holds
  the research credential. A token per tenant is the shape that strands every
  new customer on an unconfigured host, and it buys nothing: the tenant is
  already an authenticated field of the brief.
- A `held` answer is an editorial outcome, not an outage. It is surfaced with
  its reason and never retried as if the service had failed. A `failed` answer
  is a real failure and is raised.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.contracts import safe_provider_message


class EditorialError(RuntimeError):
    """Base error for a safe editorial service failure."""


class EditorialUnavailableError(EditorialError):
    """The service could not be reached, or refused the service credential."""


class EditorialRejectedError(EditorialError):
    """The service refused the brief itself; retrying it unchanged cannot help."""

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class EditorialTimeout(EditorialError):
    """The post did not reach a terminal state inside the caller's budget."""


@dataclass(frozen=True)
class EditorialPost:
    """One terminal editorial post and the artifact a destination consumes."""

    post_id: str
    state: str
    artifacts: Mapping[str, Mapping[str, Any]]
    error: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    @property
    def held(self) -> bool:
        return self.state == "held"

    def artifact(self, locale: str) -> Mapping[str, Any]:
        artifact = self.artifacts.get(locale)
        if not isinstance(artifact, Mapping):
            raise EditorialError(
                f"editorial post {self.post_id} has no '{locale}' artifact "
                f"(it returned {sorted(self.artifacts) or 'none'})"
            )
        return artifact


TERMINAL_STATES = frozenset({"ready", "awaiting_approval", "held", "failed", "cancelled", "published"})


class EditorialClient:
    """A small typed client over editorial's documented `/v1` surface."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        poll_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_response_bytes = max(1, int(max_response_bytes))
        self.poll_seconds = max(0.0, float(poll_seconds))

    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured():
            raise EditorialUnavailableError(
                "the editorial service connection is not configured (providers.editorial)"
            )
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "HelloAda/site-agent-editorial",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read(8193).decode("utf-8"))
                if isinstance(payload, Mapping):
                    detail = str(payload.get("error") or payload.get("detail") or "")
            except (ValueError, OSError):
                detail = ""
            message = f"editorial rejected the {path} request (HTTP {exc.code})"
            if detail:
                message = f"{message}: {safe_provider_message(detail)[:300]}"
            if exc.code in {401, 403}:
                raise EditorialUnavailableError(message) from None
            if exc.code >= 500 or exc.code == 429:
                raise EditorialUnavailableError(message) from None
            raise EditorialRejectedError(message, status_code=exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EditorialUnavailableError(
                f"the editorial service could not be reached at {self.base_url}: {safe_provider_message(str(exc))[:200]}"
            ) from None
        if len(raw) > self.max_response_bytes:
            raise EditorialError("the editorial response exceeded the configured size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise EditorialError("the editorial service returned a non-JSON response") from exc
        if not isinstance(payload, Mapping):
            raise EditorialError("the editorial service returned an invalid response")
        return dict(payload)

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/healthz", timeout=self.timeout_seconds
            ) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def submit(self, brief: Mapping[str, Any]) -> str:
        """Queue one brief and return its post id.

        The idempotency key is the caller's, so a retried acceptance of the same
        action revision cannot buy a second article.
        """
        payload = self._request("POST", "/v1/posts", brief)
        post_id = str(payload.get("post_id") or "").strip()
        if not post_id:
            raise EditorialError("the editorial service accepted the brief without a post id")
        return post_id

    def post(self, post_id: str) -> EditorialPost:
        payload = self._request("GET", f"/v1/posts/{post_id}")
        artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), Mapping) else {}
        return EditorialPost(
            post_id=str(payload.get("id") or post_id),
            state=str(payload.get("state") or ""),
            artifacts={str(key): value for key, value in artifacts.items() if isinstance(value, Mapping)},
            error=str(payload.get("error") or ""),
        )

    def wait(self, post_id: str, *, deadline_seconds: float, on_poll: Any = None) -> EditorialPost:
        """Poll until the post is terminal or the caller's budget runs out.

        The budget belongs to the caller: editorial's own deadline may be longer
        than the request that started it, and a chat turn must not hang on it.
        """
        deadline = time.monotonic() + max(1.0, float(deadline_seconds))
        while True:
            post = self.post(post_id)
            if post.state in TERMINAL_STATES:
                if post.state == "failed":
                    raise EditorialError(
                        f"editorial post {post_id} failed: {post.error[:300] or 'no reason given'}"
                    )
                return post
            if time.monotonic() >= deadline:
                raise EditorialTimeout(
                    f"editorial post {post_id} was still {post.state or 'working'} after "
                    f"{int(deadline_seconds)}s; it continues in the editorial service and can be "
                    "polled again by its id"
                )
            if callable(on_poll):
                on_poll(post)
            time.sleep(min(self.poll_seconds, max(0.0, deadline - time.monotonic())))

    def write(self, brief: Mapping[str, Any], *, deadline_seconds: float) -> EditorialPost:
        """Submit a brief and wait for its terminal post."""
        return self.wait(self.submit(brief), deadline_seconds=deadline_seconds)


def build_editorial_client(config: Mapping[str, Any] | None) -> EditorialClient:
    """Resolve the one host connection into a client.

    Imported here rather than at module scope so `hands` stays importable
    without the credential wiring (tests, offline installs).
    """
    from ..credentials import editorial_connection

    url, token = editorial_connection(config)
    return EditorialClient(base_url=url, token=token)
