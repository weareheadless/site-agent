import pytest

from site_agent.application.approvals import ApprovalService
from site_agent.application.capabilities import CapabilityRegistry, default_capabilities
from site_agent.application.social_posts import (
    SocialIdempotencyConflict,
    SocialPostBrief,
    SocialPostService,
    approval_hash,
)
from site_agent.core.contracts import ArtifactKind
from site_agent.core.memory import Memory
from site_agent.hands.cicero import (
    CiceroClient,
    CiceroClientError,
    CiceroOperation,
    CiceroResponse,
)


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, path, headers, body=None):
        self.calls.append((method, path, headers, body))
        if method == "POST":
            return CiceroResponse(202, {"Content-Type": "application/json"}, b'{"operation_id":"7","status":"queued"}')
        if path == "/api/v1/operations/7":
            return CiceroResponse(200, {}, b'{"operation_id":"7","status":"completed","artifact":{"post_id": "8", "content_hash":"sha256:provider", "format":"single", "caption":"Exact"}}')
        if path == "/api/v1/posts/8/assets/preview.png":
            return CiceroResponse(200, {"Content-Type": "image/png"}, b"png")
        if path == "/api/v1/posts/8":
            return CiceroResponse(200, {}, b'{"post_id":8,"content_hash":"sha256:provider","format":"single","caption":"Exact","preview_assets":[{"name":"preview.png","media_type":"image/png"}]}')
        if path == "/api/v1/media":
            return CiceroResponse(200, {}, b'[{"name":"preview.png","media_type":"image/png"}]')
        return CiceroResponse(404, {}, b'{"detail":"not found"}')


def _brief():
    return SocialPostBrief(
        goal="Teach a habit",
        audience="Beginners",
        brief="A calm practice post",
        caption="Exact",
        visual_message="Small steps matter.",
        format="single",
        source_context=({"title": "Guide", "url": "https://example.com/guide"},),
    )


def test_cicero_client_auth_headers_idempotency_and_asset_validation():
    transport = FakeTransport()
    client = CiceroClient("https://cicero.test", "secret-token", transport=transport)
    operation = client.prepare(_brief().to_payload(), "key-1")
    assert operation.operation_id == "7"
    assert transport.calls[0][2]["Authorization"] == "Bearer secret-token"
    assert transport.calls[0][2]["Idempotency-Key"] == "key-1"
    assert client.wait_operation("7", poll_interval_seconds=0.05, timeout_seconds=1).status == "completed"
    assert client.media()[0]["name"] == "preview.png"
    data, media_type = client.asset("8", "preview.png")
    assert data == b"png" and media_type == "image/png"
    with pytest.raises(CiceroClientError):
        client.asset("8", "../secret.txt")


def test_cicero_client_translates_http_errors_without_response_secrets():
    class ErrorTransport:
        def request(self, method, path, headers, body=None):
            return CiceroResponse(409, {}, b'{"detail":"Bearer secret-token cannot be reused"}')

    client = CiceroClient("https://cicero.test", "secret-token", transport=ErrorTransport())
    with pytest.raises(CiceroClientError) as exc:
        client.prepare({}, "key")
    assert "secret-token" not in str(exc.value)
    assert exc.value.status_code == 409


def test_social_preparation_creates_one_artifact_and_approval_and_reuses_it(tmp_path):
    class FakeCicero:
        def __init__(self):
            self.prepare_calls = 0
            self.wait_calls = 0

        def prepare(self, payload, idempotency_key):
            self.prepare_calls += 1
            return CiceroOperation("7", "queued")

        def wait_operation(self, operation_id, **kwargs):
            self.wait_calls += 1
            return CiceroOperation(
                "7",
                "completed",
                artifact={
                    "post_id": "8",
                    "content_hash": "sha256:provider",
                    "format": "single",
                    "caption": "Exact",
                    "preview_assets": [{"name": "preview.png", "media_type": "image/png"}],
                },
            )

        def post(self, post_id):
            return {
                "post_id": 8,
                "content_hash": "sha256:provider",
                "format": "single",
                "caption": "Exact",
                "preview_assets": [{"name": "preview.png", "media_type": "image/png"}],
            }

        def asset(self, post_id, filename):
            return b"png", "image/png"

    memory = Memory(tmp_path / "memory.db")
    cicero = FakeCicero()
    capabilities = CapabilityRegistry(default_capabilities(cicero_available=True))
    approvals = ApprovalService(memory, capabilities=capabilities)
    service = SocialPostService(memory, cicero, approvals=approvals, capabilities=capabilities)
    first = service.prepare(_brief(), idempotency_key="stable-key")
    second = service.prepare(_brief(), idempotency_key="stable-key")

    assert first.artifact.artifact_id == second.artifact.artifact_id
    assert first.approval.approval_id == second.approval.approval_id
    assert first.action.id == second.action.id
    assert first.artifact.kind is ArtifactKind.SOCIAL_POST
    assert first.artifact.preview_data["provider_content_hash"] == "sha256:provider"
    assert first.artifact.content_hash == approval_hash("cicero", "8", "sha256:provider")
    assert len(memory.conn.execute("SELECT id FROM artifacts").fetchall()) == 1
    assert len(memory.conn.execute("SELECT id FROM approval_requests").fetchall()) == 1
    assert cicero.prepare_calls == 1
    assert cicero.wait_calls == 1
    memory.close()


def test_social_preparation_rejects_conflicting_idempotency_key(tmp_path):
    class FakeCicero:
        def prepare(self, *args, **kwargs):
            return CiceroOperation("7", "queued")

        def wait_operation(self, *args, **kwargs):
            return CiceroOperation(
                "7", "completed",
                artifact={
                    "post_id": "8", "content_hash": "sha256:provider", "format": "single",
                    "caption": "Exact", "preview_assets": [{"name": "preview.png", "media_type": "image/png"}],
                },
            )

        def post(self, post_id):
            return {
                "post_id": 8, "content_hash": "sha256:provider", "format": "single",
                "caption": "Exact", "preview_assets": [{"name": "preview.png", "media_type": "image/png"}],
            }

    memory = Memory(tmp_path / "memory.db")
    service = SocialPostService(memory, FakeCicero())
    service.prepare(_brief(), idempotency_key="same")
    changed = SocialPostBrief(
        goal="Teach a habit", audience="Beginners", brief="A different post", caption="Exact",
        visual_message="Different message",
    )
    with pytest.raises(SocialIdempotencyConflict):
        service.prepare(changed, idempotency_key="same")
    memory.close()
