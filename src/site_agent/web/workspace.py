"""The narrow server-to-server bridge used by the owner workspace.

This module intentionally does not share the browser's password session. The
Payload server calls these endpoints with a dedicated bearer token, while the
existing admin API routes keep their current authentication and
behavior.
The route prefix remains configurable because the first customer still uses
``/v1/workspace``.  The implementation itself is not customer-specific.
"""

from __future__ import annotations

import asyncio
import datetime
import hmac
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..application.analytics import AnalyticsError, GoogleAnalyticsService
from ..application.growth_evidence import growth_evidence
from ..application.growth_delivery import GrowthDeliveryError
from ..application.bootstrap import BootstrapError, WebsiteBootstrapService
from ..application.tenant_registration import TenantRegistrationError, TenantRegistrationService
from ..application.workspace import BridgeError, ChatService, SourceConflict, Tenant, TenantRegistry
from ..application import preview_host
from ..config import ConfigError, resolve_secret
from ..hands.google_platform import GooglePlatformError
from .design_preview import (
    DESIGN_PREVIEW_REFS,
    candidate_is_previewable,
    list_html_at,
    output_artifact_root,
    preview_ref,
    render_candidate_file,
)
from .preview import PreviewAccess, PreviewBuildCache


def authenticated_owner_actor(request: Request, tenant: Tenant | None = None) -> str | None:
    """Read only after service/control authentication, never from owner JSON.

    The authenticated Worker/HelloAda proxy sets this from its own principal;
    it must not forward an incoming browser header or body actor claim.
    """
    actor = request.headers.get("x-helloada-owner-id")
    if actor is None:
        return None
    if not re.fullmatch(r"(?:payload|helloada):[A-Za-z0-9_.:-]{1,180}", actor):
        raise HTTPException(status_code=400, detail="Authenticated owner identity is invalid")
    if tenant is not None and actor.startswith("payload:") and not actor.startswith(f"payload:{tenant.tenant_id}:"):
        raise HTTPException(status_code=403, detail="Authenticated owner identity does not belong to this tenant")
    return actor

