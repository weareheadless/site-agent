"""web/server.py — the admin API + UI.

Password auth with in-memory sessions (the OceanicVibes model): the owner
logs in once, everything else is same-origin cookie. All site mutations
flow through drafts: approve is the only path to a commit.
"""

from __future__ import annotations

import base64
import asyncio
import datetime
import hmac
import json
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from ..application.actions import ActionServiceError, OwnerActionService
from ..application.workspace import ChatService
from ..application.approvals import ApprovalService, ApprovalServiceError, StaleApproval
from ..application.conversations import ConversationBusy, ConversationNotFound, ConversationService, ConversationServiceError
from ..application.designs import DesignRunNotFound, DesignService, DesignServiceError
from ..application.home import HomeService
from ..application.media import MediaServiceError
from ..application.business_knowledge import BusinessKnowledgeError
from ..application.social_posts import (
    SocialBriefError,
    SocialIdempotencyConflict,
    SocialPostError,
    SocialPostBrief,
)
from ..brain.self_model import current_self
from ..config import resolve_secret
from ..credentials import credential_environment
from ..core.contracts import ActionState, ApprovalStatus
from ..core.design_contracts import DesignRunStatus
from ..core.reflect import approve_reflection, effective_persona
from ..hands import file_cache
from ..hands.base import AdapterError, DesignMergeAdapter, MergeAdapter, SiteAdapter, get_adapter
from ..hands.cicero import CiceroClientError
from ..hands.site_build import SiteOutputArtifactStore
from .workspace import register_workspace_routes
from .preview import PreviewAccess, PreviewBuildCache, rewrite_preview_css, rewrite_preview_html, rewrite_preview_js

SESSION_TTL = 12 * 3600
COOKIE = "sa_session"
STATIC_DIR = Path(__file__).parent / "static"


def _site_url(config: dict[str, Any]) -> str:
    site = config.get("site") if isinstance(config.get("site"), dict) else {}
    return str(site.get("url") or site.get("preview_url") or "").rstrip("/")


class Sessions:
    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}

    def create(self) -> str:
        token = secrets.token_hex(32)
        self._tokens[token] = _now() + SESSION_TTL
        return token

    def valid(self, token: str | None) -> bool:
        if not token or token not in self._tokens:
            return False
        if self._tokens[token] < _now():
            del self._tokens[token]
            return False
        return True

    def drop(self, token: str | None) -> None:
        if token:
            self._tokens.pop(token, None)


def _now() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def _password_ok(config: dict[str, Any], supplied: str, env: dict[str, str]) -> bool:
    expected = resolve_secret(config, "admin_password", env)
    if not expected:
        return False
    return hmac.compare_digest(supplied.encode(), expected.encode())


def _git_ref_exists(clone: Path, ref: str) -> bool:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "--verify", ref],
        capture_output=True,
        timeout=30,
    )
    return proc.returncode == 0


def _git_ref_file_exists(clone: Path, ref: str, name: str) -> bool:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(clone), "cat-file", "-e", f"{ref}:{name}"],
        capture_output=True,
        timeout=30,
    )
    return proc.returncode == 0


def _published_ref(clone: Path) -> str:
    return "origin/main" if _git_ref_exists(clone, "origin/main") else "main"


_DESIGN_PREVIEW_REFS = {"original": "base_sha", "deepseek": "candidate_sha"}
_DESIGN_PREVIEW_STATUSES = frozenset({
    DesignRunStatus.CANDIDATE_READY.value,
    DesignRunStatus.VALIDATING.value,
    DesignRunStatus.READY_FOR_REVIEW.value,
    DesignRunStatus.NEEDS_REPAIR.value,
    DesignRunStatus.INCOMPLETE.value,
    DesignRunStatus.INTERRUPTED.value,
    DesignRunStatus.FAILED.value,
    DesignRunStatus.CANCELLED.value,
})


def _design_candidate_is_previewable(run: dict[str, Any]) -> bool:
    """Allow immutable candidate inspection without making it reviewable."""
    return bool(run.get("candidate_sha")) and str(run.get("status") or "") in _DESIGN_PREVIEW_STATUSES


def _design_preview_ref(run: dict[str, Any], variant: str = "deepseek") -> tuple[str, str]:
    """Resolve only the persisted immutable SHA for a design preview variant."""
    normalized = str(variant or "deepseek").strip().lower()
    if normalized not in _DESIGN_PREVIEW_REFS:
        raise HTTPException(status_code=422, detail="variant must be original or deepseek")
    field = _DESIGN_PREVIEW_REFS[normalized]
    ref = str(run.get(field) or "").strip().lower()
    if not ref:
        raise HTTPException(status_code=409, detail=f"design run has no {normalized} preview SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise HTTPException(status_code=409, detail=f"design run {field} is invalid")
    return normalized, ref


def _design_build_profile(design_service: Any, run: dict[str, Any], variant: str) -> str:
    """Resolve the only supported design build profile from its frozen run."""
    resolver = getattr(design_service, "build_profile_for_run", None)
    if not callable(resolver):
        raise HTTPException(status_code=409, detail="design service cannot resolve the frozen build profile")
    try:
        profile = str(resolver(str(run.get("run_id") or "")) or "").strip()
    except DesignServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if profile != "next_react":
        raise HTTPException(status_code=409, detail="design run has no canonical next_react profile")
    return profile


def _design_output_artifact(design_service: Any, run: dict[str, Any]) -> Path | None:
    """Resolve the immutable candidate output required by owner review."""
    if not bool(run.get("artifact_required")):
        raise HTTPException(status_code=409, detail="design run has no retained canonical output artifact")
    artifact_id = str(run.get("output_artifact_id") or "").strip()
    tree_hash = str(run.get("output_tree_hash") or "").strip().lower()
    if not artifact_id or not tree_hash:
        raise HTTPException(status_code=409, detail="design output artifact is not retained")
    store = getattr(design_service, "output_artifact_store", None)
    resolver = getattr(store, "resolve", None)
    if not callable(resolver):
        raise HTTPException(status_code=409, detail="design output artifact store is unavailable")
    try:
        artifact = resolver(artifact_id)
    except Exception as exc:  # noqa: BLE001 - do not fall back to a rebuild
        raise HTTPException(status_code=409, detail="design output artifact is unavailable") from exc
    if str(getattr(artifact, "tree_hash", "") or "").strip().lower() != tree_hash:
        raise HTTPException(status_code=409, detail="design output artifact identity does not match the run")
    path = Path(getattr(artifact, "path", "")).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=409, detail="design output artifact is unavailable")
    return path


DEFAULT_ADMIN_THEME = {
    "bg": "#f6f8f4",
    "card": "#fffefa",
    "panel": "#eaf3f0",
    "line": "#c8d8d2",
    "text": "#132a28",
    "dim": "#607571",
    "accent": "#0b6968",
    "brand": "#e75c48",
    "ok": "#16745e",
    "warn": "#99631d",
    "bad": "#b63f4b",
    "radius": "8px",
    "font_body": "'Manrope', Avenir Next, Inter, ui-sans-serif, sans-serif",
    "font_display": "'Cormorant Garamond', Iowan Old Style, Palatino Linotype, Georgia, serif",
    "fonts_url": "",
    "logo": "",
}


def _admin_theme(config: dict[str, Any]) -> dict[str, Any]:
    """Per-site brand theme served to the admin UI. Any field can be overridden
    in config under `admin.theme` (admin UI) and `site.brand` (fonts/logo)."""
    theme = dict(DEFAULT_ADMIN_THEME)
    admin_theme = (config.get("admin") or {}).get("theme") or {}
    if isinstance(admin_theme, dict):
        theme.update({k: v for k, v in admin_theme.items() if v not in (None, "")})
    brand = config.get("site", {}).get("brand") or {}
    if isinstance(brand, dict):
        for key in ("font_body", "font_display", "fonts_url", "logo"):
            if brand.get(key):
                theme[key] = brand[key]
    return theme


