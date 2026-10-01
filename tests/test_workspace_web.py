from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from site_agent.application.workspace import (
    ChatService,
    DesignBuildHandoff,
    Journey,
    Tenant,
    TenantRegistry,
    _journey_for_config,
)
from site_agent.application.intake_coordinator import IntakeCoordinator
from site_agent.core.memory import Memory
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.config import ConfigError
from site_agent.hands.payload_gateway import (
    PayloadContract,
    PayloadGatewayClient,
    PayloadGatewayError,
    PayloadGatewaySiteAdapter,
    PayloadMediaService,
)
from site_agent.hands.base import ADAPTERS, AdapterError
from site_agent.web.workspace import register_workspace_routes


def test_workspace_bridge_requires_a_server_token(tmp_path):
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=ChatService(Memory(tmp_path / "memory.db"), object()),
    )

    with TestClient(app) as client:
        assert client.post("/api/workspace/chat", json={"message": "hello"}).status_code == 401
        assert client.post(
            "/api/workspace/chat",
            headers={"Authorization": "Bearer wrong"},
            json={"message": "hello"},
        ).status_code == 401


@pytest.mark.parametrize("api_key", ["workspace_api"])
def test_shared_host_credentials_are_inherited_by_tenants(tmp_path, api_key):
    tenant_config = tmp_path / "tenant.yaml"
    tenant_config.write_text(
        f"instance_name: demo\ndata_dir: {tmp_path / 'data'}\n",
        encoding="utf-8",
    )
    registry = TenantRegistry.from_config(
        {
            "credentials": {
                "github": {"ssh_key_path": "/host/github.key"},
                "cloudflare": {"env_file": "/host/cloudflare.env", "api_token_env": "CF_TOKEN"},
            },
            api_key: {
                "enabled": True,
                "tenants": {
                    "demo": {
                        "config_path": str(tenant_config),
                        "api_token_env": "WORKSPACE_DEMO_TOKEN",
                    }
                },
            },
        },
        {"WORKSPACE_DEMO_TOKEN": "bridge-secret", "CF_TOKEN": "cloudflare-secret"},
    )
    try:
        credentials = registry.tenants["demo"].config["credentials"]
        assert credentials["github"]["ssh_key_path"] == "/host/github.key"
        assert credentials["cloudflare"]["api_token_env"] == "CF_TOKEN"
    finally:
        registry.close()


