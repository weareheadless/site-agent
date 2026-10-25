import asyncio
import io
import json
from unittest import mock

import pytest

from site_agent.application.crawlseo import CrawlSEOApplicationError, CrawlSEOApplicationService
from site_agent.application import growth_workflow
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
        "connector_token_env": "",
        "connector_url": "",
        "research_authority": "local",
        "timeout_seconds": 30,
        "max_response_bytes": 2097152,
    }
    disabled = CrawlSEOSettings.from_config(config, env={})
    assert disabled.enabled is False

    authoritative = {"providers": {"crawlseo": {"enabled": True, "url": "https://crawlseo.example/mcp",
        "connector_url": "https://crawlseo.example/api/connector/v1", "research_authority": "crawlseo",
        "token_env": "CRAWLSEO_TOKEN"}}}
    settings = CrawlSEOSettings.from_config(authoritative, env={"CRAWLSEO_TOKEN": "secret"})
    assert settings.research_authority == "crawlseo"
    assert settings.connector_url.endswith("/api/connector/v1")
    authoritative["providers"]["crawlseo"]["connector_token_env"] = "CRAWLSEO_READ_TOKEN"
    separate = CrawlSEOSettings.from_config(authoritative, env={
        "CRAWLSEO_TOKEN": "legacy-mcp-secret", "CRAWLSEO_READ_TOKEN": "connector-read-secret",
    })
    assert separate.token == "legacy-mcp-secret"
    assert separate.connector_token == "connector-read-secret"
    assert "connector-read-secret" not in repr(separate)
    with pytest.raises(ConfigError, match="CRAWLSEO_READ_TOKEN"):
        CrawlSEOSettings.from_config(authoritative, env={"CRAWLSEO_TOKEN": "legacy-mcp-secret"})
    authoritative["providers"]["crawlseo"]["connector_token_env"] = "NOT-A-VALID-ENV-NAME"
    with pytest.raises(ConfigError, match="connector_token_env"):
        CrawlSEOSettings.from_config(authoritative, env={
            "CRAWLSEO_TOKEN": "legacy-mcp-secret", "CRAWLSEO_READ_TOKEN": "connector-read-secret",
        })
    authoritative["providers"]["crawlseo"]["connector_token_env"] = "CRAWLSEO_READ_TOKEN"
    authoritative["providers"]["crawlseo"]["connector_url"] = "https://crawlseo.example/api/connector/v2"
    with pytest.raises(ConfigError, match="connector_url"):
        CrawlSEOSettings.from_config(authoritative, env={"CRAWLSEO_TOKEN": "secret", "CRAWLSEO_READ_TOKEN": "read"})

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
    assert headers["User-Agent"] == "HelloAda/site-agent-crawlseo"

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


def test_crawlseo_connector_findings_calls_only_the_versioned_scoped_route():
    settings = HandCrawlSEOSettings(enabled=True, url="https://crawlseo.example/mcp", token_env="CRAWLSEO_TOKEN",
        token="secret", connector_url="https://crawlseo.example/api/connector/v1")
    client = CrawlSEOClient(settings, runtime=object())
    response = {"schemaVersion": "1.0", "projectId": "project-1", "siteId": "site-1", "findings": [], "nextCursor": None}
    with mock.patch.object(client, "_connector_request", return_value=response) as request:
        assert client.connector_findings(site_id="site-1", run_id="run-2", since="2026-10-24T00:00:00Z",
            limit=10, cursor="cursor-1") == response
    request.assert_called_once_with("GET", "/findings?siteId=site-1&limit=10&runId=run-2&since=2026-10-24T00%3A00%3A00Z&cursor=cursor-1")
    with pytest.raises(CrawlSEOProtocolError, match="finding limit"):
        client.connector_findings(site_id="site-1", limit=101)


def test_connector_rest_requests_use_the_separate_read_token_when_configured():
    settings = HandCrawlSEOSettings(enabled=True, url="https://crawlseo.example/mcp", token_env="CRAWLSEO_TOKEN",
        token="legacy-mcp-secret", connector_token="connector-read-secret",
        connector_url="https://crawlseo.example/api/connector/v1")
    client = CrawlSEOClient(settings, runtime=object())
    response = io.BytesIO(b'{"schemaVersion":"1.0"}')
    opener = mock.Mock()
    opener.open.return_value = response
    with mock.patch("site_agent.hands.crawlseo.build_opener", return_value=opener):
        assert client._connector_request("GET", "/capabilities?siteId=site-1") == {"schemaVersion": "1.0"}
    request = opener.open.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer connector-read-secret"
    assert request.get_header("User-agent") == "HelloAda/site-agent-crawlseo"


