import json

import pytest

from site_agent.application.lane_proof import (
    LaneProofError,
    classify,
    proof_tenant,
    prove_lane,
)

REGISTRY = {
    "customers": {
        "casamigo": {"disposable": False},
        "ada-e2e-studio": {"disposable": True},
        "northstar-coffee-e2e": {"disposable": True},
    }
}


class _Response:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body


def test_a_customer_tenant_can_never_be_the_proof():
    with pytest.raises(LaneProofError, match="not disposable"):
        proof_tenant(REGISTRY, "casamigo")


def test_the_proof_tenant_is_a_registered_disposable_tenant():
    assert proof_tenant(REGISTRY) == "ada-e2e-studio"
    assert proof_tenant(REGISTRY, "northstar-coffee-e2e") == "northstar-coffee-e2e"


def test_a_registry_without_a_disposable_tenant_refuses_to_prove():
    with pytest.raises(LaneProofError, match="no tenant is declared disposable"):
        proof_tenant({"customers": {"casamigo": {}}})


def test_the_classification_names_the_layer_that_answered():
    assert classify(200, {"bindings": [], "groups": []})[0] == "served"
    assert classify(503, {"error": "workspace_route_not_owned"})[0] == "wrong_layer"
    assert classify(503, {"detail": "CrawlSEO connector is unavailable"})[0] == "lane_unmapped"
    assert classify(403, {"detail": "Authenticated owner identity is invalid"})[0] == "identity_rejected"
    assert classify(404, {"detail": "website was not found"})[0] == "not_registered"


def test_prove_lane_records_the_answering_layer():
    evidence = prove_lane(
        "growth", tenant="ada-e2e-studio", api_url="https://api.example/v1", token="t",
        opener=lambda request, timeout: _Response(200, {"bindings": [], "groups": []}),
    )
    assert evidence["lane"] == "growth"
    assert evidence["tenant"] == "ada-e2e-studio"
    assert evidence["outcome"] == "served"
    assert evidence["status"] == 200


def test_prove_lane_refuses_a_tenant_runtime_that_answered_instead():
    with pytest.raises(LaneProofError, match="wrong_layer"):
        prove_lane(
            "growth", tenant="ada-e2e-studio", api_url="https://api.example/v1", token="t",
            opener=lambda request, timeout: _Response(
                503, {"error": "workspace_route_not_owned", "route": "/growth/bindings"}
            ),
        )
