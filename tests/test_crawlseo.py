import asyncio
from unittest import mock

import pytest

from site_agent.application.crawlseo import CrawlSEOApplicationService
from site_agent.config import ConfigError, CrawlSEOSettings, load
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler
from site_agent.hands.crawlseo import (
    CrawlSEOClient,
    CrawlSEOProtocolError,
    CrawlSEOResponseTooLargeError,
    CrawlSEOSettings as HandCrawlSEOSettings,
    _LimitedAsyncTransport,
    _request_headers,
)
from site_agent.runtime import Runtime
from site_agent.senses import ga as ga_sense
from site_agent.senses import seo as seo_sense


class FakeCrawlSEO:
    def __init__(self, search=None, analytics=None):
        self.search = search or {"period_days": 28, "top_queries": []}
        self.analytics = analytics or {
            "current_week": {},
            "previous_week": {},
            "delta_pct": {},
            "top_pages": [],
            "sources": [],
            "organic_queries": [],
        }
        self.calls = []

    def project(self):
        self.calls.append(("project",))
        return {
            "project_id": "project-1",
            "site": {"domain": "example.com", "url": "https://example.com/"},
            "connections": {
                "gsc": {"status": "active", "property": "https://example.com/"},
                "ga4": {"status": "active", "property": "123"},
            },
        }

    def search_summary(self, days, query_limit):
        self.calls.append(("search_summary", days, query_limit))
        return self.search

    def analytics_summary(self):
        self.calls.append(("analytics_summary",))
        return self.analytics

    def crawl_summary(self):
        self.calls.append(("crawl_summary",))
        return {"status": "complete", "health_score": 98, "page_count": 4, "issue_count": 0, "finished_at": "now"}

    def crawl_issues(self, severity, limit):
        self.calls.append(("crawl_issues", severity, limit))
        return []


def test_crawlseo_defaults_and_enabled_settings_are_validated():
    config, _ = load(env={})
    assert config["providers"]["crawlseo"] == {
        "enabled": False,
        "url": "",
        "token_env": "CRAWLSEO_SERVICE_TOKEN",
        "timeout_seconds": 30,
        "max_response_bytes": 2097152,
    }
    disabled = CrawlSEOSettings.from_config(config, env={})
    assert disabled.enabled is False

    enabled = {
        "providers": {
            "crawlseo": {
                "enabled": True,
                "url": "https://crawlseo.example/mcp",
                "token_env": "CRAWLSEO_TOKEN",
                "timeout_seconds": 4,
                "max_response_bytes": 1024,
            }
        }
    }
    settings = CrawlSEOSettings.from_config(enabled, env={"CRAWLSEO_TOKEN": "secret"})
    assert settings.enabled is True
    assert settings.timeout_seconds == 4
    assert settings.max_response_bytes == 1024
    assert settings.token == "secret"
    assert "secret" not in repr(settings)

    with pytest.raises(ConfigError, match="not set"):
        CrawlSEOSettings.from_config(enabled, env={})
    enabled["providers"]["crawlseo"]["max_response_bytes"] = 20 * 1024 * 1024
    with pytest.raises(ConfigError, match="max_response_bytes"):
        CrawlSEOSettings.from_config(enabled, env={"CRAWLSEO_TOKEN": "secret"})


def test_crawlseo_hand_adapter_uses_only_fixed_tools_and_auth_header():
    settings = HandCrawlSEOSettings(
        enabled=True,
        url="https://crawlseo.example/mcp",
        token_env="CRAWLSEO_TOKEN",
        token="secret",
    )
    headers = _request_headers(settings)
    assert headers["Authorization"] == "Bearer secret"
    assert headers["X-Request-ID"]

    class FakeRuntime:
        def __init__(self):
            self.calls = []

        def invoke(self, name, arguments):
            self.calls.append((name, arguments))
            return {"ok": True}

        def start(self):
            pass

        def close(self):
            pass

    runtime = FakeRuntime()
    client = CrawlSEOClient(settings, runtime=runtime)
    assert client.project() == {"ok": True}
    assert client.search_summary(7, 3) == {"ok": True}
    assert client.dataforseo_domain_report() == {"ok": True}
    assert client.dataforseo_keyword_report("seo") == {"ok": True}
    assert [name for name, _ in runtime.calls] == [
        "seo_get_project",
        "seo_get_search_summary",
        "seo_get_dataforseo_domain_report",
        "seo_get_dataforseo_keyword_report",
    ]
    assert not hasattr(client, "call_tool")
    with pytest.raises(CrawlSEOProtocolError, match="fixed read surface"):
        client._invoke("arbitrary_brain_tool", {})