def test_connector_never_follows_redirect_with_its_bearer_credential():
    from site_agent.hands.crawlseo import _NoConnectorRedirect
    with pytest.raises(CrawlSEOProtocolError, match="redirects"):
        _NoConnectorRedirect().redirect_request(None, None, 307, "redirect", {}, "https://other.example")


@pytest.mark.parametrize("mount", ["", "/crawlseo", "/customer/sites/crawlseo"])
def test_crawlseo_connector_accepts_safe_explicit_mount_prefixes(mount):
    config = {"providers": {"crawlseo": {
        "enabled": True,
        "url": "https://crawlseo.example/mcp",
        "connector_url": f"https://crawlseo.example{mount}/api/connector/v1",
    }}}
    settings = CrawlSEOSettings.from_config(config, env={"CRAWLSEO_SERVICE_TOKEN": "secret"})
    assert settings.connector_url.endswith(f"{mount}/api/connector/v1")


@pytest.mark.parametrize("url", [
    "https://user:pass@crawlseo.example/crawlseo/api/connector/v1",
    "https://crawlseo.example/crawlseo/api/connector/v1?token=x",
    "https://crawlseo.example/crawlseo/api/connector/v1#frag",
    "https://crawlseo.example/crawlseo/../api/connector/v1",
    "https://crawlseo.example/crawlseo/%2e%2e/api/connector/v1",
    "https://crawlseo.example/crawlseo/%252e%252e/api/connector/v1",
    "https://crawlseo.example/crawlseo%5cadmin/api/connector/v1",
    "https://crawlseo.example/api/connector/v2",
    "https://crawlseo.example/crawlseo/api/connector/v1/extra",
    "https://crawlseo.example/crawlseo//api/connector/v1",
    "https://crawlseo.example/crawlseo mount/api/connector/v1",
    " https://crawlseo.example/api/connector/v1",
    "https://crawlseo.example/crawlseo%2fadmin/api/connector/v1",
    "https://crawlseo.example:99999/crawlseo/api/connector/v1",
    "https://crawlseo.example:/crawlseo/api/connector/v1",
    "https://crawlseo.example/crawlseo./api/connector/v1",
])
def test_crawlseo_connector_rejects_unsafe_or_unexpected_urls(url):
    config = {"providers": {"crawlseo": {
        "enabled": True,
        "url": "https://crawlseo.example/mcp",
        "connector_url": url,
    }}}
    with pytest.raises(ConfigError, match="connector_url"):
        CrawlSEOSettings.from_config(config, env={"CRAWLSEO_SERVICE_TOKEN": "secret"})


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
    from site_agent.application.crawlseo import CrawlSEOApplicationError, CrawlSEORequestNotDispatched

    class FakeProvider:
        def request_article_keyword_research(self, **kwargs):
            raise AssertionError("invalid queries must not reach the provider")

    service = CrawlSEOApplicationService(FakeProvider())
    with pytest.raises(CrawlSEORequestNotDispatched, match="5 to 10"):
        service.request_article_keyword_research(
            idea_key="idea", idea_summary="summary",
            queries=["a", "b", "c", "d"],
            language="en", country="US", idempotency_key="k",
        )
    with pytest.raises(CrawlSEORequestNotDispatched, match="unique"):
        service.request_article_keyword_research(
            idea_key="idea", idea_summary="summary",
            queries=["a", "A", "c", "d", "e"],
            language="en", country="US", idempotency_key="k",
        )


def test_crawlseo_provider_failure_is_not_mislabeled_as_proven_pre_dispatch():
    from site_agent.application.crawlseo import CrawlSEOApplicationError, CrawlSEORequestNotDispatched

    class ProviderFailure:
        def request_article_keyword_research(self, **_kwargs):
            raise RuntimeError("request is unavailable")

    service = CrawlSEOApplicationService(ProviderFailure())
    with pytest.raises(CrawlSEOApplicationError) as caught:
        service.request_article_keyword_research(
            idea_key="idea", idea_summary="summary",
            queries=["a", "b", "c", "d", "e"],
            language="en", country="US", idempotency_key="k",
        )
    assert not isinstance(caught.value, CrawlSEORequestNotDispatched)


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


