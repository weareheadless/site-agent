import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from site_agent.hands.crawlseo_migration_control import (
    CrawlSEOMigrationControlClient, CrawlSEOMigrationControlError, _NoRedirect,
)


def test_receipt_read_uses_configured_mount_and_exact_identity_without_returning_token():
    client = CrawlSEOMigrationControlClient(
        "https://crawlseo.example/crawlseo/api/internal/projects/provision", "host-secret")
    response = io.BytesIO(json.dumps({"id": "receipt-1", "snapshot": {}}).encode())
    response.status = 200
    def read(request, timeout):
        assert request.full_url == "https://crawlseo.example/crawlseo/api/internal/budget-imports?receiptId=receipt-1"
        assert request.get_header("Authorization") == "Bearer host-secret"
        assert request.get_header("User-agent") == "HelloAda/migration-control"
        assert timeout == 20
        return response
    opener = SimpleNamespace(open=read)
    with patch("site_agent.hands.crawlseo_migration_control.build_opener", return_value=opener):
        assert client.budget_import_receipt("receipt-1")["id"] == "receipt-1"
    assert "host-secret" not in repr(client)


@pytest.mark.parametrize("url", [
    "http://crawlseo.example/api/internal/projects/provision",
    "https://user:pass@crawlseo.example/api/internal/projects/provision",
    "https://crawlseo.example/a/../api/internal/projects/provision",
    "https://crawlseo.example/a%2fb/api/internal/projects/provision",
    "https://crawlseo.example/api/internal/projects/provision?token=x",
    "https://crawlseo.example:99999/api/internal/projects/provision",
])
def test_control_client_rejects_unsafe_profile_endpoints(url):
    with pytest.raises(CrawlSEOMigrationControlError):
        CrawlSEOMigrationControlClient(url, "host-secret")


def test_receipt_lookup_rejects_redirects_and_wrong_receipt_identity():
    with pytest.raises(CrawlSEOMigrationControlError, match="redirects"):
        _NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://other.example")
    response = io.BytesIO(b'{"id":"other"}')
    response.status = 200
    opener = SimpleNamespace(open=lambda request, timeout: response)
    client = CrawlSEOMigrationControlClient("https://crawlseo.example/api/internal/projects/provision", "secret")
    with patch("site_agent.hands.crawlseo_migration_control.build_opener", return_value=opener):
        with pytest.raises(CrawlSEOMigrationControlError, match="different identity"):
            client.budget_import_receipt("receipt-1")
