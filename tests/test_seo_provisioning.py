import json
import stat
from pathlib import Path

import pytest

from site_agent.application.seo_provisioning import (
    SeoProvisioningError,
    SeoProvisioningService,
    tenant_token_env,
    write_token_env,
)
from site_agent.hands.cloudflare_dns import CloudflareDNSClient, CloudflareDNSError
from site_agent.hands.google_platform import GooglePlatformError


def _service_account_file(tmp_path: Path) -> Path:
    path = tmp_path / "sa.json"
    path.write_text(json.dumps({
        "type": "service_account",
        "client_email": "provisioner@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
        "project_id": "example-project",
    }))
    return path


class StubGoogle:
    def __init__(self, verify_fails=False):
        self.calls = []
        self.created = False
        self.verify_fails = verify_fails

    def create_property(self, account_id, display_name, *, time_zone="UTC", currency_code="EUR"):
        self.calls.append(("create_property", account_id, display_name))
        return {"property_id": "555", "property": "properties/555", "created": not self.created}

    def ensure_web_stream(self, property_id, site_url, *, display_name=None):
        self.calls.append(("ensure_web_stream", property_id, site_url))
        return {"data_stream_id": "9", "measurement_id": "G-TEST123", "created": True}

    def verification_token(self, identifier, *, method="DNS_TXT", site_type="INET_DOMAIN"):
        self.calls.append(("verification_token", identifier, method))
        return "google-site-verification=token"

    def verify_domain(self, identifier, *, method="DNS_TXT", site_type="INET_DOMAIN"):
        self.calls.append(("verify_domain", identifier, method))
        if self.verify_fails:
            raise GooglePlatformError("token not found on site")
        return True

    def add_search_console_site(self, site_url):
        self.calls.append(("add_site", site_url))


class StubDNS:
    def __init__(self):
        self.calls = []

    def zone_id(self, name):
        self.calls.append(("zone_id", name))
        return "zone-1"

    def ensure_public_host(self, zone_id, name, *, target="192.0.2.1"):
        self.calls.append(("ensure_public_host", name))
        return "record-a"

    def upsert_txt(self, zone_id, name, content, *, ttl=120):
        self.calls.append(("upsert_txt", name, content))
        return "record-txt"


class StubCrawlSEO:
    def __init__(self, token="cseo_test_token"):
        self.payload = None
        self._token = token

    def provision(self, payload):
        self.payload = dict(payload)
        return {
            "workspace_id": "ws-1",
            "project_id": "proj-1",
            "site_id": "site-1",
            "credential_id": "cred-1",
            "credential_token": self._token,
            "credential_reused": False,
            "dataforseo_grant_source": "platform",
            "jobs": {"gsc": "j1", "ga4": "j2"},
        }


def _config(tmp_path: Path) -> dict:
    return {
        "credentials": {
            "google": {
                "service_account_file": str(_service_account_file(tmp_path)),
                "platform_analytics_account": "405581435",
            }
        }
    }


def test_tenant_token_env_is_a_safe_unique_name():
    assert tenant_token_env("atelier-harmonie") == "CRAWLSEO_TOKEN_ATELIER_HARMONIE"
    with pytest.raises(SeoProvisioningError):
        tenant_token_env("Atelier Harmonie")


def test_write_token_env_is_private(tmp_path):
    path = write_token_env(tmp_path, "CRAWLSEO_TOKEN_TENANT", "cseo_secret")
    assert path.name == "crawlseo.env"
    assert path.read_text().strip().endswith("CRAWLSEO_TOKEN_TENANT=cseo_secret")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_provision_runs_the_full_chain(tmp_path):
    google, dns, crawlseo = StubGoogle(), StubDNS(), StubCrawlSEO()
    service = SeoProvisioningService(_config(tmp_path), {}, google=google, dns=dns, crawlseo=crawlseo)

    receipt = service.provision(
        tenant_id="atelier-harmonie",
        domain="atelier-harmonie.weareheadless.workers.dev",
        project_name="Atelier Harmonie",
        time_zone="Europe/Paris",
    )

    assert receipt["ga4_property_id"] == "555"
    assert receipt["ga4_measurement_id"] == "G-TEST123"
    assert receipt["gsc_property"] == "sc-domain:atelier-harmonie.weareheadless.workers.dev"
    assert receipt["gsc_verified"] is True
    assert receipt["credential_issued"] is True
    assert receipt["token_env"] == "CRAWLSEO_TOKEN_ATELIER_HARMONIE"

    # GSC ownership is proven through the DNS TXT token before verification.
    assert ("upsert_txt", "atelier-harmonie.weareheadless.workers.dev", "google-site-verification=token") in dns.calls
    assert ("verify_domain", "atelier-harmonie.weareheadless.workers.dev", "DNS_TXT") in google.calls
    # The CrawlSEO payload carries the platform service account, never a user token.
    assert crawlseo.payload["externalProjectId"] == "atelier-harmonie"
    assert crawlseo.payload["ga4PropertyId"] == "555"
    assert crawlseo.payload["gscProperty"] == receipt["gsc_property"]
    assert crawlseo.payload["serviceAccountCredentials"]["client_email"].endswith(".iam.gserviceaccount.com")
    assert crawlseo.payload["domainVerificationMethod"] == "verified_gsc"