def test_connector_sync_refreshes_context_without_acknowledging_unpersisted_events():
    class FakeConnector:
        def __init__(self):
            self.calls = []
        def connector_capabilities(self, site_id=None):
            self.calls.append(("capabilities", site_id))
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id, "binding": {"generation": 4}}
        def connector_context(self, site_id=None):
            self.calls.append(("context", site_id))
            return {"revision": "3", "snapshot": {"revision": "3"}}
        def connector_update_context(self, snapshot):
            self.calls.append(("update", dict(snapshot)))
            return {"revision": snapshot["revision"]}
        def connector_events(self, after, limit, site_id=None):
            self.calls.append(("events", site_id))
            return {"events": [{"id": "evt-1", "sequence": 1, "actionId": "act-1", "type": "action.updated"}]}
        def connector_action(self, action_id, site_id=None):
            self.calls.append(("action", action_id))
            return {"schemaVersion": "1.0", "project": {"id": "project-1"}, "site": {"id": "site-1"}, "id": action_id, "revision": 2}
        def connector_ack_events(self, acknowledged, failed=None, site_id=None):
            self.calls.append(("ack", acknowledged))
            return {"acknowledged": 1}
        def connector_actions(self, since=None, limit=50, cursor=None, site_id=None):
            self.calls.append(("actions", site_id))
            return {"actions": [{"schemaVersion": "1.0", "project": {"id": "project-1"}, "site": {"id": "site-1"}, "id": "act-1", "revision": 2}], "nextCursor": None}

    provider = FakeConnector()
    service = CrawlSEOApplicationService(provider)
    result = service.connector_sync(snapshot={"siteId": "site-1", "revision": "4", "expectedRevision": "3",
        "canonicalOrigin": "https://example.com", "observedAt": "2026-10-24T00:00:00Z",
        "websiteInventory": [], "businessFacts": {}, "capabilities": {"supported": []}})
    assert result["contextRevision"] == "3"
    assert result["actions"] == [{"schemaVersion": "1.0", "project": {"id": "project-1"}, "site": {"id": "site-1"}, "id": "act-1", "revision": 2}]
    assert next(i for i, call in enumerate(provider.calls) if call == ("context", "site-1")) < next(i for i, call in enumerate(provider.calls) if isinstance(call, tuple) and call[0] == "update")
    assert all(call[1] == "site-1" for call in provider.calls if isinstance(call, tuple) and call[0] in {"capabilities", "context", "events", "actions"})
    assert result["events"] == [{"id": "evt-1", "sequence": 1, "actionId": "act-1", "type": "action.updated"}]
    assert not any(isinstance(call, tuple) and call[0] == "ack" for call in provider.calls)


def test_connector_sync_retries_failed_action_reads_without_acknowledging_them():
    class FakeConnector:
        def __init__(self):
            self.acks = []
        def connector_capabilities(self, site_id=None):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id, "binding": {"generation": 4}}
        def connector_context(self, site_id=None):
            return {"snapshot": {"revision": "1"}}
        def connector_update_context(self, snapshot):
            return {"revision": snapshot["revision"]}
        def connector_events(self, after, limit, site_id=None):
            return {"events": [{"id": "evt-failed", "actionId": "act-gone", "type": "action.updated"}]}
        def connector_action(self, action_id, site_id=None):
            raise RuntimeError("temporary read outage")
        def connector_ack_events(self, acknowledged, failed=None, site_id=None):
            self.acks.append((acknowledged, failed))
            return {"acknowledged": 0}
        def connector_actions(self, since=None, limit=50, cursor=None, site_id=None):
            return {"actions": [], "nextCursor": None}

    provider = FakeConnector()
    result = CrawlSEOApplicationService(provider).connector_sync(snapshot={"siteId": "site-1",
        "canonicalOrigin": "https://example.com", "websiteInventory": [], "businessFacts": {}, "capabilities": {"supported": []}})
    assert result["events"][0]["id"] == "evt-failed"
    assert provider.acks == [([], [{"id": "evt-failed", "message": "CrawlSEO connector action is unavailable"}])]


