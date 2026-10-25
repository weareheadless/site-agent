from __future__ import annotations

from typing import Any

import pytest

from site_agent.application import seo_bootstrap


CONFIG: dict[str, Any] = {
    "instance_name": "oceanicvibes",
    "data_dir": "/tmp/oceanicvibes/data",
    "site": {
        "public_url": "https://oceanicvibes.com/",
        "brand": {"audience": "Freedivers"},
        "sources": {},
    },
    "sources": {"subreddits": ["freediving"], "rss_feeds": [{"name": "deeperblue", "url": "https://x/feed"}]},
    "seo": {
        "enabled": True,
        "research": {
            "enabled": True,
            "cadence": "weekly",
            "audience": "Freedivers and ocean-curious people",
            "business_goals": ["Increase qualified freediving training enquiries"],
            "anchor_topics": ["Freediving safety for beginners", "Cenote freediving in the Riviera Maya"],
            "competitors": [],
            "languages": [{"code": "en", "markets": ["US", "MX"], "primary": True}],
        },
        "article_research": {"enabled": True, "min_interval_days": 7},
    },
    "providers": {"crawlseo": {"enabled": True, "url": "https://crawlseo.helloada.app/mcp", "token_env": "CRAWLSEO_SERVICE_TOKEN"}},
}


def test_build_research_profile_uses_the_confirmed_business_context() -> None:
    payload = seo_bootstrap.build_research_profile(
        CONFIG, site_id="site-1", tenant_id="oceanicvibes", expected_revision=2
    )
    assert payload["siteId"] == "site-1"
    assert payload["expectedRevision"] == 2
    assert payload["profile"] == {
        "topics": ["Freediving safety for beginners", "Cenote freediving in the Riviera Maya"],
        "audience": "Freedivers and ocean-curious people",
        "market": "US, MX",
        "language": "en",
        "goals": ["Increase qualified freediving training enquiries"],
        "exclusions": [],
    }
    assert payload["researchPolicy"]["providers"] == ["reddit", "news"]
    assert payload["seoResearch"]["articleResearchEnabled"] is True
    assert payload["idempotencyKey"].startswith("site-agent:oceanicvibes:research-profile:")


def test_sync_research_profile_pushes_the_read_only_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    class FakeClient:
        def connector_policy(self, site_id: str) -> dict[str, Any]:
            calls["policy_site"] = site_id
            return {"policy": {"revision": 3}}

        def connector_update_research_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
            calls["payload"] = payload
            return {"revision": 4}

    monkeypatch.setattr(seo_bootstrap.CrawlSEOClient, "from_config", classmethod(lambda cls, config, env=None: FakeClient()))
    monkeypatch.setattr(
        seo_bootstrap, "credential_profile", lambda config, name: {"connector_url": "https://crawlseo.example/crawlseo/api/connector/v1"}
    )
    result = seo_bootstrap.sync_research_profile(
        CONFIG,
        {"CRAWLSEO_SERVICE_TOKEN": "cseo_mcp", "CRAWLSEO_CONNECTOR_TOKEN": "cseo_connector"},
        {"crawlseo": {"site_id": "site-1"}},
        "oceanicvibes",
    )
    assert result["state"] == "configured"
    assert result["revision"] == 4
    assert calls["policy_site"] == "site-1"
    assert calls["payload"]["expectedRevision"] == 3
    assert calls["payload"]["researchPolicy"]["providers"] == ["reddit", "news"]


def test_sync_research_profile_skips_without_a_connector_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seo_bootstrap, "credential_profile", lambda config, name: {})
    result = seo_bootstrap.sync_research_profile(
        CONFIG, {"CRAWLSEO_SERVICE_TOKEN": "cseo_mcp"}, {"crawlseo": {"site_id": "site-1"}}, "oceanicvibes"
    )
    assert result == {"state": "skipped", "reason": "connector_url_not_configured"}


def test_connector_runtime_token_is_written_to_a_protected_file(tmp_path) -> None:
    from site_agent.application.seo_provisioning import write_connector_runtime_token

    path = write_connector_runtime_token(tmp_path, "cseo_" + "a" * 32)
    assert path.name == "crawlseo-connector-runtime.env"
    assert path.read_text(encoding="utf-8").splitlines() == [
        "CRAWLSEO_CONNECTOR_TOKEN=cseo_" + "a" * 32
    ]
    assert path.stat().st_mode & 0o777 == 0o600


def test_safe_receipt_removes_both_one_time_credentials() -> None:
    receipt = {"credential_token": "mcp-secret", "connector_credential_token": "connector-secret", "site_id": "site-1"}
    assert seo_bootstrap._safe_receipt(receipt) == {"site_id": "site-1"}
