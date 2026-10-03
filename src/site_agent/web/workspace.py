"""The narrow server-to-server bridge used by the owner workspace.

This module intentionally does not share the browser's password session. The
Payload server calls these endpoints with a dedicated bearer token, while the
existing admin API and Intake Lab routes keep their current authentication and
behavior.
The route prefix remains configurable because the first customer still uses
``/v1/workspace``.  The implementation itself is not customer-specific.
"""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..application.analytics import AnalyticsError, GoogleAnalyticsService
from ..application.growth_evidence import growth_evidence
from ..application.bootstrap import BootstrapError, WebsiteBootstrapService
from ..application.tenant_registration import TenantRegistrationError, TenantRegistrationService
from ..application.workspace import BridgeError, ChatService, SourceConflict, Tenant, TenantRegistry
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

    def source_preview_response(value: Any) -> Any:
        """Bind relative preview paths to this API's configured prefix."""
        if not isinstance(value, dict):
            return value
        result = dict(value)
        canonical = "/api/workspace"
        for key in ("runtime_path", "preview_url"):
            raw = result.get(key)
            if isinstance(raw, str) and raw.startswith(canonical):
                result[key] = prefix + raw[len(canonical):]
        return result

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

    @app.get(f"{prefix}/chat/status")
    def workspace_chat_status(request: Request, conversation_id: int | None = None):
        tenant = require_service(request)
        try:
            return service.status(conversation_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/chat/intake/confirm")
    async def workspace_intake_confirm(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.confirm_intake(body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/chat/design/start")
    async def workspace_design_start(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalize malformed bridge input
            raise HTTPException(status_code=400, detail="invalid json")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.start_first_page(body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/recommendations")
    def workspace_design_recommendations(request: Request, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.recommendations(limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/direction")
    async def workspace_design_direction(request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.propose_direction(body, tenant=tenant)
        except BridgeError as exc:
            status = 409 if "must be accepted" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/recommendations/{{action_id}}/accept")
    async def workspace_accept_design_recommendation(action_id: int, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.accept_recommendation(action_id, body, tenant=tenant)
        except BridgeError as exc:
            status = 409 if "stale" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post(f"{prefix}/design/recommendations/{{action_id}}/dismiss")
    def workspace_dismiss_design_recommendation(action_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.dismiss_recommendation(action_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/operations")
    def workspace_design_operations(request: Request, status: str | None = None, limit: int = 50):
        tenant = require_service(request)
        try:
            return service.operations(status=status, limit=limit, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/design/operations/{{operation_id}}")
    def workspace_design_operation(operation_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.operation(operation_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
                site_url=str(((tenant.config.get("blog") or {}).get("site_url") or "")),
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

    @app.post(f"{prefix}/design/runs/{{run_id}}/retry")
    async def workspace_design_retry(run_id: str, request: Request):
        tenant = require_service(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            return service.retry_design_run(run_id, body, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @app.post(f"{prefix}/growth/check")
    def workspace_growth_check(request: Request):
        tenant = require_service(request)
        try:
            return service.request_growth_check(tenant=tenant)
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
    def workspace_seo_analytics(request: Request, days: int = 28):
        tenant = require_service(request)
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
            return service.approve_draft(draft_id, tenant=tenant, review_package_hash=(body or {}).get("review_package_hash"))
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/drafts/{{draft_id}}/discard")
    def workspace_discard_draft(draft_id: int, request: Request, body: dict[str, Any] | None = Body(default=None)):
        tenant = require_service(request)
        try:
            return service.discard_draft(draft_id, tenant=tenant, review_package_hash=(body or {}).get("review_package_hash"))
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(f"{prefix}/versions/{{version_id}}/restore")
    def workspace_restore_version(version_id: int, request: Request):
        tenant = require_service(request)
        try:
            return service.restore_version(version_id, tenant=tenant)
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
            return service.analyze_media(body, tenant=tenant)
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
            return source_preview_response(service.source_preview_latest(branch, tenant=tenant))
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
            return source_preview_response(service.source_preview_start(body, tenant=tenant))
        except BridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview/{{job_id}}")
    def workspace_source_preview_status(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return source_preview_response(service.source_preview_status(job_id, tenant=tenant))
        except BridgeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(f"{prefix}/source/preview/{{job_id}}/runtime/{{file_path:path}}")
    def workspace_source_preview_runtime(job_id: str, file_path: str, request: Request):
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
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=result.get("body") or b"",
            status_code=int(result.get("status") or 502),
            headers={
                "Content-Type": str(result.get("content_type") or "application/octet-stream"),
                "Cache-Control": "private, no-store",
                "X-Workspace-Preview-Commit": str(result.get("commit") or ""),
            },
        )

    @app.post(f"{prefix}/source/preview/{{job_id}}/deploy")
    def workspace_source_preview_deploy(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.source_preview_promote(job_id, tenant=tenant)
        except BridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(f"{prefix}/chat/jobs/{{job_id}}")
    def workspace_chat_job(job_id: str, request: Request):
        tenant = require_service(request)
        try:
            return service.job(job_id, tenant=tenant)
        except BridgeError as exc:
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
            try:
                result = bootstrap.start(
                    website_id,
                    display_name=str(body.get("display_name") or "").strip(),
                )
            except (BootstrapError, TenantRegistrationError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            status_code = 200 if result.get("status") == "done" else 202
            return JSONResponse(result, status_code=status_code)

        @app.get(f"{control_prefix}/{{website_id}}/bootstrap")
        def control_plane_bootstrap_status(website_id: str, request: Request):
            require_control_plane(request)
            if registry is None or bootstrap is None or registry.for_tenant_id(website_id) is None:
                raise HTTPException(status_code=404, detail="website was not found")
            try:
                return bootstrap.status(website_id)
            except BootstrapError as exc:
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
            except BridgeError as exc:
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
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/design/recommendations")
        def control_plane_recommendations(website_id: str, request: Request, limit: int = 50):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.recommendations(limit=limit, tenant=tenant)
            except BridgeError as exc:
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
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post(f"{control_prefix}/{{website_id}}/design/recommendations/{{action_id}}/dismiss")
        def control_plane_dismiss_recommendation(website_id: str, action_id: int, request: Request):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.dismiss_recommendation(action_id, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/design/operations")
        def control_plane_operations(website_id: str, request: Request, status: str | None = None, limit: int = 50):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.operations(status=status, limit=limit, tenant=tenant)
            except BridgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.get(f"{control_prefix}/{{website_id}}/history")
        def control_plane_history(website_id: str, request: Request, limit: int = 50):
            tenant = require_control_tenant(request, website_id)
            try:
                return service.history(limit=limit, tenant=tenant)
            except BridgeError as exc:
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
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

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
                return service.approve_draft(draft_id, tenant=tenant, review_package_hash=(body or {}).get("review_package_hash"))
            except BridgeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc


def create_workspace_api_app(
    registry: TenantRegistry,
    *,
    prefix: str = "/v1/workspace",
    control_token: str | None = None,
    registration: TenantRegistrationService | None = None,
    bootstrap: WebsiteBootstrapService | None = None,
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
        bootstrap=bootstrap,
    )
    return app


__all__ = [
    "create_workspace_api_app",
    "register_workspace_routes",
]
