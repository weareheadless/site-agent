"""The narrow server-to-server bridge used by the owner workspace.

This module intentionally does not share the browser's password session. The
Payload server calls these endpoints with a dedicated bearer token, while the
existing admin API and Intake Lab routes keep their current authentication and
behavior.
The route prefix remains configurable because the first customer still uses
``/v1/atelier``.  The implementation itself is not customer-specific.
"""

from __future__ import annotations

import hmac
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from ..application.analytics import AnalyticsError, GoogleAnalyticsService
from ..application.tenant_registration import TenantRegistrationError, TenantRegistrationService
from ..application.workspace import BridgeError, ChatService, SourceConflict, Tenant, TenantRegistry
from ..config import resolve_secret
from ..hands.google_platform import GooglePlatformError

# Local compatibility aliases keep the existing handler names readable while
# the public service and route modules use generic workspace terminology.
AtelierBridgeError = BridgeError
AtelierChatService = ChatService
AtelierSourceConflict = SourceConflict
AtelierTenant = Tenant
AtelierTenantRegistry = TenantRegistry


def register_workspace_routes(
    app: FastAPI,
    *,
    config: dict[str, Any],
    env: dict[str, str],
    service: ChatService,
    registry: TenantRegistry | None = None,
    prefix: str = "/api/atelier",
    control_prefix: str | None = None,
    control_token: str | None = None,
    registration: TenantRegistrationService | None = None,
) -> None:
    """Register the smallest trusted bridge needed by an owner workspace.

    The bridge exposes the narrow chat, history, and job views needed by the
    Payload workspace. Content mutations remain Payload operations, and design
    jobs continue through the existing site-agent workflow rather than
    receiving a second orchestration system.
    """

    prefix = "/" + prefix.strip("/")

    def require_service(request: Request) -> Tenant | None:
        authorization = request.headers.get("authorization", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if registry is not None:
            if not supplied:
                raise HTTPException(status_code=401, detail="Atelier service authentication required")
            tenant = registry.for_token(supplied)
            if tenant is None:
                raise HTTPException(status_code=401, detail="Atelier service authentication required")
            return tenant

        expected = env.get("ATELIER_SITE_AGENT_TOKEN", "") or resolve_secret(
            config,
            "workspace_service_token",
            env,
        ) or resolve_secret(config, "atelier_service_token", env)
        if not expected:
            raise HTTPException(status_code=503, detail="Atelier service token is not configured")

        if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Atelier service authentication required")
        return None

    def require_control_tenant(request: Request, website_id: str) -> Tenant:
        """Authenticate the server-only HelloAda bridge and scope by website."""
        require_control_plane(request)
        if registry is None:
            raise HTTPException(status_code=503, detail="tenant registry is unavailable")
        tenant = registry.for_tenant_id(website_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="website was not found")
        return tenant

    def require_control_plane(request: Request) -> None:
        """Authenticate the server-only HelloAda control plane."""
        expected = str(control_token or env.get("HELLOADA_CONTROL_PLANE_TOKEN") or "").strip()
        if not expected:
            raise HTTPException(status_code=503, detail="HelloAda control-plane authentication is not configured")
        authorization = request.headers.get("authorization", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="HelloAda control-plane authentication required")

    def analytics_for(tenant: Tenant | None) -> GoogleAnalyticsService:
        if tenant is None:
            raise HTTPException(status_code=503, detail="tenant analytics are unavailable")
        google = tenant.context.get("google_platform")
        if google is None:
            raise HTTPException(status_code=503, detail="Google analytics is not configured for this tenant")
        state = tenant.context.get("seo_provisioning_state") or tenant.memory.kv_get("seo_provisioning_state", {})
        return GoogleAnalyticsService(tenant.config, google, state)

    def ga_property_id(tenant: Tenant | None) -> str:
        if tenant is None:
            raise HTTPException(status_code=503, detail="tenant analytics are unavailable")
        state = tenant.context.get("seo_provisioning_state") or tenant.memory.kv_get("seo_provisioning_state", {})
        property_id = str((state or {}).get("ga4_property_id") or ((tenant.config.get("ga") or {}).get("property_id") or "")).strip()
        if not property_id:
            raise HTTPException(status_code=503, detail="GA4 property is not configured for this tenant")
        return property_id

    def access_binding_view(binding: dict[str, Any]) -> dict[str, Any]:
        roles = [str(role).rsplit("/", 1)[-1] for role in (binding.get("roles") or [])]
        return {
            "name": str(binding.get("name") or ""),
            "user": str(binding.get("user") or ""),
            "group": str(binding.get("group") or ""),
            "roles": roles,
        }

    @app.post(f"{prefix}/chat")
    async def atelier_chat(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.enqueue(body, tenant=tenant)
        except AtelierBridgeError as exc:
            status = 413 if str(exc) == "message too long" else 400
            if str(exc) == "LLM not configured":
                status = 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/status")
    def atelier_chat_status(request: Request, conversation_id: int | None = None):
        tenant = require_service(request)
        try:
            return service.status(conversation_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/chat/intake/confirm")
    async def atelier_intake_confirm(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.confirm_intake(body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/chat/design/start")
    async def atelier_design_start(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.start_first_page(body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/recommendations")
    def atelier_design_recommendations(request: Request, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.recommendations(limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/direction")
    async def atelier_design_direction(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.propose_direction(body, tenant=tenant)
        except AtelierBridgeError as exc:
            status = 409 if "must be accepted" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/recommendations/{{action_id}}/accept")
    async def atelier_accept_design_recommendation(action_id: int, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.accept_recommendation(action_id, body, tenant=tenant)
        except AtelierBridgeError as exc:
            status = 409 if "stale" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/recommendations/{{action_id}}/dismiss")
    def atelier_dismiss_design_recommendation(action_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.dismiss_recommendation(action_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/operations")
    def atelier_design_operations(request: Request, status: str | None = None, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.operations(status=status, limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/operations/{{operation_id}}")
    def atelier_design_operation(operation_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.operation(operation_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/conversations")
    def atelier_conversations(request: Request, include_archived: bool = False, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.conversations(include_archived=include_archived, limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/conversations/{{conversation_id}}")
    def atelier_conversation(conversation_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.conversation(conversation_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/history")
    def atelier_history(request: Request, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.history(limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/worktree")
    def atelier_worktree(request: Request):
        tenant = require_service(request)
        try:
            return service.worktree(tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/worktree/discard")
    def atelier_worktree_discard(request: Request):
        tenant = require_service(request)
        try:
            return service.discard_worktree(tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/runs")
    def atelier_design_runs(
        request: Request,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
    ):
        tenant = require_service(request)
        try:
            return service.design_runs(status=status, mode=mode, limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/runs/{{run_id}}")
    def atelier_design_run(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.design_run(run_id, tenant=tenant)
        except AtelierBridgeError as exc:
            status = 404 if "no such" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/runs/{{run_id}}/review")
    def atelier_design_review(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.create_design_review(run_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/runs/{{run_id}}/retry")
    async def atelier_design_retry(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.retry_design_run(run_id, body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/drafts")
    def atelier_drafts(request: Request, status: str | None = None, limit: int = 50):
        tenant = require_service(request)
        try:
            history = service.history(limit=limit, tenant=tenant)
            drafts = history.get("drafts") or []
            if status:
                drafts = [item for item in drafts if item.get("status") == status]
            return {
                "drafts": drafts,
                "current_update": history.get("current_update"),
            }
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/seo/insights")
    def atelier_seo_insights(request: Request, limit: int = 12):
        tenant = require_service(request)
        try:
            return service.seo_insights(limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/seo/analytics")
    def atelier_seo_analytics(request: Request, days: int = 28):
        tenant = require_service(request)
        try:
            return analytics_for(tenant).report(days=days)
        except AnalyticsError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except GooglePlatformError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get(f"{prefix}/seo/access")
    def atelier_seo_access(request: Request):
        tenant = require_service(request)
        google = tenant.context.get("google_platform") if tenant is not None else None
        property_id = ga_property_id(tenant)
        if google is None:
            raise HTTPException(status_code=503, detail="Google analytics is not configured for this tenant")
        try:
            bindings = google.list_ga4_access_bindings(property_id)
        except GooglePlatformError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        state = tenant.context.get("seo_provisioning_state") or tenant.memory.kv_get("seo_provisioning_state", {})
        return {
            "entity": {
                "siteUrl": str((state or {}).get("site_url") or ((tenant.config.get("seo") or {}).get("site_url") or "")),
                "gscProperty": str((state or {}).get("gsc_property") or ""),
                "ga4PropertyId": property_id,
            },
            "ga4": {"available": True, "bindings": [access_binding_view(item) for item in bindings]},
            "gsc": {
                "available": False,
                "reason": "Search Console does not expose user-permission management through its public API. The platform service account remains the automation owner.",
            },
        }

    @app.post(f"{prefix}/seo/access")
    async def atelier_seo_access_grant(request: Request):
        tenant = require_service(request)
        google = tenant.context.get("google_platform") if tenant is not None else None
        property_id = ga_property_id(tenant)
        if google is None:
            raise HTTPException(status_code=503, detail="Google analytics is not configured for this tenant")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        email = str(body.get("email") or "").strip().lower()
        role = str(body.get("role") or "viewer").strip().lower()
        try:
            binding = google.grant_ga4_access(property_id, email, role)
        except GooglePlatformError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if tenant is not None:
            tenant.memory.record_action("analytics_access", f"GA4 {role} access granted to {email}")
        return {
            "ga4": access_binding_view(binding),
            "gsc": {
                "available": False,
                "reason": "Search Console access still needs to be granted from Search Console itself.",
            },
        }

    @app.post(f"{prefix}/seo/access/revoke")
    async def atelier_seo_access_revoke(request: Request):
        tenant = require_service(request)
        google = tenant.context.get("google_platform") if tenant is not None else None
        property_id = ga_property_id(tenant)
        if google is None:
            raise HTTPException(status_code=503, detail="Google analytics is not configured for this tenant")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        binding_name = str(body.get("name") or "").strip()
        expected_prefix = f"properties/{property_id}/accessBindings/"
        if not binding_name.startswith(expected_prefix):
            raise HTTPException(status_code=400, detail="access binding does not belong to this tenant")
        try:
            bindings = google.list_ga4_access_bindings(property_id)
            binding = next((item for item in bindings if str(item.get("name") or "") == binding_name), None)
            if binding is None:
                raise HTTPException(status_code=404, detail="access binding not found")
            roles = {str(role).rsplit("/", 1)[-1] for role in (binding.get("roles") or [])}
            if not roles or not roles.issubset({"viewer", "analyst"}):
                raise HTTPException(status_code=409, detail="administrator access cannot be revoked from this workspace")
            google.delete_ga4_access_binding(binding_name)
        except GooglePlatformError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if tenant is not None:
            tenant.memory.record_action("analytics_access", f"GA4 access revoked for {binding.get('user') or binding.get('group') or binding_name}")
        return {"revoked": True, "name": binding_name}

    @app.post(f"{prefix}/drafts/{{draft_id}}/approve")
    def atelier_approve_draft(draft_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.approve_draft(draft_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/drafts/{{draft_id}}/discard")
    def atelier_discard_draft(draft_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.discard_draft(draft_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/versions/{{version_id}}/restore")
    def atelier_restore_version(version_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.restore_version(version_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/media/analyze")
    async def atelier_analyze_media(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.analyze_media(body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/media")
    def atelier_media(request: Request, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.media(limit=limit, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/inventory")
    def atelier_source_inventory_get(request: Request, branch: str | None = None):
        tenant = require_service(request)
        try:
            body = {"branch": branch} if branch else {}
            return service.source_inventory(body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/source/inventory")
    async def atelier_source_inventory(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.source_inventory(body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/source/edit")
    async def atelier_source_edit(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.source_edit(body, tenant=tenant)
        except AtelierSourceConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview/styles")
    def atelier_source_preview_styles(request: Request):
        tenant = require_service(request)
        try:
            return service.source_preview_styles(tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview")
    def atelier_source_preview_latest(request: Request, branch: str | None = None):
        tenant = require_service(request)
        try:
            return service.source_preview_latest(branch, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(f"{prefix}/source/preview")
    async def atelier_source_preview(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.source_preview_start(body, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview/{{job_id}}")
    def atelier_source_preview_status(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.source_preview_status(job_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview/{{job_id}}/runtime/{{file_path:path}}")
    def atelier_source_preview_runtime(job_id: str, file_path: str, request: Request):
        tenant = require_service(request)
        try:
            result = service.source_preview_runtime(
                job_id,
                file_path,
                request.url.query,
                {
                    "Accept": request.headers.get("accept", ""),
                    "Cookie": request.headers.get("cookie", ""),
                    "User-Agent": request.headers.get("user-agent", ""),
                },
                tenant=tenant,
            )
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=result.get("body") or b"",
            status_code=int(result.get("status") or 502),
            headers={
                "Content-Type": str(result.get("content_type") or "application/octet-stream"),
                "Cache-Control": "private, no-store",
                "X-Atelier-Preview-Commit": str(result.get("commit") or ""),
            },
        )

    @app.post(f"{prefix}/source/preview/{{job_id}}/deploy")
    def atelier_source_preview_deploy(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.source_preview_promote(job_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/jobs/{{job_id}}")
    def atelier_chat_job(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.job(job_id, tenant=tenant)
        except AtelierBridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    if control_prefix:
        control_prefix = "/" + control_prefix.strip("/")

        @app.post(f"{control_prefix}/{{website_id}}/register")
        async def control_plane_register(website_id: str, request: Request):
            require_control_plane(request)
            if registration is None:
                raise HTTPException(status_code=503, detail="tenant registration is unavailable")
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                receipt = registration.register(
                    website_id,
                    display_name=str(body.get("display_name") or "").strip(),
                    env=env,
                )
                # Paths and token environment names are host-only details. The
                # control-plane caller only needs the durable tenant identity
                # and schema/status receipt.
                return {
                    "tenant_id": receipt.get("tenant_id"),
                    "schema_version": receipt.get("schema_version"),
                    "status": receipt.get("status"),
                    "created": receipt.get("created"),
                }
            except TenantRegistrationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/chat")
        async def control_plane_chat(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="invalid json")
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.enqueue(body, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/chat/status")
        def control_plane_chat_status(website_id: str, request: Request, conversation_id: int | None = None):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.status(conversation_id, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/intake/confirm")
        async def control_plane_intake_confirm(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="invalid json")
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.confirm_intake(body, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/design/direction")
        async def control_plane_design_direction(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.propose_direction(body, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/design/recommendations")
        def control_plane_recommendations(website_id: str, request: Request, limit: int = 50):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.recommendations(limit=limit, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/design/recommendations/{{action_id}}/accept")
        async def control_plane_accept_recommendation(website_id: str, action_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.accept_recommendation(action_id, body, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/design/recommendations/{{action_id}}/dismiss")
        def control_plane_dismiss_recommendation(website_id: str, action_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.dismiss_recommendation(action_id, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/design/operations")
        def control_plane_operations(website_id: str, request: Request, status: str | None = None, limit: int = 50):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.operations(status=status, limit=limit, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/design/runs/{{run_id}}/retry")
        async def control_plane_design_retry(website_id: str, run_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.retry_design_run(run_id, body, tenant=tenant)
            except AtelierBridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc


def create_workspace_api_app(
    registry: TenantRegistry,
    *,
    prefix: str = "/v1/atelier",
    control_token: str | None = None,
    registration: TenantRegistrationService | None = None,
) -> FastAPI:
    """Create the single shared, tenant-aware API process."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        registry.start()
        try:
            yield
        finally:
            registry.close()

    app = FastAPI(
        title="Ada API",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix=prefix,
        control_prefix="/v1/control-plane/websites",
        control_token=control_token,
        registration=registration,
    )
    return app


# Compatibility names for the original customer integration.  The public route
# prefix remains configurable, so this does not change `/v1/atelier`.
register_atelier_routes = register_workspace_routes
create_atelier_api_app = create_workspace_api_app

__all__ = [
    "create_atelier_api_app",
    "create_workspace_api_app",
    "register_atelier_routes",
    "register_workspace_routes",
]
