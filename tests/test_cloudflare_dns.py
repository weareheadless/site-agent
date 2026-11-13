from urllib.parse import parse_qs, urlsplit

from site_agent.hands.cloudflare_dns import CloudflareDNSClient, CloudflareDNSError


def test_zone_lookup_chooses_the_active_zone_when_a_name_exists_twice():
    """A retired zone must not make the live one unreachable.

    `astridrincon.com` exists in two accounts: the platform's active zone and
    one left behind as `moved`. The API does not promise an order, so the
    lookup has to choose by state, not by position.
    """

    class DuplicateClient(CloudflareDNSClient):
        def __init__(self, results):
            super().__init__("token")
            self.results = results
            self.paths = []

        def _request(self, path, *, method="GET", body=None):
            self.paths.append(path)
            return {"success": True, "result": self.results}

    moved = {"id": "moved-zone", "name": "example.com", "status": "moved"}
    active = {"id": "live-zone", "name": "example.com", "status": "active"}

    assert DuplicateClient([moved, active]).zone_id("example.com") == "live-zone"
    assert DuplicateClient([active, moved]).zone_id("example.com") == "live-zone"
    # A single zone is used whatever its state; the caller reports the state.
    assert DuplicateClient([moved]).zone_id("example.com") == "moved-zone"


def test_two_active_zones_are_reported_as_ambiguous():
    class DuplicateClient(CloudflareDNSClient):
        def _request(self, path, *, method="GET", body=None):
            return {
                "success": True,
                "result": [
                    {"id": "one", "name": "example.com", "status": "active"},
                    {"id": "two", "name": "example.com", "status": "active"},
                ],
            }

    try:
        DuplicateClient("token").zone_id("example.com")
    except CloudflareDNSError as exc:
        assert "ambiguous" in str(exc)
    else:  # pragma: no cover - the assertion is the point
        raise AssertionError("two active zones must not be resolved by position")


def test_zone_lookup_reads_every_duplicate_not_just_the_first_page_entry():
    class Client(CloudflareDNSClient):
        def _request(self, path, *, method="GET", body=None):
            query = parse_qs(urlsplit(path).query)
            assert query["per_page"] == ["50"]
            return {"success": True, "result": [
                {"id": "live", "name": "example.com", "status": "active"},
            ]}

    assert Client("token").zone_id("example.com") == "live"
