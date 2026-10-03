import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application.crawlseo import CrawlSEOApplicationError
from site_agent.application.growth_evidence import growth_evidence
from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
from site_agent.core.memory import Memory
from site_agent.web.workspace import register_workspace_routes


def provider(keyword="local service"):
    return SimpleNamespace(
        latest_research_report=lambda: {"period": "2026-10", "completed_at": "2026-10-01", "report": {
            "focus_market": {"language": "en", "country": "MX"},
            "dataforseo": [
                {"kind": "keyword_seed", "status": "completed", "result": [{"keyword": keyword, "volume": 40, "difficulty": None, "credential": "secret"}]},
                {"kind": "domain_overview", "status": "completed", "input": {"domain": "example.test"}, "result": {"organicTraffic": 120}},
                {"kind": "backlinks_overview", "status": "completed", "input": {"domain": "example.test"}, "result": {"totalBacklinks": 12}},
            ],
        }},
        list_article_keyword_research=lambda **_: {"runs": [
            {"kind": "keyword_overview", "status": "completed", "language": "en", "country": "MX", "completed_at": "2026-10-02", "result": [{"keyword": keyword, "volume": 60}]},
            {"kind": "related_keywords", "status": "completed", "language": "fr", "country": "FR", "result": [{"keyword": keyword, "volume": 25}]},
            {"kind": "organic_serp", "status": "completed", "result": {"query": "not a metric"}},
        ]},
        list_research_reports=lambda **_: {"reports": [{"period": "2026-10"}]},
        crawl_summary=lambda: {"status": "none", "health_score": None},
        crawl_issues=lambda **_: [],
    )


def test_research_normalizes_real_contract_and_keeps_markets_separate():
    result = growth_evidence(provider(), "research")
    assert [row["volume"] for row in result["keywords"]] == [60, 25]
    assert result["keywords"][0]["difficulty"] is None
    assert result["domains"][0]["organicTraffic"] == 120
    assert result["backlinks"][0]["totalBacklinks"] == 12
    assert "secret" not in json.dumps(result)
    assert result["reports"][0]["period"] == "2026-10"


def test_unavailable_is_not_an_empty_success_or_perfect_health_score():
    service = provider()
    def unavailable():
        raise CrawlSEOApplicationError("source unavailable")
    service.crawl_summary = unavailable
    result = growth_evidence(service, "health")
    assert result["summary"] is None
    assert result["errors"]["summary"] == "source unavailable"
    assert result["issues"] == []
    with pytest.raises(ValueError):
        growth_evidence(service, "unknown")


def test_evidence_requires_authentication_and_uses_only_resolved_tenant(tmp_path):
    tenants = {name: Tenant(name, {}, Memory(tmp_path / f"{name}.db"), None, {"crawlseo_service": provider(name)}, f"{name}-token") for name in ("alpha", "beta")}
    registry = TenantRegistry(tenants)
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=ChatService(registry=registry), registry=registry)
    with TestClient(app) as client:
        assert client.get("/api/workspace/seo/evidence").status_code == 401
        for name in tenants:
            response = client.get("/api/workspace/seo/evidence", headers={"Authorization": f"Bearer {name}-token"})
            assert response.status_code == 200
            assert response.json()["tenant"] == name
            assert response.json()["keywords"][0]["keyword"] == name
        assert client.get("/api/workspace/seo/evidence?section=bad", headers={"Authorization": "Bearer alpha-token"}).status_code == 400
