import json
from pathlib import Path
from unittest import mock

import pytest

from site_agent.application.crawlseo import CrawlSEOApplicationError, CrawlSEOApplicationService
from site_agent.hands.crawlseo import CrawlSEOClient, CrawlSEOProtocolError, CrawlSEOSettings

ANALYTICS_FIXTURE = json.loads((Path(__file__).parent / "fixtures/crawlseo_connector_analytics_v1.json").read_text())


class Provider:
    def __init__(self, capability="opportunities.read"):
        self.calls = []
        self.capability = capability

    def connector_capabilities(self, site_id=None):
        self.calls.append(("capabilities", site_id))
        return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id,
                "capabilities": [self.capability, "opportunities.decide", "tasks.read", "tasks.confirm", "analytics.read"]}

    def connector_opportunities(self, **kwargs):
        self.calls.append(("opportunities", kwargs))
        return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"],
                "opportunities": [{"id": "opp-1"}], "nextCursor": None}

    def connector_task(self, **kwargs):
        self.calls.append(("task", kwargs))
        return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"], "task": {"id": kwargs["task_id"]}}

    def connector_opportunity_operation(self, **kwargs):
        self.calls.append(("operation", kwargs))
        return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["operation"]["siteId"], "accepted": True}

    def connector_confirm_task(self, **kwargs):
        self.calls.append(("confirm", kwargs))
        return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["confirmation"]["siteId"], "confirmed": True}

    def connector_analytics(self, **kwargs):
        self.calls.append(("analytics", kwargs))
        return {**ANALYTICS_FIXTURE, "siteId": kwargs["site_id"]}


def confirmation(**extra):
    return {"siteId": "site-1", "generation": 3, "idempotencyKey": "key-1", "confirmedBy": "owner-7",
            "confirmationRef": "message-22", **extra}


def test_hand_methods_use_only_fixed_versioned_routes_and_escape_ids():
    settings = CrawlSEOSettings(enabled=True, url="https://crawlseo.example/mcp", token_env="T", token="t",
                                connector_url="https://crawlseo.example/api/connector/v1")
    client = CrawlSEOClient(settings, runtime=object())
    with mock.patch.object(client, "_connector_request", return_value={}) as request:
        client.connector_opportunities("site 1", 5, "cur/sor")
        request.assert_called_with("GET", "/opportunities?siteId=site+1&limit=5&cursor=cur%2Fsor")
        client.connector_task("site-1", "a/b")
        assert request.call_args.args == ("GET", "/tasks/a%2Fb?siteId=site-1")
        client.connector_opportunity_operation("opp-1", {"operation": "accept"})
        assert request.call_args.args == ("POST", "/opportunities/opp-1/operations", {"operation": "accept"})
        client.connector_confirm_task("task-1", {"status": "delivered"})
        assert request.call_args.args == ("POST", "/tasks/task-1", {"status": "delivered"})
        client.connector_analytics("site-1", "2026-10-01", "2026-10-31")
        assert request.call_args.args == ("GET", "/analytics?siteId=site-1&startDate=2026-10-01&endDate=2026-10-31")
    with pytest.raises(CrawlSEOProtocolError):
        client.connector_opportunities("site-1", 101)


def test_application_reads_opportunities_and_checks_capabilities_and_identity():
    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    assert service.connector_opportunities("site-1", limit=10)["opportunities"][0]["id"] == "opp-1"
    assert provider.calls[-1] == ("opportunities", {"site_id": "site-1", "limit": 10, "cursor": None, "status": None})
    assert service.connector_opportunities("site-1", status="detected")["opportunities"][0]["id"] == "opp-1"
    assert provider.calls[-1] == ("opportunities", {"site_id": "site-1", "limit": 50, "cursor": None, "status": "detected"})
    with pytest.raises(CrawlSEOApplicationError, match="status"):
        service.connector_opportunities("site-1", status="decided")
    class Missing(Provider):
        def connector_capabilities(self, site_id=None):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": site_id, "capabilities": []}
    with pytest.raises(CrawlSEOApplicationError, match="unavailable"):
        CrawlSEOApplicationService(Missing()).connector_opportunities("site-1")
    class Wrong(Provider):
        def connector_opportunities(self, **kwargs):
            return {"schemaVersion": "1.0", "projectId": "other", "siteId": kwargs["site_id"], "opportunities": []}
    with pytest.raises(CrawlSEOApplicationError, match="identity"):
        CrawlSEOApplicationService(Wrong()).connector_opportunities("site-1")


