from __future__ import annotations

import pytest

from site_agent.application.email_provisioning import EmailProvisioningError, EmailProvisioningService


DOMAIN = "oceanicvibes.com"
WORKER = "oceanicvibes"
MAILGUN_MX = ["mxa.mailgun.org", "mxb.mailgun.org"]
MAILGUN_SPF = "v=spf1 include:mailgun.org ~all"


class FakeCloudflare:
    def __init__(self):
        self.enabled = False
        self.dns = [
            {"id": "mx-a", "type": "MX", "name": DOMAIN, "content": MAILGUN_MX[0], "priority": 10},
            {"id": "mx-b", "type": "MX", "name": DOMAIN, "content": MAILGUN_MX[1], "priority": 10},
            {"id": "spf", "type": "TXT", "name": DOMAIN, "content": MAILGUN_SPF},
            {"id": "dmarc", "type": "TXT", "name": f"_dmarc.{DOMAIN}", "content": "v=DMARC1; p=none"},
        ]
        self.rules = [{
            "id": "old-forward",
            "source": "api",
            "enabled": True,
            "name": "existing forwarding",
            "priority": 0,
            "matchers": [{"type": "literal", "field": "to", "value": f"hello@{DOMAIN}"}],
            "actions": [{"type": "forward", "value": ["owner@example.net"]}],
        }]
        self.sendings = []
        self.sender_dns = []
        self.writes = []

    def zone(self, name):
        assert name == DOMAIN
        return {"id": "zone-1", "name": DOMAIN, "status": "active", "account": {"id": "account-1"}}

    def dns_records(self, zone_id):
        return [dict(record) for record in self.dns]

    def routing_settings(self, zone_id):
        return {"enabled": self.enabled, "status": "ready" if self.enabled else "disabled"}

    def routing_dns(self, zone_id):
        if not self.enabled:
            return []
        return [
            {"type": "MX", "name": "@", "content": "route1.mx.cloudflare.net", "priority": 13},
            {"type": "MX", "name": "@", "content": "route2.mx.cloudflare.net", "priority": 86},
            {"type": "TXT", "name": "@", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        ]

    def routing_rules(self, zone_id):
        return [dict(rule) for rule in self.rules]

    def catch_all(self, zone_id):
        return {"enabled": False}

    def sending_domains(self, zone_id):
        return [dict(item) for item in self.sendings]

    def sending_dns(self, zone_id, identifier):
        assert identifier == "sending-1"
        return [dict(item) for item in self.sender_dns]

    def ensure_sending_domain(self, zone_id, domain, existing):
        self.writes.append(("sending", domain))
        sending = {"name": domain, "enabled": True, "tag": "sending-1"}
        self.sendings = [sending]
        self.dns.extend(
            {**record, "id": f"sending-{index}"}
            for index, record in enumerate(self.sender_dns)
            if record["name"] != f"_dmarc.{DOMAIN}"
        )
        return dict(sending)

    def delete_dns_record(self, zone_id, record_id):
        self.writes.append(("delete-dns", record_id))
        self.dns = [record for record in self.dns if record.get("id") != record_id]

    def enable_routing(self, zone_id, domain):
        self.writes.append(("routing", domain))
        self.enabled = True
        self.dns.extend([
            {"id": "routing-mx-a", "type": "MX", "name": "@", "content": "route1.mx.cloudflare.net", "priority": 13},
            {"id": "routing-mx-b", "type": "MX", "name": "@", "content": "route2.mx.cloudflare.net", "priority": 86},
            {"id": "routing-spf", "type": "TXT", "name": "@", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        ])
        return {"enabled": True, "status": "ready"}

    def update_routing_rule(self, zone_id, rule_id, rule, *, address, worker):
        self.writes.append(("update-rule", rule_id))
        updated = {
            **rule,
            "enabled": True,
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "worker", "value": [worker]}],
        }
        self.rules = [updated]
        return dict(updated)


def _policy(**values):
    return {
        "domain": DOMAIN,
        "address": f"hello@{DOMAIN}",
        "worker": WORKER,
        **values,
    }


def test_plan_is_read_only_and_requires_explicit_legacy_mailgun_approval():
    client = FakeCloudflare()
    service = EmailProvisioningService(client)

    with pytest.raises(EmailProvisioningError, match="not authorized"):
        service.plan("oceanicvibes", _policy())

    assert client.writes == []
    assert client.dns[0]["content"] == MAILGUN_MX[0]


def test_plan_requires_exact_mailgun_records_and_explicit_forward_rule_approval():
    client = FakeCloudflare()
    service = EmailProvisioningService(client)
    policy = _policy(
        approvedLegacyMx=MAILGUN_MX,
        approvedLegacySpf=MAILGUN_SPF,
        allowLegacyMailgunCutover=True,
    )

    with pytest.raises(EmailProvisioningError, match="forward rule"):
        service.plan("oceanicvibes", policy)
    plan = service.plan("oceanicvibes", {**policy, "allowForwardingCutover": True})

    assert plan["state"] == "ready_to_apply"
    assert plan["snapshot"]["existingMailboxRule"]["id"] == "old-forward"
    assert "replace only the exact, explicitly approved legacy Mailgun MX/SPF records" in plan["operations"]
    assert "route hello@oceanicvibes.com to the registered Worker" in plan["operations"]
    assert client.writes == []


