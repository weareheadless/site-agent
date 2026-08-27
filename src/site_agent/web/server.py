"""web/server.py — the admin API + UI.

Password auth with in-memory sessions (the OceanicVibes model): the owner
logs in once, everything else is same-origin cookie. All site mutations
flow through drafts: approve is the only path to a commit.
"""

from __future__ import annotations

import base64
import datetime
import hmac
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from ..application.actions import ActionServiceError, OwnerActionService
from ..application.approvals import ApprovalService, ApprovalServiceError, StaleApproval
from ..application.conversations import ConversationBusy, ConversationNotFound, ConversationService, ConversationServiceError
from ..application.home import HomeService
from ..brain import editor as brain_editor
from ..config import resolve_secret
from ..core.contracts import ApprovalStatus
from ..core.reflect import approve_reflection, effective_persona
from ..hands import file_cache, pelican_blog
from ..hands.base import AdapterError, MergeAdapter, PreviewAdapter, SiteAdapter, get_adapter
from .journal import setup_job, status as journal_status
from .preview import PreviewBuildCache, rewrite_preview_html

SESSION_TTL = 12 * 3600
COOKIE = "sa_session"
STATIC_DIR = Path(__file__).parent / "static"


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


def _normalize_ops(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """New-style ops list; tolerates the older single-file / dotted-field shapes."""
    if isinstance(meta.get("ops"), list):
        return meta["ops"]
    if meta.get("file_op"):
        return [{"op": "edit", "path": meta["path"], "find": meta["find"], "replace": meta["replace"]}]
    return [
        {"op": "set_field", "path": c.get("path", ""), "field": c["field"], "value": c["after"]}
        for c in (meta.get("changes") or [])
    ]


DEFAULT_ADMIN_THEME = {
    "bg": "#0b1017",
    "card": "#111a24",
    "panel": "#0d1520",
    "line": "#22303f",
    "text": "#e8eef5",
    "dim": "#8b98a8",
    "accent": "#7ec8ff",
    "brand": "#9edbd1",
    "ok": "#4ade80",
    "warn": "#f0c25e",
    "bad": "#ff7a8a",
    "radius": "14px",
    "font_body": "-apple-system, Segoe UI, Roboto, sans-serif",
    "font_display": "inherit",
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

    env = os.environ if env is None else env
    config = context["config"]
    memory: Any = context["memory"]
    home_service = context.get("home_service") or HomeService(memory)
    owner_action_service = context.get("owner_action_service") or OwnerActionService(memory)
    approval_service = context.get("approval_service") or ApprovalService(memory, actions=owner_action_service)
    conversation_service = context.get("conversation_service") or ConversationService(memory)
    context.setdefault("home_service", home_service)
    context.setdefault("owner_action_service", owner_action_service)
    context.setdefault("approval_service", approval_service)
    context.setdefault("conversation_service", conversation_service)
    sessions = Sessions()
    preview_cache = PreviewBuildCache()
    def current_token(request: Request) -> str | None:
        return request.cookies.get(COOKIE)

    def require_auth(request: Request) -> None:
        if not sessions.valid(current_token(request)):
            raise HTTPException(status_code=401, detail="authentication required")

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

        # A process killed during a build cannot safely resume its side effects.
        # Surface that work as retryable instead of replaying it automatically.
        memory.interrupt_running_chat_jobs()
        executor = ChatJobExecutor(context, adapter_factory=adapter)
        executor.start()
        _app.state._chat_executor = executor
        try:
            yield
        finally:
            executor.stop()
            executor.join()
            preview_cache.clear()
            _app.state._chat_executor = None

    app = FastAPI(
        title="site-agent admin",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
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

    @app.get("/api/approvals/{approval_id}")
    def approval_preview(approval_id: int, request: Request):
        require_auth(request)
        try:
            return approval_service.preview(approval_id)
        except ApprovalServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/approvals/{approval_id}/approve")
    def approve_artifact(approval_id: int, request: Request):
        require_auth(request)
        try:
            approval = approval_service.decide(approval_id, True)
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
        return {"approvals": approval_service.list(status=approval_status, limit=max(1, min(limit, 100)))}

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

    @app.get("/api/content")
    def get_content(request: Request):
        """Read the site's content.json for the Content editor tab."""
        require_auth(request)
        try:
            ad = adapter()
            return {"content": ad.get_content()}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"read content failed: {exc}")

    @app.post("/api/content")
    async def put_content(request: Request):
        """Save edited content.json straight to the site (same as the old studio editor)."""
        require_auth(request)
        file_cache.clear()
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid json")
        content = (body or {}).get("content")
        if not isinstance(content, dict):
            raise HTTPException(status_code=400, detail="content must be a JSON object")
        ad = adapter()
        try:
            payload = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
            result = ad.commit_file(
                str(config.get("site", {}).get("content_path", "content.json")),
                payload.encode(),
                "Website content edit (admin)",
            )
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=f"save failed: {exc}")
        memory.record_action("content", "content.json edited and published")
        return {"ok": True, "published": result}

    @app.get("/api/media")
    def media_list(request: Request):
        """List existing image assets in the site repo (useful for replacing an image)."""
        require_auth(request)
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
        """Upload an image to Cloudflare R2 (S3-compatible). Body: {name, data(base64)}."""
        require_auth(request)
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

    @app.get("/api/conversations/{conv_id}")
    def get_conversation(conv_id: int, request: Request):
        require_auth(request)
        try:
            return conversation_service.get(conv_id)
        except ConversationServiceError as exc:
            raise _conversation_error(exc)

    @app.get("/api/preview/{file_path:path}")
    async def preview_file(file_path: str, request: Request):
        """Serve the site's published state (origin/main) from the local clone —
        instant visual reference with zero dependence on Cloudflare build times.
        The clone's working tree is transient (the builder checks out the preview
        branch), so we read straight from git instead of the checked-out files."""
        require_auth(request)
        import mimetypes
        import subprocess

        clone = Path(str(config.get("site", {}).get("clone_path", "")).strip())
        if not clone.exists():
            raise HTTPException(status_code=404, detail="no clone configured")
        name = file_path.lstrip("/")
        if not name:
            name = "index.html"
        published_ref = _published_ref(clone)
        if _git_ref_file_exists(clone, published_ref, "pelicanconf.py"):
            built = preview_cache.read_file(clone, published_ref, name)
            if built:
                if name.lower().endswith((".html", ".htm")):
                    built = rewrite_preview_html(
                        built,
                        0,
                        name,
                        str((config.get("blog") or {}).get("site_url") or ""),
                    )
                mt = mimetypes.guess_type(name)[0] or "application/octet-stream"
                return Response(content=built, media_type=mt,
                                headers={"Cache-Control": "no-store"})
        proc = subprocess.run(
            ["git", "-C", str(clone), "show", f"{published_ref}:{name}"],
            capture_output=True, timeout=30,
        )
        if proc.returncode != 0 and "." not in Path(name).name:
            proc = subprocess.run(
                ["git", "-C", str(clone), "show", f"{published_ref}:index.html"],
                capture_output=True, timeout=30,
            )
            name = "index.html"
        if proc.returncode != 0:
            raise HTTPException(status_code=404, detail=f"{name} not on main")
        mt = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return Response(content=proc.stdout, media_type=mt,
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/review/{draft_id}/{file_path:path}")
    async def review_file(draft_id: int, file_path: str, request: Request):
        """Review a staged draft — no GitHub Pages build needed.

        merge drafts: served straight out of git (origin/preview) so the
        builder's working tree is never disturbed. edit drafts: the base file
        (origin/main) with this draft's find/replace ops applied live."""
        import mimetypes
        import subprocess

        require_auth(request)
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        clone = Path(str(config.get("site", {}).get("clone_path", "")).strip())
        if not clone.exists():
            raise HTTPException(status_code=404, detail="no clone configured")
        name = file_path.lstrip("/")
        if not name:
            name = "index.html"
        path_parts = Path(name).parts
        if Path(name).is_absolute() or ".." in path_parts:
            raise HTTPException(status_code=400, detail="invalid preview path")
        try:
            subprocess.run(
                ["git", "-C", str(clone), "fetch", "origin", "preview", "main"],
                capture_output=True, timeout=45,
            )
        except Exception:  # noqa: BLE001 — stale ref still works
            pass

        def _show_at(ref: str, rel: str) -> bytes:
            proc = subprocess.run(
                ["git", "-C", str(clone), "show", f"{ref}:{rel}"],
                capture_output=True, timeout=30,
            )
            return proc.stdout if proc.returncode == 0 else b""

        def _serve(rel: str, data: bytes) -> Response:
            mt = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            return Response(content=data, media_type=mt,
                            headers={"Cache-Control": "no-store"})

        kind = draft["kind"]
        if kind == "edit":
            # Apply this draft's ops onto the base file (origin/main) live.
            # Once decided (approved/declined/discarded) the ops no longer apply:
            # the visualizer falls back to the live file, so reject genuinely rolls back.
            ops = _normalize_ops(draft["meta"]) if draft["status"] == "pending" else []
            content = _show_at("origin/main", name) or _show_at("main", name)
            if not content and "." not in Path(name).name:
                content = _show_at("origin/main", "index.html") or _show_at("main", "index.html")
                name = "index.html"
            if not content:
                raise HTTPException(status_code=404, detail=f"{name} not on main")
            # Binary assets (images, fonts, …) pass through untouched — ops only
            # target text files, and decoding them would corrupt the bytes.
            if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico", ".avif", ".woff", ".woff2", ".eot", ".ttf", ".otf"}:
                return _serve(name, content)
            text = content.decode("utf-8", "replace")
            for op in ops:
                opath = str(op.get("path", "")).lstrip("/").split("?")[0]
                if opath != name:
                    continue
                if op.get("op") == "edit":
                    text = text.replace(op.get("find", ""), op.get("replace", ""))
                elif op.get("op") == "write":
                    text = str(op.get("content", ""))
            rendered = text.encode()
            return _serve(
                name,
                rewrite_preview_html(
                    rendered,
                    draft_id,
                    name,
                    str((config.get("blog") or {}).get("site_url") or ""),
                )
                if name.lower().endswith((".html", ".htm"))
                else rendered,
            )

        # Prefer generated output for staged builds. This covers Pelican pages
        # and theme assets while falling back to committed files for legacy sites.
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
                        str((config.get("blog") or {}).get("site_url") or ""),
                    )
                    if name.lower().endswith((".html", ".htm"))
                    else built,
                )

        # merge / rollback / article drafts: read the staged preview-branch file.
        content = _show_at("origin/preview", name)
        if not content:
            content = _show_at("preview", name)
        if not content:
            if "." not in Path(name).name:
                content = _show_at("origin/preview", "index.html")
                name = "index.html"
            if not content:
                content = _show_at("preview", "index.html")
                name = "index.html"
        if not content:
            raise HTTPException(status_code=404, detail=f"{name} not on preview branch")
        return _serve(
            name,
            rewrite_preview_html(
                content,
                draft_id,
                name,
                str((config.get("blog") or {}).get("site_url") or ""),
            )
            if name.lower().endswith((".html", ".htm"))
            else content,
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
            and not line.strip().startswith(("themes/", "content/"))
        )
        return sorted(pages, key=lambda p: (p != "index.html", p))

    @app.get("/api/pages")
    def pages(request: Request, draft_id: int | None = None):
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
        if draft_id is not None:
            draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail="no such draft")
            if draft["status"] != "pending":
                ref = published_ref
            elif draft["kind"] in ("merge", "rollback"):
                # Pages the staged build adds beyond what's already published.
                preview_ref = "origin/preview" if _git_ref_exists(clone, "origin/preview") else "preview"
                preview_pages = _list_html_at(clone, preview_ref)
                if _git_ref_file_exists(clone, preview_ref, "pelicanconf.py"):
                    preview_pages.append("articles.html")
                ref = preview_ref
                draft_new = [p for p in preview_pages if p not in main_pages]
            else:  # edit draft: base pages + any write-ops (new pages) + edit-ops targets
                ops = _normalize_ops(draft["meta"])
                write_pages = {
                    str(op["path"]).lstrip("/").split("?")[0]
                    for op in ops
                    if op.get("op") == "write"
                    and str(op["path"]).lstrip("/").split("?")[0].lower().endswith((".html", ".htm"))
                }
                draft_new = sorted(write_pages, key=lambda p: (p != "index.html", p))
        pages_list = _list_html_at(clone, ref)
        if not pages_list:
            pages_list = main_pages
        if _git_ref_file_exists(clone, ref, "pelicanconf.py"):
            pages_list.append("articles.html")
        pages_list = list(dict.fromkeys(pages_list + draft_new))
        return {"pages": pages_list, "new_pages": draft_new}

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

    def _enqueue_chat(message: str, conv_id: int) -> int:
        """Persist the user message and its background job in one transaction."""
        return memory.enqueue_chat_job(conv_id, message)

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

        job_id = _enqueue_chat(message, conv_id)
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
        """Customer-facing published website versions, without Git details."""
        require_auth(request)
        rows = []
        for publish in memory.list_publishes(limit=50):
            if not publish.get("commit_sha"):
                continue
            rows.append({
                "id": publish["id"],
                "summary": publish["summary"],
                "published_ts": publish["ts"],
                "actor": publish.get("actor") or "ada",
                "version_type": publish.get("version_type") or "edit",
                "current": False,
                "restored": publish.get("version_type") == "rollback",
            })
        if rows:
            rows[0]["current"] = True
        return {"versions": rows}

    @app.get("/api/journal")
    def journal(request: Request):
        require_auth(request)
        return journal_status(config, memory)

    @app.post("/api/journal/enable")
    def enable_journal(request: Request):
        require_auth(request)
        blog = config.get("blog") or {}
        if str(blog.get("engine", "pelican")).lower() != "pelican":
            raise HTTPException(status_code=400, detail="Pelican is not enabled for this site")
        llm = context.get("llm")
        if llm is None or (hasattr(llm, "api_key") and not llm.api_key):
            raise HTTPException(status_code=503, detail="LLM not configured")
        if memory.kv_get("journal_setup_requested", False):
            existing = setup_job(memory)
            if existing and existing["status"] in {"queued", "running"}:
                return {"ok": True, "enabled": True, "already_requested": True, "job_id": existing["id"]}
        memory.kv_set("journal_enabled", True)
        memory.kv_set("journal_setup_requested", True)
        conv_id = memory.create_conversation("Set up Ada's journal")
        message = (
            "Set up the customer-facing journal for this website. Inspect the existing homepage and design language. "
            "Ada must personally design and implement the Pelican article listing and article page so they feel like this website, not a generic CMS. "
            "Make the journal discoverable from the existing navigation when appropriate, keep it responsive and accessible, "
            "and limit code changes to the existing Pelican templates, journal-scoped CSS, and public navigation; do not modify build.sh, pelicanconf.py, or deployment configuration. "
            "The homepage header is fixed and uses the 1240px/48px gutter system: keep every journal first-content block below the header safe offset, and do not reuse homepage class names without supplying the required journal styles. "
            "Redesign base.html, index.html, and article.html as one coherent system. Run build.sh, inspect output/articles.html, and verify the article template before finishing. "
            "Work autonomously in the native Build session; use native task delegation when it materially helps, but keep final design decisions and implementation in the primary session. "
            "Do not modify build.sh, pelicanconf.py, deployment configuration, or invent customer content. Work in the normal preview flow; do not publish directly. "
            "When the design is ready, leave a preview for the owner to approve."
        )
        job_id = memory.enqueue_chat_job(conv_id, message)
        memory.kv_set("journal_setup_job_id", job_id)
        memory.record_action("journal_enabled", f"journal enabled; setup job #{job_id}")
        return {"ok": True, "enabled": True, "conversation_id": conv_id, "job_id": job_id}

    @app.post("/api/drafts/{draft_id}/preview")
    def preview(draft_id: int, request: Request):
        require_auth(request)
        file_cache.clear()
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        if draft["kind"] != "edit" or draft["status"] != "pending":
            raise HTTPException(status_code=400, detail="only pending edit drafts can be previewed")
        ad = adapter_validated()
        pbranch = str(config.get("site", {}).get("preview_branch") or "")
        if not pbranch:
            raise HTTPException(status_code=400, detail="set site.preview_branch (Cloudflare Pages builds it automatically)")
        if not isinstance(ad, PreviewAdapter):
            raise HTTPException(status_code=400, detail="adapter does not support previews")
        try:
            ad.ensure_branch(pbranch)
            results = brain_editor._apply_ops(ad, _normalize_ops(draft["meta"]), branch=pbranch)
            pushed = results[0] if results else {"committed": False}
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=f"preview push failed: {exc}")

        preview_url = None
        cf_token = resolve_secret(config, "cloudflare_api_token", env)
        cf = config.get("site", {}).get("cloudflare") or {}
        if cf_token and cf.get("account_id") and cf.get("project_name"):
            try:
                from ..senses import cloudflare as cf_sense
                preview_url = cf_sense.latest_preview_url(
                    str(cf["account_id"]), str(cf["project_name"]), pbranch, cf_token
                )
            except Exception:  # noqa: BLE001 — URL lookup must not fail the push
                preview_url = None
        memory.kv_set("last_preview_url", preview_url)
        memory.record_action("preview", f"draft #{draft_id} -> branch {pbranch}")
        return {"ok": bool(pushed.get("committed")), "branch": pbranch, "pushed": pushed, "preview_url": preview_url}

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
                "kind": d["kind"],
                "status": d["status"],
                "title": d["title"],
                "created_ts": d["created_ts"],
                "commit_sha": (p or {}).get("commit_sha"),
                "reverted_ts": (p or {}).get("reverted_ts"),
            })
        return {"history": entries}

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: int, request: Request):
        require_auth(request)
        draft = next((d for d in memory.list_drafts(limit=100) if d["id"] == draft_id), None)
        if draft is None:
            raise HTTPException(status_code=404, detail="no such draft")
        return draft

    def _publish_article(ad: SiteAdapter, draft: dict[str, Any]) -> dict[str, Any]:
        slug = brain_editor.slugify(draft["title"])
        if pelican_blog.enabled(config):
            meta = dict(draft.get("meta") or {})
            meta["slug"] = slug
            payload = pelican_blog.document(config, draft["title"], draft["body"], meta)
            path = pelican_blog.article_path(config, slug)
        else:
            payload = draft["body"].encode()
            path = f"articles/{slug}.md"
        result = ad.commit_file(
            path,
            payload,
            f"article: {draft['title']} (by {config.get('persona', {}).get('name', 'Ada')})",
        )
        return result

    def _draft_ops_paths(draft: dict[str, Any]) -> set[str] | None:
        """The files a pending edit/merge draft would touch (for overlap checks).
        A merge replaces the whole preview branch -> returns None meaning
        'overlaps everything'."""
        if draft["kind"] in ("merge", "rollback"):
            return None
        return {
            str(op.get("path", "")).lstrip("/").split("?")[0]
            for op in _normalize_ops(draft["meta"])
            if op.get("path")
        }

    def _supersede_overlapping_pending(draft: dict[str, Any]) -> list[int]:
        """After approving a change, any other pending edit/merge draft touching
        the same files can no longer apply cleanly to the published site — mark
        them discarded so stale work never reappears in the review UI."""
        if draft["kind"] not in ("edit", "merge", "rollback"):
            return []
        approved_paths = _draft_ops_paths(draft)
        superseded = []
        for other in memory.list_drafts(status="pending"):
            if other["id"] == draft["id"]:
                continue
            if other["kind"] not in ("edit", "merge", "rollback"):
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

        published = None
        if draft["kind"] == "reflection":
            if not approve_reflection(memory, draft_id):
                raise HTTPException(status_code=400, detail="could not merge reflection")
        elif draft["kind"] == "edit":
            ad = adapter_validated()
            try:
                results = brain_editor._apply_ops(ad, _normalize_ops(draft["meta"]))
                published = results[0] if results else None
                if len(results) > 1:
                    memory.record_action("approve_detail", json.dumps(results)[:400])
            except (AdapterError, brain_editor.EditError, KeyError) as exc:
                raise HTTPException(status_code=400, detail=f"apply failed: {exc}")
            memory.update_draft_status(draft_id, "approved")
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
        elif draft["kind"] == "article":
            ad = adapter_validated()
            try:
                published = _publish_article(ad, draft)
                if not pelican_blog.enabled(config):
                    slug = brain_editor.slugify(draft["title"])
                    _, raw_index = ad.get_file("articles/index.json")
                    index = json.loads(raw_index) if raw_index else []
                    entry = {
                        "slug": slug,
                        "title": draft["title"],
                        "date": datetime.date.today().isoformat(),
                    }
                    if entry["slug"] not in [e.get("slug") for e in index]:
                        index.insert(0, entry)
                    ad.commit_file(
                        "articles/index.json",
                        (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode(),
                        f"article index: {slug}",
                    )
            except AdapterError as exc:
                raise HTTPException(status_code=400, detail=f"publish failed: {exc}")
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
            )
        superseded = _supersede_overlapping_pending(draft)
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

    def _unpublish_article(ad: SiteAdapter, draft: dict[str, Any]) -> dict[str, Any]:
        """Remove a mistakenly approved article from the site: delete its file and
        drop its entry from the index. Used by decline."""
        if not hasattr(ad, "delete_file"):
            raise AdapterError("adapter does not support deleting files")
        slug = brain_editor.slugify(draft["title"])
        path = pelican_blog.article_path(config, slug) if pelican_blog.enabled(config) else f"articles/{slug}.md"
        deleted = ad.delete_file(
            path,
            f"Decline article draft #{draft['id']}: remove {slug}",
        )
        if pelican_blog.enabled(config):
            return {"removed": slug, "deleted": bool(deleted.get("deleted"))}
        _, raw_index = ad.get_file("articles/index.json")
        index = json.loads(raw_index) if raw_index else []
        pruned = [e for e in index if e.get("slug") != slug]
        if len(pruned) != len(index):
            ad.commit_file(
                "articles/index.json",
                (json.dumps(pruned, indent=2, ensure_ascii=False) + "\n").encode(),
                f"article index: remove {slug}",
            )
        return {"removed": slug, "deleted": bool(deleted.get("deleted"))}

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
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        feedback = str((body or {}).get("feedback", "")).strip()

        unpublished = None
        reset = None
        if draft["kind"] == "article" and draft["status"] == "approved":
            ad = adapter()
            try:
                unpublished = _unpublish_article(ad, draft)
                memory.mark_publish_reverted(draft_id=draft_id)
            except (AdapterError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"unpublish failed: {exc}")
        elif draft["kind"] in ("merge", "rollback"):
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
        if feedback:
            memory.record_observation(
                "feedback",
                f"Owner declined draft #{draft_id} \"{draft['title']}\": {feedback}",
                meta={"draft_id": draft_id, "kind": draft["kind"], "reason": "decline"},
            )
        memory.record_action("decline", f"#{draft_id} [{draft['kind']}] {draft['title']}" + (f" — {feedback[:100]}" if feedback else "") + (f" (removed {unpublished['removed']})" if unpublished else ""))
        return {"ok": True, "unpublished": unpublished, "reset": reset}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-cache"})

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app