def test_mutations_forward_exact_explicit_owner_confirmation_without_reading_live_state():
    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    op = confirmation(operation="accept", expectedUpdatedAt="2026-10-31T10:00:00Z", expectedDecisionId="decision-1", reason="Reviewed")
    service.connector_opportunity_operation("opp-1", op)
    assert provider.calls[-1] == ("operation", {"opportunity_id": "opp-1", "operation": op})
    task = confirmation(opportunityId="opp-1", expectedStatus="todo", status="in_progress")
    service.connector_confirm_task("task-1", task)
    assert provider.calls[-1] == ("confirm", {"task_id": "task-1", "confirmation": task})
    assert [call[0] for call in provider.calls].count("capabilities") == 2
    assert not any(call[0] in {"task", "opportunities"} for call in provider.calls)


@pytest.mark.parametrize("bad", [
    {}, confirmation(generation=True), confirmation(confirmedBy=""),
    confirmation(operation="accept", expectedUpdatedAt="2026-10-31", reason="x"),
])
def test_mutation_requires_valid_explicit_confirmation_before_dispatch(bad):
    provider = Provider()
    with pytest.raises(CrawlSEOApplicationError):
        CrawlSEOApplicationService(provider).connector_opportunity_operation("opp-1", bad)
    assert provider.calls == []


def test_task_confirmation_and_analytics_are_bounded_and_analytics_allowlisted():
    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    with pytest.raises(CrawlSEOApplicationError):
        service.connector_confirm_task("task-1", confirmation(opportunityId="opp-1", expectedStatus="unknown", status="delivered"))
    result = service.connector_analytics("site-1")
    encoded = json.dumps(result)
    assert "must-not-pass" not in encoded
    assert result["ga4"]["data"]["current_week"] == {"activeUsers": 8, "sessions": 12}
    assert result["ga4"]["data"]["previous_week"]["sessions"] == 9
    assert result["ga4"]["data"]["delta_pct"]["activeUsers"] == 60
    assert result["ga4"]["data"]["top_pages"] == [{"path": "/", "views": 40}]
    assert result["ga4"]["data"]["sources"][0]["source"] == "Organic Search"
    assert result["ga4"]["data"]["organic_queries"][0]["query"] == "sample query"
    assert result["gsc"]["queries"][0]["device"] == "DESKTOP"
    assert result["gsc"]["queries"][0]["country"] == "usa"
    assert result["gsc"]["rowCount"] == {"queries": 1, "pages": 1}
    assert result["gsc"]["truncation"] == {"queries": 0, "pages": 0}
    assert result["ga4"]["latestSync"]["errorCode"] == "GA4_SYNC_FAILED"
    assert result["gsc"]["latestSync"]["errorCode"] == "GSC_SYNC_FAILED"
    assert result["requestedPeriod"] == ANALYTICS_FIXTURE["requestedPeriod"]
    assert provider.calls[-1] == ("analytics", {"site_id": "site-1", "start_date": None, "end_date": None})


