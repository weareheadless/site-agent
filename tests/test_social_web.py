from fastapi.testclient import TestClient

from site_agent.application.approvals import ApprovalService
from site_agent.application.capabilities import CapabilityRegistry, default_capabilities
from site_agent.application.social_posts import SocialPostService
from site_agent.core.memory import Memory
from site_agent.hands.cicero import CiceroOperation
from site_agent.web.server import create_app


class FakeCicero:
    def prepare(self, payload, idempotency_key):
        return CiceroOperation("9", "queued")

    def wait_operation(self, operation_id, **kwargs):
        return CiceroOperation(
            "9", "completed",
            artifact={
                "post_id": "10",
                "content_hash": "sha256:provider",
                "format": "single",
                "caption": "Exact owner caption",
                "preview_assets": [{"name": "preview.png", "media_type": "image/png"}],
            },
        )

    def post(self, post_id):
        return {
            "post_id": 10,
            "content_hash": "sha256:provider",
            "format": "single",
            "caption": "Exact owner caption",
            "preview_assets": [{"name": "preview.png", "media_type": "image/png"}],
        }

    def asset(self, post_id, filename):
        return b"preview", "image/png"


def test_manual_social_prepare_enters_owner_queue_and_proxies_preview(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    capabilities = CapabilityRegistry(default_capabilities(cicero_available=True))
    approvals = ApprovalService(memory, capabilities=capabilities)
    social = SocialPostService(memory, FakeCicero(), approvals=approvals, capabilities=capabilities)
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD"},
        "instance_name": "testsite",
        "site": {"adapter": "github_static"},
        "persona": {"name": "Ada", "voice": "", "audience": "", "taboo": []},
        "admin": {"host": "127.0.0.1", "port": 3011},
    }
    app = create_app(
        {"config": config, "memory": memory, "llm": None, "scheduler": None, "social_post_service": social},
        env={"SITE_AGENT_ADMIN_PASSWORD": "sekret"},
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/login", json={"password": "sekret"}).status_code == 200
        response = client.post(
            "/api/social/posts/prepare",
            headers={"Idempotency-Key": "manual-social"},
            json={
                "goal": "Teach a habit",
                "audience": "Beginners",
                "brief": "A calm practice post",
                "caption": "Exact owner caption",
                "visual_message": "Small steps matter.",
                "format": "single",
                "source_context": [{"title": "Guide", "url": "https://example.com/guide"}],
            },
        )
        assert response.status_code == 202, response.text
        payload = response.json()
        assert payload["artifact"]["kind"] == "social_post"
        assert payload["artifact"]["preview_data"]["provider_content_hash"] == "sha256:provider"
        assert payload["approval"]["status"] == "pending"
        asset_url = payload["artifact"]["preview_data"]["preview_assets"][0]["url"]
        assert client.get(asset_url).content == b"preview"
        assert len(client.get("/api/approvals?status=pending").json()["approvals"]) == 1
    memory.close()
