from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application.actions import OwnerActionService
from site_agent.application.design_direction import DesignDirectionService
from site_agent.application.design_intake import DesignIntakeService
from site_agent.application.design_operations import (
    DesignOperationError,
    DesignOperationService,
)
from site_agent.application.workspace import AtelierJourney, AtelierTenant, ChatService, TenantRegistry
from site_agent.core.contracts import ActionPriority, ActionState, Artifact, ArtifactKind
from site_agent.core.memory import Memory
from site_agent.web.workspace import register_workspace_routes


def _confirmed_intake_service(memory):
    from site_agent.core.design_contracts import SiteIntake

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
    service = DesignIntakeService(memory, default_intake=intake)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-direction-service",
    )
    return service, confirmed["session"]


def _service(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = DesignOperationService(
        memory,
        OwnerActionService(memory),
        website_id="site-123",
    )
    return memory, service


def test_recommendation_acceptance_creates_one_operation_with_provenance(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.direction",
            title="Prepare a visual direction",
            reason="The confirmed brief is ready.",
            scope={"intake_revision": 3},
            bound_state={"intake_revision": 3},
            source_ref="conversation:42",
            priority=ActionPriority.NORMAL,
        )

        accepted = service.accept(recommendation.id)
        replayed = service.accept(recommendation.id)

        assert accepted.id is not None
        assert accepted.source_action_id == recommendation.id
        assert accepted.origin == "recommendation"
        assert accepted.status == "queued"
        assert replayed.id == accepted.id
        assert replayed.input_hash == accepted.input_hash
        assert memory.list_operations(website_id="site-123") == [accepted]
        assert service.actions.get(recommendation.id).state is ActionState.STARTED
    finally:
        memory.close()


def test_build_recommendation_requires_an_approved_direction(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.build",
            title="Build the homepage",
            reason="The direction is approved.",
            scope={
                "session_id": "intake-1",
                "confirmed_revision": 7,
                "direction_hash": "direction-1",
                "direction_artifact_id": 1,
                "page": "index.html",
            },
            bound_state={"intake_revision": 7, "direction_hash": "direction-1", "revision_id": None},
            source_ref="direction:1",
        )

        with pytest.raises(DesignOperationError, match="direction_not_approved"):
            service.accept(recommendation.id)

        assert service.actions.get(recommendation.id).state is ActionState.OPEN
        assert memory.list_operations(website_id="site-123") == []
    finally:
        memory.close()


def test_build_recommendation_rejects_a_direction_from_another_intake_revision(tmp_path):
    memory, service = _service(tmp_path)
    try:
        artifact = memory.create_artifact(Artifact(
            kind=ArtifactKind.DESIGN_DIRECTION,
            title="Direction",
            summary="Approved direction",
            renderer="design-direction",
            capability_id="website.design.direction",
            provider_id="site-agent",
            content_hash="direction-1",
            preview_data={"confirmed_revision": 3},
        ))
        recommendation = service.recommend(
            tool="design.build",
            title="Build the homepage",
            reason="The direction is approved.",
            scope={
                "session_id": "intake-1",
                "confirmed_revision": 4,
                "direction_hash": "direction-1",
                "direction_artifact_id": artifact.artifact_id,
                "page": "index.html",
            },
            bound_state={"intake_revision": 4, "direction_hash": "direction-1", "revision_id": None},
            source_ref="direction:1",
        )

        with pytest.raises(DesignOperationError, match="direction_outdated"):
            service.accept(recommendation.id)

        assert service.actions.get(recommendation.id).state is ActionState.OPEN
    finally:
        memory.close()


def test_change_recommendation_requires_a_current_revision(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.change",
            title="Soften the hero",
            reason="The hero is heavier than the approved direction.",
            scope={"request": "Use a lighter display weight."},
            bound_state={"intake_revision": 3, "direction_hash": "direction-1", "revision_id": None},
            source_ref="review:run-1",
        )

        with pytest.raises(DesignOperationError, match="no_current_revision"):
            service.accept(recommendation.id)

        assert service.actions.get(recommendation.id).state is ActionState.OPEN
    finally:
        memory.close()


def test_recommendation_is_bound_to_state_and_dismissal_does_not_create_operation(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.change",
            title="Soften the hero typography",
            reason="The current hero is heavier than the approved direction.",
            scope={"request": "Use a lighter display weight."},
            bound_state={"intake_revision": 3, "direction_hash": "direction-1", "revision_id": 8},
            source_ref="review:run-1",
        )
        dismissed = service.dismiss(recommendation.id)

        assert dismissed.state is ActionState.DISMISSED
        assert memory.list_operations(website_id="site-123") == []
    finally:
        memory.close()


def test_recommendation_with_a_changed_bound_state_is_stale(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.page",
            title="Build the services page",
            reason="The confirmed inventory includes a services page.",
            scope={"page": "services.html"},
            bound_state={"intake_revision": 3, "direction_hash": "direction-1", "revision_id": 8},
            source_ref="review:run-1",
        )

        with pytest.raises(DesignOperationError, match="recommendation is stale"):
            service.accept(recommendation.id, current_state={
                "intake_revision": 4,
                "direction_hash": "direction-1",
                "revision_id": 8,
            })

        assert service.actions.get(recommendation.id).state is ActionState.STALE
        assert memory.list_operations(website_id="site-123") == []
    finally:
        memory.close()


def test_operation_state_transitions_are_durable_and_bounded(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.direction",
            title="Prepare a visual direction",
            reason="The brief is confirmed.",
            scope={"intake_revision": 3},
            bound_state={"intake_revision": 3},
            source_ref="conversation:42",
        )
        operation = service.accept(recommendation.id)
        running = service.start(operation.id)
        done = service.complete(operation.id, outcome={"revision_id": 9})

        assert running.status == "running"
        assert done.status == "done"
        assert done.outcome == {"revision_id": 9}
        assert service.get(operation.id).status == "done"
        assert service.actions.get(recommendation.id).state is ActionState.COMPLETED

        with pytest.raises(DesignOperationError, match="cannot transition"):
            service.start(operation.id)
    finally:
        memory.close()


def test_reapproving_a_failed_operation_requeues_the_same_request(tmp_path):
    memory, service = _service(tmp_path)
    try:
        recommendation = service.recommend(
            tool="design.direction",
            title="Prepare a visual direction",
            reason="The brief is confirmed.",
            scope={"intake_revision": 3},
            bound_state={"intake_revision": 3},
            source_ref="conversation:42",
        )
        operation = service.accept(recommendation.id)
        running = service.start(operation.id)
        failed = service.fail(running.id, error_code="temporary_failure", reason="The tenant was not ready.")
        assert failed.status == "failed"

        retried = service.accept(recommendation.id)

        assert retried.id == operation.id
        assert retried.status == "queued"
        assert retried.error_code is None
        assert retried.outcome == {}
        assert retried.payload["retry_count"] == 1
        assert service.actions.get(recommendation.id).state is ActionState.WAITING
    finally:
        memory.close()


def test_workspace_routes_expose_the_same_recommendation_and_operation_records(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        service = ChatService(memory, object())
        recommendation = service.design_operations().recommend(
            tool="design.direction",
            title="Prepare a visual direction",
            reason="The brief is confirmed.",
            scope={"intake_revision": 3},
            bound_state={"intake_revision": 3},
            source_ref="conversation:42",
        )
        app = FastAPI()
        register_workspace_routes(
            app,
            config={},
            env={"ATELIER_SITE_AGENT_TOKEN": "workspace-secret"},
            service=service,
        )

        with TestClient(app) as client:
            headers = {"Authorization": "Bearer workspace-secret"}
            listed = client.get("/api/atelier/design/recommendations", headers=headers)
            accepted = client.post(
                f"/api/atelier/design/recommendations/{recommendation.id}/accept",
                headers=headers,
                json={"current_state": {"intake_revision": 3}},
            )
            operations = client.get("/api/atelier/design/operations", headers=headers)

        assert listed.status_code == 200
        assert listed.json()["recommendations"][0]["recommendation"]["proposed_tool"] == "design.direction"
        assert accepted.status_code == 200
        operation = accepted.json()["operation"]
        assert operation["origin"] == "recommendation"
        assert operation["source_action_id"] == recommendation.id
        assert operations.status_code == 200
        assert operations.json()["operations"][0]["id"] == operation["id"]
    finally:
        memory.close()


def test_direction_is_read_only_and_waits_with_a_build_recommendation(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        intake, session = _confirmed_intake_service(memory)
        operations = DesignOperationService(
            memory,
            website_id="site-123",
        )
        direction = DesignDirectionService(memory, intake, operations)

        result = direction.propose(
            session["session_id"],
            confirmed_revision=session["confirmed_revision_id"],
            conversation_id=session["conversation_id"],
        )

        assert result["artifact"]["kind"] == "design_direction"
        assert result["recommendation"]["recommendation"]["proposed_tool"] == "design.build"
        assert result["operation"]["status"] == "done"
        assert result["operation"]["origin"] == "owner_message"
        assert memory.list_design_runs() == []

        replay = direction.propose(
            session["session_id"],
            confirmed_revision=session["confirmed_revision_id"],
            conversation_id=session["conversation_id"],
        )
        assert replay["operation"]["id"] == result["operation"]["id"]
        assert replay["recommendation"]["id"] == result["recommendation"]["id"]
    finally:
        memory.close()


def test_accepting_a_build_recommendation_submits_the_existing_async_build(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    calls = []

    class Intake:
        def build(self, session_id, **kwargs):
            calls.append((session_id, kwargs))
            return {"run": {"run_id": "design-run-1", "status": "building"}}

    class Coordinator:
        pass

    class Runtime:
        def close(self):
            pass

    tenant = AtelierTenant(
        tenant_id="site-123",
        config={},
        memory=memory,
        runtime=Runtime(),
        context={
            "llm": object(),
            "intake_coordinator": Coordinator(),
            "design_intake_service": Intake(),
            "atelier_journey": AtelierJourney(website_present=False, incubation_needed=False),
            "design_operations": DesignOperationService(memory, website_id="site-123"),
        },
        api_token="tenant-secret",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    try:
        service = ChatService(registry=registry)
        operation_service = tenant.context["design_operations"]
        direction_artifact = memory.create_artifact(Artifact(
            kind=ArtifactKind.DESIGN_DIRECTION,
            title="Direction",
            summary="Approved direction",
            renderer="design-direction",
            capability_id="website.design.direction",
            provider_id="site-agent",
            content_hash="direction-1",
            preview_data={"confirmed_revision": 7},
        ))
        recommendation = operation_service.recommend(
            tool="design.build",
            title="Build the homepage",
            reason="The direction is approved.",
            scope={
                "session_id": "intake-1",
                "confirmed_revision": 7,
                "direction_hash": "direction-1",
                "direction_artifact_id": direction_artifact.artifact_id,
                "page": "index.html",
            },
            bound_state={"intake_revision": 7, "direction_hash": "direction-1", "revision_id": None},
            source_ref="direction:1",
        )

        result = service.accept_recommendation(
            recommendation.id,
            {"current_state": {"intake_revision": 7, "direction_hash": "direction-1", "revision_id": None}},
            tenant=tenant,
        )

        assert result["operation"]["status"] == "done"
        assert result["operation"]["revision_id"] == "design-run-1"
        assert calls[0][0] == "intake-1"
        assert calls[0][1]["confirmed_revision"] == 7
    finally:
        registry.close()


def test_helloada_control_plane_scopes_requests_by_website_without_tenant_tokens(tmp_path):
    memory = Memory(tmp_path / "memory.db")

    class Runtime:
        def close(self):
            pass

    tenant = AtelierTenant(
        tenant_id="site-123",
        config={},
        memory=memory,
        runtime=Runtime(),
        context={"llm": object()},
        api_token="tenant-secret",
    )
    registry = TenantRegistry({tenant.tenant_id: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/atelier",
        control_prefix="/v1/control-plane/websites",
        control_token="control-secret",
    )
    try:
        with TestClient(app) as client:
            denied = client.get(
                "/v1/control-plane/websites/site-123/chat/status",
                headers={"Authorization": "Bearer tenant-secret"},
            )
            allowed = client.get(
                "/v1/control-plane/websites/site-123/chat/status",
                headers={"Authorization": "Bearer control-secret"},
            )
            missing = client.get(
                "/v1/control-plane/websites/missing/chat/status",
                headers={"Authorization": "Bearer control-secret"},
            )

        assert denied.status_code == 401
        assert allowed.status_code == 200
        assert allowed.json()["tenant"] == "site-123"
        assert missing.status_code == 404
    finally:
        registry.close()
