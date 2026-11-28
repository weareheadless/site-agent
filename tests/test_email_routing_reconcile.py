from __future__ import annotations

import pytest

from site_agent.application.email_routing_reconcile import (
    RoutingReconcileError,
    apply_routing_reconciliation,
    plan_routing_reconciliation,
)


def rule(rule_id, address, worker, *, enabled=True, zone="zone-a", extra_targets=()):
    return {
        "id": rule_id,
        "enabled": enabled,
        "matchers": [{"type": "literal", "field": "to", "value": address}],
        "actions": [{"type": "worker", "value": [worker, *extra_targets]}],
    }


PLATFORM_ZONE = "zone-platform"
TENANTS = [
    # One tenant, two zones: the retained platform alias lives in the platform
    # zone, the custom domain has its own.
    {"tenantId": "casamigo", "worker": "helloada-casamigo",
     "domains": {"helloada.app": PLATFORM_ZONE},
     "addresses": ["casamigo@helloada.app"]},
    {"tenantId": "site-ff8e9af06f56201f", "worker": "helloada-site-astridrincon",
     "domains": {"helloada.app": PLATFORM_ZONE, "astridrincon.com": "zone-b"},
     "addresses": ["hello@astridrincon.com", "site-ff8e9af06f56201f@helloada.app"]},
]


def test_a_correct_table_needs_no_actions():
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={
            PLATFORM_ZONE: [
                rule("r1", "casamigo@helloada.app", "helloada-casamigo"),
                rule("r3", "site-ff8e9af06f56201f@helloada.app", "helloada-site-astridrincon"),
            ],
            "zone-b": [rule("r2", "hello@astridrincon.com", "helloada-site-astridrincon")],
        },
        known_workers={"helloada-casamigo", "helloada-site-astridrincon"},
    )
    assert plan.changed is False
    assert plan.actions == []
    assert plan.unnamed == []


def test_a_renamed_worker_is_repointed_and_reported_as_stale():
    # The live defect: the alias rule still names the pre-rename Worker.
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={
            PLATFORM_ZONE: [
                rule("r1", "casamigo@helloada.app", "helloada-casamigo"),
                rule("r2", "site-ff8e9af06f56201f@helloada.app", "helloada-site-ff8e9af06f56201f"),
            ],
        },
        known_workers={"helloada-casamigo", "helloada-site-astridrincon"},
    )
    repoint = [action for action in plan.actions if action.kind == "repoint"]
    assert len(repoint) == 1
    assert repoint[0].address == "site-ff8e9af06f56201f@helloada.app"
    assert repoint[0].worker == "helloada-site-astridrincon"
    assert repoint[0].reason.startswith("stale_worker")


def test_a_rule_pointing_at_another_live_tenant_is_still_wrong():
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={
            PLATFORM_ZONE: [rule("r1", "casamigo@helloada.app", "helloada-site-astridrincon")],
        },
        known_workers={"helloada-casamigo", "helloada-site-astridrincon"},
    )
    repoint = [action for action in plan.actions if action.kind == "repoint"]
    assert len(repoint) == 1
    assert repoint[0].reason.startswith("wrong_worker")


def test_a_disabled_rule_for_the_right_worker_is_enabled():
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={
            PLATFORM_ZONE: [rule("r1", "casamigo@helloada.app", "helloada-casamigo", enabled=False)],
        },
        known_workers={"helloada-casamigo"},
    )
    assert [action.kind for action in plan.actions] == ["enable"]


def test_a_rule_in_the_wrong_zone_is_not_moved_automatically():
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={
            PLATFORM_ZONE: [rule("r1", "hello@astridrincon.com", "helloada-site-astridrincon")],
        },
        known_workers={"helloada-site-astridrincon"},
    )
    assert plan.actions == []
    assert any(item["reason"] == "rule_in_other_zone" for item in plan.unnamed)


def test_an_orphan_rule_is_reported_and_only_deleted_when_asked():
    rules = {
        PLATFORM_ZONE: [
            rule("r1", "casamigo@helloada.app", "helloada-casamigo"),
            rule("orphan", "site-5fe73d3d38ff6f77@helloada.app", "helloada-site-5fe73d3d38ff6f77"),
        ],
    }
    reported = plan_routing_reconciliation(
        tenants=TENANTS, rules_by_zone=rules, known_workers={"helloada-casamigo"},
    )
    assert [item["address"] for item in reported.orphans] == ["site-5fe73d3d38ff6f77@helloada.app"]
    assert not [action for action in reported.actions if action.kind == "delete"]

    applied = plan_routing_reconciliation(
        tenants=TENANTS, rules_by_zone=rules, known_workers={"helloada-casamigo"}, remove_orphans=True,
    )
    deletes = [action for action in applied.actions if action.kind == "delete"]
    assert [action.rule_id for action in deletes] == ["orphan"]


def test_two_tenants_claiming_one_address_is_refused():
    with pytest.raises(RoutingReconcileError, match="claimed by"):
        plan_routing_reconciliation(
            tenants=[
                *TENANTS,
                {"tenantId": "other", "worker": "other",
                 "domains": {"helloada.app": PLATFORM_ZONE},
                 "addresses": ["casamigo@helloada.app"]},
            ],
            rules_by_zone={},
            known_workers=set(),
        )