def test_connector_sync_rejects_cross_site_or_wrong_project_actions():
    from site_agent.application.crawlseo import CrawlSEOApplicationError, CrawlSEOApplicationService

    class Provider:
        def connector_capabilities(self, site_id=None):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id}
        def connector_context(self, site_id=None):
            return {"snapshot": {"revision": "1"}}
        def connector_update_context(self, snapshot):
            return {"revision": snapshot["revision"]}
        def connector_events(self, after, limit, site_id=None):
            return {"events": []}
        def connector_actions(self, since=None, limit=50, cursor=None, site_id=None):
            return {"actions": [{"schemaVersion": "1.0", "project": {"id": "other-project"},
                "site": {"id": "site-1"}, "id": "action-1", "revision": 1}], "nextCursor": None}

    with pytest.raises(CrawlSEOApplicationError, match="identity or schema"):
        CrawlSEOApplicationService(Provider()).connector_sync(snapshot={"siteId": "site-1", "canonicalOrigin": "https://example.com",
            "websiteInventory": [], "businessFacts": {}, "capabilities": {"supported": []}})


def test_connector_sync_rejects_actions_with_incomplete_evidence():
    from site_agent.application.crawlseo import CrawlSEOApplicationError, CrawlSEOApplicationService

    class Provider:
        def connector_capabilities(self, site_id=None):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id}
        def connector_context(self, site_id=None):
            return {"snapshot": {"revision": "1"}}
        def connector_update_context(self, snapshot):
            return {"revision": snapshot["revision"]}
        def connector_events(self, after, limit, site_id=None):
            return {"events": []}
        def connector_actions(self, since=None, limit=50, cursor=None, site_id=None):
            return {"actions": [{"schemaVersion": "1.0", "project": {"id": "project-1"},
                "site": {"id": "site-1"}, "id": "action-1", "revision": 1,
                "evidenceComplete": False, "unavailableEvidenceSourceIds": ["missing-source"]}], "nextCursor": None}

    with pytest.raises(CrawlSEOApplicationError, match="missing evidence sources"):
        CrawlSEOApplicationService(Provider()).connector_sync(snapshot={"siteId": "site-1",
            "canonicalOrigin": "https://example.com", "websiteInventory": [], "businessFacts": {}, "capabilities": {"supported": []}})


@pytest.mark.parametrize("age,limit,expected", [
    (0, 30, True), (30, 30, True), (30.01, 30, False), (-5 / 1440, 30, True),
    (-6 / 1440, 30, False), (True, 30, False), (0, None, False),
])
def test_crawlseo_preparation_freshness_uses_effective_current_policy_limit(age, limit, expected):
    assert growth_workflow._crawlseo_evidence_freshness_valid(age, limit) is expected


def test_unbound_connector_events_are_redacted_and_persisted_before_ack(tmp_path):
    memory = Memory(tmp_path / "crawlseo-event-inbox.db")
    event = {"id": "event-1", "sequence": 8, "siteId": "site-1", "actionId": None,
        "actionRevision": None, "type": "future.event", "payload": {"text": "untrusted instruction secret"}}

    class Connector:
        def __init__(self):
            self.acks = []
        def connector_ack_events(self, ids, site_id=None):
            assert memory.conn.execute("SELECT COUNT(*) FROM crawlseo_event_inbox WHERE event_id = ?", (ids[0],)).fetchone()[0] == 1
            self.acks.append(list(ids))

    connector = Connector()
    acknowledged = growth_workflow._persist_unbound_crawlseo_events(memory, connector, [event,
        {**event, "id": "event-action", "actionId": "action-1"}])
    assert acknowledged == ["event-1"]
    assert connector.acks == [["event-1"]]
    snapshot = memory.crawlseo_migration_snapshot()
    receipt = snapshot["connectorEvents"]["items"][0]
    assert receipt["disposition"] == "unsupported"
    assert "untrusted instruction secret" not in json.dumps(snapshot)
    assert memory.record_crawlseo_connector_event(event, disposition="unsupported", reason="Event type has no local execution effect")["event_id"] == "event-1"
    with pytest.raises(Exception, match="reused with different data"):
        memory.record_crawlseo_connector_event({**event, "payload": {"changed": True}}, disposition="unsupported")
    memory.close()


