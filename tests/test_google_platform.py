from site_agent.hands.google_platform import GooglePlatformClient
import datetime
import sys
from types import SimpleNamespace

import pytest


class ExpiringCredentials:
    def __init__(self):
        self.token = None
        self.expiry = datetime.datetime.min
        self.refreshes = 0
        self.fail_refresh = False

    def refresh(self, request):
        if self.fail_refresh:
            raise RuntimeError("refresh failed")
        self.refreshes += 1
        self.token = f"test-token-{self.refreshes}"
        self.expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=1)

    def before_request(self, request, method, url, headers):
        if not self.token or self.expiry <= datetime.datetime.utcnow() + datetime.timedelta(minutes=4):
            self.refresh(request)
        headers["authorization"] = f"Bearer {self.token}"


@pytest.fixture
def credential_factory(monkeypatch):
    created = []

    def from_file(path, *, scopes):
        credentials = ExpiringCredentials()
        created.append((tuple(scopes), credentials))
        return credentials

    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", SimpleNamespace(Request=object))
    monkeypatch.setitem(sys.modules, "google.oauth2", SimpleNamespace(service_account=SimpleNamespace(
        Credentials=SimpleNamespace(from_service_account_file=from_file))))
    return created


def test_google_credentials_refresh_before_cached_token_expires(credential_factory):
    client = GooglePlatformClient("unused-test-key.json")
    assert client.access_token(["scope-a"]) == "test-token-1"
    credentials = credential_factory[0][1]
    assert client.access_token(["scope-a"]) == "test-token-1"
    assert credentials.refreshes == 1
    credentials.expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=1)
    assert client.access_token(["scope-a"]) == "test-token-2"
    assert credentials.refreshes == 2
    assert len(credential_factory) == 1


def test_google_credentials_are_isolated_by_normalized_scope(credential_factory):
    client = GooglePlatformClient("unused-test-key.json")
    client.access_token(["scope-b", "scope-a", "scope-a"])
    client.access_token(["scope-a", "scope-b"])
    client.access_token(["scope-c"])
    assert [scopes for scopes, _ in credential_factory] == [("scope-a", "scope-b"), ("scope-c",)]


def test_google_refresh_failure_never_returns_an_expired_cached_token(credential_factory):
    client = GooglePlatformClient("unused-test-key.json")
    client.access_token(["scope-a"])
    credentials = credential_factory[0][1]
    credentials.expiry = datetime.datetime.min
    credentials.fail_refresh = True
    with pytest.raises(RuntimeError, match="refresh failed"):
        client.access_token(["scope-a"])


def test_concurrent_google_reads_share_one_credential_refresh(credential_factory):
    from concurrent.futures import ThreadPoolExecutor
    client = GooglePlatformClient("unused-test-key.json")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: client.access_token(["scope-a"]), range(24)))
    assert results == ["test-token-1"] * 24
    assert len(credential_factory) == 1
    assert credential_factory[0][1].refreshes == 1


class StubGooglePlatform(GooglePlatformClient):
    def __init__(self, streams):
        self.streams = streams
        self.requests = []

    def _request(self, url, *, scopes, method="GET", body=None):
        self.requests.append((url, method))
        if method == "GET":
            return 200, {"dataStreams": self.streams}
        raise AssertionError("the test must not create a duplicate stream")


def test_ensure_web_stream_reuses_www_stream_for_apex_origin():
    client = StubGooglePlatform([
        {
            "name": "properties/551030734/dataStreams/15478447566",
            "type": "WEB_DATA_STREAM",
            "webStreamData": {
                "defaultUri": "https://www.oceanicvibes.com",
                "measurementId": "G-48GFTHRC1V",
            },
        }
    ])

    receipt = client.ensure_web_stream("551030734", "https://oceanicvibes.com/", display_name="OceanicVibes")

    assert receipt == {
        "data_stream_id": "15478447566",
        "measurement_id": "G-48GFTHRC1V",
        "created": False,
    }
    assert client.requests == [(
        "https://analyticsadmin.googleapis.com/v1beta/properties/551030734/dataStreams",
        "GET",
    )]
