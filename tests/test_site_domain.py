from __future__ import annotations

import pytest

from site_agent.application import site_domain
from site_agent.application.site_domain import (
    SiteDomainError,
    SiteDomainService,
    canonical_host,
    registered_domain,
)
from site_agent.application.site_identity import site_identity


class FakeDNS:
    def __init__(self, *, zone=None, records=None):
        self.zone_row = zone or {"id": "zone-1", "name": "example.com", "status": "active"}
        self.rows = records or {}
        self.deleted: list[str] = []

    def zone_for_hostname(self, hostname):
        return dict(self.zone_row)

    def records(self, zone_id, *, record_type="", name=""):
        return list(self.rows.get(name, []))

    def delete_record(self, zone_id, record_id):
        self.deleted.append(record_id)
        return True


class FakeDomains:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.attached: list[tuple[str, str, str]] = []
        self.detached: list[str] = []

    def list(self):
        return list(self.rows)

    def for_hostname(self, hostname):
        return next((row for row in self.rows if row["hostname"] == hostname), None)

    def attach(self, *, zone_id, hostname, service):
        self.attached.append((zone_id, hostname, service))
        return {"hostname": hostname, "service": service}

    def detach(self, domain_id):
        self.detached.append(domain_id)


def _service(monkeypatch, dns, domains):
    service = SiteDomainService({}, {})
    monkeypatch.setattr(service, "_dns_client", lambda: dns)
    monkeypatch.setattr(service, "_domains_client", lambda: domains)
    return service


def test_registered_domain_accepts_a_url_and_strips_www():
    assert registered_domain("https://www.casamigo.net/") == "casamigo.net"
    assert registered_domain("WWW.Casamigo.NET.") == "casamigo.net"
    assert canonical_host("casamigo.net", "www") == "www.casamigo.net"
    assert canonical_host("casamigo.net", "apex") == "casamigo.net"


def test_registered_domain_rejects_a_bare_label():
    with pytest.raises(SiteDomainError):
        registered_domain("localhost")


def test_attach_attaches_apex_and_www_to_the_tenant_worker(monkeypatch):
    dns, domains = FakeDNS(), FakeDomains()
    service = _service(monkeypatch, dns, domains)

    result = service.attach(domain="casamigo.net", worker_name="helloada-casamigo")

    assert result["publicUrl"] == "https://www.casamigo.net/"
    assert [row[1] for row in domains.attached] == ["casamigo.net", "www.casamigo.net"]
    assert {row[2] for row in domains.attached} == {"helloada-casamigo"}


def test_attach_reports_a_hostname_owned_by_another_worker(monkeypatch):
    domains = FakeDomains([{"id": "d1", "hostname": "casamigo.net", "service": "apex-redirect"}])
    service = _service(monkeypatch, FakeDNS(), domains)

    with pytest.raises(SiteDomainError) as caught:
        service.attach(domain="casamigo.net", worker_name="helloada-casamigo")

    assert caught.value.conflict is not None
    assert caught.value.conflict.kind == "custom_domain"
    assert caught.value.conflict.service == "apex-redirect"
    assert domains.attached == []


def test_attach_takeover_detaches_the_other_service(monkeypatch):
    domains = FakeDomains([{"id": "d1", "hostname": "casamigo.net", "service": "apex-redirect"}])
    service = _service(monkeypatch, FakeDNS(), domains)

    service.attach(domain="casamigo.net", worker_name="helloada-casamigo", takeover=True)

    assert domains.detached == ["d1"]
    assert [row[1] for row in domains.attached] == ["casamigo.net", "www.casamigo.net"]


def test_attach_reports_a_conflicting_dns_record(monkeypatch):
    dns = FakeDNS(records={
        "www.casamigo.net": [
            {"id": "r1", "type": "CNAME", "name": "www.casamigo.net",
             "content": "cdn.webflow.com", "proxied": True},
        ],
    })
    service = _service(monkeypatch, dns, FakeDomains())

    with pytest.raises(SiteDomainError) as caught:
        service.attach(domain="casamigo.net", worker_name="helloada-casamigo")

    assert caught.value.conflict is not None
    assert caught.value.conflict.kind == "dns_record"
    assert caught.value.conflict.records[0]["content"] == "cdn.webflow.com"
    assert dns.deleted == []


