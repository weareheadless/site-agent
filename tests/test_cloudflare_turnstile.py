"""Strict tests for tenant-scoped Turnstile provisioning."""

import pytest

from site_agent.hands.cloudflare_resources import CloudflareResourceError
from site_agent.hands.cloudflare_turnstile import CloudflareTurnstileProvisioner


class FakeTurnstile(CloudflareTurnstileProvisioner):
    def __init__(self, replies):
        super().__init__("a" * 32, "test-token")
        self.replies = iter(replies)
        self.calls = []

    def _request(self, method, path, *, payload=None):
        self.calls.append((method, path, payload))
        status, body = next(self.replies)
        return status, body


def response(result, status=200):
    return status, {"success": True, "result": result}


def test_creates_a_widget_once_and_never_exposes_its_secret_in_receipts():
    provisioner = FakeTurnstile([
        response([], status=200),
        response({
            "name": "helloada-oceanicvibes-forms",
            "sitekey": "0xsitekey",
            "secret": "private-secret",
            "domains": ["oceanicvibes.com"],
        }, status=200),
    ])
    receipt = provisioner.ensure_widget("oceanicvibes", ["oceanicvibes.com"])

    assert receipt.sitekey == "0xsitekey"
    assert receipt.secret == "private-secret"
    assert receipt.created is True
    assert receipt.to_dict() == {
        "name": "helloada-oceanicvibes-forms",
        "sitekey": "0xsitekey",
        "domains": ["oceanicvibes.com"],
        "created": True,
    }
    assert "private-secret" not in repr(receipt)
    assert provisioner.calls[1][0:2] == (
        "POST", "/accounts/" + "a" * 32 + "/challenges/widgets",
    )


def test_updates_exact_hostnames_for_a_saved_widget():
    provisioner = FakeTurnstile([
        response({
            "name": "helloada-oceanicvibes-forms",
            "sitekey": "0xsitekey",
            "secret": "private-secret",
            "domains": ["oceanicvibes.workers.dev"],
            "mode": "managed",
        }),
        response({
            "name": "helloada-oceanicvibes-forms",
            "sitekey": "0xsitekey",
            "domains": ["oceanicvibes.com", "oceanicvibes.workers.dev"],
            "mode": "managed",
        }),
    ])
    receipt = provisioner.ensure_widget(
        "oceanicvibes",
        ["oceanicvibes.workers.dev", "oceanicvibes.com"],
        sitekey="0xsitekey",
        secret="private-secret",
    )

    assert receipt.domains == ("oceanicvibes.com", "oceanicvibes.workers.dev")
    assert [call[0] for call in provisioner.calls] == ["GET", "PUT"]


@pytest.mark.parametrize("domains", [["https://example.com"], ["*.example.com"], ["bad domain"]])
def test_rejects_invalid_turnstile_hostnames_before_api_calls(domains):
    provisioner = FakeTurnstile([])
    with pytest.raises(CloudflareResourceError, match="hostname"):
        provisioner.ensure_widget("demo", domains)
    assert provisioner.calls == []


def test_rejects_empty_hostnames_before_api_calls():
    provisioner = FakeTurnstile([])
    with pytest.raises(CloudflareResourceError, match="one to ten"):
        provisioner.ensure_widget("demo", [])
    assert provisioner.calls == []


def test_rejects_more_than_cloudflare_free_host_allowlist_before_api_calls():
    provisioner = FakeTurnstile([])
    with pytest.raises(CloudflareResourceError, match="one to ten"):
        provisioner.ensure_widget("demo", [f"site-{index}.example.com" for index in range(11)])
    assert provisioner.calls == []


def test_fails_closed_when_stored_tenant_identity_does_not_match_cloudflare():
    provisioner = FakeTurnstile([
        response({
            "name": "helloada-another-tenant-forms",
            "sitekey": "0xsitekey",
            "secret": "private-secret",
            "domains": ["example.com"],
        }),
    ])
    with pytest.raises(CloudflareResourceError, match="identity"):
        provisioner.ensure_widget("demo", ["example.com"], sitekey="0xsitekey", secret="private-secret")


def test_fails_closed_when_multiple_widgets_match_an_unpersisted_tenant():
    provisioner = FakeTurnstile([
        response([
            {"name": "helloada-demo-forms", "sitekey": "one"},
            {"name": "helloada-demo-forms", "sitekey": "two"},
        ]),
    ])
    with pytest.raises(CloudflareResourceError, match="multiple"):
        provisioner.ensure_widget("demo", ["example.com"])
