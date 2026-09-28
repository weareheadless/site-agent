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

from ..application.workspace import BridgeError, ChatService, SourceConflict, Tenant, TenantRegistry
from ..config import resolve_secret

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


def create_workspace_api_app(registry: TenantRegistry, *, prefix: str = "/v1/atelier") -> FastAPI:
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
