from types import SimpleNamespace
import json

from site_agent.application.growth_evidence import growth_evidence
from site_agent.application.crawlseo import CrawlSEOApplicationError


def service():
    return SimpleNamespace(
        project=lambda: {"site": {"domain": "owner.test", "url": "https://owner.test/"}},
        latest_research_report=lambda: {"period": "2026-09", "completed_at": "2026-10-01", "report": {
            "brief": {"competitor": "rival.test"},
            "focus_market": {"language": "en", "country": "MX"},
            "dataforseo": [
                {"kind": "domain_overview", "status": "completed", "input": {"domain": "owner.test"}, "result": {"organicKeywords": 0, "organicTraffic": 12}},
                {"kind": "domain_overview", "status": "completed", "input": {"domain": "rival.test"}, "result": {"organicKeywords": 25, "organicTraffic": 100, "secret": "hidden"}},
                {"kind": "backlinks_overview", "status": "completed", "input": {"domain": "rival.test"}, "result": {"referringDomains": 4}},
                {"kind": "domain_overview", "status": "failed", "input": {"domain": "failed.test"}, "result": {"organicKeywords": 100}},
            ]}},
        list_article_keyword_research=lambda **_: {"runs": [
            {"id": "old", "kind": "organic_serp", "status": "completed", "language": "en", "country": "MX", "completed_at": "2026-09-01", "result": {"query": "local service", "organic": [{"rank": 1, "domain": "old.test", "url": "https://old.test/"}]}},
            {"id": "new", "kind": "organic_serp", "status": "completed", "language": "en", "country": "MX", "completed_at": "2026-10-01", "result": {"query": "local service", "organic": [
                {"rank": 1, "domain": "rival.test", "url": "https://rival.test/service", "title": "Service", "secret": "hidden"},
                {"rank": 3, "domain": "www.owner.test", "url": "https://www.owner.test/service"},
                {"rank": 4, "domain": "rival.test", "url": "https://rival.test/other"},
                {"rank": 2, "domain": "unsafe.test", "url": "javascript:alert(1)"},
            ]}},
            {"id": "fr", "kind": "organic_serp", "status": "completed", "language": "fr", "country": "FR", "completed_at": "2026-10-01", "result": {"query": "local service", "organic": [{"rank": 2, "domain": "french.test", "url": "https://french.test/"}]}},
            {"id": "failed", "kind": "organic_serp", "status": "failed", "result": {"query": "failed", "organic": []}},
        ]},
    )


def test_competition_projects_real_benchmarks_without_merging_missing_with_zero():
    result = growth_evidence(service(), "competition")
    assert result["site"]["domain"] == "owner.test"
    assert result["selectedCompetitor"] == "rival.test"
    benchmarks = {row["domain"]: row for row in result["benchmarks"]}
    assert benchmarks["owner.test"]["organicKeywords"] == 0
    assert benchmarks["owner.test"]["referringDomains"] is None
    assert benchmarks["rival.test"]["referringDomains"] == 4
    assert "failed.test" not in benchmarks
    assert "hidden" not in json.dumps(result)


def test_competition_keeps_latest_serp_per_keyword_and_market_and_safe_urls():
    result = growth_evidence(service(), "competition")
    assert len(result["serps"]) == 2
    mexico = next(row for row in result["serps"] if row["country"] == "MX")
    france = next(row for row in result["serps"] if row["country"] == "FR")
    assert mexico["ownPosition"] == 3
    assert france["ownPosition"] is None
    assert [row["domain"] for row in mexico["organic"]] == ["rival.test", "owner.test", "rival.test"]
    assert {row["domain"] for row in result["rivals"]} == {"rival.test", "french.test"}
    assert next(row for row in result["rivals"] if row["domain"] == "rival.test")["appearances"] == 1
    assert result["coverage"] == "sampled_top_10_not_domain_keyword_gap"


def test_empty_competition_is_honest_and_does_not_dispatch_paid_work():
    calls = []
    source = SimpleNamespace(project=lambda: {"site": {"domain": "owner.test"}},
        latest_research_report=lambda: {"report": None}, list_article_keyword_research=lambda **_: {"runs": []},
        request_research_report=lambda *args: calls.append("paid"))
    result = growth_evidence(source, "competition")
    assert result["benchmarks"] == result["serps"] == result["rivals"] == []
    assert result["selectedCompetitor"] is None
    assert calls == []


def test_competition_reports_provider_failures_without_inventing_empty_success():
    source = service()
    def unavailable(*args, **kwargs):
        raise CrawlSEOApplicationError("provider unavailable")
    source.latest_research_report = unavailable
    source.list_article_keyword_research = unavailable
    result = growth_evidence(source, "competition")
    assert result["errors"] == {"report": "provider unavailable", "serps": "provider unavailable"}
    assert result["benchmarks"] == result["serps"] == []
