"""CrawlSEO's fixed, project-scoped MCP transport adapter.

The optional MCP SDK is deliberately imported only when this adapter starts.
This keeps direct Google and offline site-agent installs usable without the
optional dependency, while still using the official Streamable HTTP client when
the provider is enabled.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack
from typing import Any

try:
    from httpx import AsyncByteStream
except ImportError:  # pragma: no cover - the optional MCP extra supplies httpx
    class AsyncByteStream:  # type: ignore[no-redef]
        """Fallback base so the optional dependency remains lazy."""

        pass

from ..config import ConfigError, CrawlSEOSettings, crawlseo_configured
from ..core.contracts import safe_provider_message


class CrawlSEOError(RuntimeError):
    """Base error for safe CrawlSEO provider failures."""


class CrawlSEOConfigurationError(CrawlSEOError, ConfigError):
    """The provider cannot start because its local configuration is invalid."""


class CrawlSEOUnavailableError(CrawlSEOError):
    """The configured endpoint or provider session is unavailable."""


class CrawlSEOTimeoutError(CrawlSEOError):
    """A provider operation exceeded the configured timeout."""


class CrawlSEOResponseTooLargeError(CrawlSEOError):
    """The provider response exceeded the configured byte limit."""


class CrawlSEOProtocolError(CrawlSEOError):
    """The provider returned a result outside the fixed MCP contract."""


_KNOWN_TOOLS = frozenset({
    "seo_get_project",
    "seo_get_search_summary",
    "seo_get_analytics_summary",
    "seo_request_research_report",
    "seo_get_research_report_status",
    "seo_get_research_report",
    "seo_get_latest_research_report",
    "seo_list_research_reports",
    "seo_get_dataforseo_domain_report",
    "seo_get_dataforseo_keyword_report",
    "seo_get_crawl_summary",
    "seo_get_crawl_issues",
    "seo_prepare_monthly_site_evidence",
    "seo_get_monthly_site_evidence",
    "seo_request_article_keyword_research",
    "seo_request_article_serp_research",
    "seo_get_article_keyword_research_status",
    "seo_get_article_keyword_research",
    "seo_list_article_keyword_research",
})
_MISSING = object()


class _LimitedResponseStream(AsyncByteStream):
    """Limit decoded response bytes before the MCP SDK parses a message."""

    def __init__(self, stream: Any, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes

    async def __aiter__(self):
        total = 0
        try:
            async for chunk in self._stream:
                total += len(chunk)
                if total > self._max_bytes:
                    raise CrawlSEOResponseTooLargeError("CrawlSEO response exceeded the configured size limit")
                yield chunk
        except Exception:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()


class _LimitedAsyncTransport:
    """A small httpx transport wrapper; MCP remains responsible for MCP framing."""

    def __init__(self, transport: Any, max_bytes: int) -> None:
        self._transport = transport
        self._max_bytes = max_bytes

    async def __aenter__(self):
        await self._transport.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self.aclose()

    async def handle_async_request(self, request: Any) -> Any:
        response = await self._transport.handle_async_request(request)
        raw_length = response.headers.get("content-length")
        try:
            declared_length = int(raw_length) if raw_length is not None else None
        except (TypeError, ValueError):
            declared_length = None
        if declared_length is not None and declared_length > self._max_bytes:
            await response.aclose()
            raise CrawlSEOResponseTooLargeError("CrawlSEO response exceeded the configured size limit")
        response.stream = _LimitedResponseStream(response.stream, self._max_bytes)
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def _load_mcp_sdk():
    """Load only the official v1 client surface supported by this adapter."""
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except (ImportError, AttributeError) as exc:
        raise CrawlSEOConfigurationError(
            "CrawlSEO requires the official MCP Python client with Streamable HTTP; "
            "install the optional dependency with pip install 'site-agent[crawlseo]'"
        ) from exc
    if not callable(streamable_http_client) or not callable(ClientSession):
        raise CrawlSEOConfigurationError(
            "the installed MCP Python client does not provide the supported Streamable HTTP API"
        )
    return ClientSession, streamable_http_client


def _safe_exception(exc: BaseException, token: str = "") -> str:
    text = safe_provider_message(str(exc), max_chars=300)
    if token:
        text = text.replace(token, "[REDACTED]")
    return text or "CrawlSEO provider request failed"


def _request_headers(settings: CrawlSEOSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.token}",
        "X-Request-ID": uuid.uuid4().hex,
    }


class _MCPRuntime:
    """Own one MCP session on one event-loop thread for the process lifetime."""

    def __init__(self, settings: CrawlSEOSettings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive() and self._session is not None:
                return
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._thread_main,
                name="site-agent-crawlseo-mcp",
                daemon=True,
            )
            self._thread.start()
            thread = self._thread

        if not self._ready.wait(timeout=self.settings.timeout_seconds):
            self.close()
            raise CrawlSEOTimeoutError("CrawlSEO MCP runtime did not start before the configured timeout")
        with self._lock:
            loop = self._loop
        if loop is None:
            self.close()
            raise CrawlSEOUnavailableError("CrawlSEO MCP runtime is unavailable")

        future = asyncio.run_coroutine_threadsafe(self._connect(), loop)
        try:
            future.result(timeout=self.settings.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            self.close()
            raise CrawlSEOTimeoutError("CrawlSEO MCP session did not initialize before the configured timeout") from exc
        except CrawlSEOError:
            self.close()
            raise
        except Exception as exc:  # noqa: BLE001 — provider details stay behind a safe boundary
            self.close()
            raise CrawlSEOUnavailableError("CrawlSEO MCP session is unavailable") from exc
        if not thread.is_alive():
            raise CrawlSEOUnavailableError("CrawlSEO MCP runtime stopped during startup")

    def close(self) -> None:
        with self._lock:
            thread = self._thread
            loop = self._loop
        if thread is None:
            return
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._disconnect(), loop)
            try:
                future.result(timeout=self.settings.timeout_seconds)
            except Exception:  # noqa: BLE001 — shutdown must not mask the original provider error
                future.cancel()
            loop.call_soon_threadsafe(loop.stop)
        if thread is not threading.current_thread():
            thread.join(timeout=self.settings.timeout_seconds)
        with self._lock:
            self._thread = None
            self._loop = None
            self._session = None
            self._stack = None

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Mapping[str, Any]:
        self.start()
        with self._lock:
            loop = self._loop
        if loop is None:
            raise CrawlSEOUnavailableError("CrawlSEO MCP runtime is unavailable")
        future = asyncio.run_coroutine_threadsafe(self._call(tool_name, arguments), loop)
        try:
            result = future.result(timeout=self.settings.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise CrawlSEOTimeoutError("CrawlSEO request exceeded the configured timeout") from exc
        except CrawlSEOError:
            raise
        except Exception as exc:  # noqa: BLE001 — do not expose remote payloads
            raise CrawlSEOUnavailableError(_safe_exception(exc, self.settings.token)) from exc
        if not isinstance(result, Mapping):
            raise CrawlSEOProtocolError("CrawlSEO returned a non-object structured result")
        return result

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            stack = self._stack
            if stack is not None:
                loop.run_until_complete(stack.aclose())
            with self._lock:
                self._session = None
                self._stack = None
            loop.close()

    async def _connect(self) -> None:
        ClientSession, streamable_http_client = _load_mcp_sdk()
        try:
            import httpx
        except ImportError as exc:
            raise CrawlSEOConfigurationError(
                "CrawlSEO requires httpx through the official MCP client; install 'site-agent[crawlseo]'"
            ) from exc

        stack = AsyncExitStack()
        try:
            transport = _LimitedAsyncTransport(
                httpx.AsyncHTTPTransport(),
                self.settings.max_response_bytes,
            )
            timeout = httpx.Timeout(
                self.settings.timeout_seconds,
                connect=min(self.settings.timeout_seconds, 10.0),
                read=self.settings.timeout_seconds,
                write=self.settings.timeout_seconds,
                pool=self.settings.timeout_seconds,
            )
            http_client = httpx.AsyncClient(
                headers=_request_headers(self.settings),
                timeout=timeout,
                transport=transport,
            )
            await stack.enter_async_context(http_client)
            try:
                stream_context = streamable_http_client(self.settings.url, http_client=http_client)
            except TypeError as exc:
                raise CrawlSEOConfigurationError(
                    "the installed MCP Python client does not support the configured Streamable HTTP API"
                ) from exc
            streams = await stack.enter_async_context(stream_context)
            if not isinstance(streams, (tuple, list)) or len(streams) < 2:
                raise CrawlSEOConfigurationError("the installed MCP Python client returned invalid Streamable HTTP streams")
            session = ClientSession(streams[0], streams[1])
            await stack.enter_async_context(session)
            await asyncio.wait_for(session.initialize(), timeout=self.settings.timeout_seconds)
        except CrawlSEOError:
            await stack.aclose()
            raise
        except TypeError as exc:
            await stack.aclose()
            raise CrawlSEOConfigurationError(
                "the installed MCP Python client does not provide the supported Streamable HTTP API"
            ) from exc
        except asyncio.TimeoutError as exc:
            await stack.aclose()
            raise CrawlSEOTimeoutError("CrawlSEO MCP session initialization timed out") from exc
        except Exception as exc:  # noqa: BLE001 — endpoint details are not safe diagnostics
            await stack.aclose()
            raise CrawlSEOUnavailableError("CrawlSEO MCP endpoint is unavailable") from exc
        with self._lock:
            self._stack = stack
            self._session = session

    async def _disconnect(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> Mapping[str, Any]:
        session = self._session
        if session is None:
            raise CrawlSEOUnavailableError("CrawlSEO MCP session is not initialized")
        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=self.settings.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise CrawlSEOTimeoutError("CrawlSEO request exceeded the configured timeout") from exc
        if bool(getattr(result, "isError", False) or getattr(result, "is_error", False)):
            raise CrawlSEOUnavailableError("CrawlSEO tool request failed")
        payload: Any = _MISSING
        if isinstance(result, Mapping):
            payload = result.get("structuredContent", result.get("structured_content", _MISSING))
        else:
            for name in ("structuredContent", "structured_content"):
                value = getattr(result, name, _MISSING)
                if value is not _MISSING:
                    payload = value
                    break
        if payload is _MISSING or not isinstance(payload, Mapping):
            raise CrawlSEOProtocolError("CrawlSEO tool returned no structured content")
        return payload


class CrawlSEOClient:
    """Fixed hand adapter for project-scoped reads, evidence, and research."""

    def __init__(self, settings: CrawlSEOSettings, *, runtime: Any | None = None) -> None:
        if not settings.enabled:
            raise CrawlSEOConfigurationError("CrawlSEO client cannot be created while the provider is disabled")
        if not settings.token:
            raise CrawlSEOConfigurationError("CrawlSEO client requires a configured service token")
        self.settings = settings
        self._runtime = runtime or _MCPRuntime(settings)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        env: dict[str, str] | None = None,
    ) -> "CrawlSEOClient | None":
        settings = CrawlSEOSettings.from_config(config, env=env)
        return cls(settings) if settings.enabled else None

    def start(self) -> None:
        self._runtime.start()

    def close(self) -> None:
        self._runtime.close()

    def project(self) -> Mapping[str, Any]:
        return self._invoke("seo_get_project", {})

    def search_summary(self, days: int = 28, query_limit: int = 10) -> Mapping[str, Any]:
        return self._invoke("seo_get_search_summary", {"days": days, "query_limit": query_limit})

    def analytics_summary(self) -> Mapping[str, Any]:
        return self._invoke("seo_get_analytics_summary", {})

    def request_research_report(self, brief: Mapping[str, Any], idempotency_key: str) -> Mapping[str, Any]:
        market = brief.get("focus_market") if isinstance(brief.get("focus_market"), Mapping) else {}
        rationale = brief.get("selection_rationale") if isinstance(brief.get("selection_rationale"), Mapping) else {}
        arguments = {
            "period": brief.get("period"),
            "focus_language": market.get("language"),
            "focus_country": market.get("country"),
            "business_goal": brief.get("business_goal"),
            "audience": brief.get("audience", []),
            "priority_services": brief.get("priority_services", []),
            "keyword_seeds": brief.get("keyword_seeds", []),
            "competitor": brief.get("competitor"),
            "research_questions": brief.get("research_questions", []),
            "market_rationale": rationale.get("market", ""),
            "seed_rationales": rationale.get("seeds", []),
            "competitor_rationale": rationale.get("competitor", ""),
            "idempotency_key": idempotency_key,
        }
        return self._invoke("seo_request_research_report", arguments)

    def research_report_status(self, report_id: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_research_report_status", {"report_id": report_id})

    def research_report(self, report_id: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_research_report", {"report_id": report_id})

    def latest_research_report(self) -> Mapping[str, Any]:
        return self._invoke("seo_get_latest_research_report", {})

    def list_research_reports(self, limit: int = 12) -> Mapping[str, Any]:
        return self._invoke("seo_list_research_reports", {"limit": limit})

    def dataforseo_domain_report(self) -> Mapping[str, Any]:
        return self._invoke("seo_get_dataforseo_domain_report", {})

    def dataforseo_keyword_report(self, seed: str = "seo") -> Mapping[str, Any]:
        return self._invoke("seo_get_dataforseo_keyword_report", {"seed": seed})

    def crawl_summary(self) -> Mapping[str, Any]:
        return self._invoke("seo_get_crawl_summary", {})

    def crawl_issues(self, severity: str | None = None, limit: int = 50) -> list[Mapping[str, Any]]:
        arguments: dict[str, Any] = {"limit": limit}
        if severity is not None:
            arguments["severity"] = severity
        result = self._invoke("seo_get_crawl_issues", arguments)
        issues = result.get("issues", [])
        if not isinstance(issues, list) or not all(isinstance(issue, Mapping) for issue in issues):
            raise CrawlSEOProtocolError("CrawlSEO returned an invalid crawl issue list")
        return issues

    def prepare_monthly_site_evidence(
        self,
        period: str,
        idempotency_key: str,
        max_crawl_pages: int = 200,
    ) -> Mapping[str, Any]:
        return self._invoke("seo_prepare_monthly_site_evidence", {
            "period": period,
            "idempotency_key": idempotency_key,
            "max_crawl_pages": max_crawl_pages,
        })

    def monthly_site_evidence(self, period: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_monthly_site_evidence", {"period": period})

    def request_article_keyword_research(
        self,
        *,
        idea_key: str,
        idea_summary: str,
        queries: list[str],
        language: str,
        country: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        return self._invoke("seo_request_article_keyword_research", {
            "idea_key": idea_key,
            "idea_summary": idea_summary,
            "queries": queries,
            "language": language,
            "country": country,
            "idempotency_key": idempotency_key,
        })

    def article_keyword_research_status(self, run_id: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_article_keyword_research_status", {"run_id": run_id})

    def article_keyword_research(self, run_id: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_article_keyword_research", {"run_id": run_id})

    def request_article_serp_research(
        self,
        *,
        parent_run_id: str,
        keyword: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        return self._invoke("seo_request_article_serp_research", {
            "parent_run_id": parent_run_id,
            "keyword": keyword,
            "idempotency_key": idempotency_key,
        })

    def article_serp_research_status(self, run_id: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_article_keyword_research_status", {"run_id": run_id})

    def article_serp_research(self, run_id: str) -> Mapping[str, Any]:
        return self._invoke("seo_get_article_keyword_research", {"run_id": run_id})

    def list_article_keyword_research(self, period: str | None = None, limit: int = 20) -> Mapping[str, Any]:
        arguments: dict[str, Any] = {"limit": limit}
        if period:
            arguments["period"] = period
        return self._invoke("seo_list_article_keyword_research", arguments)

    def _invoke(self, tool_name: str, arguments: dict[str, Any]) -> Mapping[str, Any]:
        if tool_name not in _KNOWN_TOOLS:
            raise CrawlSEOProtocolError("CrawlSEO tool is not part of the fixed read surface")
        result = self._runtime.invoke(tool_name, arguments)
        if not isinstance(result, Mapping):
            raise CrawlSEOProtocolError("CrawlSEO returned a non-object structured result")
        return result

    def __enter__(self) -> "CrawlSEOClient":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


def configured(config: dict[str, Any]) -> bool:
    return crawlseo_configured(config)


__all__ = [
    "CrawlSEOClient",
    "CrawlSEOConfigurationError",
    "CrawlSEOError",
    "CrawlSEOProtocolError",
    "CrawlSEOResponseTooLargeError",
    "CrawlSEOTimeoutError",
    "CrawlSEOUnavailableError",
    "configured",
]
