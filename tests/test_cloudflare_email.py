from urllib.parse import parse_qs, urlsplit

import site_agent.hands.cloudflare_email as cloudflare_email
from site_agent.hands.cloudflare_email import CloudflareEmailClient


def test_sending_dns_reads_every_page():
    class PagedClient(CloudflareEmailClient):
        def __init__(self):
            self.paths = []

        def request(self, method, path, body=None):
            self.paths.append(path)
            page = int(parse_qs(urlsplit(path).query)["page"][0])
            return {
                "result": [{"type": "TXT", "name": f"selector-{page}.example.com", "content": f"key-{page}"}],
                "result_info": {"total_pages": 2},
            }

    client = PagedClient()

    records = client.sending_dns("zone-id", "sender-id")

    assert [record["content"] for record in records] == ["key-1", "key-2"]
    assert len(client.paths) == 2
    assert all(path.startswith("/zones/zone-id/email/sending/subdomains/sender-id/dns?") for path in client.paths)


def test_zone_lookup_resolves_the_most_specific_managed_parent_zone():
    class ZoneClient(CloudflareEmailClient):
        def __init__(self):
            self.paths = []

        def request(self, method, path, body=None):
            self.paths.append(path)
            if path.startswith("/zones?name="):
                return {"result": []}
            return {
                "result": [
                    {"id": "broad-zone", "name": "example.com", "status": "active"},
                    {"id": "specific-zone", "name": "shop.example.com", "status": "active"},
                ],
                "result_info": {"total_pages": 1},
            }

    client = ZoneClient()

    zone = client.zone("www.shop.example.com")

    assert zone["id"] == "specific-zone"
    assert len(client.paths) == 2


def test_cloudflare_email_client_routes_dns_and_email_calls_to_separate_tokens(monkeypatch):
    tokens = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            return b'{"success":true,"result":{}}'

    def urlopen(request, timeout):
        tokens.append(request.get_header("Authorization"))
        return Response()

    monkeypatch.setattr(cloudflare_email.urllib.request, "urlopen", urlopen)
    client = CloudflareEmailClient("email-secret", "dns-secret")

    client.request("GET", "/zones/zone-id/dns_records")
    client.request("GET", "/zones/zone-id/email/routing")

    assert tokens == ["Bearer dns-secret", "Bearer email-secret"]