def test_provision_reuses_an_existing_ga4_property_and_can_skip_gsc(tmp_path):
    google, dns, crawlseo = StubGoogle(), StubDNS(), StubCrawlSEO()
    service = SeoProvisioningService(_config(tmp_path), {}, google=google, dns=dns, crawlseo=crawlseo)

    receipt = service.provision(
        tenant_id="casamigo",
        domain="casamigo.net",
        project_name="casamigo",
        ga4_property_id="411596330",
        verify_gsc=False,
    )

    assert receipt["ga4_property_id"] == "411596330"
    assert receipt["ga4_created"] is False
    assert "gsc_verified" not in receipt
    assert all(call[0] != "verify_domain" for call in google.calls)
    assert crawlseo.payload["ga4PropertyId"] == "411596330"


def test_platform_available_requires_the_host_profiles(tmp_path):
    assert SeoProvisioningService(_config(tmp_path), {}).platform_available is False
    assert SeoProvisioningService({}, {}).platform_available is False


def test_crawlseo_client_missing_configuration_is_reported(tmp_path):
    service = SeoProvisioningService({}, {})
    with pytest.raises(SeoProvisioningError, match="provisioning_url"):
        service.crawlseo_client()


def test_cloudflare_upsert_replaces_a_stale_record(monkeypatch):
    client = CloudflareDNSClient("token")

    recorded: list[tuple[str, str, dict | None]] = []

    def fake_request(path, *, method="GET", body=None):
        recorded.append((path, method, body))
        if method == "GET":
            return {"success": True, "result": [{"id": "old", "content": "google-site-verification=stale"}]}
        return {"success": True, "result": {"id": "old"}}

    monkeypatch.setattr(client, "_request", fake_request)
    record_id = client.upsert_txt("zone-1", "example.test", "google-site-verification=fresh")

    assert record_id == "old"
    assert ("/zones/zone-1/dns_records/old", "PUT", {"type": "TXT", "name": "example.test", "content": "google-site-verification=fresh", "ttl": 120}) in recorded


def test_cloudflare_client_requires_a_token():
    with pytest.raises(CloudflareDNSError):
        CloudflareDNSClient("")


def test_provision_with_meta_verification_returns_the_tag(tmp_path):
    google, dns, crawlseo = StubGoogle(), StubDNS(), StubCrawlSEO()
    service = SeoProvisioningService(_config(tmp_path), {}, google=google, dns=dns, crawlseo=crawlseo)

    receipt = service.provision(
        tenant_id="atelier-harmonie",
        domain="atelier-harmonie.weareheadless.workers.dev",
        project_name="Atelier Harmonie",
        site_url="https://atelier-harmonie.weareheadless.workers.dev",
        verification_method="meta",
    )

    assert receipt["gsc_meta_tag"] == "google-site-verification=token"
    assert receipt["gsc_property"] == "https://atelier-harmonie.weareheadless.workers.dev"
    assert receipt["gsc_verified"] is True
    assert receipt["gsc_verification_method"] == "meta"
    assert ("verify_domain", "https://atelier-harmonie.weareheadless.workers.dev", "META") in google.calls
    assert crawlseo.payload["gscProperty"] == "https://atelier-harmonie.weareheadless.workers.dev"


def test_meta_verification_defers_when_the_tag_is_not_live_yet(tmp_path):
    google, dns, crawlseo = StubGoogle(verify_fails=True), StubDNS(), StubCrawlSEO()
    service = SeoProvisioningService(_config(tmp_path), {}, google=google, dns=dns, crawlseo=crawlseo)

    receipt = service.provision(
        tenant_id="atelier-harmonie",
        domain="atelier-harmonie.weareheadless.workers.dev",
        project_name="Atelier Harmonie",
        site_url="https://atelier-harmonie.weareheadless.workers.dev",
        verification_method="meta",
    )

    assert receipt["gsc_verified"] is False
    assert "meta tag" in receipt["gsc_pending"]
    assert receipt["gsc_meta_tag"]
    assert all(call[0] != "add_site" for call in google.calls)


def test_verify_gsc_completes_a_deferred_verification(tmp_path):
    google = StubGoogle()
    service = SeoProvisioningService(_config(tmp_path), {}, google=google, dns=StubDNS(), crawlseo=StubCrawlSEO())
    receipt = service.verify_gsc(
        identifier="https://atelier-harmonie.weareheadless.workers.dev",
        property_url="https://atelier-harmonie.weareheadless.workers.dev",
    )
    assert receipt["property"] == "https://atelier-harmonie.weareheadless.workers.dev"
    assert receipt["method"] == "META"
    assert receipt["verified_at"]
    assert ("add_site", "https://atelier-harmonie.weareheadless.workers.dev") in google.calls
