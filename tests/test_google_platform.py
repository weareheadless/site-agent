from site_agent.hands.google_platform import GooglePlatformClient


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
