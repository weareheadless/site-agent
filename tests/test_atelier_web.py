from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from site_agent.application.atelier import (
    AtelierChatService,
    AtelierDesignBuildHandoff,
    AtelierJourney,
    AtelierTenant,
    AtelierTenantRegistry,
    _journey_for_config,
)
from site_agent.application.atelier_intake import AtelierIntakeCoordinator
from site_agent.core.memory import Memory
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.hands.atelier_payload import AtelierPayloadClient, AtelierPayloadError, AtelierPayloadMediaService
from site_agent.web.atelier import register_atelier_routes


def test_atelier_bridge_requires_a_server_token(tmp_path):
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={"ATELIER_SITE_AGENT_TOKEN": "atelier-secret"},
        service=AtelierChatService(Memory(tmp_path / "memory.db"), object()),
    )

    with TestClient(app) as client:
        assert client.post("/api/atelier/chat", json={"message": "hello"}).status_code == 401
        assert client.post(
            "/api/atelier/chat",
            headers={"Authorization": "Bearer wrong"},
            json={"message": "hello"},
        ).status_code == 401


def test_atelier_bridge_enqueues_contextual_chat(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    app = FastAPI()
    service = AtelierChatService(memory, object())
    register_atelier_routes(
        app,
        config={},
        env={"ATELIER_SITE_AGENT_TOKEN": "atelier-secret"},
        service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/atelier/chat",
            headers={"Authorization": "Bearer atelier-secret"},
            json={
                "message": "Change the heading",
                "context": {
                    "site": "atelier-harmonie",
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
                        "preview": {"state": "draft", "url": "https://atelier.example/atelier-preview/shop"},
                        "payload": {"collection": "products", "id": "42", "sourceId": "product-source-id"},
                    },
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"]
        job = client.get(
            f"/api/atelier/chat/jobs/{payload['job_id']}",
            headers={"Authorization": "Bearer atelier-secret"},
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
                "title": "Atelier Harmonie",
                "content": {"heading": "Une maison douce", "body": "Book a consultation."},
            }

        def read_global(self, slug, *, draft):
            assert (slug, draft) == ("navigation", True)
            return {"items": [{"label": "Menu", "path": "/menu"}]}

    memory = Memory(tmp_path / "memory.db")
    coordinator = AtelierIntakeCoordinator(
        memory,
        config={"atelier_intake": {"database_only": True}},
        llm=None,
        payload_client=_Payload(),
    )
    snapshot = coordinator._existing_site_snapshot({
        "route": "/",
        "collection": "pages",
        "target": {"route": {"path": "/", "kind": "page", "sourceId": "home-source"}},
    })

    assert snapshot["status"] == "existing_live_website"
    assert snapshot["page"]["title"] == "Atelier Harmonie"
    assert snapshot["navigation"]["items"][0]["label"] == "Menu"
    memory.close()


def test_atelier_bridge_reports_workspace_phase_without_intake(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={"ATELIER_SITE_AGENT_TOKEN": "atelier-secret"},
        service=AtelierChatService(memory, object()),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/atelier/chat/status",
            headers={"Authorization": "Bearer atelier-secret"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "workspace"
    assert response.json()["website_context_enabled"] is True
    memory.close()


def test_atelier_bridge_exposes_durable_conversation_history(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("A saved conversation")
    memory.add_message(conversation_id, "user", "Keep this history")
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={"ATELIER_SITE_AGENT_TOKEN": "atelier-secret"},
        service=AtelierChatService(memory, object()),
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer atelier-secret"}
        listed = client.get("/api/atelier/chat/conversations", headers=headers)
        detail = client.get(f"/api/atelier/chat/conversations/{conversation_id}", headers=headers)

    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["id"] == conversation_id
    assert detail.status_code == 200
    assert detail.json()["messages"][0]["text"] == "Keep this history"
    memory.close()


def test_atelier_bridge_exposes_bounded_activity_history(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("A saved conversation")
    memory.create_design_run(
        run_id="run-history",
        mode="local_experiment",
        intake_json={"business": {"name": "History"}},
    )
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={"ATELIER_SITE_AGENT_TOKEN": "atelier-secret"},
        service=AtelierChatService(memory, object()),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/atelier/history?limit=1",
            headers={"Authorization": "Bearer atelier-secret"},
        )

    assert response.status_code == 200
    assert response.json()["tenant"] == "legacy"
    assert response.json()["conversations"][0]["id"] == conversation_id
    assert len(response.json()["design_runs"]) == 1
    memory.close()


def test_atelier_intake_requires_explicit_owner_acceptance(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    intake = AtelierIntakeCoordinator(
        memory,
        config={"atelier_intake": {"database_only": True, "research": {"enabled": False}}},
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
        idempotency_key="accept-atelier-brief",
    )

    assert before["confirmed"] is False
    assert before["readiness"]["state"] == "ready_to_build"
    assert accepted["confirmed"] is True
    assert intake.needs_intake(session["conversation_id"]) is False
    memory.close()


def test_atelier_payload_client_is_server_configured_and_schema_bounded():
    client = AtelierPayloadClient.from_config(
        {
            "site": {
                "payload": {
                    "enabled": True,
                    "url": "https://atelier.example.test",
                }
            },
            "env": {},
        },
        {"ATELIER_SITE_AGENT_TOKEN": "atelier-secret"},
    )
    assert client is not None
    assert client.base_url == "https://atelier.example.test"

    with pytest.raises(AtelierPayloadError, match="outside the pages draft contract"):
        client._data("pages", {"password": "never"})
    with pytest.raises(AtelierPayloadError, match="outside the navigation global contract"):
        client._global_data("navigation", {"password": "never"})


def test_shared_api_scopes_jobs_to_the_token_selected_tenant(tmp_path):
    class Tenant:
        def __init__(self, tenant_id, token):
            self.tenant_id = tenant_id
            self.api_token = token
            self.memory = Memory(tmp_path / tenant_id / "memory.db")
            self.context = {"llm": object()}

    class Registry:
        def __init__(self):
            self.tenants = {"atelier-one": Tenant("atelier-one", "one-token")}

        def for_token(self, token):
            return next((tenant for tenant in self.tenants.values() if tenant.api_token == token), None)

    registry = Registry()
    app = FastAPI()
    service = AtelierChatService(registry=registry)
    register_atelier_routes(
        app,
        config={},
        env={},
        service=service,
        registry=registry,
        prefix="/v1/atelier",
    )

    with TestClient(app) as client:
        denied = client.post("/v1/atelier/chat", json={"message": "hello"})
        assert denied.status_code == 401
        accepted = client.post(
            "/v1/atelier/chat",
            headers={"Authorization": "Bearer one-token"},
            json={"message": "hello", "context": {"route": "/"}},
        )
        assert accepted.status_code == 200
        job_id = accepted.json()["job_id"]
        assert client.get(
            f"/v1/atelier/chat/jobs/{job_id}",
            headers={"Authorization": "Bearer one-token"},
        ).status_code == 200

    stored = registry.tenants["atelier-one"].memory.get_chat_job(job_id)
    assert '"site": "atelier-one"' in stored["message"]
    registry.tenants["atelier-one"].memory.close()


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
            self.tenant_id = "atelier-intake"
            self.api_token = "intake-token"
            self.memory = Memory(tmp_path / "atelier-intake" / "memory.db")
            self.context = {"llm": object(), "atelier_intake": Intake()}

    tenant = Tenant()

    class Registry:
        tenants = {"atelier-intake": tenant}

        @staticmethod
        def for_token(token):
            return tenant if token == tenant.api_token else None

    app = FastAPI()
    registry = Registry()
    register_atelier_routes(
        app,
        config={},
        env={},
        service=AtelierChatService(registry=registry),
        registry=registry,
        prefix="/v1/atelier",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/atelier/chat",
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
    assert tenant.context["atelier_intake"].calls == [
        ("needs", None),
        ("send", "Je veux créer une page", None, "turn-1"),
    ]
    tenant.memory.close()


def test_atelier_journey_separates_existing_site_incubation_from_new_site_intake():
    existing = _journey_for_config({
        "site": {"payload": {"enabled": True}},
        "atelier_intake": {"enabled": True},
    })
    new_site = _journey_for_config({
        "site": {"adapter": "github_static"},
    })

    assert existing == AtelierJourney(website_present=True, incubation_needed=True)
    assert existing.initial_phase == "incubation"
    assert new_site == AtelierJourney(website_present=False, incubation_needed=False)
    assert new_site.initial_phase == "intake"

    observed_site = _journey_for_config({
        "site": {"adapter": "github_static"},
        "customer_profile": {"business": {"observed_site_settings": {"website_url": "https://example.test"}}},
        "atelier_intake": {"enabled": True},
    })
    forced_no_site = _journey_for_config({
        "ada_journey": {"website_present": False, "incubation_needed": True},
        "atelier_intake": {"enabled": True},
    })
    assert observed_site == AtelierJourney(website_present=True, incubation_needed=True)
    assert forced_no_site == AtelierJourney(website_present=False, incubation_needed=False)


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
    handoff = AtelierDesignBuildHandoff({"design_service": design, "design_executor": executor})
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

    memory = Memory(tmp_path / "atelier-attachments" / "memory.db")
    tenant = AtelierTenant(
        tenant_id="atelier-attachments",
        config={},
        memory=memory,
        runtime=None,
        context={
            "llm": object(),
            "media_service": Media(),
            "atelier_journey": AtelierJourney(website_present=True, incubation_needed=True),
        },
        api_token="attachments-token",
    )
    registry = AtelierTenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={},
        service=AtelierChatService(registry=registry),
        registry=registry,
        prefix="/v1/atelier",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/atelier/chat",
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
        base_url = "https://atelier.example.test"

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

    service = AtelierPayloadMediaService(Payload())
    resolved = service.resolve_attachments([7])
    assert resolved[0]["asset_id"] == 7
    assert resolved[0]["url"] == "https://atelier.example.test/media/lamp.jpg"
    assert resolved[0]["alt_text"] == "Woven lamp"
    assert resolved[0]["analysis_error"] is None


def test_no_site_confirmation_hands_off_to_the_full_design_build(tmp_path):
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

    class DesignIntake:
        lab_service = object()

        def build(self, session_id, **kwargs):
            assert session_id == "intake-new-site"
            assert kwargs["confirmed_revision"] == 22
            return {"run": {"run_id": "design-first-site", "status": "building"}}

    memory = Memory(tmp_path / "atelier-new-site" / "memory.db")
    tenant = AtelierTenant(
        tenant_id="atelier-new-site",
        config={},
        memory=memory,
        runtime=None,
        context={
            "llm": object(),
            "atelier_intake": Intake(),
            "design_intake_service": DesignIntake(),
            "atelier_journey": AtelierJourney(website_present=False, incubation_needed=False),
        },
        api_token="new-site-token",
    )
    registry = AtelierTenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={},
        service=AtelierChatService(registry=registry),
        registry=registry,
        prefix="/v1/atelier",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/atelier/chat/intake/confirm",
            headers={"Authorization": "Bearer new-site-token"},
            json={"conversation_id": 12, "revision": 2, "draft_hash": "abc"},
        )

    assert response.status_code == 200
    assert response.json()["build"]["run"]["run_id"] == "design-first-site"
    memory.close()


def test_shared_api_exposes_media_library_and_analysis(tmp_path):
    class Payload:
        base_url = "https://atelier.example.test"

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
            assert image_urls == ["https://atelier.example.test/media/lamp.jpg"]
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

    memory = Memory(tmp_path / "atelier-media" / "memory.db")
    payload = Payload()
    tenant = AtelierTenant(
        tenant_id="atelier-media",
        config={},
        memory=memory,
        runtime=None,
        context={"llm": object(), "atelier_payload": payload, "media_analyzer": Analyzer()},
        api_token="media-token",
    )
    registry = AtelierTenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={},
        service=AtelierChatService(registry=registry),
        registry=registry,
        prefix="/v1/atelier",
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer media-token"}
        listed = client.get("/v1/atelier/media?limit=12", headers=headers)
        analyzed = client.post(
            "/v1/atelier/media/analyze",
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

    memory = Memory(tmp_path / "atelier-design" / "memory.db")
    tenant = AtelierTenant(
        tenant_id="atelier-design",
        config={"site": {"branch": "main"}},
        memory=memory,
        runtime=None,
        context={"llm": object(), "design_service": DesignService(), "design_adapter": Adapter()},
        api_token="design-token",
    )
    registry = AtelierTenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_atelier_routes(
        app,
        config={},
        env={},
        service=AtelierChatService(registry=registry),
        registry=registry,
        prefix="/v1/atelier",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/atelier/drafts/7/approve",
            headers={"Authorization": "Bearer design-token"},
        )

    assert response.status_code == 200
    assert response.json()["published"]["commit_sha"] == "published-sha"
    assert memory.list_publishes(limit=10)[0]["commit_sha"] == "published-sha"
    assert memory.recent_actions(limit=10)[0]["kind"] == "approve"
    memory.close()