def test_analytics_accepts_missing_sources_and_empty_metrics_with_nullable_values():
    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    missing = json.loads(json.dumps(ANALYTICS_FIXTURE))
    missing["ga4"].update(status="missing", propertyId=None, observedAt=None, coverage=None, data=None, snapshotId=None)
    missing["gsc"].update(status="missing", propertyId=None, observedAt=None, coverage=None, queries=[], pages=[], rowCount={"queries": 0, "pages": 0}, truncation={"queries": 0, "pages": 0})
    missing["ga4"]["connection"] = {"status": "unconnected", "lastSuccessfulAt": None, "errorCode": None}
    missing["gsc"]["connection"] = {"status": "unconnected", "lastSuccessfulAt": None, "errorCode": None}
    missing["ga4"]["latestSync"] = {"status": "none", "observedAt": None, "errorCode": None}
    missing["gsc"]["latestSync"] = {"status": "none", "observedAt": None, "errorCode": None}
    provider.connector_analytics = lambda **_kwargs: missing
    result = service.connector_analytics("site-1")
    assert result["ga4"]["propertyId"] is None and result["ga4"]["observedAt"] is None and result["ga4"]["data"] is None
    assert result["gsc"]["propertyId"] is None and result["gsc"]["observedAt"] is None

    empty = json.loads(json.dumps(missing))
    empty["ga4"].update(status="invalid", propertyId="properties/123", data=None, snapshotId="empty")
    provider.connector_analytics = lambda **_kwargs: empty
    assert service.connector_analytics("site-1")["ga4"]["data"] is None


def test_analytics_requires_paired_bounded_dates_and_does_not_truncate_lists():
    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    with pytest.raises(CrawlSEOApplicationError, match="provided together"):
        service.connector_analytics("site-1", "2026-11-01")
    with pytest.raises(CrawlSEOApplicationError, match="366"):
        service.connector_analytics("site-1", "2025-01-01", "2026-01-02")
    response = json.loads(json.dumps(ANALYTICS_FIXTURE))
    response["gsc"]["queries"] = response["gsc"]["queries"] * 10001
    response["gsc"]["rowCount"]["queries"] = 10001
    response["gsc"]["truncation"]["queries"] = 0
    provider.connector_analytics = lambda **_kwargs: response
    assert len(service.connector_analytics("site-1")["gsc"]["queries"]) == 10001


def test_task_and_opportunity_responses_require_exact_requested_ids_and_row_shape():
    provider = Provider()
    service = CrawlSEOApplicationService(provider)
    class WrongTask(Provider):
        def connector_task(self, **kwargs):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"], "task": {"id": "other"}}
    with pytest.raises(CrawlSEOApplicationError, match="requested task"):
        CrawlSEOApplicationService(WrongTask()).connector_task("site-1", "task-1")
    class BadOpportunity(Provider):
        def connector_opportunities(self, **kwargs):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"], "opportunities": [{"name": "no id"}]}
    with pytest.raises(CrawlSEOApplicationError, match="opportunities"):
        CrawlSEOApplicationService(BadOpportunity()).connector_opportunities("site-1")


def test_analytics_matches_producer_empty_comparison_maps_and_numeric_contract():
    response = json.loads(json.dumps(ANALYTICS_FIXTURE))
    response["ga4"]["data"]["previous_week"] = {}
    response["ga4"]["data"]["delta_pct"] = {}
    provider = Provider()
    provider.connector_analytics = lambda **_kwargs: response
    result = CrawlSEOApplicationService(provider).connector_analytics("site-1")
    assert result["ga4"]["data"]["previous_week"] == {}
    assert result["ga4"]["data"]["delta_pct"] == {}
    response["ga4"]["data"]["current_week"]["activeUsers"] = None
    with pytest.raises(CrawlSEOApplicationError, match="metric"):
        CrawlSEOApplicationService(provider).connector_analytics("site-1")


