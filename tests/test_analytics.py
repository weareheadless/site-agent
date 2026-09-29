from __future__ import annotations

from typing import Any

import pytest

from site_agent.application.analytics import GoogleAnalyticsService
from site_agent.hands.google_platform import GooglePlatformClient, GooglePlatformError


class FakeGoogle:
    def run_analytics_report(self, _property_id: str, body: dict[str, Any]) -> dict[str, Any]:
        dimensions = [item["name"] for item in body.get("dimensions", [])]
        metrics = [item["name"] for item in body.get("metrics", [])]
        if dimensions == ["date"]:
            return {
                "dimensionHeaders": [{"name": "date"}],
                "metricHeaders": [{"name": name, "type": "TYPE_INTEGER"} for name in metrics],
                "rows": [{"dimensionValues": [{"value": "2026-09-28"}], "metricValues": [{"value": "4"} for _ in metrics]},],
            }
        return {
            "metricHeaders": [{"name": name, "type": "TYPE_INTEGER"} for name in metrics],
            "rows": [{"metricValues": [{"value": "5"} for _ in metrics]}],
        }

    def run_search_console_report(self, _site_url: str, body: dict[str, Any]) -> dict[str, Any]:
        dimensions = body.get("dimensions", [])
        if dimensions:
            return {"rows": [{"keys": [dimensions[0]], "clicks": 2, "impressions": 10, "ctr": 0.2, "position": 3.4}]}
        return {"rows": [{"clicks": 2, "impressions": 10, "ctr": 0.2, "position": 3.4}]}


def test_google_analytics_report_returns_provider_sections() -> None:
    service = GoogleAnalyticsService(
        {"seo": {"site_url": "https://example.test/"}, "ga": {"property_id": "123"}},
        FakeGoogle(),
        {
            "site_url": "https://example.test/",
            "gsc_property": "https://example.test/",
            "ga4_property_id": "123",
        },
    )

    result = service.report(7)

    assert result["window"]["days"] == 7
    assert result["entity"]["gscProperty"] == "https://example.test/"
    assert result["ga4"]["overview"]["current"]["sessions"] == 5
    assert result["gsc"]["overview"]["current"]["clicks"] == 2.0
    assert result["errors"] == {}


def test_google_analytics_report_keeps_partial_provider_errors() -> None:
    class BrokenGoogle(FakeGoogle):
        def run_search_console_report(self, _site_url: str, body: dict[str, Any]) -> dict[str, Any]:
            raise GooglePlatformError("Search Console is unavailable")

    result = GoogleAnalyticsService(
        {"seo": {"site_url": "https://example.test/"}, "ga": {"property_id": "123"}},
        BrokenGoogle(),
        {"site_url": "https://example.test/", "gsc_property": "https://example.test/", "ga4_property_id": "123"},
    ).report(28)

    assert result["ga4"]["available"] is True
    assert result["gsc"]["overview"]["current"] == {}
    assert result["errors"]["gsc.overview"] == "Search Console is unavailable"


def test_ga4_access_grant_is_bounded_to_safe_roles() -> None:
    client = GooglePlatformClient("/does/not/need/to/exist")
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_request(url: str, *, scopes: Any, method: str = "GET", body: dict[str, Any] | None = None):
        calls.append((url, method, body))
        return 200, {"name": "properties/123/accessBindings/test", "user": "owner@example.com", "roles": ["predefinedRoles/viewer"]}

    client._request = fake_request  # type: ignore[method-assign]
    result = client.grant_ga4_access("123", "Owner@Example.com", "viewer")

    assert result["user"] == "owner@example.com"
    assert calls[0][1] == "POST"
    assert calls[0][2] == {"user": "owner@example.com", "roles": ["predefinedRoles/viewer"]}
    with pytest.raises(GooglePlatformError, match="viewer or analyst"):
        client.grant_ga4_access("123", "owner@example.com", "admin")