def test_crawlseo_hand_adapter_maps_research_brief_to_explicit_request_tool():
    class FakeRuntime:
        def __init__(self):
            self.calls = []

        def invoke(self, name, arguments):
            self.calls.append((name, arguments))
            return {"report_id": "report-1", "status": "requested"}

        def start(self):
            pass

        def close(self):
            pass

    settings = HandCrawlSEOSettings(
        enabled=True,
        url="https://crawlseo.example/mcp",
        token_env="CRAWLSEO_TOKEN",
        token="secret",
    )
    runtime = FakeRuntime()
    client = CrawlSEOClient(settings, runtime=runtime)
    brief = {
        "period": "2026-07",
        "focus_market": {"language": "fr", "country": "FR"},
        "business_goal": "Grow qualified leads",
        "audience": ["French buyers"],
        "priority_services": ["Advisory"],
        "keyword_seeds": ["one", "two", "three", "four", "five"],
        "competitor": "competitor.example",
        "research_questions": ["What should we write next?"],
        "selection_rationale": {
            "market": "French demand is growing",
            "seeds": ["a", "b", "c", "d", "e"],
            "competitor": "Direct competitor",
        },
        "package": "standard-v1",
    }

    assert client.request_research_report(brief, "seo:2026-07:standard-v1") == {
        "report_id": "report-1",
        "status": "requested",
    }
    assert runtime.calls == [(
        "seo_request_research_report",
        {
            "period": "2026-07",
            "focus_language": "fr",
            "focus_country": "FR",
            "business_goal": "Grow qualified leads",
            "audience": ["French buyers"],
            "priority_services": ["Advisory"],
            "keyword_seeds": ["one", "two", "three", "four", "five"],
            "competitor": "competitor.example",
            "research_questions": ["What should we write next?"],
            "market_rationale": "French demand is growing",
            "seed_rationales": ["a", "b", "c", "d", "e"],
            "competitor_rationale": "Direct competitor",
            "idempotency_key": "seo:2026-07:standard-v1",
        },
    )]


def test_crawlseo_hand_adapter_maps_article_candidates_and_serp_to_fixed_tools():
    class FakeRuntime:
        def __init__(self):
            self.calls = []

        def invoke(self, name, arguments):
            self.calls.append((name, arguments))
            if name == "seo_request_article_keyword_research":
                return {"run_id": "run-overview", "status": "requested"}
            return {"run_id": "run-serp", "status": "requested"}

        def start(self):
            pass

        def close(self):
            pass

    settings = HandCrawlSEOSettings(
        enabled=True,
        url="https://crawlseo.example/mcp",
        token_env="CRAWLSEO_TOKEN",
        token="secret",
    )
    runtime = FakeRuntime()
    client = CrawlSEOClient(settings, runtime=runtime)
    queries = ["a", "b", "c", "d", "e"]

    assert client.request_article_keyword_research(
        idea_key="article:2026-W30",
        idea_summary="Help readers.",
        queries=queries,
        language="en",
        country="US",
        idempotency_key="article-research:hash:v1",
    )["run_id"] == "run-overview"
    assert client.request_article_serp_research(
        parent_run_id="run-overview",
        keyword="a",
        idempotency_key="article-serp:hash:v1",
    )["run_id"] == "run-serp"
    assert client.article_serp_research_status("run-serp")["status"] == "requested"
    assert client.article_serp_research("run-serp")["run_id"] == "run-serp"

    names = [name for name, _ in runtime.calls]
    assert names == [
        "seo_request_article_keyword_research",
        "seo_request_article_serp_research",
        "seo_get_article_keyword_research_status",
        "seo_get_article_keyword_research",
    ]
    assert runtime.calls[0][1]["queries"] == queries
    assert runtime.calls[1][1] == {
        "parent_run_id": "run-overview",
        "keyword": "a",
        "idempotency_key": "article-serp:hash:v1",
    }