def test_attach_replaces_dns_when_the_caller_confirms(monkeypatch):
    dns = FakeDNS(records={
        "www.casamigo.net": [
            {"id": "r1", "type": "CNAME", "name": "www.casamigo.net",
             "content": "cdn.webflow.com", "proxied": True},
        ],
    })
    service = _service(monkeypatch, dns, FakeDomains())

    service.attach(domain="casamigo.net", worker_name="helloada-casamigo", replace_dns=True)

    assert dns.deleted == ["r1"]


def test_attach_keeps_a_placeholder_record_of_our_own_domain(monkeypatch):
    dns = FakeDNS(records={
        "casamigo.net": [
            {"id": "r1", "type": "AAAA", "name": "casamigo.net",
             "content": "100::", "proxied": True},
        ],
    })
    service = _service(monkeypatch, dns, FakeDomains())

    service.attach(domain="casamigo.net", worker_name="helloada-casamigo")

    assert dns.deleted == []


def test_status_is_tolerant_when_the_zone_is_absent(monkeypatch):
    class MissingZone(FakeDNS):
        def zone_for_hostname(self, hostname):
            from site_agent.hands.cloudflare_dns import CloudflareDNSError

            raise CloudflareDNSError("zone not found")

    identity = site_identity("casamigo", {
        "site": {"public_url": "https://www.casamigo.net/", "custom_domain": "casamigo.net",
                 "preview_url": "https://helloada-casamigo.weareheadless.workers.dev",
                 "source_deployment": {"worker_name": "helloada-casamigo"}},
    })
    service = _service(monkeypatch, MissingZone(), FakeDomains())
    monkeypatch.setattr(service, "probe", lambda url: {"ok": True, "status": 200})

    result = service.status(identity)

    assert result["available"] is False
    assert "not in the platform Cloudflare account" in result["reason"]
    assert result["serving"]["ok"] is True


def test_identity_resolves_every_address_from_the_record():
    identity = site_identity("casamigo", {
        "display_name": "Casamigo",
        "site": {
            "public_url": "https://www.casamigo.net/",
            "custom_domain": "casamigo.net",
            "preview_url": "https://helloada-casamigo.weareheadless.workers.dev",
            "payload": {"url": "https://helloada-casamigo.weareheadless.workers.dev"},
            "source_deployment": {"worker_name": "helloada-casamigo"},
        },
    })

    assert identity.worker_url == "https://helloada-casamigo.weareheadless.workers.dev/"
    assert identity.public_url == "https://www.casamigo.net/"
    assert identity.admin_url == "https://www.casamigo.net/admin"
    assert identity.registered_domain == "casamigo.net"
    assert identity.canonical_host == "www.casamigo.net"


def test_identity_falls_back_to_the_canonical_host():
    identity = site_identity("astrid", {
        "site": {
            "public_url": "https://astridrincon.com/",
            "preview_url": "https://helloada-site-astridrincon.weareheadless.workers.dev",
            "source_deployment": {"worker_name": "helloada-site-astridrincon"},
        },
    })

    assert identity.registered_domain == "astridrincon.com"
    assert identity.admin_url == "https://astridrincon.com/admin"


def test_attach_checks_every_host_before_moving_any(monkeypatch):
    # The apex is owned by another Worker and www has a blocking record. Even
    # with takeover allowed, the second host's conflict must be found before the
    # first host is detached: a refused attach changes nothing.
    dns = FakeDNS(records={
        "www.casamigo.net": [
            {"id": "r1", "type": "CNAME", "name": "www.casamigo.net",
             "content": "cdn.webflow.com", "proxied": True},
        ],
    })
    domains = FakeDomains([{"id": "d1", "hostname": "casamigo.net", "service": "apex-redirect"}])
    service = _service(monkeypatch, dns, domains)

    with pytest.raises(SiteDomainError) as caught:
        service.attach(domain="casamigo.net", worker_name="helloada-casamigo", takeover=True)

    assert caught.value.conflict.kind == "dns_record"
    assert domains.detached == []
    assert domains.attached == []
    assert dns.deleted == []