def test_action_connector_events_are_persisted_before_ack_and_include_all_pages(tmp_path):
    memory = Memory(tmp_path / "crawlseo-action-event-inbox.db")
    events = [{"id": f"event-{index}", "sequence": index, "siteId": "site-1",
        "actionId": "action-1", "actionRevision": 2, "type": "action.updated",
        "payload": {"status": "PROPOSED"}} for index in range(205)]

    class Connector:
        def __init__(self):
            self.pages = []
        def connector_ack_events(self, ids, site_id=None):
            assert all(memory.conn.execute(
                "SELECT COUNT(*) FROM crawlseo_event_inbox WHERE event_id = ?", (event_id,),
            ).fetchone()[0] == 1 for event_id in ids)
            self.pages.append(list(ids))

    connector = Connector()
    acknowledged = growth_workflow._persist_action_crawlseo_events(memory, connector, events, "action-1")
    assert len(acknowledged) == 205
    assert [len(page) for page in connector.pages] == [100, 100, 5]
    receipts = memory.crawlseo_migration_snapshot()["connectorEvents"]["items"]
    assert len(receipts) == 205
    assert {row["disposition"] for row in receipts} == {"reconciled"}
    memory.close()


@pytest.mark.parametrize("approved,decision", [(True, "approved"), (False, "declined")])
def test_crawlseo_owner_approval_is_reported_against_exact_candidate(approved, decision):
    class Memory:
        def __init__(self):
            self.binding = {"site_id": "site-1", "action_id": "action-1", "action_revision": 4,
                "generation": 7, "state": "ready", "detail": {"candidateRef": "payload-growth:action-1:4:7",
                    "reviewUrl": "https://helloada.example/admin"}}
        def list_strategy_initiatives(self, **_kwargs):
            return [{"id": 12, "approval_id": 88, "review_package_hash": "a" * 64,
                "expected": {"crawlseoActionId": "action-1", "crawlseoRevision": 4, "crawlseoGeneration": 7}}]
        def get_crawlseo_execution_binding(self, *_args):
            return dict(self.binding)
        def update_crawlseo_execution_binding(self, *_args, expected_state, state, detail, **_kwargs):
            assert self.binding["state"] == expected_state
            self.binding.update(state=state, detail=dict(detail))
            return dict(self.binding)

    class Service:
        def __init__(self):
            self.reports = []
        def connector_record_execution(self, action_id, report):
            self.reports.append((action_id, dict(report)))

    memory, service = Memory(), Service()
    context = {"memory": memory, "crawlseo_service": service,
        "config": {"providers": {"crawlseo": {"enabled": True, "research_authority": "crawlseo",
            "connector_url": "https://crawlseo.example/api/connector/v1"}}},
        "connector_site_id": "site-1"}
    assert growth_workflow.record_crawlseo_owner_decision(context, 88, approved) is True
    assert service.reports[0][0] == "action-1"
    assert service.reports[0][1]["ownerDecision"] == decision
    assert service.reports[0][1]["candidateRef"] == "payload-growth:action-1:4:7"
    assert service.reports[0][1]["detail"]["reviewPackageHash"] == "a" * 64
    assert memory.binding["state"] == "owner_decision"