def test_a_tenant_without_routing_identity_is_refused():
    with pytest.raises(RoutingReconcileError, match="incomplete"):
        plan_routing_reconciliation(
            tenants=[{"tenantId": "casamigo", "worker": "helloada-casamigo", "domains": {}, "addresses": []}],
            rules_by_zone={},
            known_workers=set(),
        )


def test_an_address_whose_domain_has_no_registered_zone_is_refused():
    # Never guess a zone from a hostname: an address the tenant owns but whose
    # domain this application has no zone for cannot be reconciled safely.
    with pytest.raises(RoutingReconcileError, match="no registered zone"):
        plan_routing_reconciliation(
            tenants=[{"tenantId": "casamigo", "worker": "helloada-casamigo",
                      "domains": {"helloada.app": PLATFORM_ZONE},
                      "addresses": ["hello@elsewhere.example"]}],
            rules_by_zone={},
            known_workers=set(),
        )


def test_a_forwarding_rule_is_reported_but_never_deleted():
    # `admin@helloada.app -> ben@jamin.io` is a person's mail, not a HelloAda
    # route. Sweeping it up as an orphan would silently stop their email.
    rules = {
        PLATFORM_ZONE: [
            rule("r1", "casamigo@helloada.app", "helloada-casamigo"),
            {
                "id": "forward",
                "enabled": True,
                "matchers": [{"type": "literal", "field": "to", "value": "admin@helloada.app"}],
                "actions": [{"type": "forward", "value": ["ben@jamin.io"]}],
            },
        ],
    }
    plan = plan_routing_reconciliation(
        tenants=TENANTS, rules_by_zone=rules, known_workers={"helloada-casamigo"}, remove_orphans=True,
    )
    orphan = plan.orphans[0]
    assert orphan["address"] == "admin@helloada.app"
    assert orphan["forwarding"] is True
    assert not [action for action in plan.actions if action.kind == "delete"]


class FakeClient:
    """The email adapter's routing surface, with the live table it mutates."""

    def __init__(self, rules_by_zone):
        self.rules = {zone: [dict(item) for item in rules] for zone, rules in rules_by_zone.items()}
        self.calls = []
        self.drop_updates = False

    def routing_rules(self, zone_id):
        return [dict(item) for item in self.rules.get(zone_id, [])]

    def update_routing_rule(self, zone_id, rule_id, rule, *, address, worker):
        self.calls.append(("update", zone_id, rule_id, worker))
        if self.drop_updates:
            return {}
        for item in self.rules.get(zone_id, []):
            if item["id"] == rule_id:
                item["actions"] = [{"type": "worker", "value": [worker]}]
                item["enabled"] = True
                item["matchers"] = [{"type": "literal", "field": "to", "value": address}]
        return {}

    def create_routing_rule(self, zone_id, *, address, worker):
        self.calls.append(("create", zone_id, address, worker))
        rule_id = f"created-{len(self.calls)}"
        self.rules.setdefault(zone_id, []).append(rule(rule_id, address, worker, zone=zone_id))
        return {"id": rule_id}

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "DELETE":
            rule_id = path.rsplit("/", 1)[-1]
            for zone_id, rules in self.rules.items():
                self.rules[zone_id] = [item for item in rules if item["id"] != rule_id]
        return {"success": True, "result": {}}


def test_apply_changes_exactly_the_plan_and_verifies_the_result():
    client = FakeClient({
        PLATFORM_ZONE: [
            rule("r1", "casamigo@helloada.app", "helloada-casamigo"),
            rule("r2", "site-ff8e9af06f56201f@helloada.app", "helloada-site-ff8e9af06f56201f"),
            rule("orphan", "site-5fe73d3d38ff6f77@helloada.app", "helloada-site-5fe73d3d38ff6f77"),
        ],
    })
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={PLATFORM_ZONE: client.rules[PLATFORM_ZONE]},
        known_workers={"helloada-casamigo", "helloada-site-astridrincon"},
        remove_orphans=True,
    )
    applied = apply_routing_reconciliation(client, plan)
    assert {item["state"] for item in applied} == {"repointed", "deleted"}

    live = {item["matchers"][0]["value"]: item for item in client.rules[PLATFORM_ZONE]}
    assert live["site-ff8e9af06f56201f@helloada.app"]["actions"][0]["value"] == ["helloada-site-astridrincon"]
    assert "site-5fe73d3d38ff6f77@helloada.app" not in live


def test_apply_fails_when_the_write_did_not_take_effect():
    client = FakeClient({
        PLATFORM_ZONE: [rule("r2", "site-ff8e9af06f56201f@helloada.app", "helloada-site-ff8e9af06f56201f")],
    })
    client.drop_updates = True
    plan = plan_routing_reconciliation(
        tenants=TENANTS,
        rules_by_zone={PLATFORM_ZONE: client.rules[PLATFORM_ZONE]},
        known_workers={"helloada-site-astridrincon"},
    )
    with pytest.raises(RoutingReconcileError, match="does not target"):
        apply_routing_reconciliation(client, plan)
