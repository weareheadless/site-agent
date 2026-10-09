from io import BytesIO
from urllib.error import HTTPError

import pytest

from site_agent.hands.resend import ResendCredentialError, ResendProvisioner, ResendVerificationPending


class FakeCloudflare:
    def __init__(self):
        self.created = []
        self.records = []

    def zone(self, domain):
        assert domain == "new-customer.example"
        return {"id": "zone-1", "name": "new-customer.example"}

    def dns_records(self, zone_id):
        assert zone_id == "zone-1"
        return list(self.records)

    def create_dns_record(self, zone_id, record):
        assert zone_id == "zone-1"
        self.created.append(record)
        self.records.append({**record, "id": f"record-{len(self.records) + 1}"})


def test_send_only_key_is_rejected_during_read_only_management_preflight(monkeypatch):
    def reject_management(*_args, **_kwargs):
        raise HTTPError(
            "https://api.resend.com/domains?limit=1",
            401,
            "restricted_api_key",
            {},
            BytesIO(b'{"message":"restricted_api_key"}'),
        )

    monkeypatch.setattr("site_agent.hands.resend.urllib.request.urlopen", reject_management)
    provisioner = ResendProvisioner("send-only-key", FakeCloudflare())

    with pytest.raises(ResendCredentialError, match="Full access API key is required"):
        provisioner.validate_management_access()


def test_new_sender_domain_is_created_then_verified_on_reconciliation():
    cloudflare = FakeCloudflare()
    provisioner = ResendProvisioner("management-key", cloudflare)
    requests = []
    domain = {
        "id": "domain-1",
        "name": "new-customer.example",
        "records": [
            {"type": "TXT", "name": "@", "value": "v=spf1 include:resend.com ~all"},
            {"type": "MX", "name": "send", "value": "feedback-smtp.us-east-1.amazonses.com", "priority": 10},
        ],
    }
    provider_state = {"status": "pending", "created": False}

    def request(method, path, body=None):
        requests.append((method, path, body))
        if method == "GET" and path.startswith("/domains?"):
            domains = [{**domain, **provider_state}] if provider_state["created"] else []
            return {"data": domains, "has_more": False}
        if method == "POST" and path == "/domains":
            provider_state["created"] = True
            return {"data": {**domain, **provider_state}}
        if method == "GET" and path == "/domains/domain-1":
            return {"data": {**domain, **provider_state}}
        raise AssertionError(f"Unexpected Resend request: {method} {path}")

    provisioner._request = request

    with pytest.raises(ResendVerificationPending):
        provisioner.ensure_domain("New-Customer.example.")

    assert len(cloudflare.created) == 2
    provider_state["status"] = "verified"
    result = provisioner.ensure_domain("New-Customer.example.")

    assert result == {
        "id": "domain-1",
        "domain": "new-customer.example",
        "status": "verified",
        "dnsRecordsCreated": 0,
    }
    assert [(item[0], item[1]) for item in requests] == [
        ("GET", "/domains?limit=100"),
        ("POST", "/domains"),
        ("GET", "/domains/domain-1"),
        ("GET", "/domains?limit=100"),
        ("GET", "/domains/domain-1"),
        ("GET", "/domains/domain-1"),
    ]
    assert cloudflare.created == [
        {"type": "TXT", "name": "new-customer.example", "content": "v=spf1 include:resend.com ~all"},
        {"type": "MX", "name": "send.new-customer.example", "content": "feedback-smtp.us-east-1.amazonses.com", "priority": 10},
    ]
