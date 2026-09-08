"""Standalone loopback web adapter for the local Intake Lab."""

from __future__ import annotations

import json
import base64
import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..application.design_intake import DesignIntakeServiceError
from ..application.incubations import IncubationApplicationService, IncubationServiceError
from ..application.intake_lab import IntakeLabError, IntakeLabService
from ..hands.local_media import LocalMediaStore
from .preview import PreviewAccess, PreviewBuildCache, rewrite_preview_css, rewrite_preview_html


STATIC_PATH = Path(__file__).parent / "static" / "intake_lab.html"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_VARIANTS = {"candidate"}
_MAX_BODY_BYTES = 400_000
INTAKE_SESSION_COOKIE = "ada_intake_session"
_INTAKE_SESSION_MAX_AGE = 60 * 60 * 24 * 30


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": str(message)[:500]}}, status_code=status_code)


def _same_origin(request: Request, origin: str) -> bool:
    expected = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    return origin.rstrip("/") == expected


def _require_api_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and not _same_origin(request, origin):
        raise HTTPException(status_code=403, detail="request origin is not allowed")


def _safe_file_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").lstrip("/")
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=404, detail="preview file not found")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".git" in path.parts or ".opencode" in path.parts:
        raise HTTPException(status_code=404, detail="preview file not found")
    return str(path)


def _site_url(service: IntakeLabService) -> str:
    site = service.config.get("site") or {}
    blog = service.config.get("blog") or {}
    return str(site.get("url") or site.get("preview_url") or blog.get("site_url") or "").strip()


def _preview_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Access-Control-Allow-Origin": "null",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Security-Policy": "sandbox allow-scripts; frame-ancestors 'self'",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def _run_id(value: str) -> str:
    result = str(value or "").strip()
    if not _RUN_ID.fullmatch(result):
        raise HTTPException(status_code=404, detail="Intake Lab run not found")
    return result