def test_crawlseo_source_publication_requires_verified_release_and_reports_exact_receipt():
    from site_agent.application.growth_workflow import record_crawlseo_source_publication

    class Memory:
        def __init__(self):
            self.binding = {"site_id": "site-1", "action_id": "action-1", "action_revision": 4,
                "generation": 7, "state": "owner_decision", "detail": {"candidateRef": "source-growth:action-1:4:7",
                    "reviewUrl": "https://helloada.example/admin", "reviewPackageHash": "d" * 64}}
        def get_crawlseo_execution_binding(self, *_args):
            return dict(self.binding)
        def update_crawlseo_execution_binding(self, *_args, expected_state, state, detail, **_kwargs):
            assert self.binding["state"] == expected_state
            self.binding.update(state=state, detail=dict(detail))
            return dict(self.binding)

    class Service:
        def __init__(self):
            self.reports = []
        def connector_record_execution(self, action_id, report):
            self.reports.append((action_id, dict(report)))

    memory, service = Memory(), Service()
    context = {"memory": memory, "crawlseo_service": service}
    package = {"crawlseoBinding": {"siteId": "site-1", "actionId": "action-1", "actionRevision": 4,
        "generation": 7, "candidateRef": "source-growth:action-1:4:7", "targetUrl": "https://example.com/robots.txt"},
        "source": {"candidateSha": "a" * 40}}
    pending = {"status": "deploying", "live": False, "release_id": "release-1", "commit": "a" * 40,
        "release_receipt": {"connectionVerifiedAt": "2026-10-25T12:00:00Z"}}
    promotion = {"refs": {"candidateSha": "a" * 40, "sourceSha": "b" * 40, "treeSha": "c" * 40}}
    assert record_crawlseo_source_publication(context, package, pending, promotion) is False
    assert record_crawlseo_source_publication(context, package, pending, {"refs": {**promotion["refs"], "sourceSha": "d" * 40}}) is False
    assert service.reports == []
    naive_time = {**pending, "status": "deployed", "live": True, "verified_commit": "b" * 40,
        "release_receipt": {"connectionVerifiedAt": "2026-10-25T12:00:00"}}
    assert record_crawlseo_source_publication(context, package, naive_time, promotion) is False
    assert record_crawlseo_source_publication(context, package, {**naive_time, "commit": "e" * 40,
        "release_receipt": {"connectionVerifiedAt": "2026-10-25T12:00:00Z", "uploadedVersion": "v-2"}}, promotion) is False
    assert service.reports == []
    deployed = {**pending, "status": "deployed", "live": True, "commit": "b" * 40, "verified_commit": "b" * 40,
        "release_receipt": {"connectionVerifiedAt": "2026-10-25T12:00:00Z", "uploadedVersion": "v-2"}}
    assert record_crawlseo_source_publication(context, package, deployed, promotion) is True
    assert service.reports[0][1]["publicationReceipt"] == {
        "candidateRef": "source-growth:action-1:4:7", "receiptId": "release-1",
        "targetUrl": "https://example.com/robots.txt", "publishedAt": "2026-10-25T12:00:00Z",
        "contentHash": "a" * 40,
    }
    assert service.reports[0][1]["detail"]["reviewPackageHash"] == "d" * 64


def test_research_policy_is_read_and_written_through_the_fixed_connector():
    class Provider:
        def __init__(self):
            self.calls = []
        def connector_policy(self, site_id):
            self.calls.append(("read_policy", site_id))
            return {"policy": {"schemaVersion": "1.0", "siteId": site_id, "revision": 2, "topics": ["topic"]}}
        def connector_update_policy(self, policy):
            self.calls.append(("write_policy", dict(policy)))
            return {"policy": {**policy, "revision": 3}}

    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    assert service.connector_policy("site-1")["revision"] == 2
    updated = service.connector_update_policy({"siteId": "site-1", "expectedRevision": 2, "topics": ["new topic"]})
    assert updated["revision"] == 3
    assert provider.calls == [
        ("read_policy", "site-1"),
        ("write_policy", {"siteId": "site-1", "expectedRevision": 2, "topics": ["new topic"]}),
    ]


