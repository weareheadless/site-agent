from __future__ import annotations

import json

import pytest

from site_agent.application.email_routing_fleet import (
    collect_tenant_routing_identity,
    reconcile_fleet_email_routing,
)
from site_agent.application.email_routing_reconcile import RoutingReconcileError


class FakeClient:
    def __init__(self, rules_by_zone):
        self.rules = {zone: [dict(item) for item in rules] for zone, rules in rules_by_zone.items()}

    def routing_rules(self, zone_id):
        return [dict(item) for item in self.rules.get(zone_id, [])]

    def update_routing_rule(self, zone_id, rule_id, rule, *, address, worker):
        for item in self.rules.get(zone_id, []):
            if item["id"] == rule_id:
                item["actions"] = [{"type": "worker", "value": [worker]}]
                item["enabled"] = True
        return {}

    def create_routing_rule(self, zone_id, *, address, worker):
        self.rules.setdefault(zone_id, []).append({
            "id": f"created-{address}",
            "enabled": True,
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "worker", "value": [worker]}],
        })
        return {"id": f"created-{address}"}

    def request(self, method, path, body=None):
        if method == "DELETE":
            rule_id = path.rsplit("/", 1)[-1]
            for zone_id in list(self.rules):
                self.rules[zone_id] = [item for item in self.rules[zone_id] if item["id"] != rule_id]
        return {"success": True, "result": {}}


def rule(rule_id, address, worker, zone_id):
    return {
        "id": rule_id,
        "enabled": True,
        "matchers": [{"type": "literal", "field": "to", "value": address}],
        "actions": [{"type": "worker", "value": [worker]}],
        "zone_id": zone_id,
    }


def test_a_tenant_without_an_address_is_action_required_not_an_error():
    identity, problem = collect_tenant_routing_identity(
        tenant_id="unprovisioned",
        worker="helloada-unprovisioned",
        tenant_env={},
        account_id="a" * 32,
        api_token="token",
        zone_lookup=lambda _host: "zone",
    )
    assert identity is None
    assert problem == {"tenantId": "unprovisioned", "reason": "no_registered_address"}


def test_a_zone_the_credential_cannot_manage_is_reported_for_that_tenant():
    identity, problem = collect_tenant_routing_identity(
        tenant_id="casamigo",
        worker="helloada-casamigo",
        tenant_env={"MAILFLARE_ADDRESS": "casamigo@helloada.app"},
        account_id="a" * 32,
        api_token="token",
        zone_lookup=lambda _host: "",
    )
    assert identity is None
    assert problem["reason"] == "zone_unavailable"
    assert problem["hostname"] == "helloada.app"
    assert "cannot manage this zone" in problem["detail"]


def test_a_reachable_zone_produces_a_full_identity(monkeypatch):
    monkeypatch.setattr(
        "site_agent.application.email_routing_fleet._d1_aliases",
        lambda *args, **kwargs: [{"address": "site-ff8e9af06f56201f@helloada.app", "hostname": "helloada.app"}],
    )
    identity, problem = collect_tenant_routing_identity(
        tenant_id="site-ff8e9af06f56201f",
        worker="helloada-site-astridrincon",
        tenant_env={"MAILFLARE_ADDRESS": "hello@astridrincon.com", "MAILFLARE_DB_ID": "db"},
        account_id="a" * 32,
        api_token="token",
        zone_lookup=lambda host: {"helloada.app": "zone-platform", "astridrincon.com": "zone-b"}[host],
    )
    assert problem is None
    assert identity["domains"] == {"helloada.app": "zone-platform", "astridrincon.com": "zone-b"}
    assert identity["addresses"] == ["hello@astridrincon.com", "site-ff8e9af06f56201f@helloada.app"]


def test_the_fleet_plan_covers_every_tenant_and_reports_the_rest():
    tenants = [
        {"tenantId": "casamigo", "worker": "helloada-casamigo",
         "domains": {"helloada.app": "zone-p"}, "addresses": ["casamigo@helloada.app"]},
        {"tenantId": "site-ff8e9af06f56201f", "worker": "helloada-site-astridrincon",
         "domains": {"helloada.app": "zone-p"}, "addresses": ["site-ff8e9af06f56201f@helloada.app"]},
    ]
    client = FakeClient({
        "zone-p": [
            rule("r1", "casamigo@helloada.app", "helloada-casamigo", "zone-p"),
            rule("r2", "site-ff8e9af06f56201f@helloada.app", "helloada-site-ff8e9af06f56201f", "zone-p"),
        ],
    })
    planned = reconcile_fleet_email_routing(
        tenants=tenants,
        rules_by_zone={"zone-p": client.routing_rules("zone-p")},
        client=client,
        known_workers={"helloada-casamigo", "helloada-site-astridrincon"},
    )
    assert planned["state"] == "planned"
    assert planned["mode"] == "plan_only"
    # A plan changes nothing on the account.
    assert client.rules["zone-p"][1]["actions"][0]["value"] == ["helloada-site-ff8e9af06f56201f"]

    applied = reconcile_fleet_email_routing(
        tenants=tenants,
        rules_by_zone={"zone-p": client.routing_rules("zone-p")},
        client=client,
        known_workers={"helloada-casamigo", "helloada-site-astridrincon"},
        apply=True,
    )
    assert applied["state"] == "applied"
    assert [item["state"] for item in applied["applied"]] == ["repointed"]
    assert client.rules["zone-p"][1]["actions"][0]["value"] == ["helloada-site-astridrincon"]


def test_an_apply_that_cannot_take_effect_is_a_failure_not_a_receipt():
    tenants = [
        {"tenantId": "site-ff8e9af06f56201f", "worker": "helloada-site-astridrincon",
         "domains": {"helloada.app": "zone-p"}, "addresses": ["site-ff8e9af06f56201f@helloada.app"]},
    ]
    client = FakeClient({"zone-p": [rule("r2", "site-ff8e9af06f56201f@helloada.app", "old", "zone-p")]})
    client.update_routing_rule = lambda *a, **k: {}  # write silently does nothing
    result = reconcile_fleet_email_routing(
        tenants=tenants,
        rules_by_zone={"zone-p": client.routing_rules("zone-p")},
        client=client,
        known_workers={"helloada-site-astridrincon"},
        apply=True,
    )
    assert result["state"] == "failed"
    assert "does not target" in result["error"]


def test_a_bad_tenant_mapping_is_refused_before_anything_is_written():
    client = FakeClient({})
    with pytest.raises(RoutingReconcileError):
        reconcile_fleet_email_routing(
            tenants=[
                {"tenantId": "a", "worker": "wa", "domains": {"helloada.app": "zone-p"}, "addresses": ["x@helloada.app"]},
                {"tenantId": "b", "worker": "wb", "domains": {"helloada.app": "zone-p"}, "addresses": ["x@helloada.app"]},
            ],
            rules_by_zone={},
            client=client,
            apply=True,
        )
    assert client.rules == {}