def test_plan_stops_on_unrecognized_mx_or_multiple_spf_records():
    client = FakeCloudflare()
    client.dns[0]["content"] = "mx.example.net"
    policy = _policy(
        approvedLegacyMx=MAILGUN_MX,
        approvedLegacySpf=MAILGUN_SPF,
        allowLegacyMailgunCutover=True,
        allowForwardingCutover=True,
    )

    with pytest.raises(EmailProvisioningError, match="exact approved legacy set"):
        EmailProvisioningService(client).plan("oceanicvibes", policy)

    client = FakeCloudflare()
    client.dns.append({"id": "spf2", "type": "TXT", "name": DOMAIN, "content": "v=spf1 include:other.example ~all"})
    with pytest.raises(EmailProvisioningError, match="Multiple apex SPF"):
        EmailProvisioningService(client).plan("oceanicvibes", policy)


def test_active_cloudflare_routing_must_match_provider_declared_mx_and_spf():
    client = FakeCloudflare()
    client.enabled = True
    client.dns = [
        {"id": "mx-a", "type": "MX", "name": DOMAIN, "content": "route1.mx.cloudflare.net", "priority": 13},
        {"id": "mx-b", "type": "MX", "name": DOMAIN, "content": "route2.mx.cloudflare.net", "priority": 86},
        {"id": "spf", "type": "TXT", "name": DOMAIN, "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        {"id": "send-mx", "type": "MX", "name": f"cf-bounce.{DOMAIN}", "content": "route1.mx.cloudflare.net", "priority": 12},
        {"id": "send-spf", "type": "TXT", "name": f"cf-bounce.{DOMAIN}", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        {"id": "send-dkim", "type": "TXT", "name": f"cf-bounce._domainkey.{DOMAIN}", "content": "v=DKIM1; k=rsa; p=public-key"},
        {"id": "dmarc", "type": "TXT", "name": f"_dmarc.{DOMAIN}", "content": "v=DMARC1; p=none"},
    ]
    client.rules = [{
        "id": "worker-route", "source": "api", "enabled": True,
        "matchers": [{"type": "literal", "field": "to", "value": f"hello@{DOMAIN}"}],
        "actions": [{"type": "worker", "value": [WORKER]}],
    }]
    client.sendings = [{"name": DOMAIN, "enabled": True, "tag": "sending-1"}]
    client.sender_dns = [
        {"type": "MX", "name": f"cf-bounce.{DOMAIN}", "content": "route1.mx.cloudflare.net", "priority": 12},
        {"type": "TXT", "name": f"cf-bounce.{DOMAIN}", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        {"type": "TXT", "name": f"cf-bounce._domainkey.{DOMAIN}", "content": "v=DKIM1; k=rsa; p=public-key"},
    ]

    plan = EmailProvisioningService(client).plan("oceanicvibes", _policy())

    assert plan["operations"] == []
    assert len(plan["snapshot"]["sendingDns"]) == 3


def test_plan_stops_when_cloudflare_sending_authentication_dns_is_missing():
    client = FakeCloudflare()
    client.sendings = [{"name": DOMAIN, "enabled": True, "tag": "sending-1"}]
    client.sender_dns = [
        {"type": "TXT", "name": f"cf-bounce.{DOMAIN}", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
    ]

    with pytest.raises(EmailProvisioningError, match="Email Sending DNS records declared by Cloudflare"):
        EmailProvisioningService(client).plan("oceanicvibes", _policy())


def test_apply_moves_exact_legacy_records_and_forward_to_the_tenant_worker():
    client = FakeCloudflare()
    client.sender_dns = [
        {"type": "MX", "name": f"cf-bounce.{DOMAIN}", "content": "route1.mx.cloudflare.net", "priority": 12},
        {"type": "TXT", "name": f"cf-bounce.{DOMAIN}", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        {"type": "TXT", "name": f"cf-bounce._domainkey.{DOMAIN}", "content": "v=DKIM1; p=public-key"},
        {"type": "TXT", "name": f"_dmarc.{DOMAIN}", "content": "v=DMARC1; p=reject"},
    ]
    client.routing_dns = lambda zone_id: [
        {"type": "MX", "name": "@", "content": "route1.mx.cloudflare.net", "priority": 13},
        {"type": "MX", "name": "@", "content": "route2.mx.cloudflare.net", "priority": 86},
        {"type": "TXT", "name": "@", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
    ]
    client.policy = _policy(
        approvedLegacyMx=MAILGUN_MX,
        approvedLegacySpf=MAILGUN_SPF,
        allowLegacyMailgunCutover=True,
        allowForwardingCutover=True,
    )

    service = EmailProvisioningService(client)
    plan = service.plan("oceanicvibes", client.policy)
    result = service.provision(plan, client.policy)

    assert result["state"] == "cloudflare_ready"
    assert result["forwardRuleWasPresent"] is True
    assert client.rules[0]["actions"] == [{"type": "worker", "value": [WORKER]}]
    root_mx = [
        (record["content"], record["priority"])
        for record in client.dns
        if record["type"] == "MX" and record["name"] in ("@", DOMAIN)
    ]
    assert root_mx == [("route1.mx.cloudflare.net", 13), ("route2.mx.cloudflare.net", 86)]
    assert next(record["content"] for record in client.dns if record["name"] == f"_dmarc.{DOMAIN}") == "v=DMARC1; p=none"


def test_apply_replans_and_stops_if_legacy_state_becomes_unapproved_after_preflight():
    client = FakeCloudflare()
    service = EmailProvisioningService(client)
    policy = _policy(
        approvedLegacyMx=MAILGUN_MX,
        approvedLegacySpf=MAILGUN_SPF,
        allowLegacyMailgunCutover=True,
        allowForwardingCutover=True,
    )
    plan = service.plan("oceanicvibes", policy)
    client.dns[0]["content"] = "changed.mailgun.org"

    with pytest.raises(EmailProvisioningError, match="exact approved legacy set"):
        service.provision(plan, policy)