@pytest.mark.parametrize("current_request_id,expected_status", [
    ("prepare-attempt-9", "ready"),
    ("prepare-attempt-10", "stale_attempt"),
])
def test_accepted_crawlseo_action_prepares_one_bound_payload_candidate(tmp_path, monkeypatch, current_request_id, expected_status):
    memory = Memory(tmp_path / "crawlseo-execution.db")
    inventory = [{"collection": "pages", "document": {"id": "page-1", "slug": "services"},
        "sourceRef": "payload:pages:page-1", "route": "/services",
        "assessmentScope": {"documentHash": "sha256:current"}, "contentPreview": "Current service copy"}]

    class Payload:
        base_url = "https://payload.example"

    class Connector:
        def __init__(self):
            self.reports = []
        def connector_context(self, site_id=None):
            return {"snapshot": {"canonicalOrigin": "https://example.com", "websiteInventory": [
                {"collection": "pages", "id": "page-1", "route": "/services", "documentHash": "sha256:current"}]}}
        def connector_action(self, action_id, site_id=None):
            return {"schemaVersion": "1.0", "id": action_id, "revision": 4, "preparationStatus": "queued",
                "preparationRequestId": current_request_id}
        def connector_record_execution(self, action_id, status):
            self.reports.append((action_id, dict(status)))
            return {"recorded": True}

    connector = Connector()
    monkeypatch.setattr(growth_workflow, "_inventory", lambda _context: inventory)
    from site_agent.application import growth_candidates
    monkeypatch.setattr(growth_candidates, "prepare_payload_candidate", lambda _context, initiative, opportunity, _inventory, evidence: {
        **initiative, "candidate_hash": "sha256:candidate", "review_package_hash": "sha256:package",
        "draft_id": 22, "approval_id": 23})
    _, created = memory.claim_crawlseo_execution_binding("site-1", "action-1", 4, 9,
        state="preparing", detail={"ownerActionId": 11, "preparationRequestId": "prepare-attempt-9"})
    assert created
    binding = memory.get_crawlseo_execution_binding("site-1", "action-1", 4)
    remote = {"id": "action-1", "revision": 4, "problem": "Service details are unclear",
        "preparationRequestId": "prepare-attempt-9",
        "recommendation": "Clarify the service page using the supplied findings.",
        "expectedOutcome": "More qualified service enquiries", "target": {"canonicalUrl": "https://example.com/services"},
        "requiredCapabilities": ["content.prepare"], "evidence": [{"id": "source-1", "url": "https://research.example/source",
            "freshnessDays": 2, "recencyLimitDays": 30, "observedAt": "2026-10-24T00:00:00Z", "retrievedAt": "2026-10-24T00:00:00Z"}]}
    result = growth_workflow._execute_crawlseo_preparation({
        "memory": memory, "config": {"instance_name": "demo", "growth": {"timezone": "UTC"}, "site": {"payload": {"url": "https://payload.example"}}},
        "payload_gateway": Payload(), "crawlseo_service": connector,
    }, remote, binding, site_id="site-1", generation=9)
    assert result["status"] == expected_status, result
    if expected_status == "stale_attempt":
        assert connector.reports == []
        assert memory.get_crawlseo_execution_binding("site-1", "action-1", 4)["state"] == "preparing"
        memory.close()
        return
    assert connector.reports[0][1]["status"] == "preparation_ready"
    assert connector.reports[0][1]["preparationRequestId"] == "prepare-attempt-9"
    assert connector.reports[0][1]["candidateRef"] == "payload-growth:action-1:4:9"
    saved = memory.get_crawlseo_execution_binding("site-1", "action-1", 4)
    assert saved["state"] == "ready"
    initiative = memory.update_strategy_initiative(saved["detail"]["initiativeId"])
    assert initiative["expected"]["crawlseoActionId"] == "action-1"
    assert initiative["state"] == "preparing"
    memory.close()


def test_preparation_ready_report_is_replayed_from_durable_local_binding(tmp_path):
    memory = Memory(tmp_path / "crawlseo-ready-report.db")
    row, created = memory.claim_crawlseo_execution_binding("site-1", "action-1", 4, 9,
        state="preparation_unreported", detail={"report": {"status": "preparation_ready",
            "preparationRequestId": "prepare-attempt-9", "candidateRef": "payload-growth:action-1:4:9",
            "reviewUrl": "https://payload.example/admin",
            "detail": {"reviewPackageHash": "b" * 64}}})
    assert created

    class Connector:
        def __init__(self):
            self.calls = []

        def connector_record_execution(self, action_id, report):
            self.calls.append((action_id, dict(report)))

    connector = Connector()
    assert growth_workflow._reconcile_crawlseo_execution_report({"memory": memory, "crawlseo_service": connector}, row)
    assert connector.calls[0][1]["candidateRef"] == "payload-growth:action-1:4:9"
    assert memory.get_crawlseo_execution_binding("site-1", "action-1", 4)["state"] == "ready"
    memory.close()