def test_crawlseo_application_validates_candidate_query_bounds():
    from site_agent.application.crawlseo import CrawlSEOApplicationError

    class FakeProvider:
        def request_article_keyword_research(self, **kwargs):
            raise AssertionError("invalid queries must not reach the provider")

    service = CrawlSEOApplicationService(FakeProvider())
    with pytest.raises(CrawlSEOApplicationError, match="5 to 10"):
        service.request_article_keyword_research(
            idea_key="idea", idea_summary="summary",
            queries=["a", "b", "c", "d"],
            language="en", country="US", idempotency_key="k",
        )
    with pytest.raises(CrawlSEOApplicationError, match="unique"):
        service.request_article_keyword_research(
            idea_key="idea", idea_summary="summary",
            queries=["a", "A", "c", "d", "e"],
            language="en", country="US", idempotency_key="k",
        )


def test_crawlseo_transport_rejects_declared_and_streamed_oversize_responses():
    class Response:
        def __init__(self, length, stream):
            self.headers = {} if length is None else {"content-length": str(length)}
            self.stream = stream
            self.closed = False

        async def aclose(self):
            self.closed = True

    class Inner:
        def __init__(self, response):
            self.response = response

        async def handle_async_request(self, _request):
            return self.response

        async def aclose(self):
            pass

    class Stream:
        async def __aiter__(self):
            yield b"123"
            yield b"456"

        async def aclose(self):
            pass

    declared = Response(10, Stream())
    transport = _LimitedAsyncTransport(Inner(declared), max_bytes=5)
    with pytest.raises(CrawlSEOResponseTooLargeError):
        asyncio.run(transport.handle_async_request(None))
    assert declared.closed is True

    streamed = Response(None, Stream())
    transport = _LimitedAsyncTransport(Inner(streamed), max_bytes=5)

    async def consume():
        response = await transport.handle_async_request(None)
        return [chunk async for chunk in response.stream]

    with pytest.raises(CrawlSEOResponseTooLargeError):
        asyncio.run(consume())


def test_seo_direct_and_crawlseo_summaries_have_identical_shapes():
    response = {
        "rows": [
            {"keys": ["mouthfill technique"], "clicks": 12.4, "impressions": 900, "ctr": 0.0138, "position": 8.3},
        ]
    }
    direct_config = {"seo": {"source": "gsc", "site_url": "https://example.com/", "key_path": "/tmp/key.json"}}
    with mock.patch.object(seo_sense, "_run", return_value=response):
        direct = seo_sense.summary(direct_config)

    fake = FakeCrawlSEO(search={"period_days": 28, "top_queries": direct["top_queries"]})
    service = CrawlSEOApplicationService(fake)
    crawl_config = {"seo": {"source": "crawlseo"}}
    assert seo_sense.summary(crawl_config, crawlseo_service=service) == direct


def test_ga_direct_and_crawlseo_weekly_summaries_have_identical_shapes():
    direct_config = {"ga": {"source": "ga4", "property_id": "123", "key_path": "/tmp/key.json"}}
    direct = {
        "current_week": {"activeUsers": 10},
        "previous_week": {"activeUsers": 5},
        "delta_pct": {"activeUsers": 100.0},
        "top_pages": [{"path": "/", "views": 40}],
        "sources": [{"source": "Organic Search", "sessions": 12, "users": 9}],
        "organic_queries": [{"query": "mouthfill", "sessions": 4, "users": 3, "views": 8}],
    }
    with mock.patch.object(ga_sense, "_totals", side_effect=[direct["current_week"], direct["previous_week"]]), mock.patch.object(
        ga_sense, "top_pages", return_value=direct["top_pages"]
    ), mock.patch.object(ga_sense, "traffic_sources", return_value=direct["sources"]), mock.patch.object(
        ga_sense, "organic_queries", return_value=direct["organic_queries"]
    ):
        direct_result = ga_sense.weekly_summary(direct_config)

    fake = FakeCrawlSEO(analytics=direct)
    service = CrawlSEOApplicationService(fake)
    crawl_result = ga_sense.weekly_summary({"ga": {"source": "crawlseo"}}, crawlseo_service=service)
    assert crawl_result == direct_result


def test_runtime_injects_crawlseo_service_without_exposing_arbitrary_tools(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = CrawlSEOApplicationService(FakeCrawlSEO())
    config = {"providers": {"crawlseo": {"enabled": True}}}
    runtime = Runtime(config, memory, Scheduler(memory, tmp_path / "lock"), None, "", crawlseo_service=service)
    assert runtime.context()["crawlseo_service"] is service
    assert runtime.capability_registry.get("crawlseo.search.read") is not None
    assert runtime.capability_registry.get("crawlseo.crawl.request").approval_required is True
    runtime.close()
    memory.close()