def test_shared_registry_rejects_payload_token_name_drift(tmp_path):
    tenant_config = tmp_path / "tenant.yaml"
    tenant_config.write_text(
        f"""instance_name: demo
data_dir: {tmp_path / 'data'}
site:
  payload:
    enabled: true
    url: https://demo.example.test
    token_env: LEGACY_DEMO_TOKEN
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="payload.token_env must match"):
        TenantRegistry.from_config(
            {
                "workspace_api": {
                    "enabled": True,
                    "tenants": {
                        "demo": {
                            "config_path": str(tenant_config),
                            "api_token_env": "PROVISIONED_DEMO_TOKEN",
                        }
                    },
                }
            },
            {
                "PROVISIONED_DEMO_TOKEN": "bridge-secret",
                "LEGACY_DEMO_TOKEN": "legacy-secret",
            },
        )


def test_workspace_bridge_enqueues_contextual_chat(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    app = FastAPI()
    service = ChatService(memory, object())
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/workspace/chat",
            headers={"Authorization": "Bearer workspace-secret"},
            json={
                "message": "Change the heading",
                "context": {
                    "site": "workspace-harmonie",
                    "route": "/shop",
                    "collection": "products",
                    "document": "product-source-id",
                    "document_id": "42",
                    "state": "draft",
                    "mode": "workspace",
                    "target": {
                        "mode": "workspace",
                        "scope": "page",
                        "route": {"path": "/shop", "kind": "page", "sourceId": "route-42"},
                        "preview": {"state": "draft", "url": "https://workspace.example/workspace-preview/shop"},
                        "payload": {"collection": "products", "id": "42", "sourceId": "product-source-id"},
                    },
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"]
        job = client.get(
            f"/api/workspace/chat/jobs/{payload['job_id']}",
            headers={"Authorization": "Bearer workspace-secret"},
        )
        assert job.status_code == 200
        stored = memory.get_chat_job(payload["job_id"])
        assert '"route": "/shop"' in stored["message"]
        assert '"collection": "products"' in stored["message"]
        assert '"document_id": "42"' in stored["message"]
        assert '"target"' in stored["message"]
        assert '"scope": "page"' in stored["message"]

    memory.close()


def test_existing_site_snapshot_reads_selected_page_and_navigation(tmp_path):
    class _Payload:
        def read(self, collection, *, identifier, identifier_kind, draft):
            assert (collection, identifier, identifier_kind, draft) == ("pages", "home-source", "sourceId", True)
            return {
                "sourceId": "home-source",
                "slug": "home",
                "title": "Workspace Harmonie",
                "content": {"heading": "Une maison douce", "body": "Book a consultation."},
            }

        def read_global(self, slug, *, draft):
            assert (slug, draft) == ("navigation", True)
            return {"items": [{"label": "Menu", "path": "/menu"}]}

    memory = Memory(tmp_path / "memory.db")
    coordinator = IntakeCoordinator(
        memory,
        config={"intake": {"database_only": True}},
        llm=None,
        payload_client=_Payload(),
    )
    snapshot = coordinator._existing_site_snapshot({
        "route": "/",
        "collection": "pages",
        "target": {"route": {"path": "/", "kind": "page", "sourceId": "home-source"}},
    })

    assert snapshot["status"] == "existing_live_website"
    assert snapshot["page"]["title"] == "Workspace Harmonie"
    assert snapshot["navigation"]["items"][0]["label"] == "Menu"
    memory.close()


def test_workspace_bridge_reports_workspace_phase_without_intake(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=ChatService(memory, object()),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/workspace/chat/status",
            headers={"Authorization": "Bearer workspace-secret"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "workspace"
    assert response.json()["website_context_enabled"] is True
    memory.close()


def test_workspace_bridge_reports_active_chat_job_for_resume(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("A working conversation")
    job_id = memory.enqueue_chat_job(conversation_id, "Keep working in the background")
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=ChatService(memory, object()),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/workspace/chat/status?conversation_id={conversation_id}",
            headers={"Authorization": "Bearer workspace-secret"},
        )

    assert response.status_code == 200
    active_job = response.json()["active_job"]
    assert active_job["id"] == job_id
    assert active_job["conversation_id"] == conversation_id
    assert active_job["status"] == "queued"
    assert active_job["created_ts"]
    assert active_job["updated_ts"]
    memory.close()


def test_workspace_bridge_exposes_durable_conversation_history(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("A saved conversation")
    memory.add_message(conversation_id, "user", "Keep this history")
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=ChatService(memory, object()),
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer workspace-secret"}
        listed = client.get("/api/workspace/chat/conversations", headers=headers)
        detail = client.get(f"/api/workspace/chat/conversations/{conversation_id}", headers=headers)

    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["id"] == conversation_id
    assert detail.status_code == 200
    assert detail.json()["messages"][0]["text"] == "Keep this history"
    memory.close()


def test_workspace_bridge_exposes_bounded_activity_history(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("A saved conversation")
    memory.create_design_run(
        run_id="run-history",
        mode="local_experiment",
        intake_json={"business": {"name": "History"}},
    )
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=ChatService(memory, object()),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/workspace/history?limit=1",
            headers={"Authorization": "Bearer workspace-secret"},
        )

    assert response.status_code == 200
    assert response.json()["tenant"] == "legacy"
    assert response.json()["conversations"][0]["id"] == conversation_id
    assert len(response.json()["design_runs"]) == 1
    memory.close()


def test_intake_requires_explicit_owner_acceptance(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    intake = IntakeCoordinator(
        memory,
        config={"intake": {"database_only": True, "research": {"enabled": False}}},
        llm=object(),
    )
    site_intake = SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
            "location": "North Shore",
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["index.html"]},
    })
    session = intake.intake_service.create_session(draft=DesignIntakeDraft.from_site_intake(site_intake))
    before = intake.status(session["conversation_id"])
    accepted = intake.confirm(
        session["conversation_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        confirmation_text="I accept this working brief.",
        idempotency_key="accept-workspace-brief",
    )

    assert before["confirmed"] is False
    assert before["readiness"]["state"] == "ready_to_build"
    assert accepted["confirmed"] is True
    assert intake.needs_intake(session["conversation_id"]) is False
    memory.close()


def test_payload_gateway_client_is_server_configured_and_schema_bounded():
    client = PayloadGatewayClient.from_config(
        {
            "site": {
                "payload": {
                    "enabled": True,
                    "url": "https://workspace.example.test",
                    "api_prefix": "/v1/content",
                    "contract": {
                        "collections": {"pages": ["sourceId", "title"]},
                        "globals": {"navigation": ["items"]},
                        "media_fields": ["alt"],
                    },
                }
            },
            "env": {},
        },
        {"PAYLOAD_GATEWAY_TOKEN": "workspace-secret"},
    )
    assert client is not None
    assert client.base_url == "https://workspace.example.test"
    assert client.gateway_prefix == "/v1/content"

    with pytest.raises(PayloadGatewayError, match="outside the pages draft contract"):
        client._data("pages", {"password": "never"})
    with pytest.raises(PayloadGatewayError, match="outside the navigation global contract"):
        client._global_data("navigation", {"password": "never"})


def test_payload_gateway_client_uses_declarative_editable_field_gateway(monkeypatch):
    client = PayloadGatewayClient(
        "https://workspace.example.test",
        "workspace-secret",
        PayloadContract({"pages": frozenset({"title"})}, {}, frozenset()),
        gateway_prefix="/api/workspace",
    )
    requests = []

    def request(_self, method, path, *, query=None, payload=None):
        requests.append((method, path, query, payload))
        return {"fields": [], "valid": True}

    monkeypatch.setattr(PayloadGatewayClient, "_request", request)

    client.inspect_editable_fields("pages", identifier="home")
    client.define_editable_field(
        "pages",
        identifier="home",
        key="home.hero.heading",
        field_type="text",
        label="Hero heading",
        value="Une maison douce",
    )
    client.set_editable_field(
        "pages",
        identifier="home",
        key="home.hero.heading",
        value="Une maison joyeuse",
        expected_value="Une maison douce",
    )
    client.migrate_editable_fields(
        "pages",
        identifier="home",
        fields=[{
            "key": "home.diy.body",
            "type": "richText",
            "label": "DIY introduction",
            "value": "Une introduction.",
        }],
    )
    client.validate_editable_fields("pages", identifier="home")

    assert requests[0][0:2] == ("GET", "/api/workspace/editable-fields")
    assert requests[0][2]["sourceId"] == "home"
    assert requests[1][3]["operation"] == "define"
    assert requests[1][3]["key"] == "home.hero.heading"
    assert requests[2][3]["operation"] == "set_value"
    assert requests[2][3]["expected_value"] == "Une maison douce"
    assert requests[3][3]["operation"] == "migrate"
    assert requests[3][3]["fields"][0]["key"] == "home.diy.body"
    assert requests[4][3]["operation"] == "validate"


def test_payload_gateway_contract_is_instance_configured_and_adapter_is_registered():
    client = PayloadGatewayClient(
        "https://example.test",
        "secret",
        PayloadContract({"articles": frozenset({"headline"})}, {}, frozenset()),
    )

    assert client._collection("articles") == "articles"
    with pytest.raises(PayloadGatewayError, match="unsupported Payload collection"):
        client._collection("pages")
    assert ADAPTERS["payload_gateway"] is PayloadGatewaySiteAdapter


def test_payload_gateway_site_adapter_reads_source_without_granting_write_access():
    class ReadAdapter:
        def __init__(self):
            self.paths = []

        def get_file(self, path, branch=None):
            assert branch == "preview"
            self.paths.append(path)
            return "sha-1", f"source:{path}".encode()

        def list_files(self, branch=None):
            assert branch == "preview"
            return ["src/app/(frontend)/styles.css"]

    payload = object()
    reader = ReadAdapter()
    adapter = PayloadGatewaySiteAdapter(
        {"site": {"content_path": "content.json", "payload": {"enabled": True}}},
        payload_client=payload,
        read_adapter=reader,
    )

    assert adapter.get_file("content.json", branch="preview") == (None, None)
    assert adapter.get_file("src/app/(frontend)/styles.css", branch="preview") == (
        "sha-1",
        b"source:src/app/(frontend)/styles.css",
    )
    assert reader.paths == ["src/app/(frontend)/styles.css"]
    assert adapter.list_files(branch="preview") == ["src/app/(frontend)/styles.css"]
    with pytest.raises(AdapterError, match="file commits are disabled"):
        adapter.commit_file("src/app/(frontend)/styles.css", b"new", "no write")


def test_shared_api_scopes_jobs_to_the_token_selected_tenant(tmp_path):
    class Tenant:
        def __init__(self, tenant_id, token):
            self.tenant_id = tenant_id
            self.api_token = token
            self.memory = Memory(tmp_path / tenant_id / "memory.db")
            self.context = {"llm": object()}

    class Registry:
        def __init__(self):
            self.tenants = {"workspace-one": Tenant("workspace-one", "one-token")}

        def for_token(self, token):
            return next((tenant for tenant in self.tenants.values() if tenant.api_token == token), None)

    registry = Registry()
    app = FastAPI()
    service = ChatService(registry=registry)
    register_workspace_routes(
        app,
        config={},
        env={},
        service=service,
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        denied = client.post("/v1/workspace/chat", json={"message": "hello"})
        assert denied.status_code == 401
        accepted = client.post(
            "/v1/workspace/chat",
            headers={"Authorization": "Bearer one-token"},
            json={"message": "hello", "context": {"route": "/"}},
        )
        assert accepted.status_code == 200
        job_id = accepted.json()["job_id"]
        assert client.get(
            f"/v1/workspace/chat/jobs/{job_id}",
            headers={"Authorization": "Bearer one-token"},
        ).status_code == 200

    stored = registry.tenants["workspace-one"].memory.get_chat_job(job_id)
    assert '"site": "workspace-one"' in stored["message"]
    registry.tenants["workspace-one"].memory.close()


def test_shared_api_routes_new_tenant_conversations_through_database_intake(tmp_path):
    class Intake:
        def __init__(self):
            self.calls = []

        def needs_intake(self, conversation_id):
            self.calls.append(("needs", conversation_id))
            return True

        def send_message(self, message, *, conversation_id=None, idempotency_key=None):
            self.calls.append(("send", message, conversation_id, idempotency_key))
            return {
                "job_id": 44,
                "conversation_id": conversation_id or 9,
                "session_id": "intake-test",
            }

    class Tenant:
        def __init__(self):
            self.tenant_id = "workspace-intake"
            self.api_token = "intake-token"
            self.memory = Memory(tmp_path / "workspace-intake" / "memory.db")
            self.context = {"llm": object(), "intake_coordinator": Intake()}

    tenant = Tenant()

    class Registry:
        tenants = {"workspace-intake": tenant}

        @staticmethod
        def for_token(token):
            return tenant if token == tenant.api_token else None

    app = FastAPI()
    registry = Registry()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workspace/chat",
            headers={"Authorization": "Bearer intake-token"},
            json={"message": "Je veux créer une page", "idempotency_key": "turn-1"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": 44,
        "conversation_id": 9,
        "intake_session_id": "intake-test",
        "mode": "intake",
    }
    assert tenant.context["intake_coordinator"].calls == [
        ("needs", None),
        ("send", "Je veux créer une page", None, "turn-1"),
    ]
    tenant.memory.close()


def test_shared_api_stamps_existing_site_journey_into_intake_context(tmp_path):
    class Intake:
        def __init__(self):
            self.contexts = []

        def needs_intake(self, conversation_id):
            return True

        def send_message(self, message, *, conversation_id=None, owner_context=None, idempotency_key=None):
            self.contexts.append(dict(owner_context or {}))
            return {"job_id": 45, "conversation_id": conversation_id or 10, "session_id": "intake-existing"}

    class Tenant:
        def __init__(self):
            self.tenant_id = "workspace-existing"
            self.api_token = "existing-token"
            self.memory = Memory(tmp_path / "workspace-existing" / "memory.db")
            self.context = {
                "llm": object(),
                "intake_coordinator": Intake(),
                "journey": Journey(website_present=True, incubation_needed=True),
            }

    tenant = Tenant()

    class Registry:
        tenants = {"workspace-existing": tenant}

        @staticmethod
        def for_token(token):
            return tenant if token == tenant.api_token else None

    app = FastAPI()
    registry = Registry()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workspace/chat",
            headers={"Authorization": "Bearer existing-token"},
            json={"message": "Continue the research."},
        )

    assert response.status_code == 200
    assert response.json()["phase"] == "incubation"
    assert response.json()["website_present"] is True
    assert tenant.context["intake_coordinator"].contexts == [{
        "website_present": True,
        "incubation_needed": True,
        "journey": "incubation",
    }]
    tenant.memory.close()


def test_workspace_journey_separates_existing_site_incubation_from_new_site_intake():
    existing = _journey_for_config({
        "site": {"payload": {"enabled": True}},
        "intake": {"enabled": True},
    })
    new_site = _journey_for_config({
        "site": {"adapter": "github_static"},
    })

    assert existing == Journey(website_present=True, incubation_needed=True)
    assert existing.initial_phase == "incubation"
    assert new_site == Journey(website_present=False, incubation_needed=False)
    assert new_site.initial_phase == "intake"

    observed_site = _journey_for_config({
        "site": {"adapter": "github_static"},
        "customer_profile": {"business": {"observed_site_settings": {"website_url": "https://example.test"}}},
        "intake": {"enabled": True},
    })
    forced_no_site = _journey_for_config({
        "ada_journey": {"website_present": False, "incubation_needed": True},
        "intake": {"enabled": True},
    })
    assert observed_site == Journey(website_present=True, incubation_needed=True)
    assert forced_no_site == Journey(website_present=False, incubation_needed=False)


def test_no_site_build_handoff_uses_the_normal_design_worker():
    class Design:
        def __init__(self):
            self.calls = []
            self.run = {"run_id": "run-first-site", "status": "queued"}

        def resolve_base_sha(self):
            self.calls.append(("resolve_base_sha",))
            return "base-sha"

        def create_run(self, intake, **kwargs):
            assert isinstance(intake, SiteIntake)
            self.calls.append(("create_run", kwargs))
            return self.run

        def capture_context_snapshot(self, run_id, **kwargs):
            self.calls.append(("capture_context_snapshot", run_id, kwargs))

        def prepare_initial_request(self, run_id):
            self.calls.append(("prepare_initial_request", run_id))
            return "typed-build-request"

        def build_target_for_run(self, run_id):
            self.calls.append(("build_target_for_run", run_id))
            return {"branch": "ada-design"}

        def queue_build(self, run_id, request, target):
            self.calls.append(("queue_build", run_id, request, target))

        def get_run(self, run_id):
            assert run_id == "run-first-site"
            return self.run

    class Executor:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, run_id):
            self.enqueued.append(run_id)

    design = Design()
    executor = Executor()
    handoff = DesignBuildHandoff({"design_service": design, "design_executor": executor})
    intake = SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
            "location": "North Shore",
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["index.html"]},
    })

    result = handoff.submit(
        "Build the first website.",
        intake.to_dict(),
        run_id="run-first-site",
        conversation_id=12,
        source_message_id=13,
        intake_session_id="intake-first-site",
        intake_revision_id=14,
        context_extra={"journey": "full_intake"},
    )

    assert result == {"run_id": "run-first-site", "status": "queued"}
    assert executor.enqueued == ["run-first-site"]
    assert any(call[0] == "queue_build" for call in design.calls)


def test_shared_api_persists_conversation_image_attachments(tmp_path):
    class Media:
        def resolve_attachments(self, asset_ids):
            assert asset_ids == [7]
            return [{"asset_id": 7, "position": 0}]

    memory = Memory(tmp_path / "workspace-attachments" / "memory.db")
    tenant = Tenant(
        tenant_id="workspace-attachments",
        config={},
        memory=memory,
        runtime=None,
        context={
            "llm": object(),
            "media_service": Media(),
            "journey": Journey(website_present=True, incubation_needed=True),
        },
        api_token="attachments-token",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workspace/chat",
            headers={"Authorization": "Bearer attachments-token"},
            json={"message": "Use this reference", "attachments": [{"asset_id": 7}]},
        )

    assert response.status_code == 200
    job = memory.get_chat_job(response.json()["job_id"])
    assert job["conversation_id"] == response.json()["conversation_id"]
    assert memory.get_messages(job["conversation_id"])[-1]["attachments"] == [{"asset_id": 7, "position": 0}]
    assert response.json()["website_present"] is True
    assert response.json()["incubation_needed"] is True
    memory.close()


def test_payload_media_service_resolves_chat_attachments():
    class Payload:
        base_url = "https://workspace.example.test"

        def read_media(self, identifier, *, identifier_kind, draft):
            assert identifier == "7"
            assert identifier_kind == "id"
            assert draft is True
            return {
                "id": 7,
                "filename": "lamp.jpg",
                "mimeType": "image/jpeg",
                "url": "/media/lamp.jpg",
                "width": 800,
                "height": 600,
                "alt": "Woven lamp",
                "analysisStatus": "ready",
                "analysisError": "",
                "tags": [{"value": "lamp"}],
            }

    service = PayloadMediaService(Payload())
    resolved = service.resolve_attachments([7])
    assert resolved[0]["asset_id"] == 7
    assert resolved[0]["url"] == "https://workspace.example.test/media/lamp.jpg"
    assert resolved[0]["alt_text"] == "Woven lamp"
    assert resolved[0]["analysis_error"] is None


def test_no_site_confirmation_requires_an_explicit_first_page_action(tmp_path):
    class Intake:
        def confirm(self, conversation_id, **kwargs):
            assert conversation_id == 12
            assert kwargs["revision"] == 2
            return {
                "session_id": "intake-new-site",
                "conversation_id": 12,
                "revision": 2,
                "confirmed_revision": 2,
                "confirmed_revision_id": 22,
                "confirmed": True,
            }

        def status(self, conversation_id):
            assert conversation_id == 12
            return {
                "session_id": "intake-new-site",
                "conversation_id": 12,
                "confirmed_revision": 2,
                "confirmed_revision_id": 22,
                "confirmed": True,
            }

    class DesignIntake:
        lab_service = object()

        def build(self, session_id, **kwargs):
            assert session_id == "intake-new-site"
            assert kwargs["confirmed_revision"] == 22
            return {"run": {"run_id": "design-first-site", "status": "building"}}

    memory = Memory(tmp_path / "workspace-new-site" / "memory.db")
    tenant = Tenant(
        tenant_id="workspace-new-site",
        config={},
        memory=memory,
        runtime=None,
        context={
            "llm": object(),
            "intake_coordinator": Intake(),
            "design_intake_service": DesignIntake(),
            "journey": Journey(website_present=False, incubation_needed=False),
        },
        api_token="new-site-token",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workspace/chat/intake/confirm",
            headers={"Authorization": "Bearer new-site-token"},
            json={"conversation_id": 12, "revision": 2, "draft_hash": "abc"},
        )
        start_response = client.post(
            "/v1/workspace/chat/design/start",
            headers={"Authorization": "Bearer new-site-token"},
            json={"conversation_id": 12, "confirmed_revision": 22},
        )

    assert response.status_code == 200
    assert "build" not in response.json()
    assert start_response.status_code == 200
    assert start_response.json()["run"]["run_id"] == "design-first-site"
    memory.close()


def test_shared_api_exposes_media_library_and_analysis(tmp_path):
    class Payload:
        base_url = "https://workspace.example.test"

        def __init__(self):
            self.updated = []

        def list_media(self, *, draft, limit):
            assert draft is True
            assert limit == 12
            return [{"id": "media-1", "filename": "lamp.jpg"}]

        def read_media(self, identifier, *, identifier_kind, draft):
            assert identifier == "media-1"
            assert identifier_kind == "id"
            assert draft is True
            return {"id": identifier, "filename": "lamp.jpg", "url": "/media/lamp.jpg"}

        def update_media(self, identifier, data):
            self.updated.append((identifier, data))
            return {"id": identifier, **data}

    class Analyzer:
        provider_id = "test-vision"
        model = "test-model"

        def analyze_images(self, image_urls, instruction):
            assert image_urls == ["https://workspace.example.test/media/lamp.jpg"]
            assert "grounded observations" in instruction
            return {
                "schema_version": 1,
                "subject": "A woven lamp",
                "description": "A woven lamp in warm light.",
                "alt_text": "Woven lamp in warm light",
                "tags": ["lamp", "woven"],
                "dominant_colors": ["amber"],
                "suggested_uses": ["product detail"],
                "quality_notes": ["well lit"],
                "ocr_text": "",
                "knowledge_relevant": False,
                "proposed_knowledge_markdown": "",
            }

    memory = Memory(tmp_path / "workspace-media" / "memory.db")
    payload = Payload()
    tenant = Tenant(
        tenant_id="workspace-media",
        config={},
        memory=memory,
        runtime=None,
        context={"llm": object(), "payload_gateway": payload, "media_analyzer": Analyzer()},
        api_token="media-token",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer media-token"}
        listed = client.get("/v1/workspace/media?limit=12", headers=headers)
        analyzed = client.post(
            "/v1/workspace/media/analyze",
            headers=headers,
            json={"media_id": "media-1", "focus": "texture"},
        )

    assert listed.status_code == 200
    assert listed.json()["media"][0]["id"] == "media-1"
    assert analyzed.status_code == 200
    assert analyzed.json()["draft"] is True
    assert payload.updated[0][0] == "media-1"
    assert payload.updated[0][1]["analysisStatus"] == "ready"
    memory.close()


def test_shared_api_approves_a_design_draft_through_the_design_adapter(tmp_path):
    class DesignService:
        def approve_review_draft(self, draft_id, publish):
            published = publish({"candidate_sha": "candidate-sha", "base_sha": "base-sha", "run_id": "run-1"})
            return {
                "published": published,
                "run": {"run_id": "run-1", "candidate_sha": "candidate-sha", "base_sha": "base-sha"},
            }

    class Adapter:
        def merge_design_candidate(self, config, candidate_sha, base_sha, message):
            assert candidate_sha == "candidate-sha"
            assert base_sha == "base-sha"
            assert message == "Approve design candidate: 7"
            return {"committed": True, "commit_sha": "published-sha", "parent_sha": base_sha, "path": "site"}

    memory = Memory(tmp_path / "workspace-design" / "memory.db")
    tenant = Tenant(
        tenant_id="workspace-design",
        config={"site": {"branch": "main"}},
        memory=memory,
        runtime=None,
        context={"llm": object(), "design_service": DesignService(), "design_adapter": Adapter()},
        api_token="design-token",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workspace/drafts/7/approve",
            headers={"Authorization": "Bearer design-token"},
        )

    assert response.status_code == 200
    assert response.json()["published"]["commit_sha"] == "published-sha"
    assert memory.list_publishes(limit=10)[0]["commit_sha"] == "published-sha"
    assert memory.recent_actions(limit=10)[0]["kind"] == "approve"
    memory.close()


def test_shared_api_publishes_and_rolls_back_preview_changes_through_the_workspace(tmp_path):
    class Adapter:
        def ensure_branch(self, branch):
            assert branch == "preview"
            return {"branch": branch}

        def restore_snapshot(self, commit_sha, branch, message):
            assert commit_sha == "target-sha"
            assert branch == "preview"
            return {"committed": True, "commit_sha": "rollback-preview", "parent_sha": "head-sha"}

        def merge_preview(self, config, message):
            assert config["site"]["preview_branch"] == "preview"
            return {"merged": True, "commit_sha": "rollback-publish", "parent_sha": "current-sha", "path": "preview->main"}

        def reset_preview_branch(self, branch):
            return {"reset": True, "branch": branch}

    memory = Memory(tmp_path / "workspace-rollback" / "memory.db")
    first = memory.log_publish("First", "site", "target-sha")
    newer = memory.log_publish("Newer", "site", "newer-sha")
    pending = memory.save_draft(
        "Website update",
        "preview",
        kind="merge",
        meta={"summary": "Website update"},
    )
    tenant = Tenant(
        tenant_id="workspace-rollback",
        config={"site": {"preview_branch": "preview"}},
        memory=memory,
        runtime=None,
        context={"llm": object(), "design_adapter": Adapter()},
        api_token="rollback-token",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer rollback-token"}
        published = client.post(f"/v1/workspace/drafts/{pending}/approve", headers=headers)
        rollback_draft = client.post(f"/v1/workspace/versions/{first}/restore", headers=headers)
        rollback_id = rollback_draft.json()["draft_id"]
        rollback_published = client.post(f"/v1/workspace/drafts/{rollback_id}/approve", headers=headers)

    assert published.status_code == 200
    assert rollback_draft.status_code == 200
    assert rollback_published.status_code == 200
    versions = {item["id"]: item for item in memory.list_publishes(limit=10)}
    assert versions[first]["reverted_ts"] is None
    assert versions[newer]["reverted_ts"]
    assert rollback_published.json()["published"]["commit_sha"] == "rollback-publish"
    memory.close()
