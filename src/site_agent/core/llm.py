"""llm.py — direct OpenAI-compatible chat client.

No harness, no gateway process. One HTTP call to a standard
POST /chat/completions endpoint. Every call logs tokens and computed cost
into the instance memory DB so margins are always visible.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .memory import Memory


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "llm_error",
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


def _provider_error_detail(error: Any) -> tuple[str, str, int | None]:
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("detail") or "provider error")
        raw_code = error.get("code") or error.get("type") or "provider_error"
        code = str(raw_code)
        status = error.get("status")
        if not isinstance(status, int):
            try:
                status = int(raw_code)
            except (TypeError, ValueError):
                status = None
        return message[:300], code[:100], status if isinstance(status, int) else None
    return str(error)[:300], "provider_error", None


def _provider_error_is_retryable(code: str, message: str, status: int | None) -> bool:
    if status is not None and (status == 408 or status == 429 or status >= 500):
        return True
    text = f"{code} {message}".lower()
    return any(
        marker in text
        for marker in (
            "capacity",
            "overloaded",
            "rate_limit",
            "rate limit",
            "temporar",
            "timeout",
            "unavailable",
            "server_error",
        )
    )


def _http_post(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise LLMError(
            f"llm http {exc.code}: {detail}",
            code="http_error",
            status=exc.code,
            retryable=exc.code == 408 or exc.code == 429 or exc.code >= 500,
        ) from exc
    except TimeoutError as exc:
        raise LLMError(
            f"llm request timed out: {exc}",
            code="timeout",
            retryable=True,
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        timed_out = isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()
        raise LLMError(
            f"llm connection failed: {reason}",
            code="timeout" if timed_out else "connection_failed",
            retryable=True,
        ) from exc
    except OSError as exc:
        raise LLMError(
            f"llm connection failed: {exc}",
            code="connection_failed",
            retryable=True,
        ) from exc

    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LLMError(
            "llm returned invalid JSON",
            code="invalid_response",
            retryable=True,
        ) from exc
    if not isinstance(response, dict):
        raise LLMError(
            "llm returned a non-object response",
            code="invalid_response",
            retryable=True,
        )
    if response.get("error"):
        message, code, status = _provider_error_detail(response["error"])
        raise LLMError(
            f"llm provider error ({code}): {message}",
            code="provider_error",
            status=status,
            retryable=_provider_error_is_retryable(code, message, status),
        )
    return response


class Client:
    def __init__(
        self,
        config: dict[str, Any],
        memory: Memory | None = None,
        env: dict[str, str] | None = None,
    ):
        import os

        from ..config import resolve_secret

        cfg = config.get("llm") or {}
        self.base_url = str(cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        self.model = str(cfg.get("model", ""))
        self.timeout = float(cfg.get("timeout_seconds", 60))
        self.max_retries = int(cfg.get("max_retries", 2))
        self.max_tokens = int(cfg.get("max_tokens", 0)) or None
        self.prices = cfg.get("price_per_mtok") or {}
        budget = cfg.get("daily_budget_usd")
        self.daily_budget_usd = None if budget is None else float(budget)
        self.api_key = resolve_secret(config, "llm_api_key", os.environ if env is None else env)
        self.memory = memory

    @staticmethod
    def _retryable(exc: LLMError) -> bool:
        if exc.retryable:
            return True
        # Keep injected/test errors and older adapters compatible while real
        # transport errors use the structured classification above.
        text = str(exc).lower()
        return (
            "http 408" in text
            or "http 429" in text
            or "http 5" in text
            or "connection failed" in text
            or "timed out" in text
        )

    def _post_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
        retry_limit: int,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return _http_post(url, headers, payload, timeout)
            except LLMError as exc:
                if not self._retryable(exc) or attempt >= retry_limit:
                    raise
                attempt += 1
                time.sleep(min(2 ** attempt, 8))

    def _check_budget(self) -> None:
        if self.daily_budget_usd is None or self.memory is None:
            return
        spent = self.memory.llm_spend(since_hours=24)["cost_usd"]
        if spent >= self.daily_budget_usd:
            raise LLMError(
                f"daily LLM budget exhausted: ${spent:.2f} >= ${self.daily_budget_usd:.2f}; "
                "jobs will resume when the window clears"
            )

    def chat_tools(
        self,
        messages,
        tools,
        temperature=None,
        *,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ):
        """Native tool-calling round -> {"content", "tool_calls"}."""
        if not self.api_key:
            raise LLMError("llm_api_key not configured")
        self._check_budget()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None or self.max_tokens:
            payload["max_tokens"] = max(int(max_tokens or self.max_tokens), 1)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        request_timeout = self.timeout if timeout_seconds is None else max(float(timeout_seconds), 0.1)
        retry_limit = self.max_retries if max_retries is None else max(int(max_retries), 0)
        response = self._post_with_retries(url, headers, payload, request_timeout, retry_limit)
        message = (response.get("choices") or [{}])[0].get("message", {})
        usage = response.get("usage") or {}
        if self.memory is not None:
            self.memory.log_llm_cost(
                model=response.get("model") or payload["model"],
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cost_usd=self._cost(usage),
            )
        return {"content": message.get("content"), "tool_calls": message.get("tool_calls")}

    def _cost(self, usage: dict[str, Any]) -> float | None:
        prompt_tokens = float(usage.get("prompt_tokens") or 0)
        completion_tokens = float(usage.get("completion_tokens") or 0)
        pin = self.prices.get("input")
        pout = self.prices.get("output")
        if pin is None and pout is None:
            return None
        cost = 0.0
        if pin is not None:
            cost += prompt_tokens * float(pin) / 1_000_000
        if pout is not None:
            cost += completion_tokens * float(pout) / 1_000_000
        return round(cost, 6)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> str:
        if not self.api_key:
            raise LLMError("llm_api_key not configured")
        self._check_budget()
        payload: dict[str, Any] = {"model": model or self.model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None or self.max_tokens:
            payload["max_tokens"] = max(int(max_tokens or self.max_tokens), 1)
        if json_mode:
            messages = list(messages)
            if messages and messages[0]["role"] == "system":
                messages[0] = dict(messages[0])
                messages[0]["content"] += "\n\nRespond with a single valid JSON object and nothing else."
            else:
                messages.insert(0, {"role": "system", "content": "Respond with a single valid JSON object and nothing else."})
            payload["messages"] = messages
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        request_timeout = self.timeout if timeout_seconds is None else max(float(timeout_seconds), 0.1)
        retry_limit = self.max_retries if max_retries is None else max(int(max_retries), 0)
        response = self._post_with_retries(
            url, headers, payload, request_timeout, retry_limit
        )
        try:
            content = response["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected llm response shape: {str(response)[:200]}") from exc
        if not (content or "").strip():
            raise LLMError("model returned an empty completion")
        usage = response.get("usage") or {}
        if self.memory is not None:
            self.memory.log_llm_cost(
                model=response.get("model") or payload["model"],
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cost_usd=self._cost(usage),
            )
        return content


def _unwrap_fenced(text: str) -> str:
    """Strip a markdown code fence (```json …``` or ~~~ … ~~~) if present."""
    lines = text.strip().splitlines()
    if not lines:
        return text
    if lines[0].strip().startswith(("```", "~~~")):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith(("```", "~~~")):
        lines = lines[:-1]
    return "\n".join(lines).strip() or text


def _extract_top_level_blocks(text: str) -> list[str]:
    """Scan for every complete top-level JSON object/array in the text.

    String- and escape-aware, honors nested braces/brackets with a stack, and
    yields only blocks that close cleanly. Prose around them is ignored."""
    blocks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch not in "{[":
            i += 1
            continue
        start = i
        stack: list[str] = []
        in_string = False
        j = i
        while j < n:
            c = text[j]
            if in_string:
                if c == "\\":
                    j += 2
                    continue
                if c == '"':
                    in_string = False
                j += 1
                continue
            if c == '"':
                in_string = True
                j += 1
                continue
            if c in "{[":
                stack.append("}" if c == "{" else "]")
            elif c in "}]":
                if not stack or stack[-1] != c:
                    break
                stack.pop()
                if not stack:
                    blocks.append(text[start:j + 1])
                    i = j + 1
                    break
            j += 1
        else:
            i = start + 1
    return blocks


def _parse_longest_valid(blocks: list[str]):
    """Return the parsed value of the largest block that is valid JSON
    (preferring the structured answer over any small object quoted in prose)."""
    best = None
    for block in blocks:
        try:
            parsed = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        if best is None or len(block) > len(best[1]):
            best = (parsed, block)
    return best[0] if best else None


def _repair_json_lax(text: str) -> str:
    """String-aware removal of // and /* */ comments and trailing commas — the
    most common ways models break otherwise-valid JSON."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        if ch == ",":
            k = i + 1
            while k < n and text[k] in " \t\n\r":
                k += 1
            if k < n and text[k] in "}]":
                i += 1  # drop a trailing comma before the closing bracket
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_json(text):
    """Return the most plausible JSON value in model output, or None.

    A robust pipeline instead of the old first-balanced-`{` salvage:

    1. strict parse of the trimmed text;
    2. strip a markdown code fence and retry;
    3. scan for complete, parseable top-level JSON blocks (string- and
       escape-aware) and return the largest valid one;
    4. tolerant repair (comments, trailing commas) then re-scan.

    Returns None only when nothing remotely JSON-shaped parses, so callers can
    fall back to asking the model for clean JSON.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    candidates = []
    fenced = _unwrap_fenced(text)
    candidates.append(fenced)
    if fenced != text.strip():
        candidates.append(text.strip())
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            pass
    for candidate in candidates:
        parsed = _parse_longest_valid(_extract_top_level_blocks(candidate))
        if parsed is not None:
            return parsed
    repaired = _repair_json_lax(text)
    for candidate in (_unwrap_fenced(repaired), repaired):
        parsed = _parse_longest_valid(_extract_top_level_blocks(candidate))
        if parsed is not None:
            return parsed
    return None