def register_workspace_routes(
    app: FastAPI,
    *,
    config: dict[str, Any],
    env: dict[str, str],
    service: ChatService,
    registry: TenantRegistry | None = None,
    prefix: str = "/api/workspace",
    control_prefix: str | None = None,
    control_token: str | None = None,
    registration: TenantRegistrationService | None = None,
    bootstrap: WebsiteBootstrapService | None = None,
) -> None:
    """Register the smallest trusted bridge needed by an owner workspace.

    The bridge exposes the narrow chat, history, and job views needed by the
    Payload workspace. Content mutations remain Payload operations, and design
    jobs continue through the existing site-agent workflow rather than
    receiving a second orchestration system.
    """

    prefix = "/" + prefix.strip("/")
    preview_access = PreviewAccess()
    preview_cache = PreviewBuildCache()

    def require_service(request: Request) -> Tenant | None:
        authorization = request.headers.get("authorization", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if registry is not None:
            if not supplied:
                raise HTTPException(status_code=401, detail="Workspace service authentication required")
            tenant = registry.for_token(supplied)
            if tenant is None:
                raise HTTPException(status_code=401, detail="Workspace service authentication required")
            return tenant

        expected = env.get("WORKSPACE_SITE_AGENT_TOKEN", "") or resolve_secret(
            config,
            "workspace_service_token",
            env,
        )
        if not expected:
            raise HTTPException(status_code=503, detail="Workspace service token is not configured")

        if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Workspace service authentication required")
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

    def design_service_for(tenant: Tenant | None):
        if tenant is None:
            raise HTTPException(status_code=503, detail="tenant design service is unavailable")
        service = tenant.context.get("design_service")
        if service is None:
            raise HTTPException(status_code=503, detail="tenant design service is unavailable")
        return service

    def preview_scope(tenant: Tenant, run_id: str, variant: str) -> tuple[str, ...]:
        return ("design", tenant.tenant_id, str(run_id), str(variant))

    def require_preview_scope(request: Request, run_id: str) -> tuple[Tenant, str, str]:
        """Resolve a browser-only preview token back to its isolated tenant."""
        if registry is None:
            raise HTTPException(status_code=503, detail="tenant registry is unavailable")
        token = str(request.query_params.get("preview_token") or "").strip()
        scope = preview_access.scope(token)
        if not scope or len(scope) != 4 or scope[0] != "design" or scope[2] != str(run_id):
            raise HTTPException(status_code=401, detail="preview token is invalid or expired")
        tenant = registry.for_tenant_id(scope[1])
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant was not found")
        variant = str(request.query_params.get("variant") or scope[3]).strip().lower()
        if variant != scope[3]:
            raise HTTPException(status_code=401, detail="preview token does not authorize this variant")
        return tenant, variant, token

    def access_binding_view(binding: dict[str, Any]) -> dict[str, Any]:
        roles = [str(role).rsplit("/", 1)[-1] for role in (binding.get("roles") or [])]
        return {
            "name": str(binding.get("name") or ""),
            "user": str(binding.get("user") or ""),
            "group": str(binding.get("group") or ""),
            "roles": roles,
        }

    @app.post(f"{prefix}/chat")
    async def workspace_chat(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.enqueue(body, tenant=tenant)
        except BridgeError as exc:
            status = 413 if str(exc) == "message too long" else 400
            if str(exc) == "LLM not configured":
                status = 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post(f"{prefix}/messages/reply-draft")
    async def workspace_message_reply_draft(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.draft_message_reply(body, tenant=tenant)
        except BridgeError as exc:
            message = str(exc)
            status = 413 if "too long" in message else 503 if "LLM not configured" in message or "right now" in message else 400
            raise HTTPException(status_code=status, detail=message) from exc

    @app.get(f"{prefix}/site")
    def workspace_site(request: Request):
        tenant = require_service(request)
        try:
            return service.site_snapshot(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/status")
    def workspace_chat_status(request: Request, conversation_id: int | None = None):
        tenant = require_service(request)
        try:
            return service.status(conversation_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/conversations")
    def workspace_conversations(request: Request, include_archived: bool = False, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.conversations(include_archived=include_archived, limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/conversations/{{conversation_id}}")
    def workspace_conversation(conversation_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.conversation(conversation_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/history")
    def workspace_history(request: Request, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.history(limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/history/drafts/{{draft_id}}")
    def workspace_history_draft(draft_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.activity_detail(draft_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/history/seo-reports/{{report_id}}")
    def workspace_history_seo_report(report_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.activity_seo_report_detail(report_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/history/executions/{{run_id}}")
    def workspace_history_execution(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.activity_execution_detail(run_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/worktree")
    def workspace_worktree(request: Request):
        tenant = require_service(request)
        try:
            return service.worktree(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/worktree/discard")
    def workspace_worktree_discard(request: Request):
        tenant = require_service(request)
        try:
            return service.discard_worktree(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/runs")
    def workspace_design_runs(
        request: Request,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
    ):
        tenant = require_service(request)
        try:
            return service.design_runs(status=status, mode=mode, limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/runs/{{run_id}}")
    def workspace_design_run(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.design_run(run_id, tenant=tenant)
        except BridgeError as exc:
            status = 404 if "no such" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/runs/{{run_id}}/preview-token")
    def workspace_design_preview_token(
        run_id: str,
        request: Request,
        variant: str = "deepseek",
    ):
        """Issue a short-lived browser capability for one retained candidate."""
        tenant = require_service(request)
        design_service = design_service_for(tenant)
        try:
            run = design_service.get_run(str(run_id))
        except Exception as exc:  # noqa: BLE001 - normalize service-specific lookup errors
            raise HTTPException(status_code=404, detail="design run was not found") from exc
        if not candidate_is_previewable(run):
            raise HTTPException(status_code=409, detail="design run is not ready for preview")
        try:
            selected_variant, selected_sha = preview_ref(run, variant)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        token = preview_access.issue(preview_scope(tenant, run_id, selected_variant))
        preview_url = str(request.url_for(
            "workspace_design_preview",
            run_id=str(run_id),
            file_path="index.html",
        ))
        separator = "&" if "?" in preview_url else "?"
        preview_url = (
            f"{preview_url}{separator}preview_token={token}&variant={selected_variant}"
        )
        return JSONResponse(
            {
                "token": token,
                "expires_in": preview_access.ttl,
                "variant": selected_variant,
                "candidate_sha": selected_sha,
                "preview_url": preview_url,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get(f"{prefix}/design/runs/{{run_id}}/pages")
    def workspace_design_pages(
        run_id: str,
        request: Request,
        variant: str = "deepseek",
    ):
        tenant = require_service(request)
        design_service = design_service_for(tenant)
        try:
            run = design_service.get_run(str(run_id))
        except Exception as exc:  # noqa: BLE001 - normalize service-specific lookup errors
            raise HTTPException(status_code=404, detail="design run was not found") from exc
        if not candidate_is_previewable(run):
            raise HTTPException(status_code=409, detail="design run is not ready for preview")
        try:
            selected_variant, selected_sha = preview_ref(run, variant)
            artifact_root = (
                output_artifact_root(design_service, run)
                if selected_variant == "deepseek"
                else None
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        clone = Path(design_service.clone_path_for_run(str(run_id))).expanduser().resolve()
        if artifact_root is not None:
            pages = sorted(
                str(path.relative_to(artifact_root).as_posix())
                for path in artifact_root.rglob("*")
                if path.is_file() and path.suffix.lower() in {".html", ".htm"}
            )
        else:
            if not clone.exists() or not (clone / ".git").exists():
                raise HTTPException(status_code=404, detail="design candidate clone is unavailable")
            pages = list_html_at(clone, selected_sha)
        return {
            "pages": list(dict.fromkeys(pages)),
            "variant": selected_variant,
            "ref": selected_sha,
            "base_sha": run.get("base_sha"),
            "candidate_sha": run.get("candidate_sha"),
        }

    @app.get(
        f"{prefix}/design/runs/{{run_id}}/preview/{{file_path:path}}",
        name="workspace_design_preview",
    )
    def workspace_design_preview(run_id: str, file_path: str, request: Request):
        """Serve the exact candidate artifact through a short-lived capability."""
        tenant, variant, token = require_preview_scope(request, run_id)
        design_service = design_service_for(tenant)
        try:
            run = design_service.get_run(str(run_id))
        except Exception as exc:  # noqa: BLE001 - do not disclose tenant state
            raise HTTPException(status_code=404, detail="design run was not found") from exc
        if not candidate_is_previewable(run):
            raise HTTPException(status_code=409, detail="design run is not ready for preview")
        try:
            content, media_type = render_candidate_file(
                design_service,
                run,
                file_path,
                variant=variant,
                access_token=token,
                preview_root=f"{prefix}/design/runs/{run_id}/preview/",
                site_url=str(((tenant.config.get("site") or {}).get("url") or (tenant.config.get("site") or {}).get("preview_url") or "")),
                preview_cache=preview_cache,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Preview-Candidate-SHA": str(run.get("candidate_sha") or ""),
            },
        )

    @app.post(f"{prefix}/design/runs/{{run_id}}/review")
    def workspace_design_review(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.create_design_review(run_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/runs/{{run_id}}/revalidate")
    def workspace_design_revalidate(run_id: str, request: Request):
        tenant = require_service(request)
        if tenant is None or tenant.design_executor is None:
            raise HTTPException(status_code=503, detail="tenant design worker is unavailable")
        try:
            run = design_service_for(tenant).prepare_revalidation(run_id)
            tenant.design_executor.enqueue(run_id)
            return {"run_id": run["run_id"], "candidate_sha": run["candidate_sha"], "status": run["status"]}
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)[:500]) from exc

    @app.get(f"{prefix}/drafts")
    def workspace_drafts(request: Request, status: str | None = None, limit: int = 50):
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
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/connection")
    def workspace_connection(request: Request):
        tenant = require_service(request)
        return service.connection(tenant=tenant)

    @app.get(f"{prefix}/growth")
    def workspace_growth(request: Request):
        tenant = require_service(request)
        return service.growth(tenant=tenant)

    @app.get(f"{prefix}/intelligence")
    def workspace_intelligence(request: Request):
        tenant = require_service(request)
        try:
            result = service.intelligence_summary(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return JSONResponse(result, status_code=503 if result.get("state") == "unavailable" else 200,
                            headers={"Cache-Control": "no-store"})

    @app.get(f"{prefix}/growth/articles/{{draft_id}}")
    def workspace_growth_article_review(draft_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.growth_article_review(draft_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/growth/check")
    def workspace_growth_check(request: Request):
        tenant = require_service(request)
        try:
            return service.request_growth_check(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/growth/actions/{{action_id}}/decision")
    async def workspace_crawlseo_action_decision(action_id: int, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        actor = authenticated_owner_actor(request, tenant)
        try:
            return service.decide_crawlseo_action(action_id, body, tenant=tenant, owner_actor_id=actor)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/growth/actions")
    def workspace_crawlseo_actions(request: Request):
        tenant = require_service(request)
        try:
            return service.crawlseo_actions(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(f"{prefix}/growth/opportunities")
    def workspace_growth_opportunities(request: Request, status: str | None = None,
                                       cursor: str | None = None, limit: int = 50):
        tenant = require_service(request)
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
        try:
            return service.growth_opportunities(tenant=tenant, status=status, cursor=cursor, limit=limit)
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(f"{prefix}/growth/opportunities/{{opportunity_id}}/decision")
    async def workspace_growth_opportunity_decision(opportunity_id: str, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.decide_crawlseo_opportunity(
                opportunity_id, body, tenant=tenant, owner_actor_id=authenticated_owner_actor(request, tenant))
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/growth/tasks/{{task_id}}")
    def workspace_growth_task(task_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.crawlseo_task(task_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(f"{prefix}/growth/tasks/{{task_id}}")
    async def workspace_growth_task_confirmation(task_id: str, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.confirm_crawlseo_task(
                task_id, body, tenant=tenant, owner_actor_id=authenticated_owner_actor(request, tenant))
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/growth/budget")
    def workspace_crawlseo_research_budget(request: Request):
        tenant = require_service(request)
        try:
            return service.crawlseo_research_budget(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(f"{prefix}/growth/research-policy")
    def workspace_crawlseo_research_policy(request: Request):
        tenant = require_service(request)
        try:
            return service.crawlseo_research_policy(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.put(f"{prefix}/growth/research-policy")
    async def workspace_update_crawlseo_research_policy(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        actor = authenticated_owner_actor(request, tenant)
        try:
            return service.update_crawlseo_research_policy(body, tenant=tenant, owner_actor_id=actor)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put(f"{prefix}/growth/budget")
    async def workspace_update_crawlseo_research_budget(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        actor = authenticated_owner_actor(request, tenant)
        try:
            return service.update_crawlseo_research_budget(body, tenant=tenant, owner_actor_id=actor)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/seo/insights")
    def workspace_seo_insights(request: Request, limit: int = 12):
        tenant = require_service(request)
        try:
            return service.seo_insights(limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/seo/analytics")
    def workspace_seo_analytics(request: Request, days: int | None = None):
        tenant = require_service(request)
        providers = tenant.config.get("providers") if tenant is not None and isinstance(tenant.config.get("providers"), dict) else {}
        crawlseo = providers.get("crawlseo") if isinstance(providers.get("crawlseo"), dict) else {}
        if crawlseo.get("research_authority") == "crawlseo":
            # GA4/GSC measurements belong to CrawlSEO after cutover. Read its
            # saved observations; never query the old HelloAda Google client as
            # a hidden fallback, and never fabricate an empty success.
            start_date = end_date = None
            if days is not None:
                if not 1 <= days <= 366:
                    raise HTTPException(status_code=400, detail="days must be between 1 and 366")
                end = datetime.datetime.now(datetime.timezone.utc).date()
                start_date = (end - datetime.timedelta(days=days - 1)).isoformat()
                end_date = end.isoformat()
            try:
                payload = service.crawlseo_performance(tenant=tenant, start_date=start_date, end_date=end_date)
            except BridgeError as exc:
                return {"authority": "crawlseo", "capability": "analytics.read", "status": "unavailable",
                        "reason": str(exc)[:240], "ga4": None, "gsc": None}
            return {"authority": "crawlseo", "capability": "analytics.read", "status": "available", **payload}
        try:
            return analytics_for(tenant).report(days=days)
        except AnalyticsError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except GooglePlatformError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get(f"{prefix}/seo/evidence")
    def workspace_growth_evidence(request: Request, section: str = "research"):
        tenant = require_service(request)
        if section not in ("research", "health", "competition"):
            raise HTTPException(status_code=400, detail="unknown growth evidence section")
        provider = tenant.context.get("crawlseo_service") if tenant else None
        if provider is None:
            raise HTTPException(status_code=503, detail="CrawlSEO is not configured for this tenant")
        return {"tenant": tenant.tenant_id, **growth_evidence(provider, section)}

    @app.get(f"{prefix}/seo/access")
    def workspace_seo_access(request: Request):
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
    async def workspace_seo_access_grant(request: Request):
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
    async def workspace_seo_access_revoke(request: Request):
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
    def workspace_approve_draft(draft_id: int, request: Request, body: dict[str, Any] | None = Body(default=None)):
        tenant = require_service(request)
        try:
            return service.approve_draft(draft_id, tenant=tenant, review_package_hash=(body or {}).get("review_package_hash"), owner_actor_id=authenticated_owner_actor(request, tenant))
        except (BridgeError, GrowthDeliveryError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/drafts/{{draft_id}}/discard")
    def workspace_discard_draft(draft_id: int, request: Request, body: dict[str, Any] | None = Body(default=None)):
        tenant = require_service(request)
        try:
            return service.discard_draft(draft_id, tenant=tenant, review_package_hash=(body or {}).get("review_package_hash"), owner_actor_id=authenticated_owner_actor(request, tenant))
        except (BridgeError, GrowthDeliveryError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/versions/{{version_id}}/restore")
    def workspace_restore_version(version_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.restore_version(version_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/publication")
    def workspace_publication(request: Request):
        tenant = require_service(request)
        try:
            return service.publication(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/checkpoints")
    def workspace_checkpoints(request: Request, limit: int = 30):
        tenant = require_service(request)
        try:
            return service.checkpoints(limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/checkpoints/restore")
    def workspace_restore_checkpoint(request: Request, body: dict[str, Any] | None = Body(default=None)):
        tenant = require_service(request)
        payload = body or {}
        try:
            return service.restore_checkpoint(
                payload.get("commit"),
                summary=str(payload.get("summary") or "") or None,
                tenant=tenant,
            )
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/media/analyze")
    async def workspace_analyze_media(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            # Vision and Payload calls are blocking I/O. Do not freeze every
            # tenant's conversation while a provider reads an uploaded image.
            return await asyncio.to_thread(service.analyze_media, body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/media")
    def workspace_media(request: Request, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.media(limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/inventory")
    def workspace_source_inventory_get(request: Request, branch: str | None = None):
        tenant = require_service(request)
        try:
            body = {"branch": branch} if branch else {}
            return service.source_inventory(body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/source/inventory")
    async def workspace_source_inventory(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.source_inventory(body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/source/edit")
    async def workspace_source_edit(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.source_edit(body, tenant=tenant)
        except SourceConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -- the compiled candidate's own origin -------------------------------
    #
    # A preview is a complete Next application, so it is served from its own
    # host at a signed path rather than through the workspace bridge. This
    # service owns the URL and the runtime behind it, so a request is forwarded
    # and never interpreted: no basePath is re-derived, no asset or redirect is
    # rewritten, and an address from an older workspace cannot collide with the
    # app's routes or its CMS. The signature in the path is the capability, so
    # the frame needs no cookie and the address stops working on its own.
    def preview_page(status: int, title: str, detail: str) -> HTMLResponse:
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 32px;
  background: #0d0f13; color: #e8e6e1;
  font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 460px; }}
p.eyebrow {{ margin: 0 0 14px; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; color: #8d8f96; }}
h1 {{ margin: 0 0 12px; font-size: 22px; line-height: 1.25; font-weight: 600; }}
p.detail {{ margin: 0; color: #a9abb2; }}
@media (prefers-color-scheme: light) {{
  body {{ background: #faf8f4; color: #1b1d21; }} p.eyebrow {{ color: #6f7178; }} p.detail {{ color: #55575e; }}
}}
</style></head><body><main>
<p class="eyebrow">HelloAda</p><h1>{title}</h1><p class="detail">{detail}</p>
</main></body></html>"""
        return HTMLResponse(body, status_code=status, headers={"cache-control": "no-store"})

    def preview_runtime_response(
        owner: str,
        job_id: str,
        expires: str,
        signature: str,
        file_path: str,
        request: Request,
    ):
        try:
            key = preview_host.signing_key(env)
        except preview_host.PreviewHostError:
            return preview_page(503, "This preview is unavailable", "The preview host is not configured.")
        if not preview_host.verify(key, owner, job_id, expires, signature):
            return preview_page(
                404,
                "This preview is no longer available",
                "The address has expired or belongs to an earlier version of the workspace. "
                "Reload the workspace and rebuild the preview.",
            )
        # The address names its tenant, so the request does not depend on an
        # earlier browser call or on this process having served the build.
        tenant = registry.for_tenant_id(preview_host.tenant_id(owner)) if registry is not None else None
        if registry is not None and tenant is None:
            return preview_page(
                404,
                "This preview is no longer available",
                "Its workspace is not registered on this host any more.",
            )
        try:
            result = service.source_preview_runtime(
                job_id,
                file_path,
                request.url.query,
                {
                    "Accept": request.headers.get("accept", ""),
                    "User-Agent": request.headers.get("user-agent", ""),
                    "RSC": request.headers.get("rsc", ""),
                    "Next-Router-State-Tree": request.headers.get("next-router-state-tree", ""),
                    "Next-Router-Prefetch": request.headers.get("next-router-prefetch", ""),
                    "Next-Router-Segment-Prefetch": request.headers.get("next-router-segment-prefetch", ""),
                    "Next-Url": request.headers.get("next-url", ""),
                    "Purpose": request.headers.get("purpose", ""),
                    "X-Nextjs-Data": request.headers.get("x-nextjs-data", ""),
                },
                tenant=tenant,
            )
        except BridgeError:
            return preview_page(
                409,
                "This preview is not running",
                "The build finished or the preview service restarted. Rebuild the preview from the workspace.",
            )
        headers = {
            "Content-Type": str(result.get("content_type") or "application/octet-stream"),
            "Cache-Control": "private, no-store",
            "X-Preview-Commit": str(result.get("commit") or ""),
        }
        location = str(result.get("location") or "")
        if location:
            headers["Location"] = location
        return Response(
            content=result.get("body") or b"",
            status_code=int(result.get("status") or 502),
            headers=headers,
        )

    preview_route = f"{preview_host.PREVIEW_PREFIX}/{{owner}}/{{job_id}}/{{expires}}/{{signature}}"

    @app.api_route(preview_route, methods=["GET", "HEAD"])
    def workspace_preview_runtime_root(owner: str, job_id: str, expires: str, signature: str, request: Request):
        return preview_runtime_response(owner, job_id, expires, signature, "", request)

    @app.api_route(preview_route + "/{file_path:path}", methods=["GET", "HEAD"])
    def workspace_preview_runtime(owner: str, job_id: str, expires: str, signature: str, file_path: str, request: Request):
        return preview_runtime_response(owner, job_id, expires, signature, file_path, request)

    @app.get(f"{prefix}/source/preview/styles")
    def workspace_source_preview_styles(request: Request):
        tenant = require_service(request)
        try:
            return service.source_preview_styles(tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview")
    def workspace_source_preview_latest(request: Request, branch: str | None = None):
        tenant = require_service(request)
        try:
            return service.source_preview_latest(branch, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(f"{prefix}/source/preview")
    async def workspace_source_preview(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.source_preview_start(body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview/{{job_id}}")
    def workspace_source_preview_status(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.source_preview_status(job_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/jobs/{{job_id}}")
    def workspace_chat_job(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.job(job_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    if control_prefix:
        control_prefix = "/" + control_prefix.strip("/")

        @app.get(f"{control_prefix}/{{website_id}}/growth/migration-plan")
        def control_plane_crawlseo_migration_plan(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.crawlseo_migration_plan(tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/intelligence")
        def control_plane_intelligence(website_id: str, request: Request):
            """Return available intelligence, not_started before records exist, or unavailable on failure.

            An unregistered website and a registered tenant with no canonical
            knowledge/research are lifecycle states, not service failures.
            """
            require_control_plane(request)
            if registry is None:
                raise HTTPException(status_code=503, detail="tenant registry is unavailable")
            tenant = registry.for_tenant_id(website_id)
            if tenant is None:
                result = {"state": "not_started", "reason": "tenant is not registered yet"}
                return JSONResponse(result, status_code=200, headers={"Cache-Control": "no-store"})
            try:
                result = service.intelligence_summary(tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            return JSONResponse(result, status_code=503 if result.get("state") == "unavailable" else 200,
                                headers={"Cache-Control": "no-store"})

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/resolutions")
        async def control_plane_crawlseo_migration_resolution(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_resolution(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/configuration")
        async def control_plane_crawlseo_migration_configuration(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_configuration(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/activation")
        async def control_plane_crawlseo_migration_activation(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_activation(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/freeze")
        async def control_plane_crawlseo_migration_freeze(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_producer_freeze(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/verify-routes")
        async def control_plane_crawlseo_migration_verify_routes(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_verify_routes(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/import-budget-policy")
        async def control_plane_import_budget_policy(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_import_budget_policy(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/verify-budget-import")
        async def control_plane_crawlseo_migration_verify_budget_import(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.crawlseo_migration_verify_budget_import(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/migration/references/initiative-4-owner-fact-conversation")
        async def control_plane_confirm_crawlseo_migration_reference(website_id: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.confirm_crawlseo_migration_reference(body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/initiatives/{{initiative_id}}/retire-revision")
        async def control_plane_retire_growth_revision(website_id: str, initiative_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.retire_growth_revision(initiative_id, body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/initiatives/{{initiative_id}}/retire-preparation")
        async def control_plane_retire_growth_preparation(website_id: str, initiative_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.retire_growth_preparation(initiative_id, body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/growth/drafts/{{draft_id}}/archive")
        async def control_plane_archive_growth_article(website_id: str, draft_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            try:
                return service.archive_local_growth_article(draft_id, body, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

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
            if "github_repository" in body and not isinstance(body["github_repository"], str):
                raise HTTPException(status_code=400, detail="github_repository must be a string")
            try:
                receipt = registration.register(
                    website_id,
                    display_name=str(body.get("display_name") or "").strip(),
                    env=env,
                    **({"github_repository": body["github_repository"]} if "github_repository" in body else {}),
                )
                # Paths and token environment names are host-only details. The
                # control-plane caller only needs the durable tenant identity
                # and schema/status receipt.
                return {
                    "tenant_id": receipt.get("tenant_id"),
                    "schema_version": receipt.get("schema_version"),
                    "status": receipt.get("status"),
                    "created": receipt.get("created"),
                    "provisioning_source": receipt.get("provisioning_source"),
                }
            except TenantRegistrationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/site-origin")
        async def control_plane_update_site_origin(website_id: str, request: Request):
            """Change one tenant's public origin and reconcile its providers."""
            require_control_plane(request)
            if registry is None:
                raise HTTPException(status_code=503, detail="tenant registry is unavailable")
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            public_url = str(
                body.get("public_url")
                or body.get("custom_domain")
                or body.get("site_url")
                or ""
            ).strip()
            if not public_url:
                raise HTTPException(status_code=400, detail="public_url is required")
            try:
                tenant = registry.update_site_origin(website_id, public_url, env=env)
            except ConfigError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            state = tenant.context.get("seo_provisioning_state") or tenant.memory.kv_get("seo_provisioning_state", {}) or {}
            return {
                "tenant_id": tenant.tenant_id,
                "public_url": str((tenant.config.get("site") or {}).get("public_url") or ""),
                "seo": {
                    "state": state.get("state") or state.get("provisioning_state") or "pending",
                    "site_url": state.get("site_url"),
                    "gsc_property": state.get("gsc_property"),
                    "gsc_verified": bool(state.get("gsc_verified")),
                    "ga4_property_id": state.get("ga4_property_id"),
                    "crawlseo_ready": bool(state.get("crawlseo")),
                },
            }

        @app.post(f"{control_prefix}/{{website_id}}/bootstrap")
        async def control_plane_bootstrap(website_id: str, request: Request):
            require_control_plane(request)
            if registration is None or bootstrap is None:
                raise HTTPException(status_code=503, detail="website bootstrap is unavailable")
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            if "github_repository" in body and not isinstance(body["github_repository"], str):
                raise HTTPException(status_code=400, detail="github_repository must be a string")
            try:
                result = bootstrap.start(
                    website_id,
                    display_name=str(body.get("display_name") or "").strip(),
                    **({"github_repository": body["github_repository"]} if "github_repository" in body else {}),
                )
            except (BootstrapError, TenantRegistrationError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            status_code = 200 if result.get("status") == "done" else 202
            return JSONResponse(result, status_code=status_code)

        @app.get(f"{control_prefix}/{{website_id}}/bootstrap")
        def control_plane_bootstrap_status(website_id: str, request: Request):
            require_control_plane(request)
            if registration is None or bootstrap is None:
                raise HTTPException(status_code=503, detail="website bootstrap is unavailable")
            try:
                registered = registration.is_registered(website_id)
            except TenantRegistrationError as exc:
                raise HTTPException(status_code=503, detail="website registration state is unavailable") from exc
            if not registered:
                raise HTTPException(status_code=404, detail="website was not found")
            try:
                return bootstrap.status(website_id)
            except BootstrapError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/activate-runtime")
        async def control_plane_activate_runtime(website_id: str, request: Request):
            """Mount a pending tenant after its exact Worker health receipt passes."""
            require_control_plane(request)
            if registration is None or bootstrap is None:
                raise HTTPException(status_code=503, detail="website bootstrap is unavailable")
            try:
                body = await request.json()
            except Exception:
                body = None
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="request body must be an object")
            release_id = str(body.get("release_id") or "").strip()
            source_sha = str(body.get("source_sha") or "").strip()
            verification = body.get("verification")
            if not release_id or not source_sha:
                raise HTTPException(status_code=400, detail="release_id and source_sha are required")
            if verification is not None and not isinstance(verification, dict):
                raise HTTPException(status_code=400, detail="verification must be an object")
            try:
                return bootstrap.activate_runtime_after_health(
                    website_id,
                    release_id=release_id,
                    source_sha=source_sha,
                    verification=verification,
                )
            except (BootstrapError, TenantRegistrationError) as exc:
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
            except BridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/chat/status")
        def control_plane_chat_status(website_id: str, request: Request, conversation_id: int | None = None):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.status(conversation_id, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/history")
        def control_plane_history(website_id: str, request: Request, limit: int = 50):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.history(limit=limit, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/versions/{{version_id}}/restore")
        def control_plane_restore_version(website_id: str, version_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.restore_version(version_id, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/drafts/{{draft_id}}/approve")
        def control_plane_approve_draft(website_id: str, draft_id: int, request: Request, body: dict[str, Any] | None = Body(default=None)):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.approve_draft(draft_id, tenant=tenant, review_package_hash=(body or {}).get("review_package_hash"), owner_actor_id=authenticated_owner_actor(request, tenant))
            except (BridgeError, GrowthDeliveryError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        # One trusted gateway for the owner workspace. The browser talks to the
        # HelloAda control plane; that server authenticates with its own token
        # and names the tenant. This gateway injects the tenant's workspace
        # token for the canonical API, so the tenant token never reaches a
        # browser and the normal /api/workspace auth contract is unchanged.
        gateway_prefix = control_prefix.rstrip("/") + "/"

        @app.middleware("http")
        async def control_plane_workspace_gateway(request: Request, call_next):
            path = request.url.path
            if not path.startswith(gateway_prefix):
                return await call_next(request)
            website_id, separator, suffix = path[len(gateway_prefix):].partition("/workspace/")
            if not separator or not website_id or not suffix:
                return await call_next(request)
            try:
                require_control_plane(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            if registry is None:
                return JSONResponse({"detail": "tenant registry is unavailable"}, status_code=503)
            tenant = registry.for_tenant_id(website_id)
            if tenant is None:
                return JSONResponse({"detail": "website was not found"}, status_code=404)
            request.scope["path"] = f"{prefix}/{suffix}"
            headers = [(name, value) for name, value in request.scope["headers"]
                       if name.lower() != b"authorization"]
            headers.append((b"authorization", f"Bearer {tenant.api_token}".encode()))
            request.scope["headers"] = headers
            return await call_next(request)

        # The tenant Worker owns the owner-visible site: Payload documents,
        # committed routes, previews, media and the Ada bridge. The control
        # plane reaches that same workspace with the tenant workspace token and
        # the HelloAda subject it has already authenticated. This is the only
        # server-to-server path; a browser never holds the tenant token.
        @app.api_route(
            f"{control_prefix}/{{website_id}}/worker/{{suffix:path}}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )
        async def control_plane_worker_gateway(website_id: str, suffix: str, request: Request):
            tenant = require_control_tenant(request, website_id)
            subject = request.headers.get("x-helloada-owner-subject", "").strip()
            if not subject:
                raise HTTPException(status_code=400, detail="control-plane workspace request requires an owner subject")
            if not suffix or ".." in suffix.split("/"):
                raise HTTPException(status_code=400, detail="workspace path is invalid")
            site = tenant.config.get("site") or {}
            payload_settings = site.get("payload") or {}
            base_url = str(payload_settings.get("url") or "").rstrip("/")
            if not base_url:
                raise HTTPException(status_code=503, detail="the website workspace is not configured")
            query = request.url.query
            url = f"{base_url}/api/helloada/{suffix}" + (f"?{query}" if query else "")
            body = await request.body()
            forwarded = {
                "authorization": f"Bearer {tenant.api_token}",
                "x-helloada-owner-subject": subject,
                "accept": request.headers.get("accept", "application/json"),
                # Cloudflare rejects the default Python client signature.
                "user-agent": "site-agent/control-plane-workspace",
            }
            content_type = request.headers.get("content-type")
            if content_type:
                forwarded["content-type"] = content_type
            def send():
                outbound = urllib.request.Request(url, data=body or None, headers=forwarded,
                                                  method=request.method)
                try:
                    return urllib.request.urlopen(outbound, timeout=60)
                except urllib.error.HTTPError as exc:  # a workspace error is a response
                    return exc

            try:
                upstream = await asyncio.to_thread(send)
            except (OSError, urllib.error.URLError) as exc:
                raise HTTPException(status_code=503, detail="the website workspace is unavailable") from exc
            data = await asyncio.to_thread(upstream.read)
            response = Response(content=data, status_code=upstream.status,
                                headers={"cache-control": "no-store"})
            # Representation headers the owner surface needs verbatim: the
            # attachment filename, type and a candidate redirect must survive
            # the control plane.
            for header in ("content-type", "content-disposition", "content-length", "location"):
                value = upstream.headers.get(header)
                if value:
                    response.headers[header] = value
            for cookie in upstream.headers.get_all("set-cookie") or []:
                response.headers.append("set-cookie", cookie)
            return response


def create_workspace_api_app(
    registry: TenantRegistry,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    prefix: str = "/v1/workspace",
    control_token: str | None = None,
    registration: TenantRegistrationService | None = None,
    bootstrap: WebsiteBootstrapService | None = None,
) -> FastAPI:
    """Create the single shared, tenant-aware API process."""

    host_config = dict(config or {})
    host_env = dict(env or {})

    async def ensure_preview_host() -> None:
        """Give the preview host its public record without a manual step.

        The address follows the API's own host, so a fresh installation gets a
        working preview origin on first start. A Cloudflare outage must not stop
        the API from serving; the failure is reported and retried next start.
        """
        if not host_env.get(preview_host.PREVIEW_HOST_ENV):
            return
        try:
            record = await asyncio.to_thread(preview_host.ensure_preview_host_dns, host_env, config=host_config)
        except preview_host.PreviewHostError as exc:
            print(f"[site-agent] preview host not provisioned: {exc}")
            return
        print(f"[site-agent] preview host {record['host']} -> {record['target']} (proxied)")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        registry.start()
        await ensure_preview_host()
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

    @app.get("/healthz")
    async def healthz():
        """Expose only process readiness for the VPS API release gate.

        This must stay ``async``: a synchronous handler runs in the shared
        worker pool, so a stalled pool made the liveness probe itself time out
        and the whole service look dead while the event loop was still healthy.
        """
        return {"ok": True}

    register_workspace_routes(
        app,
        config=host_config,
        env=host_env,
        service=ChatService(registry=registry),
        registry=registry,
        prefix=prefix,
        control_prefix="/v1/control-plane/websites",
        control_token=control_token,
        registration=registration,
        bootstrap=bootstrap,
    )
    return app


__all__ = [
    "create_workspace_api_app",
    "register_workspace_routes",
]