def test_connector_decision_is_fenced_by_current_revision_and_generation():
    class Provider(FakeCrawlSEO):
        def connector_action(self, action_id, site_id=None):
            self.calls.append(("connector_action", action_id))
            return {"action": {"id": action_id, "revision": 7}}
        def connector_capabilities(self, site_id=None):
            self.calls.append(("connector_capabilities",))
            return {"schemaVersion": "1.0", "binding": {"generation": 3, "status": "active"}}
        def connector_operation(self, action_id, operation):
            self.calls.append(("connector_operation", action_id, dict(operation)))
            return {"accepted": True}

    provider = Provider()
    result = CrawlSEOApplicationService(provider).connector_decide("action-1", "accept_preparation",
        idempotency_key="preparation-attempt-1")
    assert result["accepted"] is True
    call = next(row for row in provider.calls if row[0] == "connector_operation")
    assert call[2]["expectedRevision"] == 7
    assert call[2]["generation"] == 3
    assert call[2]["operation"] == "accept_preparation"
    assert call[2]["idempotencyKey"] == "preparation-attempt-1"


def test_connector_findings_read_is_versioned_site_scoped_and_bounded():
    class Provider(FakeCrawlSEO):
        def connector_capabilities(self, site_id=None):
            self.calls.append(("connector_capabilities", site_id))
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id,
                "capabilities": ["findings.read"]}

        def connector_findings(self, *, site_id, run_id=None, since=None, limit=50, cursor=None):
            self.calls.append(("connector_findings", site_id, run_id, since, limit, cursor))
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id,
                "findings": [{"id": "finding-1", "evidenceComplete": True}], "nextCursor": None}

    provider = Provider()
    result = CrawlSEOApplicationService(provider).connector_findings("site-1", run_id="run-2", limit=20)
    assert result["findings"][0]["id"] == "finding-1"
    assert ("connector_findings", "site-1", "run-2", None, 20, None) in provider.calls

    with pytest.raises(CrawlSEOApplicationError, match="binding"):
        class WrongProject(Provider):
            def connector_findings(self, *, site_id, **_kwargs):
                return {"schemaVersion": "1.0", "projectId": "other-project", "siteId": site_id,
                    "findings": [], "nextCursor": None}
        CrawlSEOApplicationService(WrongProject()).connector_findings("site-1")


def test_connector_findings_limit_is_rejected_before_provider_dispatch():
    provider = FakeCrawlSEO()
    with pytest.raises(CrawlSEOApplicationError, match="finding limit"):
        CrawlSEOApplicationService(provider).connector_findings("site-1", limit=101)
    assert provider.calls == []


def test_connector_preparation_retry_gets_a_new_idempotency_key_unless_replayed():
    class Provider(FakeCrawlSEO):
        def connector_action(self, action_id, site_id=None):
            return {"action": {"id": action_id, "revision": 7,
                "site": {"id": "site-1"}}}
        def connector_capabilities(self, site_id=None):
            return {"schemaVersion": "1.0", "binding": {"generation": 3, "status": "active"}}
        def connector_operation(self, action_id, operation):
            self.calls.append(("connector_operation", dict(operation)))
            return {"accepted": True}

    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    service.connector_decide("action-1", "accept_preparation")
    service.connector_decide("action-1", "accept_preparation")
    first, second = [row[1]["idempotencyKey"] for row in provider.calls if row[0] == "connector_operation"]
    assert first != second

    service.connector_decide("action-1", "accept_preparation", idempotency_key="same-network-retry")
    service.connector_decide("action-1", "accept_preparation", idempotency_key="same-network-retry")
    explicit = [row[1]["idempotencyKey"] for row in provider.calls if row[0] == "connector_operation"][-2:]
    assert explicit == ["same-network-retry", "same-network-retry"]


def test_execution_report_idempotency_tracks_exact_report_payload():
    class Provider(FakeCrawlSEO):
        def connector_action(self, action_id, site_id=None):
            return {"action": {"id": action_id, "revision": 7}}
        def connector_capabilities(self, site_id=None):
            return {"schemaVersion": "1.0", "binding": {"generation": 3, "status": "active"}}
        def connector_execution_status(self, action_id, status):
            self.calls.append(("connector_execution_status", action_id, dict(status)))
            return {"recorded": True}

    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    report = {"status": "preparation_blocked", "detail": {"error": "first reason"}}
    service.connector_record_execution("action-1", report)
    service.connector_record_execution("action-1", report)
    service.connector_record_execution("action-1", {"status": "preparation_blocked", "detail": {"error": "different reason"}})
    keys = [row[2]["idempotencyKey"] for row in provider.calls if row[0] == "connector_execution_status"]
    assert keys[0] == keys[1]
    assert keys[0] != keys[2]