def create_app(
    service: IntakeLabService,
    *,
    workspace: str | Path | None = None,
    preview_cache: PreviewBuildCache | None = None,
    preview_access: PreviewAccess | None = None,
    incubation_service: IncubationApplicationService | None = None,
    default_incubation_id: str | None = None,
) -> FastAPI:
    """Create the isolated app from injected application dependencies."""
    access = preview_access or PreviewAccess()
    static_path = STATIC_PATH
    workspace_path = Path(workspace or getattr(service, "workspace", ".")).expanduser().resolve()
    cache = preview_cache or PreviewBuildCache(temp_root=workspace_path / ".preview-builds")
    executor = getattr(service, "executor", None)
    chat_executor = getattr(service, "chat_executor", None)
    intake_service = getattr(service, "design_intake_service", None)
    media_service = getattr(service, "media_service", None)
    media_worker = getattr(service, "media_worker", None)

    def _incubation(value: str | None = None):
        if incubation_service is None:
            raise HTTPException(status_code=503, detail="incubation service is unavailable")
        incubation_id = str(value or default_incubation_id or "").strip()
        if not incubation_id:
            raise HTTPException(status_code=404, detail="incubation was not found")
        try:
            return incubation_service.get_record(incubation_id)
        except IncubationServiceError as exc:
            raise HTTPException(status_code=404, detail="incubation was not found") from exc

    def _session_cookie_path(request: Request) -> str:
        root_path = str(request.scope.get("root_path") or "/").strip()
        if not root_path.startswith("/"):
            root_path = "/"
        return root_path.rstrip("/") or "/"

    def _with_session_cookie(
        request: Request,
        payload: dict[str, Any],
        incubation_id: str,
        *,
        status_code: int = 200,
    ) -> JSONResponse:
        response = JSONResponse(
            payload,
            status_code=status_code,
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )
        response.set_cookie(
            key=INTAKE_SESSION_COOKIE,
            value=incubation_id,
            max_age=_INTAKE_SESSION_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path=_session_cookie_path(request),
        )
        return response

    def _cookie_incubation(request: Request):
        cookie_id = str(request.cookies.get(INTAKE_SESSION_COOKIE) or "").strip()
        if not cookie_id:
            return None
        try:
            return _incubation(cookie_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise

    def _incubation_error(exc: Exception, code: str = "incubation_failed") -> JSONResponse:
        return _error(code, str(exc), 409)

    async def _json_object(request: Request, *, allow_empty: bool = False) -> dict[str, Any]:
        try:
            payload = await request.body()
        except Exception as exc:  # noqa: BLE001 - normalize malformed request bodies
            raise HTTPException(status_code=400, detail="request body could not be read") from exc
        if len(payload) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request body is too large")
        if not payload and allow_empty:
            return {}
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        return value

    def _public_provisioning(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: _public_provisioning(item)
                for key, item in value.items()
                if key not in {"config_path", "database_path", "workspace_path"}
            }
        if isinstance(value, list):
            return [_public_provisioning(item) for item in value]
        return value

    def _public_media(incubation_id: str, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for asset in assets:
            item = dict(asset)
            asset_id = int(item["id"])
            if item.get("thumbnail_url"):
                item["thumbnail_url"] = f"./api/incubations/{incubation_id}/media/{asset_id}/thumbnail"
            if item.get("preview_url"):
                item["preview_url"] = f"./api/incubations/{incubation_id}/media/{asset_id}/preview"
            result.append(item)
        return result

    async def _media_upload_payload(request: Request) -> tuple[str, bytes, str]:
        content_type = request.headers.get("content-type", "")
        if content_type.lower().startswith("multipart/form-data"):
            form = await request.form()
            upload_file = form.get("file")
            if upload_file is None or not hasattr(upload_file, "read"):
                raise HTTPException(status_code=400, detail="file is required")
            return (
                str(getattr(upload_file, "filename", "upload")),
                await upload_file.read(),
                str(getattr(upload_file, "content_type", "") or ""),
            )
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="upload must be valid JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="upload must be an object")
        try:
            data = base64.b64decode(str(body.get("data") or ""), validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="upload data must be valid base64") from exc
        return str(body.get("name") or "upload"), data, str(body.get("content_type") or "")

    def preview_available(run_id: str, variant: str, page: str) -> bool:
        try:
            clone, sha = service.preview_identity(run_id, variant)
            profile_resolver = getattr(service, "preview_profile", None)
            profile = profile_resolver(run_id) if callable(profile_resolver) else ""
            return bool(cache.read_file(clone, sha, page, profile=profile))
        except (IntakeLabError, OSError, RuntimeError):
            return False

    def _incubation_preview_available(incubation_id: str, run_id: str, page: str) -> bool:
        try:
            clone, sha = incubation_service.design_preview_identity(incubation_id, run_id, "candidate")  # type: ignore[union-attr]
            profile = incubation_service.design_preview_profile(incubation_id, run_id)  # type: ignore[union-attr]
            return bool(cache.read_file(clone, sha, page, profile=profile))
        except (IncubationServiceError, OSError, RuntimeError):
            return False

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        incubation_started = False
        if incubation_service is not None and callable(getattr(incubation_service, "start", None)):
            incubation_service.start()
            incubation_started = True
        started = False
        chat_started = False
        media_started = False
        if not incubation_started:
            if executor is not None and callable(getattr(executor, "start", None)):
                executor.start()
                started = True
            if chat_executor is not None and callable(getattr(chat_executor, "start", None)):
                chat_executor.start()
                chat_started = True
            if media_worker is not None and callable(getattr(media_worker, "start", None)):
                media_worker.start()
                media_started = True
        app.state.executor = executor
        app.state.preview_cache = cache
        try:
            yield
        finally:
            if incubation_started:
                incubation_service.stop()  # type: ignore[union-attr]
            else:
                if started:
                    try:
                        executor.stop()
                    finally:
                        executor.join(timeout=10)
                if chat_started:
                    try:
                        chat_executor.stop()
                    finally:
                        chat_executor.join(timeout=10)
                if media_started:
                    try:
                        media_worker.stop()
                    finally:
                        media_worker.join(timeout=10)
            cache.clear()
            app.state.executor = None

    app = FastAPI(title="Ada Intake Lab", docs_url=None, redoc_url=None, lifespan=lifespan)

    vendor_dir = Path(__file__).parent / "static" / "vendor"
    if vendor_dir.is_dir():
        from starlette.staticfiles import StaticFiles

        app.mount("/vendor", StaticFiles(directory=str(vendor_dir)), name="vendor")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        try:
            text = static_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Intake Lab shell is unavailable") from exc
        return HTMLResponse(text, headers={"Cache-Control": "no-store"})

    @app.post("/api/incubations", status_code=201)
    async def incubation_create(request: Request):
        try:
            _require_api_origin(request)
            if incubation_service is None:
                return _error("incubation_unavailable", "incubation service is unavailable", 503)
            record = incubation_service.create_incubation()
            return _with_session_cookie(request, {"incubation": record.to_dict()}, record.incubation_id, status_code=201)
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_create_failed")

    @app.get("/api/incubations")
    async def incubation_list(request: Request, limit: int = 50):
        try:
            _require_api_origin(request)
            if incubation_service is None:
                return _error("incubation_unavailable", "incubation service is unavailable", 503)
            return {"incubations": [item.to_dict() for item in incubation_service.list_incubations(limit=limit)]}
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_list_failed")

    @app.get("/api/incubations/default")
    async def incubation_default(request: Request):
        try:
            _require_api_origin(request)
            if incubation_service is None:
                return _error("incubation_unavailable", "incubation service is unavailable", 503)
            record = _cookie_incubation(request)
            if record is None:
                record = incubation_service.create_incubation()
            return _with_session_cookie(request, {"incubation": record.to_dict()}, record.incubation_id)
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_default_failed")

    @app.get("/api/incubations/{incubation_id}")
    async def incubation_get(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            record = _incubation(incubation_id)
            return _with_session_cookie(request, incubation_service.summary(incubation_id), record.incubation_id)  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("not_found", "incubation was not found", 404)

    @app.post("/api/incubations/{incubation_id}/messages", status_code=202)
    async def incubation_message(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            if not isinstance(body.get("message"), str):
                return _error("invalid_request", "message must be text", 400)
            result = incubation_service.send_message(  # type: ignore[union-attr]
                incubation_id,
                body["message"],
                attachments=body.get("attachments"),
                idempotency_key=body.get("idempotency_key"),
            )
            return {"incubation_id": incubation_id, **result}
        except HTTPException:
            raise
        except (IncubationServiceError, DesignIntakeServiceError) as exc:
            return _incubation_error(exc, "incubation_message_failed")

    @app.post("/api/incubations/{incubation_id}/research", status_code=202)
    async def incubation_research(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request, allow_empty=True)
            result = incubation_service.request_research(incubation_id, body)  # type: ignore[union-attr]
            return {"incubation_id": incubation_id, **result}
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "research_failed")

    @app.get("/api/incubations/{incubation_id}/research")
    async def incubation_research_list(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return incubation_service.research_projection(incubation_id)  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("research_unavailable", "research is unavailable", 503)

    @app.get("/api/incubations/{incubation_id}/activity")
    async def incubation_activity_list(
        request: Request,
        incubation_id: str,
        after_id: str | None = None,
        before_id: str | None = None,
        limit: int = 100,
        categories: str | None = None,
    ):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            selected = tuple(item.strip() for item in str(categories or "").split(",") if item.strip())
            return incubation_service.activity_projection(  # type: ignore[union-attr]
                incubation_id,
                after_id=after_id,
                before_id=before_id,
                limit=limit,
                categories=selected,
            )
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "activity_unavailable")

    @app.get("/api/incubations/{incubation_id}/activity/{activity_id}")
    async def incubation_activity_detail(request: Request, incubation_id: str, activity_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            item = incubation_service.activity_detail(incubation_id, activity_id)  # type: ignore[union-attr]
            if item is None:
                return _error("not_found", "incubation activity was not found", 404)
            return {"activity": item}
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "activity_unavailable")

    @app.patch("/api/incubations/{incubation_id}/research/sources/{source_id}")
    async def incubation_research_source_update(request: Request, incubation_id: str, source_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            return incubation_service.update_research_source(incubation_id, source_id, body)  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "research_source_update_failed")

    @app.get("/api/incubations/{incubation_id}/media")
    async def incubation_media_list(request: Request, incubation_id: str, limit: int = 50):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return {"assets": _public_media(incubation_id, incubation_service.list_media(incubation_id, limit=limit))}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "media_unavailable")

    @app.post("/api/incubations/{incubation_id}/media", status_code=201)
    async def incubation_media_upload(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            name, data, content_type = await _media_upload_payload(request)
            return {"asset": incubation_service.upload_media(incubation_id, name, data, content_type)}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "media_upload_failed")

    @app.post("/api/incubations/{incubation_id}/intake-sessions/{session_id}/assets")
    async def incubation_assets(request: Request, incubation_id: str, session_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            assets = body.get("assets")
            if not isinstance(assets, list):
                return _error("invalid_request", "assets must be a list", 400)
            return {"session": incubation_service.update_intake_assets(incubation_id, session_id, assets)}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "intake_assets_failed")

    @app.get("/api/incubations/{incubation_id}/media/object")
    async def incubation_media_object(request: Request, incubation_id: str, key: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            data, media_type = incubation_service.media_object(incubation_id, key)  # type: ignore[union-attr]
            return Response(content=data, media_type=media_type, headers={"Cache-Control": "private, no-store"})
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            raise HTTPException(status_code=404, detail="media object not found") from exc

    @app.get("/api/incubations/{incubation_id}/media/{asset_id}/thumbnail")
    async def incubation_media_thumbnail(request: Request, incubation_id: str, asset_id: int):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            data, media_type = incubation_service.media_preview(incubation_id, asset_id, thumbnail=True)  # type: ignore[union-attr]
            return Response(content=data, media_type=media_type, headers={"Cache-Control": "private, no-store"})
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            raise HTTPException(status_code=404, detail="media object not found") from exc

    @app.get("/api/incubations/{incubation_id}/media/{asset_id}/preview")
    async def incubation_media_preview(request: Request, incubation_id: str, asset_id: int):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            data, media_type = incubation_service.media_preview(incubation_id, asset_id, thumbnail=False)  # type: ignore[union-attr]
            return Response(content=data, media_type=media_type, headers={"Cache-Control": "private, no-store"})
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            raise HTTPException(status_code=404, detail="media object not found") from exc

    @app.get("/api/incubations/{incubation_id}/runs/{run_id}")
    async def incubation_run(request: Request, incubation_id: str, run_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return incubation_service.design_run(incubation_id, _run_id(run_id))  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("not_found", "Intake Lab run not found", 404)

    @app.get("/api/incubations/{incubation_id}/runs/{run_id}/preview-token")
    async def incubation_preview_token(request: Request, incubation_id: str, run_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            safe_id = _run_id(run_id)
            incubation_service.design_run(incubation_id, safe_id)  # type: ignore[union-attr]
            token = access.issue((incubation_id, safe_id, "intake-lab"))
            return JSONResponse({"token": token, "expires_in": access.ttl}, headers={"Cache-Control": "no-store"})
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("not_found", "Intake Lab run not found", 404)

    @app.get("/api/incubations/{incubation_id}/runs/{run_id}/pages")
    async def incubation_run_pages(request: Request, incubation_id: str, run_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            safe_id = _run_id(run_id)
            run = incubation_service.design_run(incubation_id, safe_id)  # type: ignore[union-attr]
            pages = incubation_service.design_pages(incubation_id, safe_id)  # type: ignore[union-attr]
            return {
                "run_id": safe_id,
                "base_sha": run.get("base_sha"),
                "candidate_sha": run.get("candidate_sha"),
                "pages": [
                    {"path": page, "candidate": _incubation_preview_available(incubation_id, safe_id, page)}
                    for page in pages
                ],
            }
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("not_found", "Intake Lab run not found", 404)

    @app.get("/api/incubations/{incubation_id}/runs/{run_id}/preview/{variant}/{file_path:path}")
    async def incubation_preview_file(request: Request, incubation_id: str, run_id: str, variant: str, file_path: str):
        safe_id = _run_id(run_id)
        variant = str(variant or "").strip().lower()
        if variant not in _VARIANTS:
            raise HTTPException(status_code=404, detail="preview file not found")
        origin = request.headers.get("origin")
        if origin and origin != "null" and not _same_origin(request, origin):
            raise HTTPException(status_code=403, detail="request origin is not allowed")
        token = request.query_params.get("preview_token")
        if not access.valid(token, (incubation_id, safe_id, "intake-lab")):
            raise HTTPException(status_code=403, detail="preview token is invalid")
        safe_path = _safe_file_path(file_path)
        try:
            clone, sha = incubation_service.design_preview_identity(incubation_id, safe_id, variant)  # type: ignore[union-attr]
            profile = incubation_service.design_preview_profile(incubation_id, safe_id)  # type: ignore[union-attr]
            data = cache.read_file(clone, sha, safe_path, profile=profile)
            if not data:
                raise HTTPException(status_code=404, detail="preview file not found")
            if Path(safe_path).suffix.lower() in {".html", ".htm"}:
                data = rewrite_preview_html(
                    data, 0, safe_path, _site_url(service), token or "", variant,
                    preview_root=f"/api/incubations/{incubation_id}/runs/{safe_id}/preview/{variant}/",
                )
            elif Path(safe_path).suffix.lower() == ".css":
                data = rewrite_preview_css(data, safe_path, token or "", variant)
            return Response(
                content=data,
                media_type=mimetypes.guess_type(safe_path)[0] or "application/octet-stream",
                headers=_preview_headers(),
            )
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            raise HTTPException(status_code=404, detail="preview file not found") from exc

    @app.post("/api/incubations/{incubation_id}/runs/{run_id}/feedback")
    async def incubation_run_feedback(request: Request, incubation_id: str, run_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            body["run_id"] = _run_id(run_id)
            return incubation_service.feedback(incubation_id, body)  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_feedback_failed")

    @app.get("/api/incubations/{incubation_id}/chat/jobs/{job_id}")
    async def incubation_chat_job(request: Request, incubation_id: str, job_id: int):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return {"job": incubation_service.chat_job(incubation_id, job_id)}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("not_found", "Intake advice job not found", 404)

    @app.get("/api/incubations/{incubation_id}/chat/jobs")
    async def incubation_chat_jobs(request: Request, incubation_id: str, limit: int = 50):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return incubation_service.chat_jobs(incubation_id, limit=limit)  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "advice_jobs_unavailable")

    @app.get("/api/incubations/{incubation_id}/deductions")
    async def incubation_deductions(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            memory = incubation_service.open_store(incubation_id).memory  # type: ignore[union-attr]
            return {
                "deductions": memory.list_incubation_deductions(limit=200),
                "runs": memory.list_infusion_runs(limit=50),
            }
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "deductions_unavailable")

    @app.get("/api/incubations/{incubation_id}/genesis")
    async def incubation_genesis(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return {"genesis": incubation_service.genesis_projection(incubation_id)}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("genesis_unavailable", "genesis is unavailable", 503)

    @app.post("/api/incubations/{incubation_id}/confirm-intake", status_code=202)
    async def incubation_confirm_intake(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            result = incubation_service.confirm_intake(incubation_id, body)  # type: ignore[union-attr]
            return {"incubation_id": incubation_id, **result}
        except HTTPException:
            raise
        except (IncubationServiceError, DesignIntakeServiceError) as exc:
            return _incubation_error(exc, "intake_confirmation_failed")

    @app.post("/api/incubations/{incubation_id}/builds", status_code=202)
    async def incubation_build(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            result = incubation_service.build(incubation_id, body)  # type: ignore[union-attr]
            return {"incubation_id": incubation_id, **result}
        except HTTPException:
            raise
        except (IncubationServiceError, DesignIntakeServiceError) as exc:
            return _incubation_error(exc, "incubation_build_failed")

    @app.post("/api/incubations/{incubation_id}/feedback")
    async def incubation_feedback(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            return incubation_service.feedback(incubation_id, body)  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_feedback_failed")

    @app.post("/api/incubations/{incubation_id}/accept", status_code=202)
    async def incubation_accept(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            return {"incubation_id": incubation_id, **incubation_service.accept(incubation_id, body)}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_acceptance_failed")

    @app.post("/api/incubations/{incubation_id}/provision", status_code=202)
    async def incubation_provision(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request)
            return _public_provisioning({"incubation_id": incubation_id, **incubation_service.provision(incubation_id, body)})  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "provisioning_failed")

    @app.post("/api/incubations/{incubation_id}/activate", status_code=202)
    async def incubation_activate(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            body = await _json_object(request, allow_empty=True)
            return _public_provisioning({"incubation_id": incubation_id, **incubation_service.activate(incubation_id, body)})  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "activation_failed")

    @app.get("/api/incubations/{incubation_id}/provisioning")
    async def incubation_provisioning(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return _public_provisioning(incubation_service.provisioning_projection(incubation_id))  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError:
            return _error("provisioning_unavailable", "provisioning is unavailable", 503)

    @app.delete("/api/incubations/{incubation_id}")
    async def incubation_delete(request: Request, incubation_id: str):
        try:
            _require_api_origin(request)
            _incubation(incubation_id)
            return {"deleted": incubation_service.purge(incubation_id)}  # type: ignore[union-attr]
        except HTTPException:
            raise
        except IncubationServiceError as exc:
            return _incubation_error(exc, "incubation_delete_failed")

    @app.get("/api/lab")
    async def lab_info(request: Request):
        try:
            _require_api_origin(request)
            return service.describe()
        except HTTPException:
            raise
        except IntakeLabError as exc:
            return _error("lab_unavailable", str(exc), 503)

    def _require_intake() -> Any:
        if intake_service is None:
            raise HTTPException(status_code=503, detail="conversational intake is unavailable")
        return intake_service

    @app.get("/api/intake")
    async def intake_info(request: Request):
        try:
            _require_api_origin(request)
            intake = _require_intake()
            return intake.describe()
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_unavailable", str(exc), 503)

    @app.post("/api/intake-sessions", status_code=201)
    @app.post("/api/intake/sessions", status_code=201)
    async def intake_create_session(request: Request):
        try:
            _require_api_origin(request)
            intake = _require_intake()
            try:
                body = await request.json()
            except Exception:
                body = {}
            body = body if isinstance(body, dict) else {}
            return {"session": intake.create_session(conversation_id=body.get("conversation_id"))}
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_session_failed", str(exc), 400)

    @app.get("/api/intake-sessions")
    @app.get("/api/intake/sessions")
    async def intake_list_sessions(request: Request, limit: int = 20):
        try:
            _require_api_origin(request)
            intake = _require_intake()
            return {"sessions": intake.list_sessions(limit=limit)}
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_sessions_failed", str(exc), 400)

    @app.get("/api/intake-sessions/{session_id}")
    @app.get("/api/intake/sessions/{session_id}")
    async def intake_get_session(request: Request, session_id: str):
        try:
            _require_api_origin(request)
            return {"session": _require_intake().get_session(session_id)}
        except HTTPException:
            raise
        except DesignIntakeServiceError:
            return _error("not_found", "Intake session not found", 404)

    @app.post("/api/intake-sessions/{session_id}/messages", status_code=202)
    @app.post("/api/intake/sessions/{session_id}/messages", status_code=202)
    async def intake_message(request: Request, session_id: str):
        try:
            _require_api_origin(request)
            try:
                body = await request.json()
            except Exception:
                return _error("invalid_json", "request body must be valid JSON", 400)
            if not isinstance(body, dict) or not isinstance(body.get("message"), str):
                return _error("invalid_request", "message must be text", 400)
            result = _require_intake().send_message(
                session_id,
                body["message"],
                attachments=body.get("attachments"),
                idempotency_key=body.get("idempotency_key"),
            )
            return result
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_message_failed", str(exc), 400)

    @app.post("/api/intake-sessions/{session_id}/assets")
    @app.post("/api/intake/sessions/{session_id}/assets")
    async def intake_assets(request: Request, session_id: str):
        try:
            _require_api_origin(request)
            body = await request.json()
            assets = body.get("assets") if isinstance(body, dict) else body
            return {"session": _require_intake().update_assets(session_id, assets)}
        except HTTPException:
            raise
        except (DesignIntakeServiceError, ValueError) as exc:
            return _error("intake_assets_failed", str(exc), 400)

    @app.patch("/api/intake-sessions/{session_id}/assets/{asset_id}")
    @app.patch("/api/intake/sessions/{session_id}/assets/{asset_id}")
    async def intake_asset_update(request: Request, session_id: str, asset_id: int):
        try:
            _require_api_origin(request)
            body = await request.json()
            if not isinstance(body, dict):
                return _error("invalid_request", "asset update must be an object", 400)
            return {"session": _require_intake().update_asset(session_id, asset_id, body)}
        except HTTPException:
            raise
        except (DesignIntakeServiceError, ValueError) as exc:
            return _error("intake_asset_update_failed", str(exc), 400)

    @app.delete("/api/intake-sessions/{session_id}/assets/{asset_id}")
    @app.delete("/api/intake/sessions/{session_id}/assets/{asset_id}")
    async def intake_asset_delete(request: Request, session_id: str, asset_id: int):
        try:
            _require_api_origin(request)
            return {"session": _require_intake().remove_asset(session_id, asset_id)}
        except HTTPException:
            raise
        except (DesignIntakeServiceError, ValueError) as exc:
            return _error("intake_asset_delete_failed", str(exc), 400)

    @app.get("/api/intake-sessions/{session_id}/assets/{asset_id}/thumbnail")
    @app.get("/api/intake/sessions/{session_id}/assets/{asset_id}/thumbnail")
    async def intake_asset_thumbnail(request: Request, session_id: str, asset_id: int):
        try:
            _require_api_origin(request)
            _require_intake().asset_thumbnail_url(session_id, asset_id)
            return _media_preview(asset_id, thumbnail=True)
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_asset_thumbnail_failed", str(exc), 404)

    @app.post("/api/intake-sessions/{session_id}/confirm", status_code=202)
    @app.post("/api/intake/sessions/{session_id}/confirm", status_code=202)
    async def intake_confirm(request: Request, session_id: str):
        try:
            _require_api_origin(request)
            try:
                body = await request.json()
            except Exception:
                return _error("invalid_json", "request body must be valid JSON", 400)
            if not isinstance(body, dict):
                return _error("invalid_request", "confirmation must be an object", 400)
            required = ("revision", "draft_hash")
            if any(key not in body for key in required):
                return _error("invalid_request", "revision and draft_hash are required", 400)
            return _require_intake().confirm(
                session_id,
                revision=body["revision"],
                draft_hash=body["draft_hash"],
                confirmation_text=body.get("confirmation_text", "Build this"),
                idempotency_key=body.get("idempotency_key"),
            )
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_confirmation_failed", str(exc), 409)

    @app.post("/api/intake-sessions/{session_id}/build", status_code=202)
    @app.post("/api/intake/sessions/{session_id}/build", status_code=202)
    async def intake_build(request: Request, session_id: str):
        try:
            _require_api_origin(request)
            try:
                body = await request.json()
            except Exception:
                return _error("invalid_json", "request body must be valid JSON", 400)
            if not isinstance(body, dict) or "confirmed_revision" not in body:
                return _error("invalid_request", "confirmed_revision is required", 400)
            return _require_intake().build(
                session_id,
                confirmed_revision=body["confirmed_revision"],
                owner_request=body.get("owner_request", ""),
                idempotency_key=body.get("idempotency_key"),
                force_new=bool(body.get("force_new")),
            )
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_build_failed", str(exc), 409)

    @app.post("/api/intake-sessions/{session_id}/feedback")
    @app.post("/api/intake/sessions/{session_id}/feedback")
    async def intake_feedback(request: Request, session_id: str):
        try:
            _require_api_origin(request)
            body = await request.json()
            if not isinstance(body, dict):
                return _error("invalid_request", "feedback must be an object", 400)
            return {"session": _require_intake().record_feedback(
                session_id,
                body.get("kind"),
                notes=body.get("notes", ""),
                run_id=body.get("run_id"),
            )}
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_feedback_failed", str(exc), 400)

    @app.post("/api/runs/{run_id}/feedback")
    async def run_feedback(request: Request, run_id: str):
        try:
            _require_api_origin(request)
            body = await request.json()
            if not isinstance(body, dict):
                return _error("invalid_request", "feedback must be an object", 400)
            return {"session": _require_intake().record_run_feedback(
                _run_id(run_id),
                body.get("kind"),
                notes=body.get("notes", ""),
            )}
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("intake_feedback_failed", str(exc), 400)

    @app.get("/api/chat/jobs/{job_id}")
    async def intake_chat_job(request: Request, job_id: int):
        try:
            _require_api_origin(request)
            intake = _require_intake()
            job = intake.memory.get_chat_job(job_id)
            if not job or job.get("operation_kind") != "design_intake_advice":
                return _error("not_found", "Intake advice job not found", 404)
            return {"job": {
                "id": job.get("id"),
                "status": job.get("status"),
                "steps": job.get("steps") or [],
                "result": job.get("result"),
                "error": job.get("error"),
                "session_id": job.get("intake_session_id"),
                "message_id": job.get("message_id"),
            }}
        except HTTPException:
            raise
        except DesignIntakeServiceError as exc:
            return _error("job_unavailable", str(exc), 503)

    @app.get("/api/intake/media")
    async def intake_media(request: Request, limit: int = 50):
        try:
            _require_api_origin(request)
            if media_service is None:
                return {"assets": []}
            assets = media_service.list(media_kind="image", include_archived=False, limit=max(1, min(limit, 100)))
            for asset in assets:
                asset_id = int(asset["id"])
                if asset.get("thumbnail_url"):
                    asset["thumbnail_url"] = f"./api/intake/media/{asset_id}/thumbnail"
                if asset.get("preview_url"):
                    asset["preview_url"] = f"./api/intake/media/{asset_id}/preview"
            return {"assets": assets}
        except HTTPException:
            raise
        except Exception as exc:
            return _error("media_unavailable", str(exc), 503)

    @app.post("/api/intake/media", status_code=201)
    async def intake_media_upload(request: Request):
        try:
            _require_api_origin(request)
            if media_service is None:
                return _error("media_unavailable", "image uploads are unavailable", 503)
            content_type = request.headers.get("content-type", "")
            if content_type.lower().startswith("multipart/form-data"):
                form = await request.form()
                upload_file = form.get("file")
                if upload_file is None or not hasattr(upload_file, "read"):
                    return _error("invalid_request", "file is required", 400)
                data = await upload_file.read()
                name = str(getattr(upload_file, "filename", "upload"))
                mime = str(getattr(upload_file, "content_type", "") or "")
            else:
                body = await request.json()
                if not isinstance(body, dict):
                    return _error("invalid_request", "upload must be an object", 400)
                name = str(body.get("name") or "upload")
                encoded = str(body.get("data") or "")
                data = base64.b64decode(encoded, validate=True)
                mime = str(body.get("content_type") or "")
            return {"asset": media_service.upload(name, data, mime).get("asset")}
        except HTTPException:
            raise
        except Exception as exc:
            return _error("media_upload_failed", str(exc), 400)

    @app.get("/api/intake/media/object")
    async def intake_media_object(request: Request, key: str):
        try:
            _require_api_origin(request)
            if media_service is None or not isinstance(getattr(media_service, "store", None), LocalMediaStore):
                raise HTTPException(status_code=404, detail="media object not found")
            store = media_service.store
            data = store.get(key)
            return Response(content=data, media_type=store.content_type(key), headers={"Cache-Control": "no-store"})
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail="media object not found") from exc

    def _media_preview(asset_id: int, *, thumbnail: bool):
        if media_service is None:
            raise HTTPException(status_code=404, detail="media object not found")
        try:
            asset = media_service.get(asset_id)
            key = asset.thumbnail_key if thumbnail else asset.normalized_key
            if not key:
                raise HTTPException(status_code=404, detail="media object not found")
            store = getattr(media_service, "store", None)
            if isinstance(store, LocalMediaStore):
                return Response(
                    content=store.get(key),
                    media_type=store.content_type(key),
                    headers={"Cache-Control": "private, no-store"},
                )
            url = media_service.preview_url(asset_id)
            return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, no-store"})
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail="media object not found") from exc

    @app.get("/api/intake/media/{asset_id}/thumbnail")
    async def intake_media_thumbnail(request: Request, asset_id: int):
        _require_api_origin(request)
        return _media_preview(asset_id, thumbnail=True)

    @app.get("/api/intake/media/{asset_id}/preview")
    async def intake_media_preview(request: Request, asset_id: int):
        _require_api_origin(request)
        return _media_preview(asset_id, thumbnail=False)

    @app.post("/api/runs", status_code=202)
    async def create_run(request: Request):
        try:
            _require_api_origin(request)
            body = await request.body()
            if len(body) > _MAX_BODY_BYTES:
                return _error("request_too_large", "request exceeds 400000 bytes", 413)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return _error("invalid_json", "request body must be valid JSON", 400)
            if not isinstance(payload, dict) or set(payload) != {"prompt", "intake"}:
                return _error("invalid_request", "request must contain only prompt and intake", 400)
            if executor is not None and getattr(executor, "running", True) is False:
                return _error("worker_unavailable", "Intake Lab worker is not running", 503)
            try:
                result = service.submit(payload.get("prompt"), payload.get("intake"))
            except IntakeLabError as exc:
                return _error("invalid_intake", str(exc), 400)
            return JSONResponse(result, status_code=202)
        except HTTPException:
            raise
        except Exception:
            return _error("request_failed", "Intake Lab could not create the run", 503)

    @app.get("/api/runs")
    async def list_runs(request: Request):
        try:
            _require_api_origin(request)
            raw_limit = request.query_params.get("limit", "50")
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                return _error("invalid_limit", "limit must be an integer", 400)
            if not 1 <= limit <= 100:
                return _error("invalid_limit", "limit must be between 1 and 100", 400)
            return {"runs": service.list_runs(limit=limit)}
        except HTTPException:
            raise
        except IntakeLabError as exc:
            return _error("runs_unavailable", str(exc), 503)

    @app.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str):
        try:
            _require_api_origin(request)
            return service.get_run(_run_id(run_id))
        except HTTPException:
            raise
        except IntakeLabError:
            return _error("not_found", "Intake Lab run not found", 404)

    @app.get("/api/runs/{run_id}/preview-token")
    async def preview_token(request: Request, run_id: str):
        try:
            _require_api_origin(request)
            safe_id = _run_id(run_id)
            service.get_run(safe_id)
            token = access.issue((safe_id, "intake-lab"))
            return JSONResponse(
                {"token": token, "expires_in": access.ttl},
                headers={"Cache-Control": "no-store"},
            )
        except HTTPException:
            raise
        except IntakeLabError:
            return _error("not_found", "Intake Lab run not found", 404)

    @app.get("/api/runs/{run_id}/pages")
    async def run_pages(request: Request, run_id: str):
        try:
            _require_api_origin(request)
            safe_id = _run_id(run_id)
            run = service.get_run(safe_id)
            pages = service.pages(safe_id)
            return {
                "run_id": safe_id,
                "base_sha": run.get("base_sha"),
                "candidate_sha": run.get("candidate_sha"),
                "pages": [
                    {
                        "path": page,
                        "candidate": preview_available(safe_id, "candidate", page),
                    }
                    for page in pages
                ],
            }
        except HTTPException:
            raise
        except IntakeLabError:
            return _error("not_found", "Intake Lab run not found", 404)

    @app.post("/api/runs/{run_id}/visual-review", status_code=202)
    def retry_visual_review(request: Request, run_id: str):
        try:
            _require_api_origin(request)
            run = service.retry_visual_review(_run_id(run_id))
            return {"run": run}
        except HTTPException:
            raise
        except IntakeLabError as exc:
            return _error("visual_review_unavailable", str(exc), 409)

    @app.post("/api/runs/{run_id}/visual-refinement", status_code=202)
    def create_visual_refinement(request: Request, run_id: str):
        try:
            _require_api_origin(request)
            run = service.create_visual_refinement(_run_id(run_id))
            return {"parent_run_id": _run_id(run_id), "run": run}
        except HTTPException:
            raise
        except IntakeLabError as exc:
            return _error("visual_refinement_unavailable", str(exc), 409)

    @app.get("/api/runs/{run_id}/preview/{variant}/{file_path:path}")
    async def preview_file(request: Request, run_id: str, variant: str, file_path: str):
        safe_id = _run_id(run_id)
        variant = str(variant or "").strip().lower()
        if variant not in _VARIANTS:
            raise HTTPException(status_code=404, detail="preview file not found")
        origin = request.headers.get("origin")
        if origin and origin != "null" and not _same_origin(request, origin):
            raise HTTPException(status_code=403, detail="request origin is not allowed")
        token = request.query_params.get("preview_token")
        if not access.valid(token, (safe_id, "intake-lab")):
            raise HTTPException(status_code=403, detail="preview token is invalid")
        safe_path = _safe_file_path(file_path)
        try:
            clone, sha = service.preview_identity(safe_id, variant)
        except IntakeLabError as exc:
            raise HTTPException(status_code=404, detail="preview variant is unavailable") from exc
        profile_resolver = getattr(service, "preview_profile", None)
        profile = profile_resolver(safe_id) if callable(profile_resolver) else ""
        data = cache.read_file(clone, sha, safe_path, profile=profile)
        if not data:
            raise HTTPException(status_code=404, detail="preview file not found")
        suffix = Path(safe_path).suffix.lower()
        if suffix in {".html", ".htm"}:
            data = rewrite_preview_html(
                data,
                0,
                safe_path,
                _site_url(service),
                token or "",
                variant,
                preview_root=f"/api/runs/{safe_id}/preview/{variant}/",
            )
        elif suffix == ".css":
            data = rewrite_preview_css(data, safe_path, token or "", variant)
        media_type = mimetypes.guess_type(safe_path)[0] or "application/octet-stream"
        return Response(content=data, media_type=media_type, headers=_preview_headers())

    @app.get("/healthz")
    async def healthz():
        running = True if executor is None else bool(getattr(executor, "running", True))
        return {"ok": running, "worker_running": running, "workspace": str(workspace_path.name)}

    return app


def serve_intake_lab(
    service: IntakeLabService,
    *,
    host: str = "127.0.0.1",
    port: int = 3012,
    workspace: str | Path | None = None,
) -> None:
    """Serve the standalone app; the CLI owns dependency cleanup."""
    import uvicorn

    app = create_app(service, workspace=workspace)
    uvicorn.run(app, host=host, port=int(port), log_level="warning")


__all__ = ["create_app", "serve_intake_lab"]