def test_analytics_preserves_saved_data_and_an_ambiguous_connection_without_selecting_a_property():
    response = json.loads(json.dumps(ANALYTICS_FIXTURE))
    response["ga4"]["propertyId"] = None
    response["ga4"]["connection"] = {"status": "ambiguous", "lastSuccessfulAt": None, "errorCode": "MULTIPLE_GOOGLE_GRANTS"}
    provider = Provider()
    provider.connector_analytics = lambda **_kwargs: response
    result = CrawlSEOApplicationService(provider).connector_analytics("site-1")
    assert result["ga4"]["propertyId"] is None
    assert result["ga4"]["connection"] == response["ga4"]["connection"]
    assert result["ga4"]["data"]["current_week"]["activeUsers"] == 8


def test_opportunities_validate_the_whole_project_counts_and_reject_a_bad_shape():
    class Counted(Provider):
        def connector_opportunities(self, **kwargs):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"],
                    "opportunities": [{"id": "opp-1"}], "counts": {"detected": 13, "parked": 138, "total": 151},
                    "nextCursor": None}

    service = CrawlSEOApplicationService(Counted())
    assert service.connector_opportunities("site-1")["counts"]["parked"] == 138

    class Negative(Provider):
        def connector_opportunities(self, **kwargs):
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"],
                    "opportunities": [], "counts": {"detected": -1}, "nextCursor": None}

    with pytest.raises(CrawlSEOApplicationError, match="counts"):
        CrawlSEOApplicationService(Negative()).connector_opportunities("site-1")


def test_a_full_page_of_verbose_opportunities_is_not_refused_by_a_scalar_byte_cap():
    """A 100-row page is legitimately hundreds of kilobytes.

    The default 200 KB scalar bound refused the connector's own maximum page
    with "invalid CrawlSEO opportunities response", which read like a broken
    connector. The bound follows the list endpoints (findings, analytics).
    """

    class Verbose(Provider):
        def connector_opportunities(self, **kwargs):
            rows = [{
                "id": f"opp-{index}",
                "title": "Add a line-training section to the homepage " * 8,
                "summary": "Evidence paragraph about the page and its queries. " * 40,
                "dedupKey": f"phase3:content_business:{index:016x}",
                "scoreInputs": {"worth": {"targetPages": ["https://example.test/blog/a-very-long-slug-" + "x" * 60]}},
                "recommendationDecision": {"action": "Write the section and link it. " * 20},
                "tasks": [],
            } for index in range(100)]
            return {"schemaVersion": "1.0", "projectId": "project-1", "siteId": kwargs["site_id"],
                    "opportunities": rows, "nextCursor": "opp-99"}

    result = CrawlSEOApplicationService(Verbose()).connector_opportunities("site-1", limit=100)
    assert len(result["opportunities"]) == 100
    assert len(json.dumps(result, separators=(",", ":")).encode("utf-8")) > 200_000


def test_a_connector_refusal_is_reported_as_a_refusal_not_as_an_outage():
    """A stale page is not an outage.

    The connector answers 409 when the reviewed version no longer matches, and
    the transport maps that to a protocol error. Treating it as "unavailable"
    told the owner the connector was down and hid the one action that fixes it.
    """
    from site_agent.hands.crawlseo import CrawlSEOProtocolError, CrawlSEOUnavailableError

    class Refuses(Provider):
        def connector_opportunity_operation(self, **kwargs):
            raise CrawlSEOProtocolError("CrawlSEO connector rejected a stale or conflicting operation")

    with pytest.raises(CrawlSEOApplicationError, match="stale or conflicting"):
        CrawlSEOApplicationService(Refuses()).connector_opportunity_operation(
            "opp-1", confirmation(operation="accept", expectedUpdatedAt="2026-11-01T00:00:00.000Z"))

    class Down(Provider):
        def connector_opportunity_operation(self, **kwargs):
            raise CrawlSEOUnavailableError("CrawlSEO connector request failed (HTTP 503)")

    with pytest.raises(CrawlSEOApplicationError, match="unavailable"):
        CrawlSEOApplicationService(Down()).connector_opportunity_operation(
            "opp-1", confirmation(operation="accept", expectedUpdatedAt="2026-11-01T00:00:00.000Z"))