def create_app(context: dict[str, Any], env: dict[str, str] | None = None) -> FastAPI:
    import os

    config = context["config"]
    env = credential_environment(config, os.environ if env is None else env)
    memory: Any = context["memory"]
    home_service = context.get("home_service") or HomeService(memory)
    owner_action_service = context.get("owner_action_service") or OwnerActionService(memory)
    approval_service = context.get("approval_service") or ApprovalService(
        memory,
        actions=owner_action_service,
        capabilities=context.get("capability_registry"),
    )
    conversation_service = context.get("conversation_service") or ConversationService(memory)
    social_post_service = context.get("social_post_service")
    media_service = context.get("media_service")
    knowledge_service = context.get("business_knowledge_service")
    design_service = context.get("design_service") or DesignService(
        memory,
        config=config,
        output_artifact_store=SiteOutputArtifactStore(
            Path(str(config.get("data_dir") or ".")).expanduser().resolve() / "design-output-artifacts"
        ),
    )
    if getattr(design_service, "media_service", None) is None:
        design_service.media_service = media_service
    context.setdefault("home_service", home_service)
    context.setdefault("owner_action_service", owner_action_service)
    context.setdefault("approval_service", approval_service)
    context.setdefault("conversation_service", conversation_service)
    context.setdefault("design_service", design_service)
    conversation_service.media_service = media_service
    if social_post_service is not None:
        context.setdefault("social_post_service", social_post_service)
    sessions = Sessions()
    preview_access = PreviewAccess()
    preview_root = Path(str(config.get("data_dir") or ".")).expanduser().resolve() / ".preview-builds"
    preview_cache = PreviewBuildCache(temp_root=preview_root)

    def _add_social_preview_urls(result: dict[str, Any], request: Request) -> None:
        artifact = result.get("artifact") or {}
        if artifact.get("kind") != "social_post":
            return
        artifact_id = artifact.get("id")
        data = artifact.get("preview_data") or {}
        if not artifact_id or not isinstance(data, dict):
            return
        for item in data.get("preview_assets") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                item["url"] = str(request.url_for(
                    "social_artifact_asset", artifact_id=artifact_id, filename=item["name"]
                ))
    def current_token(request: Request) -> str | None:
        return request.cookies.get(COOKIE)

    def require_auth(request: Request) -> None:
        if not sessions.valid(current_token(request)):
            raise HTTPException(status_code=401, detail="authentication required")

    def require_preview_auth(request: Request, scope: tuple[str, int]) -> str | None:
        token = (request.query_params.get("preview_token") or "").strip()
        if sessions.valid(current_token(request)):
            return token if preview_access.valid(token, scope) else None
        if preview_access.valid(token, scope):
            return token
        raise HTTPException(status_code=401, detail="authentication required")

    def preview_headers(token: str | None) -> dict[str, str]:
        headers = {"Cache-Control": "no-store"}
        if token:
            headers.update({
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Content-Security-Policy": "sandbox allow-scripts allow-forms; frame-ancestors 'self'",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            })
        return headers

    def adapter() -> SiteAdapter:
        try:
            return get_adapter(str(config.get("site", {}).get("adapter", "github_static")), config)
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    def adapter_validated() -> SiteAdapter:
        ad = adapter()
        try:
            ad.validate()
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ad

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from ..core.chat_jobs import ChatJobExecutor
        from ..application.design_jobs import DesignJobExecutor

        runtime = context.get("runtime")
        executor = None
        design_executor = None
        try:
            if runtime is not None:
                runtime.start()
            # A process killed during a build cannot safely resume its side effects.
            # Surface that work as retryable instead of replaying it automatically.
            memory.interrupt_running_chat_jobs()
            memory.interrupt_running_design_runs()
            design_executor = DesignJobExecutor(context, design_service)
            context["design_executor"] = design_executor
            design_executor.start()
            executor = ChatJobExecutor(context, adapter_factory=adapter)
            executor.start()
            media_worker = None
            if media_service is not None:
                from ..core.media_worker import MediaWorker
                media_worker = MediaWorker(context)
                media_worker.start()
                _app.state._media_worker = media_worker
            _app.state._chat_executor = executor
            _app.state._design_executor = design_executor
            yield
        finally:
            if design_executor is not None:
                design_executor.stop()
                design_executor.join()
            if executor is not None:
                executor.stop()
                executor.join()
            if 'media_worker' in locals() and media_worker is not None:
                media_worker.stop()
                media_worker.join()
            preview_cache.clear()
            _app.state._chat_executor = None
            _app.state._design_executor = None
            context.pop("design_executor", None)
            if runtime is not None:
                runtime.close()

    app = FastAPI(
        title="site-agent admin",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    register_workspace_routes(
        app,
        config=config,
        env=env,
        service=context.get("workspace_service") or ChatService(
            memory,
            context.get("llm"),
            config=config,
            env=env,
        ),
    )

    @app.post("/api/login")
    async def login(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid json")
        supplied = str((body or {}).get("password", ""))
        if not _password_ok(config, supplied, env):
            raise HTTPException(status_code=401, detail="invalid password")
        token = sessions.create()
        response = JSONResponse({"ok": True})
        secure = str(request.url.scheme).lower() == "https"
        response.set_cookie(
            COOKIE, token, httponly=True, samesite="lax",
            secure=secure, max_age=SESSION_TTL,
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        sessions.drop(current_token(request))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/session")
    def session_info(request: Request):
        return {"authenticated": sessions.valid(current_token(request))}

    @app.get("/api/preview-token")
    def preview_token(request: Request, draft_id: int | None = None):
        require_auth(request)
        if draft_id is not None:
            draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail="no such draft")
            scope = ("review", draft_id)
        else:
            scope = ("published", 0)
        return JSONResponse(
            {"token": preview_access.issue(scope), "expires_in": preview_access.ttl},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/status")
    def status(request: Request):
        require_auth(request)
        from ..hands.opencode_runner import worktree_status

        scheduler = context.get("scheduler")
        health = memory.kv_get("last_health", {})
        return {
            "instance": config.get("instance_name", "default"),
            "upcoming": scheduler.upcoming() if scheduler else [],
            "recent_actions": memory.recent_actions(limit=15),
            "health": health,
            "spend_7d": round(memory.llm_spend(since_hours=24 * 7)["cost_usd"], 2),
            "themes": memory.kv_get("themes", []),
            "inner_self": current_self(memory),
            "preview_url": str(config.get("site", {}).get("preview_url", "") or ""),
            "last_preview_url": memory.kv_get("last_preview_url"),
            "preview_branch": str(config.get("site", {}).get("preview_branch", "") or ""),
            "worktree": worktree_status(config),
        }

    @app.get("/api/site/worktree")
    def site_worktree(request: Request):
        require_auth(request)
        from ..hands.opencode_runner import worktree_status

        return worktree_status(config)

    @app.post("/api/site/worktree/discard")
    def discard_site_worktree(request: Request):
        require_auth(request)
        active = memory.list_active_chat_jobs()
        if active:
            raise HTTPException(status_code=409, detail="cannot discard local work while Ada is working")
        from ..hands.opencode_runner import RunnerError, discard_worktree

        try:
            state = discard_worktree(config)
        except RunnerError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        memory.record_action("worktree", "discarded uncommitted local site work")
        return {"ok": True, "worktree": state}

    @app.get("/api/conversations")
    def conversations(request: Request, include_archived: bool = False):
        require_auth(request)
        return {"conversations": conversation_service.list(include_archived=include_archived)}

    @app.post("/api/conversations")
    async def new_conversation(request: Request):
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        title = str((body or {}).get("title") or "New conversation")
        conv_id = conversation_service.create(title)
        memory.record_action("conversation", f"#{conv_id}: {title[:60]}")
        return {"id": conv_id, "title": title}

    @app.post("/api/conversations/clear")
    async def clear_conversations(request: Request):
        """Hide past conversations while retaining durable job records."""
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        keep_id = (body or {}).get("keep_conversation_id")
        if keep_id is not None:
            try:
                keep_id = int(keep_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="keep_conversation_id must be an integer")
        result = conversation_service.archive_all(keep_id=keep_id)
        memory.record_action("conversation", f"archived {result['archived']} past conversation(s)")
        return {"ok": True, **result}

    def _conversation_error(exc: ConversationServiceError) -> HTTPException:
        status_code = 409 if isinstance(exc, ConversationBusy) else 404 if isinstance(exc, ConversationNotFound) else 400
        detail = str(exc)
        if exc.job_ids:
            detail += f" (job ids: {', '.join(map(str, exc.job_ids))})"
        return HTTPException(status_code=status_code, detail=detail)

    @app.post("/api/conversations/{conv_id}/archive")
    def archive_conversation(conv_id: int, request: Request):
        require_auth(request)
        try:
            return conversation_service.archive(conv_id)
        except ConversationServiceError as exc:
            raise _conversation_error(exc)

    @app.post("/api/conversations/{conv_id}/restore")
    def restore_conversation(conv_id: int, request: Request):
        require_auth(request)
        try:
            return conversation_service.restore(conv_id)
        except ConversationServiceError as exc:
            raise _conversation_error(exc)

    @app.delete("/api/conversations/{conv_id}")
    def delete_conversation(conv_id: int, request: Request):
        require_auth(request)
        try:
            return conversation_service.delete(conv_id)
        except ConversationServiceError as exc:
            raise _conversation_error(exc)

    @app.get("/api/theme")
    def theme(request: Request):
        """Brand theme for the admin UI — per-site colors/fonts overridable from config."""
        return _admin_theme(config)

    @app.get("/api/design/runs")
    def design_runs(request: Request, status: str | None = None, mode: str | None = None, limit: int = 50):
        require_auth(request)
        try:
            return {"runs": design_service.list_runs(status=status, mode=mode, limit=max(1, min(limit, 100)))}
        except DesignServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/design/runs", status_code=202)
    async def create_design_run(request: Request):
        require_auth(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            intake_value = body.get("intake")
            if not isinstance(intake_value, dict):
                raise ValueError("intake must be an object")
            from ..core.design_contracts import SiteIntake

            intake = SiteIntake.from_dict(intake_value)
            mode = str(body.get("mode") or "production_candidate")
            if mode == "local_experiment":
                run = design_service.create_experiment(
                    intake,
                    experiment_root=str(body.get("experiment_root") or ""),
                    base_sha=str(body.get("base_sha") or ""),
                    run_id=str(body.get("run_id") or "") or None,
                )
            else:
                run = design_service.create_run(
                    intake,
                    mode=mode,
                    base_sha=str(body.get("base_sha") or ""),
                    candidate_ref=str(body.get("candidate_ref") or ""),
                    run_id=str(body.get("run_id") or "") or None,
                )
            return {"run": run}
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/design/runs/{run_id}")
    def design_run(run_id: str, request: Request):
        require_auth(request)
        try:
            return {"run": design_service.get_run(run_id)}
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/design/runs/{run_id}/report")
    def design_run_report(run_id: str, request: Request):
        require_auth(request)
        try:
            run = design_service.get_run(run_id)
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "run_id": run_id,
            "status": run["status"],
            "quality_report": run.get("quality_report_json") or {},
            "quality_report_hash": run.get("quality_report_hash") or "",
            "planning": run.get("planning_json") or {},
            "planning_hash": run.get("planning_hash") or "",
        }

    @app.post("/api/design/runs/{run_id}/validate", status_code=202)
    def validate_design_run(run_id: str, request: Request):
        require_auth(request)
        try:
            report = design_service.validate_run(
                run_id,
                design_service.clone_path_for_run(run_id),
                browser=context.get("browser_quality"),
            )
            return {"run": design_service.get_run(run_id), "quality_report": report.to_dict()}
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/design/runs/{run_id}/visual-review", status_code=202)
    def visual_review_design_run(run_id: str, request: Request):
        require_auth(request)
        try:
            critique = design_service.visual_review_run(
                run_id,
                reviewer=context.get("design_visual_reviewer"),
                env=env,
            )
            return {
                "run": design_service.get_run(run_id),
                "visual_critique": critique.to_dict(),
            }
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/design/runs/{run_id}/visual-refinement", status_code=202)
    async def create_visual_refinement(run_id: str, request: Request):
        require_auth(request)
        executor = getattr(request.app.state, "_design_executor", None)
        if executor is None:
            raise HTTPException(status_code=503, detail="design worker is unavailable")
        try:
            try:
                body = await request.json()
            except (json.JSONDecodeError, ValueError):
                body = {}
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            run = design_service.get_run(run_id)
            report = run.get("quality_report_json") or {}
            raw_critique = body.get("visual_critique") or body.get("critique")
            if raw_critique is None and isinstance(report, dict):
                raw_critique = report.get("visual_critique")
            from ..core.design_contracts import BuildTarget, PageBuildRequest, VisualCritiqueReport

            if not isinstance(raw_critique, dict):
                raise ValueError("visual_critique must be an object")
            critique = VisualCritiqueReport.from_dict(raw_critique)
            created = design_service.create_visual_refinement_run(
                run_id,
                critique,
                run_id=str(body.get("run_id") or "") or None,
            )
            child = created["run"]
            build_request = PageBuildRequest.from_dict(created["request"])
            build_target = BuildTarget.from_dict(created["target"])
            design_service.queue_build(child["run_id"], build_request, build_target)
            executor.enqueue(child["run_id"])
            return {
                "parent_run_id": run_id,
                "run": design_service.get_run(child["run_id"]),
                "visual_critique": critique.to_dict(),
            }
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/design/runs/{run_id}/build", status_code=202)
    async def build_design_run(run_id: str, request: Request):
        require_auth(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            from ..core.design_contracts import BuildTarget, PageBuildRequest

            request_value = body.get("request")
            build_request = PageBuildRequest.from_dict(request_value) if isinstance(request_value, dict) else None
            target_value = body.get("target")
            if not isinstance(target_value, dict):
                raise ValueError("target must be an object")
            target = BuildTarget.from_dict(target_value)
            design_service.queue_build(run_id, build_request, target)
            executor = getattr(request.app.state, "_design_executor", None)
            if executor is None:
                raise HTTPException(status_code=503, detail="design worker is unavailable")
            executor.enqueue(run_id)
            return {"run": design_service.get_run(run_id)}
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/design/runs/{run_id}/cancel")
    def cancel_design_run(run_id: str, request: Request):
        require_auth(request)
        try:
            return {"run": design_service.cancel(run_id)}
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/design/runs/{run_id}/review", status_code=202)
    def create_design_review(run_id: str, request: Request):
        require_auth(request)
        try:
            return {"run": design_service.create_review_draft(run_id)}
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/design/runs/{run_id}/preview-token")
    def design_preview_token(run_id: str, request: Request):
        require_auth(request)
        try:
            run = design_service.get_run(run_id)
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not _design_candidate_is_previewable(run):
            raise HTTPException(status_code=409, detail="design run is not ready for preview")
        return JSONResponse(
            {"token": preview_access.issue(("design", run_id)), "expires_in": preview_access.ttl},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/design/runs/{run_id}/pages")
    def design_run_pages(run_id: str, request: Request, variant: str = "deepseek"):
        require_auth(request)
        try:
            run = design_service.get_run(run_id)
            clone = design_service.clone_path_for_run(run_id)
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not _design_candidate_is_previewable(run):
            raise HTTPException(status_code=409, detail="design run is not ready for preview")
        if not clone.exists() or not (clone / ".git").exists():
            raise HTTPException(status_code=404, detail="design candidate clone is unavailable")
        selected_variant, selected_sha = _design_preview_ref(run, variant)
        pages = _list_html_at(clone, selected_sha)
        return {
            "pages": list(dict.fromkeys(pages)),
            "variant": selected_variant,
            "ref": selected_sha,
            "base_sha": run.get("base_sha"),
            "candidate_sha": run.get("candidate_sha"),
        }

    @app.get("/api/approvals/{approval_id}")
    def approval_preview(approval_id: int, request: Request):
        require_auth(request)
        try:
            result = approval_service.preview(approval_id)
            _add_social_preview_urls(result, request)
            return result
        except ApprovalServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/social/posts/{artifact_id}/assets/{filename}", name="social_artifact_asset")
    async def social_artifact_asset(artifact_id: int, filename: str, request: Request):
        """Proxy known preview assets through the authenticated admin session."""
        require_auth(request)
        if social_post_service is None:
            raise HTTPException(status_code=503, detail="Cicero social provider is unavailable")
        try:
            data, media_type = await asyncio.to_thread(social_post_service.asset, artifact_id, filename)
        except SocialPostError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=data, media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/social/posts/prepare", status_code=202)
    async def prepare_social_post(request: Request):
        """Manual structured preparation path used by development and tests."""
        require_auth(request)
        if social_post_service is None:
            raise HTTPException(status_code=503, detail="Cicero social provider is unavailable")
        try:
            body = await request.json()
            brief = SocialPostBrief.from_mapping(body)
        except (SocialBriefError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            result = await asyncio.to_thread(
                social_post_service.prepare,
                brief,
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        except SocialIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (SocialPostError, CiceroClientError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        payload = {
            "artifact": result.artifact.to_preview_dict(),
            "approval": result.approval.to_owner_dict(),
            "action": result.action.to_owner_dict(),
            "provider_operation_id": result.provider_operation_id,
        }
        _add_social_preview_urls(payload, request)
        return payload

    @app.post("/api/approvals/{approval_id}/approve")
    def approve_artifact(approval_id: int, request: Request):
        require_auth(request)
        try:
            current = memory.get_approval_request(approval_id)
            artifact = memory.get_artifact(current.artifact_id) if current else None
            if current and artifact and artifact.capability_id == "knowledge.import" and knowledge_service is not None:
                return {"ok": True, "knowledge": knowledge_service.confirm(approval_id)}
            approval = approval_service.decide(approval_id, True)
            if artifact and media_service is not None:
                for asset_id in (artifact.preview_data.get("media_asset_ids") or []):
                    try:
                        memory.update_media_asset(int(asset_id), protected_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
                    except (TypeError, ValueError):
                        pass
            return {"ok": True, "approval": approval.to_owner_dict()}
        except StaleApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ApprovalServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/approvals/{approval_id}/decline")
    async def decline_artifact(approval_id: int, request: Request):
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        feedback = str((body or {}).get("feedback", "")).strip()
        try:
            current = memory.get_approval_request(approval_id)
            artifact = memory.get_artifact(current.artifact_id) if current else None
            if current and artifact and artifact.capability_id == "knowledge.import" and knowledge_service is not None:
                return {"ok": True, "knowledge": knowledge_service.decline(approval_id)}
            approval = approval_service.decide(approval_id, False, feedback)
            return {"ok": True, "approval": approval.to_owner_dict()}
        except StaleApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ApprovalServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/api/analytics")
    def analytics(request: Request):
        """One call for the overview dashboard: GA snapshot, strategist cards,
        draft queue, and recent publishes."""
        require_auth(request)
        snap = memory.latest_snapshot("ga4") or {}
        data = snap.get("data") or {}
        return {
            "traffic": data,
            "cards": (memory.kv_get("strategist_cards") or {}).get("cards") or [],
            "pending": [
                {"id": d["id"], "kind": d["kind"], "title": d["title"], "created_ts": d["created_ts"]}
                for d in memory.list_drafts(status="pending")
            ],
            "publishes": [
                {"path": p["path"], "summary": p["summary"][:80], "reverted_ts": p.get("reverted_ts"),
                 "commit_sha": p["commit_sha"]}
                for p in memory.list_publishes(limit=8)
            ],
            "themes": memory.kv_get("themes", []),
            "health": memory.kv_get("last_health", {}),
        }

    @app.get("/api/home")
    def home(request: Request, needs_limit: int = 4, suggestion_limit: int = 3):
        """Owner-facing action inbox; composition lives in HomeService."""
        require_auth(request)
        return home_service.snapshot(needs_limit=needs_limit, suggestion_limit=suggestion_limit).to_dict()

    def _action_error(exc: Exception) -> HTTPException:
        status_code = 404 if isinstance(exc, KeyError) else 409 if isinstance(exc, (ActionServiceError, ValueError)) else 400
        return HTTPException(status_code=status_code, detail=str(exc))

    @app.get("/api/approvals")
    def approvals(request: Request, status: str = "pending", limit: int = 50):
        require_auth(request)
        try:
            approval_status = ApprovalStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid approval status")
        result = {"approvals": approval_service.list(status=approval_status, limit=max(1, min(limit, 100)))}
        for item in result["approvals"]:
            _add_social_preview_urls(item, request)
        return result

    @app.post("/api/actions/{action_id}/start")
    async def start_action(action_id: int, request: Request):
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        conversation_id = (body or {}).get("conversation_id")
        if conversation_id is not None:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="conversation_id must be an integer")
        try:
            action = owner_action_service.start(action_id, conversation_id=conversation_id)
            return {"ok": True, "action": action.to_owner_dict()}
        except (ActionServiceError, KeyError, ValueError) as exc:
            raise _action_error(exc)

    @app.post("/api/actions/{action_id}/snooze")
    async def snooze_action(action_id: int, request: Request):
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        days = (body or {}).get("days", 7)
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="days must be an integer")
        try:
            action = owner_action_service.snooze_for(action_id, days)
            return {"ok": True, "action": action.to_owner_dict()}
        except (ActionServiceError, KeyError, ValueError) as exc:
            raise _action_error(exc)

    @app.post("/api/actions/{action_id}/dismiss")
    def dismiss_action(action_id: int, request: Request):
        require_auth(request)
        try:
            action = owner_action_service.dismiss(action_id)
            return {"ok": True, "action": action.to_owner_dict()}
        except (ActionServiceError, KeyError, ValueError) as exc:
            raise _action_error(exc)

    @app.get("/api/media")
    def media_list(request: Request, status: str | None = None, kind: str | None = None,
                   include_archived: bool = False, limit: int = 50, offset: int = 0):
        require_auth(request)
        if media_service is not None:
            try:
                return {"assets": media_service.list(status=status, media_kind=kind,
                                                       include_archived=include_archived, limit=limit, offset=offset)}
            except MediaServiceError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        try:
            ad = adapter()
            files = []
            for f in ad.list_files():
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif")):
                    files.append(f)
            return {"images": files[:200]}
        except Exception as exc:  # noqa: BLE001
            return {"images": [], "error": str(exc)[:200]}

    @app.post("/api/media/upload")
    async def media_upload(request: Request):
        """Upload private media, accepting multipart and the bounded legacy JSON shape."""
        require_auth(request)
        if media_service is not None:
            content_type = request.headers.get("content-type", "")
            try:
                if content_type.lower().startswith("multipart/form-data"):
                    form = await request.form()
                    upload_file = form.get("file")
                    if upload_file is None or not hasattr(upload_file, "read"):
                        raise HTTPException(status_code=400, detail="file is required")
                    data = await upload_file.read()
                    name = str(getattr(upload_file, "filename", "upload"))
                    mime = str(getattr(upload_file, "content_type", "") or "")
                else:
                    body = await request.json()
                    name = str((body or {}).get("name", ""))
                    encoded = str((body or {}).get("data", ""))
                    if not name or not encoded or len(encoded) > int(media_service.settings.get("max_image_bytes", 25 * 1024 * 1024)) * 2:
                        raise HTTPException(status_code=400, detail="need name + data (base64)")
                    data = base64.b64decode(encoded, validate=True)
                    mime = str((body or {}).get("content_type", ""))
                return media_service.upload(name, data, mime)
            except HTTPException:
                raise
            except (ValueError, MediaServiceError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid json")
        name = str((body or {}).get("name", "")).strip()
        data_b64 = str((body or {}).get("data", "")).strip()
        if not name or not data_b64:
            raise HTTPException(status_code=400, detail="need name + data (base64)")
        try:
            data = base64.b64decode(data_b64)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="data is not valid base64")
        from .media import MediaError, guess_content_type, media_configured, upload

        if not media_configured(config):
            raise HTTPException(
                status_code=400,
                detail="Cloudflare R2 is not configured — set site.media (account_id, bucket, public_url) + R2 keys in .env",
            )
        try:
            result = upload(config, name, data, guess_content_type(name))
        except MediaError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        memory.record_action("media", f"{result['key']} ({result['size']}B)")
        return result

    @app.get("/api/media/{asset_id}")
    def media_detail(asset_id: int, request: Request):
        require_auth(request)
        if media_service is None:
            raise HTTPException(status_code=404, detail="media library is disabled")
        try:
            return {"asset": media_service.serialize(media_service.get(asset_id))}
        except MediaServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    def _media_redirect(asset_id: int, request: Request, page: int | None = None):
        require_auth(request)
        if media_service is None:
            raise HTTPException(status_code=404, detail="media library is disabled")
        try:
            url = media_service.preview_url(asset_id, page=page)
        except MediaServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return Response(status_code=307, headers={"Location": url, "Cache-Control": "private, no-store"})

    @app.get("/api/media/{asset_id}/thumbnail")
    def media_thumbnail(asset_id: int, request: Request):
        return _media_redirect(asset_id, request)

    @app.get("/api/media/{asset_id}/preview")
    def media_preview(asset_id: int, request: Request, page: int | None = None):
        return _media_redirect(asset_id, request, page)

    @app.post("/api/media/{asset_id}/retry")
    def media_retry(asset_id: int, request: Request):
        require_auth(request)
        if media_service is None:
            raise HTTPException(status_code=404, detail="media library is disabled")
        try:
            return {"asset": media_service.retry(asset_id)}
        except MediaServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/media/{asset_id}/archive")
    def media_archive(asset_id: int, request: Request):
        require_auth(request)
        if media_service is None:
            raise HTTPException(status_code=404, detail="media library is disabled")
        try:
            return {"asset": media_service.archive(asset_id)}
        except MediaServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/media/{asset_id}/restore")
    def media_restore(asset_id: int, request: Request):
        require_auth(request)
        if media_service is None:
            raise HTTPException(status_code=404, detail="media library is disabled")
        try:
            return {"asset": media_service.restore(asset_id)}
        except MediaServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.delete("/api/media/{asset_id}")
    def media_delete(asset_id: int, request: Request):
        require_auth(request)
        if media_service is None:
            raise HTTPException(status_code=404, detail="media library is disabled")
        try:
            media_service.delete(asset_id)
            return {"ok": True}
        except MediaServiceError as exc:
            status = 409 if "cannot" in str(exc) or "waiting" in str(exc) else 404
            raise HTTPException(status_code=status, detail=str(exc))

    @app.post("/api/knowledge/reviews/{approval_id}/confirm")
    async def knowledge_confirm(approval_id: int, request: Request):
        require_auth(request)
        if knowledge_service is None:
            raise HTTPException(status_code=404, detail="knowledge reviews are disabled")
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            return {"knowledge": knowledge_service.confirm(approval_id, (body or {}).get("text"))}
        except BusinessKnowledgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/knowledge/reviews/{approval_id}/decline")
    def knowledge_decline(approval_id: int, request: Request):
        require_auth(request)
        if knowledge_service is None:
            raise HTTPException(status_code=404, detail="knowledge reviews are disabled")
        try:
            return {"knowledge": knowledge_service.decline(approval_id)}
        except BusinessKnowledgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/api/conversations/{conv_id}")
    def get_conversation(conv_id: int, request: Request):
        require_auth(request)
        try:
            return conversation_service.get(conv_id)
        except ConversationServiceError as exc:
            raise _conversation_error(exc)

    @app.get("/api/preview/{file_path:path}")
    async def preview_file(file_path: str, request: Request):
        """Serve the canonical framework build of the published Git revision."""
        preview_token = require_preview_auth(request, ("published", 0))
        import mimetypes

        clone = Path(str(config.get("site", {}).get("clone_path", "")).strip())
        if not clone.exists():
            raise HTTPException(status_code=404, detail="no clone configured")
        name = file_path.lstrip("/")
        if not name:
            name = "index.html"
        published_ref = _published_ref(clone)
        content = preview_cache.read_file(clone, published_ref, name)
        if not content and "." not in Path(name).name:
            name = "index.html"
            content = preview_cache.read_file(clone, published_ref, name)
        if not content:
            raise HTTPException(status_code=404, detail=f"{name} is not in the canonical site build")
        mt = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.lower().endswith((".html", ".htm")):
            content = rewrite_preview_html(
                content,
                0,
                name,
                _site_url(config),
                preview_token or "",
            )
        elif name.lower().endswith(".css"):
            content = rewrite_preview_css(content, name, preview_token or "")
        elif name.lower().endswith((".js", ".mjs")):
            content = rewrite_preview_js(content, preview_token or "")
        return Response(content=content, media_type=mt, headers=preview_headers(preview_token))

    @app.get("/api/review/{draft_id}/{file_path:path}")
    async def review_file(draft_id: int, file_path: str, request: Request, variant: str = "deepseek"):
        """Review a staged frontend draft from its canonical build output."""
        import mimetypes
        import subprocess

        preview_token = require_preview_auth(request, ("review", draft_id))
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        if draft["kind"] == "article":
            raise HTTPException(status_code=409, detail="Review Payload articles in the tenant owner workspace")
        clone = Path(str(config.get("site", {}).get("clone_path", "")).strip())
        if not clone.exists():
            raise HTTPException(status_code=404, detail="no clone configured")
        name = file_path.lstrip("/")
        if not name:
            name = "index.html"
        path_parts = Path(name).parts
        if Path(name).is_absolute() or ".." in path_parts:
            raise HTTPException(status_code=400, detail="invalid preview path")
        if draft["kind"] != "design":
            try:
                subprocess.run(
                    ["git", "-C", str(clone), "fetch", "origin", "preview", "main"],
                    capture_output=True, timeout=45,
                )
            except Exception:  # noqa: BLE001 — stale ref still works
                pass

        def _show_at(ref: str, rel: str, source_clone: Path = clone) -> bytes:
            proc = subprocess.run(
                ["git", "-C", str(source_clone), "show", f"{ref}:{rel}"],
                capture_output=True, timeout=30,
            )
            return proc.stdout if proc.returncode == 0 else b""

        def _serve(rel: str, data: bytes, preview_variant: str = "") -> Response:
            if rel.lower().endswith(".css"):
                data = rewrite_preview_css(data, rel, preview_token or "", preview_variant)
            elif rel.lower().endswith((".js", ".mjs")):
                data = rewrite_preview_js(data, preview_token or "", preview_variant)
            mt = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            return Response(content=data, media_type=mt,
                            headers=preview_headers(preview_token))

        kind = draft["kind"]
        if kind == "design":
            meta = draft.get("meta") or {}
            run_id = str(meta.get("run_id") or "")
            try:
                run = design_service.get_run(run_id)
                candidate_clone = design_service.clone_path_for_run(run_id)
            except DesignRunNotFound as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except DesignServiceError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if meta.get("candidate_sha") != run.get("candidate_sha"):
                raise HTTPException(status_code=409, detail="design review draft is stale")
            selected_variant, selected_sha = _design_preview_ref(run, variant)
            build_profile = _design_build_profile(design_service, run, selected_variant)
            artifact_root = (
                _design_output_artifact(design_service, run)
                if selected_variant == "deepseek"
                else None
            )
            if not candidate_clone.exists() or not (candidate_clone / ".git").exists():
                if artifact_root is None:
                    raise HTTPException(status_code=404, detail="design candidate is unavailable")
            built = (
                preview_cache.read_artifact(artifact_root, name)
                if artifact_root is not None
                else preview_cache.read_file(candidate_clone, selected_sha, name, profile=build_profile)
            )
            if not built and artifact_root is None:
                built = _show_at(selected_sha, name, candidate_clone)
            if not built:
                raise HTTPException(status_code=404, detail=f"{name} not in design candidate")
            rendered = (
                rewrite_preview_html(
                    built,
                    draft_id,
                    name,
                    _site_url(config),
                    preview_token or "",
                    selected_variant,
                )
                if name.lower().endswith((".html", ".htm"))
                else built
            )
            return _serve(name, rendered, selected_variant)

        if kind == "edit":
            raise HTTPException(
                status_code=409,
                detail="This file-only draft has no verified site build. Ask Ada to create a fresh implementation preview.",
            )

        # Serve staged output from the canonical framework build.
        if kind in ("merge", "rollback"):
            built = preview_cache.read_file(clone, "origin/preview", name)
            if not built:
                built = preview_cache.read_file(clone, "preview", name)
            if built:
                return _serve(
                    name,
                    rewrite_preview_html(
                        built,
                        draft_id,
                        name,
                    _site_url(config),
                        preview_token or "",
                    )
                    if name.lower().endswith((".html", ".htm"))
                    else built,
                )

        raise HTTPException(status_code=404, detail=f"{name} is not in the canonical preview build")

    @app.get("/api/design/runs/{run_id}/review/{file_path:path}")
    async def design_review_file(run_id: str, file_path: str, request: Request, variant: str = "deepseek"):
        """Serve a design candidate by its persisted SHA, never by a mutable ref."""
        import mimetypes
        import subprocess

        preview_token = require_preview_auth(request, ("design", run_id))
        try:
            run = design_service.get_run(run_id)
            clone = design_service.clone_path_for_run(run_id)
        except DesignRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DesignServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not _design_candidate_is_previewable(run):
            raise HTTPException(status_code=409, detail="design run is not ready for preview")
        name = file_path.lstrip("/") or "index.html"
        path_parts = Path(name).parts
        if Path(name).is_absolute() or ".." in path_parts or name.startswith((".git/", ".opencode/")):
            raise HTTPException(status_code=400, detail="invalid design preview path")
        selected_variant, selected_sha = _design_preview_ref(run, variant)
        build_profile = _design_build_profile(design_service, run, selected_variant)
        artifact_root = (
            _design_output_artifact(design_service, run)
            if selected_variant == "deepseek"
            else None
        )
        if artifact_root is None and (not clone.exists() or not (clone / ".git").exists()):
            raise HTTPException(status_code=404, detail="design candidate clone is unavailable")
        content = (
            preview_cache.read_artifact(artifact_root, name)
            if artifact_root is not None
            else preview_cache.read_file(clone, selected_sha, name, profile=build_profile)
        )
        if not content:
            raise HTTPException(status_code=404, detail=f"{name} not in design candidate")
        if name.lower().endswith((".html", ".htm")):
            content = rewrite_preview_html(
                content,
                run_id,
                name,
                _site_url(config),
                preview_token or "",
                selected_variant,
            )
        elif name.lower().endswith(".css"):
            content = rewrite_preview_css(content, name, preview_token or "", selected_variant)
        elif name.lower().endswith((".js", ".mjs")):
            content = rewrite_preview_js(content, preview_token or "", selected_variant)
        return Response(
            content=content,
            media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
            headers=preview_headers(preview_token),
        )

    def _list_html_at(clone: Path, ref: str) -> list[str]:
        """HTML pages present at a git ref, relative paths (index.html first)."""
        import subprocess

        proc = subprocess.run(
            ["git", "-C", str(clone), "ls-tree", "-r", "--name-only", ref],
            capture_output=True, timeout=30,
        )
        if proc.returncode != 0:
            return []
        pages = sorted(
            line.strip()
            for line in proc.stdout.decode().splitlines()
            if line.strip().lower().endswith((".html", ".htm"))
            and not line.strip().startswith(("themes/", "content/", "output/"))
        )
        return sorted(pages, key=lambda p: (p != "index.html", p))

    @app.get("/api/pages")
    def pages(request: Request, draft_id: int | None = None, variant: str = "deepseek"):
        """Pages available to the Design-tab visualizer, plus any pages the
        staged draft would newly create. Callers pass draft_id when reviewing
        a draft; otherwise the published (origin/main) pages are returned."""
        require_auth(request)
        clone = Path(str(config.get("site", {}).get("clone_path", "")).strip())
        if not clone.exists():
            raise HTTPException(status_code=404, detail="no clone configured")

        published_ref = _published_ref(clone)
        ref = published_ref
        main_pages = _list_html_at(clone, published_ref)
        draft_new: list[str] = []
        design_variant: str | None = None
        if draft_id is not None:
            draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail="no such draft")
            if draft["kind"] == "design":
                meta = draft.get("meta") or {}
                run_id = str(meta.get("run_id") or "")
                try:
                    run = design_service.get_run(run_id)
                except DesignRunNotFound as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                if meta.get("candidate_sha") != run.get("candidate_sha") or not run.get("candidate_sha"):
                    raise HTTPException(status_code=409, detail="design review draft is stale")
                design_variant, ref = _design_preview_ref(run, variant)
            elif draft["status"] != "pending":
                ref = published_ref
            elif draft["kind"] in ("merge", "rollback"):
                # Pages the staged build adds beyond what's already published.
                preview_ref = "origin/preview" if _git_ref_exists(clone, "origin/preview") else "preview"
                preview_pages = _list_html_at(clone, preview_ref)
                ref = preview_ref
                draft_new = [p for p in preview_pages if p not in main_pages]
            elif draft["kind"] == "edit":
                raise HTTPException(
                    status_code=409,
                    detail="This file-only draft has no verified site build. Ask Ada to create a fresh implementation preview.",
                )
        pages_list = _list_html_at(clone, ref)
        if not pages_list:
            pages_list = main_pages
        pages_list = list(dict.fromkeys(pages_list + draft_new))
        result = {"pages": pages_list, "new_pages": draft_new}
        if design_variant:
            result.update({
                "variant": design_variant,
                "ref": ref,
            })
        return result

    def _cf_preview_url(config: dict[str, Any]) -> str | None:
        cf = config.get("cloudflare") or {}
        proj = str(cf.get("project_name") or "").strip()
        acct = str(cf.get("account_id") or "").strip()
        if proj and acct:
            try:
                from ..senses.cloudflare import latest_preview_url
                token = resolve_secret(config, "cf_api_token")
                url = latest_preview_url(acct, proj, "preview", token)
                if url:
                    return url
            except Exception:  # noqa: BLE001
                pass
        if proj:
            return f"https://preview.{proj}.pages.dev"
        return None

    def _enqueue_chat(message: str, conv_id: int, attachments=None) -> int:
        """Persist the user message and its background job in one transaction."""
        return memory.enqueue_chat_job(conv_id, message, attachments)

    @app.post("/api/chat")
    async def chat(request: Request):
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid json")
        message = str((body or {}).get("message", "")).strip()
        if not message:
            raise HTTPException(status_code=400, detail="empty message")
        llm = context.get("llm")
        if llm is None or (hasattr(llm, "api_key") and not llm.api_key):
            raise HTTPException(status_code=503, detail="LLM not configured")

        action_id = (body or {}).get("action_id")
        if action_id is not None:
            try:
                action_id = int(action_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="action_id must be an integer")
            action = owner_action_service.get(action_id)
            if action is None:
                raise HTTPException(status_code=404, detail="no such owner action")

        conv_id = (body or {}).get("conversation_id")
        convs = {c["id"] for c in memory.list_conversations(limit=200)}
        if not conv_id or conv_id not in convs:
            conv_id = memory.create_conversation(title=message[:80])
        if action_id is not None:
            if action.conversation_id is not None and action.conversation_id != conv_id:
                raise HTTPException(status_code=409, detail="owner action belongs to another conversation")
            if action.state.value != "started":
                try:
                    action = owner_action_service.start(action_id, conversation_id=conv_id)
                except (ActionServiceError, KeyError, ValueError) as exc:
                    raise _action_error(exc)

        attachments = []
        if (body or {}).get("asset_ids") is not None:
            if media_service is None:
                raise HTTPException(status_code=400, detail="media library is disabled")
            try:
                attachments = media_service.resolve_attachments((body or {}).get("asset_ids"))
            except MediaServiceError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            attachments = [{"type": item["type"], "asset_id": item["asset_id"], "position": item["position"]}
                           for item in attachments]
        job_id = _enqueue_chat(message, conv_id, attachments)
        if action_id is not None:
            owner_action_service.link_job(action_id, job_id)
        return {"job_id": job_id, "conversation_id": conv_id}

    @app.get("/api/chat/jobs/{job_id}")
    def chat_job(job_id: int, request: Request):
        require_auth(request)
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail="no such job")
        job = memory.get_chat_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        out = {
            "id": job["id"],
            "conversation_id": job["conversation_id"],
            "status": job["status"],
            "steps": job.get("steps") or [],
        }
        if job["status"] == "done":
            out["result"] = job.get("result")
        if job["status"] == "error":
            out["error"] = job.get("error")
            out["retryable"] = True
        return out

    @app.post("/api/chat/jobs/{job_id}/retry")
    def retry_chat_job(job_id: int, request: Request):
        require_auth(request)
        if not memory.retry_chat_job(job_id):
            raise HTTPException(status_code=409, detail="only failed or incomplete chat jobs can be retried")
        job = memory.get_chat_job(job_id)
        return {"job_id": job_id, "conversation_id": job["conversation_id"] if job else None}

    @app.get("/api/chat/jobs")
    def chat_jobs(request: Request, conversation_id: int | None = None):
        require_auth(request)
        return {"jobs": memory.list_active_chat_jobs(conversation_id=conversation_id)}

    @app.get("/api/publishes")
    def publishes(request: Request):
        require_auth(request)
        return {"publishes": memory.list_publishes()}

    @app.get("/api/versions")
    def versions(request: Request):
        """Customer-facing published versions with their traceability metadata."""
        require_auth(request)
        rows = []
        for publish in memory.list_publishes(limit=50):
            if not publish.get("commit_sha"):
                continue
            rows.append({
                "id": publish["id"],
                "draft_id": publish.get("draft_id"),
                "summary": publish["summary"],
                "published_ts": publish["ts"],
                "actor": publish.get("actor") or "ada",
                "version_type": publish.get("version_type") or "edit",
                "commit_sha": publish.get("commit_sha") or "",
                "commit_message": publish.get("commit_message") or "",
                "current": False,
                "restored": publish.get("version_type") == "rollback",
            })
        if rows:
            rows[0]["current"] = True
        return {"versions": rows}

    @app.post("/api/drafts/{draft_id}/preview")
    def preview(draft_id: int, request: Request):
        require_auth(request)
        file_cache.clear()
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        if draft["kind"] == "article":
            raise HTTPException(status_code=409, detail="Review Payload articles in the tenant owner workspace")
        raise HTTPException(
            status_code=409,
            detail="This file-only draft has no verified site build. Ask Ada to create a fresh implementation preview.",
        )

    @app.post("/api/versions/{version_id}/restore")
    def restore_version(version_id: int, request: Request):
        require_auth(request)
        file_cache.clear()
        version = next((p for p in memory.list_publishes(limit=100) if p["id"] == version_id), None)
        if not version or not version.get("commit_sha"):
            raise HTTPException(status_code=404, detail="version not found")
        ad = adapter_validated()
        pbranch = str(config.get("site", {}).get("preview_branch") or "")
        if not pbranch or not hasattr(ad, "restore_snapshot"):
            raise HTTPException(status_code=400, detail="version restore is not configured")
        try:
            ad.ensure_branch(pbranch)
            result = ad.restore_snapshot(
                str(version["commit_sha"]), pbranch,
                f"Restore website version: {version['summary']}",
            )
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=f"restore preview failed: {exc}")
        draft_id = memory.save_draft(
            title=f"Restore: {version['summary'][:120]}",
            body=f"Restore the website to the published version from {version['ts'][:10]}.",
            kind="rollback",
            meta={
                "target_sha": version["commit_sha"],
                "target_publish_id": version_id,
                "head_sha": result.get("parent_sha", ""),
                "head": pbranch,
                "base": config.get("site", {}).get("branch", "main"),
                "summary": version["summary"],
            },
        )
        memory.record_action("rollback_preview", f"version #{version_id} -> draft #{draft_id}")
        return {"ok": True, "draft_id": draft_id, "branch": pbranch, "preview": result}

    @app.post("/api/publishes/revert")
    async def revert_publish(request: Request):
        """Compatibility alias that now creates an approval-gated restore."""
        require_auth(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid json")
        sha = str((body or {}).get("sha", "")).strip()
        version = next((p for p in memory.list_publishes(limit=100) if p.get("commit_sha") == sha), None)
        if not version:
            raise HTTPException(status_code=404, detail="version not found")
        return restore_version(version["id"], request)

    @app.get("/api/report/latest")
    def latest_report(request: Request):
        require_auth(request)
        reports = [d for d in memory.list_drafts(limit=50) if d["kind"] == "report"]
        if not reports:
            return {"report": None}
        return {"report": reports[0]}

    @app.get("/api/seo/site-reports/latest")
    def latest_site_seo_report(request: Request):
        require_auth(request)
        reports = memory.list_seo_site_reports(limit=1)
        report = reports[0] if reports else None
        if report and report.get("artifact_id"):
            artifact = memory.get_artifact(report["artifact_id"])
            if artifact is not None:
                report["artifact"] = artifact.to_preview_dict()
        return {"report": report}

    @app.get("/api/seo/site-reports")
    def list_site_seo_reports(request: Request, limit: int = 12):
        require_auth(request)
        return {"reports": memory.list_seo_site_reports(limit=limit)}

    @app.get("/api/seo/site-reports/{report_id}")
    def get_site_seo_report(report_id: int, request: Request):
        require_auth(request)
        report = memory.get_seo_site_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="site SEO report not found")
        if report.get("artifact_id"):
            artifact = memory.get_artifact(report["artifact_id"])
            if artifact is not None:
                report["artifact"] = artifact.to_preview_dict()
        return {"report": report}

    @app.get("/api/seo/article-research")
    def list_article_research(request: Request, status: str | None = None, limit: int = 20):
        require_auth(request)
        allowed = {"selected", "research_requested", "serp_requested", "researched", "held", "drafted", "failed"}
        normalized_status = status.strip().lower() if status else None
        if normalized_status and normalized_status not in allowed:
            raise HTTPException(status_code=400, detail="invalid article research status")
        return {
            "ideas": memory.list_article_ideas(
                status=normalized_status,
                limit=max(1, min(limit, 50)),
            )
        }

    @app.get("/api/seo/article-research/{idea_id}")
    def get_article_research(idea_id: int, request: Request):
        require_auth(request)
        idea = memory.get_article_idea(idea_id)
        if idea is None:
            raise HTTPException(status_code=404, detail="article research idea not found")
        return {"idea": idea}

    @app.get("/api/seo/article-rejections")
    def list_article_rejections(request: Request, limit: int = 50):
        require_auth(request)
        return {"rejections": memory.list_rejected_article_ideas(limit=max(1, min(limit, 200)))}

    @app.get("/api/drafts")
    def list_drafts(request: Request, status: str = "pending"):
        require_auth(request)
        return {"drafts": memory.list_drafts(status=status)}

    @app.get("/api/history")
    def history(request: Request):
        """Version-history strip for the Design tab: the recent draft lifecycle
        (staged/approved/declined/discarded) alongside publishes, newest first,
        so the owner can see the sequence that led to the current preview."""
        require_auth(request)
        drafts = memory.list_drafts(limit=50)
        pubs = memory.list_publishes(limit=30)
        pub_by_draft = {p["draft_id"]: p for p in pubs if p.get("draft_id")}
        entries = []
        for d in drafts:
            p = pub_by_draft.get(d["id"])
            entries.append({
                "id": d["id"],
                "draft_id": d["id"],
                "kind": d["kind"],
                "status": d["status"],
                "title": d["title"],
                "created_ts": d["created_ts"],
                "commit_sha": (p or {}).get("commit_sha"),
                "commit_message": (p or {}).get("commit_message", ""),
                "reverted_ts": (p or {}).get("reverted_ts"),
            })
        return {"history": entries}

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: int, request: Request):
        require_auth(request)
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        if draft["kind"] == "article":
            draft["decision_details"] = _article_decision_details(draft)
        return draft

    def _article_decision_details(draft: dict[str, Any]) -> dict[str, Any]:
        meta = draft.get("meta") if isinstance(draft.get("meta"), dict) else {}
        lineage = meta.get("article_research") if isinstance(meta.get("article_research"), dict) else {}
        idea = memory.get_article_idea_for_draft(int(draft["id"]))
        idea_data = idea.get("idea_json") if isinstance(idea, dict) and isinstance(idea.get("idea_json"), dict) else {}
        note = idea.get("research_note_json") if isinstance(idea, dict) and isinstance(idea.get("research_note_json"), dict) else {}
        results = idea.get("research_result_json") if isinstance(idea, dict) else []
        if not isinstance(results, list):
            results = []
        source_urls = idea_data.get("source_urls") or lineage.get("source_urls") or []
        if not isinstance(source_urls, list):
            source_urls = [source_urls]
        cost_micros = (
            idea.get("research_cost_micros")
            if isinstance(idea, dict) and idea.get("research_cost_micros") is not None
            else lineage.get("research_cost_micros")
        )
        research_run_id = (
            idea.get("research_run_id")
            if isinstance(idea, dict) and idea.get("research_run_id")
            else lineage.get("keyword_research_run_id")
        )
        serp_run_id = (idea or {}).get("serp_run_id") or lineage.get("serp_research_run_id")
        serp_receipt = note.get("serp_receipt") if isinstance(note.get("serp_receipt"), dict) else {}
        serp_evidence = note.get("serp_evidence") if isinstance(note.get("serp_evidence"), dict) else {}
        researched = bool(idea and (idea.get("researched_ts") or idea.get("research_result_hash")))
        research_status = "completed" if researched else (str(idea.get("status") or "not_recorded") if idea else "not_recorded")
        serp_status = "not_recorded"
        if idea:
            if idea.get("status") in {"serp_requested", "researched", "drafted", "failed"}:
                serp_status = "completed" if serp_run_id and (idea.get("researched_ts") or serp_evidence) else "pending"
            else:
                serp_status = "not_requested"
        return {
            "selection": {
                "title": idea_data.get("working_title") or draft.get("title", ""),
                "audience_need": idea_data.get("audience_need", ""),
                "reader_question": idea_data.get("reader_question", ""),
                "reader_situation": idea_data.get("reader_situation", ""),
                "reader_intent": idea_data.get("reader_intent", ""),
                "business_relevance": idea_data.get("business_relevance", ""),
                "market_context": idea_data.get("market_context", ""),
                "expert_angle": idea_data.get("expert_angle", ""),
                "expertise_basis": idea_data.get("expertise_basis", []),
                "technical_watchouts": idea_data.get("technical_watchouts", []),
                "scope_boundaries": idea_data.get("scope_boundaries", []),
                "thesis": idea_data.get("thesis", ""),
                "why_now": idea_data.get("why_now", ""),
                "origin": idea_data.get("origin", lineage.get("origin", "")),
                "candidate_queries": idea_data.get("candidate_queries", []),
                "research_seed": idea_data.get("research_seed", ""),
                "selected_query": note.get("selected_query", ""),
                "language": idea_data.get("language", lineage.get("language", "")),
                "market": idea_data.get("market", lineage.get("market", "")),
                "source_urls": [str(url) for url in source_urls if str(url).strip()],
                "draft_angle": meta.get("angle", ""),
                "draft_why": meta.get("why", ""),
            },
            "keyword_research": {
                "provider": "CrawlSEO / DataForSEO",
                "status": research_status,
                "idea_status": idea.get("status") if idea else "not_recorded",
                "run_id": research_run_id or "",
                "provider_task_id": (idea or {}).get("provider_task_id") or "",
                "cost_micros": cost_micros,
                "cost_usd": (float(cost_micros) / 1_000_000) if cost_micros is not None else None,
                "result_hash": (idea or {}).get("research_result_hash") or "",
                "result_count": len(results),
                "results": results[:50],
                "result_truncated": len(results) > 50,
                "note": note,
                "created_ts": (idea or {}).get("created_ts") or "",
                "researched_ts": (idea or {}).get("researched_ts") or "",
                "error": (idea or {}).get("error") or "",
            },
            "serp_research": {
                "provider": "CrawlSEO / DataForSEO",
                "status": serp_status,
                "run_id": serp_run_id or "",
                "provider_task_id": serp_receipt.get("provider_task_id") or "",
                "cost_micros": serp_receipt.get("cost_micros"),
                "cost_usd": (float(serp_receipt.get("cost_micros")) / 1_000_000)
                if serp_receipt.get("cost_micros") is not None else None,
                "checked_at": serp_evidence.get("checked_at") or serp_receipt.get("checked_at") or "",
                "query": serp_evidence.get("query") or note.get("selected_query") or "",
                "organic_count": len(serp_evidence.get("organic") or []),
                "evidence": serp_evidence,
            },
        }

    def _draft_ops_paths(draft: dict[str, Any]) -> set[str] | None:
        """Return source overlap for canonical whole-site candidates."""
        if draft["kind"] in ("design", "merge", "rollback"):
            return None
        return set()

    def _supersede_overlapping_pending(draft: dict[str, Any]) -> list[int]:
        """After approval, retire older whole-site candidates from review."""
        if draft["kind"] not in ("design", "merge", "rollback"):
            return []
        approved_paths = _draft_ops_paths(draft)
        superseded = []
        for other in memory.list_drafts(status="pending"):
            if other["id"] == draft["id"]:
                continue
            if other["kind"] == "edit":
                memory.update_draft_status(other["id"], "discarded")
                superseded.append(other["id"])
                continue
            if other["kind"] not in ("design", "merge", "rollback"):
                continue
            other_paths = _draft_ops_paths(other)
            overlaps = (
                approved_paths is None
                or other_paths is None
                or bool(approved_paths & other_paths)
            )
            if overlaps:
                memory.update_draft_status(other["id"], "discarded")
                superseded.append(other["id"])
        return superseded

    @app.post("/api/drafts/{draft_id}/approve")
    def approve(draft_id: int, request: Request):
        require_auth(request)
        file_cache.clear()
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        if draft["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"draft already {draft['status']}")
        if draft["kind"] == "article":
            raise HTTPException(status_code=409, detail="Publish Payload articles in the tenant owner workspace")

        published = None
        if draft["kind"] == "reflection":
            # Legacy local operator surface: the Payload owner workspace uses
            # WorkspaceService.approve_draft with the client-reviewed hash.
            # Retain this route's stored-package validation until that retired
            # surface is removed, rather than calling the stricter handler with
            # a missing argument.
            meta = draft.get("meta") if isinstance(draft.get("meta"), dict) else {}
            if not approve_reflection(memory, draft_id, str(meta.get("review_package_hash") or "")):
                raise HTTPException(status_code=400, detail="could not merge reflection")
        elif draft["kind"] == "edit":
            raise HTTPException(
                status_code=409,
                detail="This file-only draft has no verified site build and cannot be approved. Ask Ada to create a fresh implementation preview.",
            )
        elif draft["kind"] == "design":
            ad = adapter_validated()
            if not isinstance(ad, DesignMergeAdapter):
                raise HTTPException(status_code=400, detail="adapter does not support immutable design merges")
            try:
                approval_result = design_service.approve_review_draft(
                    draft_id,
                    lambda run: ad.merge_design_candidate(
                        config,
                        run["candidate_sha"],
                        run["base_sha"],
                        f"Approve design candidate: {draft['title']}",
                    ),
                )
                published = approval_result["published"]
            except DesignServiceError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif draft["kind"] in ("merge", "rollback"):
            ad = adapter_validated()
            if not isinstance(ad, MergeAdapter):
                raise HTTPException(status_code=400, detail="adapter does not support merges")
            try:
                published = ad.merge_preview(config, f"Merge preview: {draft['meta'].get('summary', '')}")
            except AdapterError as exc:
                raise HTTPException(status_code=400, detail=f"merge failed: {exc}")
            if not published.get("merged"):
                raise HTTPException(
                    status_code=400,
                    detail=f"GitHub rejected the merge (status {published.get('status')})",
                )
            memory.update_draft_status(draft_id, "approved")
        else:
            memory.update_draft_status(draft_id, "approved")

        if published and isinstance(published, dict) and (published.get("committed") or published.get("commit_sha")):
            version_type = "rollback" if draft["kind"] == "rollback" else draft["kind"]
            memory.log_publish(
                summary=f"{draft['kind']}: {draft['title']}",
                path=str(published.get("path", "")),
                commit_sha=str(published.get("commit_sha") or ""),
                draft_id=draft_id,
                parent_sha=str(published.get("parent_sha") or ""),
                actor="owner",
                version_type=version_type,
                commit_message=str(published.get("commit_message") or ""),
            )
        superseded = _supersede_overlapping_pending(draft)
        media_ids = (draft.get("meta") or {}).get("media_asset_ids") or []
        if draft["status"] == "pending" and media_ids and media_service is not None:
            for asset_id in media_ids:
                try:
                    media_service.memory.update_media_asset(int(asset_id), protected_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
                except (TypeError, ValueError):
                    pass
        if draft["kind"] == "article":
            gsc_snapshot = memory.latest_snapshot("gsc") or {}
            ga4_snapshot = memory.latest_snapshot("ga4") or {}
            gsc_data = gsc_snapshot.get("data") if isinstance(gsc_snapshot.get("data"), dict) else {}
            ga4_data = ga4_snapshot.get("data") if isinstance(ga4_snapshot.get("data"), dict) else {}
            gsc_current = gsc_data.get("current") if isinstance(gsc_data.get("current"), dict) else {}
            ga4_current = ga4_data.get("current") if isinstance(ga4_data.get("current"), dict) else {}
            baseline_metric = "gsc.clicks" if "clicks" in gsc_current else "ga4.sessions" if "sessions" in ga4_current else ""
            baseline = {
                "metric": baseline_metric,
                "gsc": gsc_snapshot,
                "ga4": ga4_snapshot,
            }
            memory.record_strategy_decision_for_draft(draft_id, "approved", baseline=baseline)
            owner_action_service.reconcile(draft_id=draft_id, succeeded=True)
        memory.record_action("approve", f"#{draft_id} [{draft['kind']}] {draft['title']}")
        if superseded:
            memory.record_action(
                "approve_superseded",
                f"#{draft_id} discarded stale pending drafts: #{', #'.join(map(str, superseded))}",
            )
        return {"ok": True, "published": published, "superseded": superseded}

    @app.post("/api/drafts/{draft_id}/discard")
    def discard(draft_id: int, request: Request):
        require_auth(request)
        file_cache.clear()
        if not memory.update_draft_status(draft_id, "discarded"):
            raise HTTPException(status_code=404, detail="no such draft")
        memory.record_action("discard", f"#{draft_id}")
        return {"ok": True}

    @app.post("/api/drafts/{draft_id}/decline")
    async def decline(draft_id: int, request: Request):
        """Owner rejects a draft with optional feedback. An approved article is
        un-published. The feedback is recorded as an observation Ada reads back,
        so she learns why her work was rejected."""
        require_auth(request)
        file_cache.clear()
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        if draft["kind"] == "article":
            raise HTTPException(status_code=409, detail="Decline Payload articles in the tenant owner workspace")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        feedback = str((body or {}).get("feedback", "")).strip()

        unpublished = None
        reset = None
        if draft["kind"] in ("merge", "rollback"):
            # Rejected build: roll the preview branch back to main so the
            # visualizer stops showing the rejected design and the next build
            # starts from a clean main. Its tweak-map overlay is stale too.
            from ..hands import tweakmap

            tweakmap.drop_builder_map(memory)
            pbranch = str(config.get("site", {}).get("preview_branch") or "")
            if pbranch:
                ad = adapter()
                try:
                    if hasattr(ad, "reset_preview_branch"):
                        reset = ad.reset_preview_branch(pbranch)
                except AdapterError as exc:
                    raise HTTPException(status_code=400, detail=f"preview reset failed: {exc}")

        if not memory.update_draft_status(draft_id, "declined"):
            raise HTTPException(status_code=404, detail="no such draft")

        memory.add_draft_feedback(draft_id, feedback)
        if draft["kind"] == "design":
            run_id = str((draft.get("meta") or {}).get("run_id") or "")
            if run_id:
                try:
                    memory.add_design_run_event(run_id, "declined", "Owner declined the design candidate.", {
                        "draft_id": draft_id,
                        "feedback": feedback[:500],
                    })
                except KeyError:
                    pass
        if feedback:
            memory.record_observation(
                "feedback",
                f"Owner declined draft #{draft_id} \"{draft['title']}\": {feedback}",
                meta={"draft_id": draft_id, "kind": draft["kind"], "reason": "decline"},
            )
        memory.record_strategy_decision_for_draft(draft_id, "declined", owner_feedback=feedback)
        for action in memory.list_owner_actions(limit=500):
            if action.draft_id == draft_id and action.state in {ActionState.OPEN, ActionState.STARTED}:
                owner_action_service.dismiss(action.id)
        memory.record_action("decline", f"#{draft_id} [{draft['kind']}] {draft['title']}" + (f" — {feedback[:100]}" if feedback else "") + (f" (removed {unpublished['removed']})" if unpublished else ""))
        return {"ok": True, "unpublished": unpublished, "reset": reset}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-cache"})

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app
