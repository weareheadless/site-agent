"""GitHub-first source inventory and narrow source editing for a tenant.

The service deliberately keeps the repository adapter as the authority for
reads and commits. A configured local checkout is only used as an inventory
tooling root when it is available; edits always re-read the target branch
through :class:`GithubStatic` before applying a patch.
"""

from __future__ import annotations

import ast
import hashlib
import html
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from ..hands.github_static import GithubStatic
from ..hands.repo_changes import normalize_path, writable


class SourceEditorError(ValueError):
    """A source inventory or edit cannot be completed safely."""


class SourceConflictError(SourceEditorError):
    """The source changed or the requested range no longer matches."""


_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
_ALLOWED_KINDS = {"literal", "jsx-attribute", "jsx-text"}
_ALLOWED_TYPES = {"text", "string", "richtext", "image", "link"}
_PREVIEW_STYLES_PATH = "src/app/(frontend)/styles.css"
_PREVIEW_STYLES_MAX_BYTES = 512 * 1024
_SAFE_ENV_KEYS = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NODE_PATH",
    "NPM_CONFIG_CACHE",
    "NO_PROXY",
    "PATH",
    "SHELL",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USER",
    "USERPROFILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_setting(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


class SourceEditorService:
    """Inventory and patch editable source fields for one tenant.

    ``adapter`` and ``runner`` are injectable so inventory and conflict logic
    can be tested without GitHub, Node, or a checked-out frontend repository.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        env: Mapping[str, str] | None = None,
        *,
        adapter: Any | None = None,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.config = dict(config)
        self.env = dict(os.environ if env is None else env)
        self.adapter = adapter or GithubStatic(self.config, self.env)
        self.runner = runner or subprocess.run
        self._inventory_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    @property
    def site(self) -> Mapping[str, Any]:
        return _mapping(self.config.get("site"))

    @property
    def settings(self) -> dict[str, Any]:
        """Accept the top-level and site-local forms used by tenant configs."""
        result: dict[str, Any] = {}
        for candidate in (
            self.site.get("source_inventory"),
            self.site.get("source_editor"),
            self.config.get("source_inventory"),
            self.config.get("source_editor"),
        ):
            if isinstance(candidate, Mapping):
                result.update(candidate)
        return result

    def _validate_adapter(self) -> None:
        validate = getattr(self.adapter, "validate", None)
        if callable(validate):
            try:
                validate()
            except Exception as exc:  # noqa: BLE001 - normalize adapter details
                raise SourceEditorError(str(exc)[:500]) from exc

    @staticmethod
    def _branch(value: Any, *, default: str) -> str:
        branch = str(value or default).strip()
        if (
            not branch
            or not _BRANCH.fullmatch(branch)
            or branch.startswith("/")
            or branch.endswith("/")
            or "//" in branch
            or ".." in Path(branch).parts
            or "@{" in branch
        ):
            raise SourceEditorError("source branch is invalid")
        return branch

    def _source_branch(self, value: Any = None) -> str:
        return self._branch(value, default=str(self.site.get("branch") or "main"))

    def _branch_revision(self, branch: str) -> str:
        get_head = getattr(self.adapter, "get_branch_head", None)
        if not callable(get_head):
            return ""
        try:
            return str(get_head(branch) or "").strip().lower()
        except Exception:
            # Revision lookup is an optimization. Inventory remains usable if
            # the adapter cannot provide it, but cross-request caching is then
            # intentionally less certain.
            return ""

    def _preview_branch(self) -> str:
        value = self.settings.get("preview_branch") or self.site.get("preview_branch")
        return self._branch(value, default="")

    def _local_checkout(self) -> Path | None:
        value = self.settings.get("clone_path") or self.site.get("clone_path")
        raw = str(value or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser().resolve()
        return path if path.is_dir() else None

    def _prefer_local_checkout(self) -> bool:
        value = self.settings.get("prefer_local_checkout", True)
        return bool(value) and self._local_checkout() is not None

    def _local_checkout_matches(self, branch: str) -> bool:
        local = self._local_checkout()
        if local is None or not (local / ".git").exists():
            # A configured source directory without Git metadata is still a
            # valid inventory root; the adapter remains authoritative for edits.
            return local is not None
        try:
            result = subprocess.run(
                ["git", "-C", str(local), "symbolic-ref", "--quiet", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._child_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0 or result.stdout.strip() != branch:
            return False
        get_head = getattr(self.adapter, "get_branch_head", None)
        if not callable(get_head):
            return True
        try:
            local_head = subprocess.run(
                ["git", "-C", str(local), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._child_env(),
                check=False,
            )
            remote_head = str(get_head(branch) or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            return False
        return local_head.returncode == 0 and bool(remote_head) and local_head.stdout.strip() == remote_head

    @staticmethod
    def _safe_path(value: Any) -> str:
        path = normalize_path(str(value or ""))
        if not path or path.startswith(".git/") or path == ".git":
            raise SourceEditorError("source file path is invalid")
        return path

    def _writable(self, path: str) -> None:
        if str(((self.config.get("design_engine") or {}).get("build_profile") or "")).strip().lower() == "next_react":
            from ..hands.site_build import is_next_react_frontend_path

            if not is_next_react_frontend_path(path):
                raise SourceEditorError("source file belongs to the shared HelloAda platform and is not editable by website work")
            return
        patterns = self.settings.get("writable_patterns") or self.site.get("writable_patterns") or ()
        if not isinstance(patterns, (list, tuple)):
            raise SourceEditorError("source writable_patterns must be a list")
        if not writable(path, [str(item) for item in patterns]):
            raise SourceEditorError("source file is not editable by tenant policy")

    @contextmanager
    def materialize_source(self, branch: str, *, prefer_local: bool = False) -> Iterator[Path]:
        """Yield a branch source tree from the local checkout or GitHub."""
        self._validate_adapter()
        local = self._local_checkout() if prefer_local else None
        if local is not None:
            yield local
            return

        list_files = getattr(self.adapter, "list_files", None)
        get_file = getattr(self.adapter, "get_file", None)
        if not callable(list_files) or not callable(get_file):
            raise SourceEditorError("GitHub source materialization is unavailable")

        try:
            paths = list(list_files(branch=branch))
        except Exception as exc:  # noqa: BLE001 - normalize adapter details
            raise SourceEditorError(str(exc)[:500]) from exc
        max_files = _int_setting(self.settings.get("max_files"), 10_000, 1, 50_000)
        if len(paths) > max_files:
            raise SourceEditorError("repository source contains too many files")
        max_bytes = _int_setting(self.settings.get("max_bytes"), 100 * 1024 * 1024, 1, 500 * 1024 * 1024)

        with tempfile.TemporaryDirectory(prefix="site-agent-source-") as directory:
            root = Path(directory)
            total_bytes = 0
            for raw_path in sorted({str(item) for item in paths}):
                path = self._safe_path(raw_path)
                try:
                    _sha, data = get_file(path, branch=branch)
                except Exception as exc:  # noqa: BLE001 - normalize adapter details
                    raise SourceEditorError(str(exc)[:500]) from exc
                if data is None:
                    raise SourceEditorError(f"source file disappeared while materializing: {path}")
                total_bytes += len(data)
                if total_bytes > max_bytes:
                    raise SourceEditorError("repository source is too large to materialize")
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            local_modules = self._local_checkout()
            if local_modules is not None and (local_modules / "node_modules").is_dir() and not (root / "node_modules").exists():
                (root / "node_modules").symlink_to(local_modules / "node_modules", target_is_directory=True)
            yield root

    def read_source(self, path: str, *, branch: str | None = None) -> dict[str, Any]:
        """Read one configured repository file through the GitHub adapter."""
        self._validate_adapter()
        clean_path = self._safe_path(path)
        source_branch = self._source_branch(branch)
        try:
            blob_sha, data = self.adapter.get_file(clean_path, branch=source_branch)
        except Exception as exc:  # noqa: BLE001 - normalize adapter details
            raise SourceEditorError(str(exc)[:500]) from exc
        if data is None:
            raise SourceEditorError(f"source file not found on branch '{source_branch}': {clean_path}")
        return {
            "path": clean_path,
            "branch": source_branch,
            "sha": str(blob_sha or ""),
            "source_hash": hashlib.sha256(data).hexdigest(),
            "bytes": data,
        }

    def preview_styles(self) -> dict[str, Any]:
        """Read the staged frontend stylesheet without building the site."""
        preview_branch = self._preview_branch()
        if not preview_branch:
            raise SourceEditorError("source preview branch is not configured")
        source = self.read_source(_PREVIEW_STYLES_PATH, branch=preview_branch)
        data = source["bytes"]
        if not isinstance(data, bytes) or len(data) > _PREVIEW_STYLES_MAX_BYTES:
            raise SourceEditorError("preview stylesheet is too large")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceEditorError("preview stylesheet is not valid UTF-8") from exc
        return {
            "path": source["path"],
            "branch": source["branch"],
            "sha": source["sha"],
            "source_hash": source["source_hash"],
            "content": content,
        }

    def _inventory_script(self, root: Path) -> Path:
        configured = self.settings.get("inventory_script") or self.settings.get("script")
        configured = (
            configured
            or self.site.get("source_inventory_script")
            or self.config.get("source_inventory_script")
            or "scripts/source-inventory.ts"
        )
        raw = Path(str(configured)).expanduser()
        local = self._local_checkout()
        candidates = [raw] if raw.is_absolute() else [root / raw]
        if local is not None and not raw.is_absolute():
            candidates.append(local / raw)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        raise SourceEditorError(f"source inventory script is missing: {configured}")

    def _node_tool(self) -> list[str]:
        configured = (
            self.settings.get("node_tool")
            or self.settings.get("node")
            or self.site.get("node_tool")
            or self.site.get("node_path")
            or self.site.get("node")
            or self.config.get("node_tool")
            or self.config.get("node_path")
        )
        if configured is None:
            local = self._local_checkout()
            if local is not None:
                tsx = local / "node_modules" / ".bin" / "tsx"
                if tsx.is_file():
                    return [str(tsx)]
            return ["npx", "--no-install", "tsx"]
        if isinstance(configured, (list, tuple)):
            command = [str(item) for item in configured if str(item).strip()]
        else:
            try:
                command = shlex.split(str(configured))
            except ValueError as exc:
                raise SourceEditorError("source node_tool is invalid") from exc
        if not command or any("\x00" in item for item in command):
            raise SourceEditorError("source node_tool is invalid")
        return command

    def _child_env(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in self.env.items()
            if key in _SAFE_ENV_KEYS and str(value)
        } | {
            "NODE_NO_WARNINGS": "1",
        }

    def _run_inventory(self, root: Path) -> dict[str, Any]:
        script = self._inventory_script(root)
        command = [*self._node_tool(), str(script), "--root", str(root)]
        timeout = _int_setting(self.settings.get("timeout_seconds"), 120, 1, 900)
        # Keep the command's working directory beside its configured tool and
        # dependencies, while --root remains the actual source under review.
        local = self._local_checkout()
        working_directory = local if local is not None and script.is_relative_to(local) else root
        try:
            result = self.runner(
                command,
                cwd=str(working_directory),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._child_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceEditorError(f"source inventory command failed: {str(exc)[:300]}") from exc
        returncode = getattr(result, "returncode", 0)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        if returncode:
            raise SourceEditorError((str(stderr or stdout or "source inventory command failed")).strip()[:500])
        if isinstance(result, Mapping) and isinstance(result.get("fields"), list):
            decoded: Any = result
        elif isinstance(stdout, Mapping):
            decoded: Any = stdout
        else:
            try:
                decoded = json.loads(str(stdout or ""))
            except json.JSONDecodeError as exc:
                raise SourceEditorError("source inventory did not return JSON") from exc
        if not isinstance(decoded, dict) or not isinstance(decoded.get("fields"), list):
            raise SourceEditorError("source inventory returned an invalid shape")
        return decoded

    def inventory(self, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Run the repository inventory against one source branch."""
        body = _mapping(request)
        requested_branch = body.get("branch") or body.get("source_branch")
        preview_branch = self._preview_branch()
        source_branch = self._source_branch(
            requested_branch or (preview_branch if body.get("draft", True) and preview_branch else None)
        )
        if preview_branch and source_branch == preview_branch:
            ensure_branch = getattr(self.adapter, "ensure_branch", None)
            if not callable(ensure_branch):
                raise SourceEditorError("configured GitHub adapter cannot create the preview branch")
            try:
                ensure_branch(preview_branch)
            except Exception as exc:  # noqa: BLE001 - normalize adapter details
                raise SourceEditorError(str(exc)[:500]) from exc

        revision = self._branch_revision(source_branch)
        cache_key = (source_branch, revision or "unknown")
        cache_seconds = _int_setting(self.settings.get("cache_seconds"), 300, 0, 3600)
        cached = self._inventory_cache.get(cache_key)
        if cached and cache_seconds > 0 and time.monotonic() - cached[0] < cache_seconds:
            return {**cached[1], "cached": True}

        prefer_local = self._prefer_local_checkout() and self._local_checkout_matches(source_branch)
        with self.materialize_source(source_branch, prefer_local=prefer_local) as root:
            inventory = self._run_inventory(root)
            source_kind = "local_checkout" if prefer_local else "github_materialized"
        result = {
            "branch": source_branch,
            "revision": revision,
            "source": source_kind,
            "inventory": inventory,
            "cached": False,
        }
        if cache_seconds > 0:
            self._inventory_cache[cache_key] = (time.monotonic(), result)
        return result

    @staticmethod
    def _pick(mapping: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in mapping:
                return mapping[key]
        return None

    @classmethod
    def _field_request(cls, body: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
        nested = body.get("field")
        field = dict(nested) if isinstance(nested, Mapping) else dict(body)
        missing = object()
        new_value: Any = missing
        for key in ("new_value", "newValue", "replacement", "next_value", "nextValue"):
            if key in body:
                new_value = body[key]
                break
        if new_value is missing and isinstance(nested, Mapping) and "value" in body:
            new_value = body["value"]
        if new_value is missing and not isinstance(nested, Mapping) and "value" in body:
            new_value = body["value"]
        if new_value is missing:
            raise SourceEditorError("source edit value is required")
        return field, new_value

    @staticmethod
    def _is_url(value: str, *, image: bool = False) -> bool:
        if not value or any(character in value for character in "\r\n\x00"):
            return False
        if image and re.match(r"^asset:[a-f0-9]+$", value, re.IGNORECASE):
            return True
        if re.match(r"^https?://[^\s]+$", value, re.IGNORECASE):
            return True
        if image and re.match(r"^(?:/|\.?\.?/)[^\s]+$", value):
            return True
        return not image and re.match(r"^(?:mailto:|tel:|#|/|\.?\.?/)[^\s]+$", value, re.IGNORECASE) is not None

    @staticmethod
    def _escape_literal(value: str, quote: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
        if quote == "`":
            escaped = escaped.replace("`", "\\`").replace("${", "\\${")
        else:
            escaped = escaped.replace(quote, f"\\{quote}")
        return escaped

    @classmethod
    def _patch_value(cls, text: str, start: int, end: int, kind: str, new_value: str) -> tuple[str, str]:
        current = text[start:end]
        if kind in {"literal", "jsx-attribute"}:
            if len(current) < 2 or current[0] not in {"'", '"', "`"} or current[-1] != current[0]:
                raise SourceEditorError("source edit range is not a string literal")
            replacement = f"{current[0]}{cls._escape_literal(new_value, current[0])}{current[-1]}"
            return text[:start] + replacement + text[end:], replacement
        if kind == "jsx-text":
            replacement = html.escape(new_value, quote=False)
            return text[:start] + replacement + text[end:], replacement
        raise SourceEditorError("dynamic source fields cannot be edited directly")

    def _commit(
        self,
        path: str,
        data: bytes,
        message: str,
        branch: str,
        expected_sha: str | None,
    ) -> dict[str, Any]:
        commit_file = getattr(self.adapter, "commit_file", None)
        if not callable(commit_file):
            raise SourceEditorError("configured GitHub adapter cannot commit source")
        try:
            result = commit_file(
                path,
                data,
                message,
                branch=branch,
                expected_sha=expected_sha,
            )
        except TypeError as exc:
            # Keep test doubles and older adapter implementations usable; the
            # source hash and range checks still happen before this call.
            if "expected_sha" not in str(exc):
                raise
            result = commit_file(path, data, message, branch=branch)
        except Exception as exc:  # noqa: BLE001 - normalize adapter details
            raise SourceEditorError(str(exc)[:500]) from exc
        if not isinstance(result, Mapping):
            raise SourceEditorError("GitHub adapter returned an invalid commit result")
        committed = bool(result.get("committed") or result.get("commit_sha"))
        if not committed:
            if int(result.get("status") or 0) == 409:
                raise SourceConflictError("source changed before the GitHub commit")
            raise SourceEditorError(str(result.get("reason") or "GitHub source commit failed")[:500])
        return dict(result)

    def _normalize_edit(self, request: Mapping[str, Any], *, target_branch: str) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise SourceEditorError("source edit must be an object")
        body = dict(request)
        field, raw_new_value = self._field_request(body)
        if not isinstance(raw_new_value, str):
            raise SourceEditorError("source edit value must be a string")
        if len(raw_new_value) > 20_000:
            raise SourceEditorError("source edit value is too long")

        body_path = self._pick(body, "file", "path")
        field_path = self._pick(field, "file", "path")
        if body_path is not None and field_path is not None and self._safe_path(body_path) != self._safe_path(field_path):
            raise SourceConflictError("source edit field and path do not match")
        path = self._safe_path(body_path or field_path)
        self._writable(path)

        source_branch = self._source_branch(self._pick(body, "branch", "source_branch") or field.get("branch"))
        body_hash = str(
            self._pick(body, "source_hash", "sourceHash", "expected_source_hash", "expectedSourceHash") or ""
        ).strip().lower()
        field_hash = str(
            self._pick(field, "source_hash", "sourceHash", "expected_source_hash", "expectedSourceHash") or ""
        ).strip().lower()
        if body_hash and field_hash and body_hash != field_hash:
            raise SourceConflictError("source edit hashes do not match")
        source_hash = body_hash or field_hash
        if not source_hash:
            raise SourceEditorError("source_hash is required")

        start_raw = self._pick(body, "value_start", "valueStart")
        end_raw = self._pick(body, "value_end", "valueEnd")
        field_start = self._pick(field, "value_start", "valueStart")
        field_end = self._pick(field, "value_end", "valueEnd")
        try:
            if start_raw is not None and field_start is not None and int(start_raw) != int(field_start):
                raise SourceConflictError("source edit start range does not match the field")
            if end_raw is not None and field_end is not None and int(end_raw) != int(field_end):
                raise SourceConflictError("source edit end range does not match the field")
        except SourceConflictError:
            raise
        except (TypeError, ValueError) as exc:
            raise SourceEditorError("source edit range is invalid") from exc
        if start_raw is None:
            start_raw = field_start
        if end_raw is None:
            end_raw = field_end
        if start_raw is None or end_raw is None:
            range_value = self._pick(body, "range") or self._pick(field, "range")
            if isinstance(range_value, Mapping):
                start_raw = range_value.get("start")
                end_raw = range_value.get("end")
        if start_raw is None:
            start_raw = self._pick(field, "start")
        if end_raw is None:
            end_raw = self._pick(field, "end")
        if isinstance(start_raw, bool) or isinstance(end_raw, bool):
            raise SourceEditorError("source edit range is invalid")
        try:
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError) as exc:
            raise SourceEditorError("source edit range is required") from exc
        if start < 0 or end <= start:
            raise SourceEditorError("source edit range is invalid")

        status = str(self._pick(field, "status") or "editable").strip().lower()
        if status != "editable" or self._pick(field, "editable") is False:
            raise SourceEditorError("source field is not editable")
        kind = str(self._pick(body, "kind") or self._pick(field, "kind") or "literal").strip().lower()
        if kind == "string":
            kind = "literal"
        if kind not in _ALLOWED_KINDS:
            raise SourceEditorError("dynamic source fields cannot be edited directly")
        field_type = str(self._pick(body, "type") or self._pick(field, "type") or "text").strip().lower()
        if field_type == "string":
            field_type = "text"
        if field_type not in _ALLOWED_TYPES:
            raise SourceEditorError("source field type is not directly editable")
        if field_type == "image" and not self._is_url(raw_new_value, image=True):
            raise SourceEditorError("image source value must be a portable asset id, relative, or HTTP(S) URL")
        if field_type == "link" and not self._is_url(raw_new_value):
            raise SourceEditorError("link source value must be a URL")
        if "\x00" in raw_new_value:
            raise SourceEditorError("source edit value is invalid")

        expected_raw = self._pick(body, "raw", "expected_raw", "expectedRaw")
        if expected_raw is None:
            expected_raw = self._pick(field, "raw", "expected_raw", "expectedRaw")
        expected_value = self._pick(
            body,
            "expected_value",
            "expectedValue",
            "current_value",
            "currentValue",
        )
        if expected_value is None and "field" in body:
            expected_value = self._pick(field, "value")

        return {
            "path": path,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "source_hash": source_hash,
            "start": start,
            "end": end,
            "kind": kind,
            "field_type": field_type,
            "new_value": raw_new_value,
            "expected_raw": expected_raw,
            "expected_value": expected_value,
            "field_id": str(self._pick(body, "field_id", "fieldId") or self._pick(field, "id") or ""),
            "message": str(body.get("message") or f"Ada source edit: {path}").strip()[:200],
            "message_explicit": bool(str(body.get("message") or "").strip()),
        }

    def _target_file(self, path: str, branch: str) -> tuple[str | None, bytes]:
        try:
            file_sha, data = self.adapter.get_file(path, branch=branch)
            if data is None:
                ensure_branch = getattr(self.adapter, "ensure_branch", None)
                if not callable(ensure_branch):
                    raise SourceEditorError("configured GitHub adapter cannot create the preview branch")
                ensure_branch(branch)
                file_sha, data = self.adapter.get_file(path, branch=branch)
        except SourceEditorError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize adapter details
            raise SourceEditorError(str(exc)[:500]) from exc
        if data is None:
            raise SourceEditorError(f"source file not found on preview branch: {path}")
        return str(file_sha or "") or None, data

    @staticmethod
    def _current_literal_value(value: str, kind: str) -> str:
        if kind == "jsx-text":
            return value
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            try:
                return str(ast.literal_eval(value))
            except (SyntaxError, ValueError):
                return value[1:-1]
        if value[:1] == "`" and value[-1:] == "`":
            return value[1:-1]
        return value

    @staticmethod
    def _utf16_index(text: str, offset: int) -> int:
        """Convert a TypeScript UTF-16 source offset to a Python index."""
        if offset < 0:
            raise SourceEditorError("source edit range is invalid")
        try:
            prefix = text.encode("utf-16-le")[: offset * 2]
            return len(prefix.decode("utf-16-le"))
        except UnicodeDecodeError as exc:
            raise SourceEditorError("source edit range splits a Unicode character") from exc

    def _validate_range(self, edit: dict[str, Any], text: str, actual_hash: str) -> None:
        source_hash = str(edit["source_hash"])
        if actual_hash != source_hash:
            raise SourceConflictError(
                f"source changed since inventory (expected {source_hash[:12]}, found {actual_hash[:12]})"
            )
        start = self._utf16_index(text, int(edit["start"]))
        end = self._utf16_index(text, int(edit["end"]))
        edit["python_start"] = start
        edit["python_end"] = end
        if end > len(text):
            raise SourceConflictError("source edit range is outside the current file")
        current_range = text[start:end]
        expected_raw = edit.get("expected_raw")
        if expected_raw is not None and current_range != str(expected_raw):
            raise SourceConflictError("source edit range no longer matches the inventoried source")
        expected_value = edit.get("expected_value")
        if expected_raw is None and expected_value is not None:
            current_value = self._current_literal_value(current_range, str(edit["kind"]))
            if current_value != str(expected_value):
                raise SourceConflictError("source edit range no longer matches the inventoried value")

    def _prepare_plans(self, edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not edits:
            raise SourceEditorError("edits must contain at least one item")
        branches = {str(edit["source_branch"]) for edit in edits}
        if len(branches) != 1:
            raise SourceEditorError("batch edits must use one source branch")

        groups: dict[str, dict[str, Any]] = {}
        for edit in edits:
            group = groups.get(str(edit["path"]))
            if group is None:
                file_sha, data = self._target_file(str(edit["path"]), str(edit["target_branch"]))
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceEditorError(f"source edit target is not UTF-8 text: {edit['path']}") from exc
                group = {
                    "path": str(edit["path"]),
                    "source_branch": str(edit["source_branch"]),
                    "target_branch": str(edit["target_branch"]),
                    "file_sha": file_sha,
                    "data": data,
                    "text": text,
                    "edits": [],
                }
                groups[str(edit["path"])] = group
            group["edits"].append(edit)

        plans: list[dict[str, Any]] = []
        for group in groups.values():
            text = str(group["text"])
            actual_hash = hashlib.sha256(group["data"]).hexdigest()
            group_edits = list(group["edits"])
            for edit in group_edits:
                self._validate_range(edit, text, actual_hash)
            ordered = sorted(group_edits, key=lambda item: (int(item["python_start"]), int(item["python_end"])))
            for previous, current in zip(ordered, ordered[1:]):
                if int(current["python_start"]) < int(previous["python_end"]):
                    raise SourceConflictError(f"source edit ranges overlap in {group['path']}")
            updated_text = text
            for edit in sorted(group_edits, key=lambda item: int(item["python_start"]), reverse=True):
                updated_text, _replacement = self._patch_value(
                    updated_text,
                    int(edit["python_start"]),
                    int(edit["python_end"]),
                    str(edit["kind"]),
                    str(edit["new_value"]),
                )
            updated = updated_text.encode("utf-8")
            plans.append({
                **group,
                "source_hash": actual_hash,
                "updated": updated,
                "updated_source_hash": hashlib.sha256(updated).hexdigest(),
            })
        return plans

    def _preflight_plans(self, plans: list[dict[str, Any]]) -> None:
        """Re-read every file before the first commit to catch intervening edits."""
        for plan in plans:
            try:
                current_sha, current_data = self.adapter.get_file(
                    str(plan["path"]), branch=str(plan["target_branch"])
                )
            except Exception as exc:  # noqa: BLE001 - normalize adapter details
                raise SourceEditorError(str(exc)[:500]) from exc
            if current_data is None or (
                plan["file_sha"] is not None and str(current_sha or "") != str(plan["file_sha"])
            ):
                raise SourceConflictError(f"source changed before the batch commit: {plan['path']}")
            if hashlib.sha256(current_data).hexdigest() != plan["source_hash"]:
                raise SourceConflictError(f"source changed before the batch commit: {plan['path']}")

    def _single_result(self, edit: Mapping[str, Any], plan: Mapping[str, Any], commit: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "path": str(plan["path"]),
            "field_id": str(edit.get("field_id") or ""),
            "source_branch": str(plan["source_branch"]),
            "branch": str(plan["target_branch"]),
            "source_hash": str(plan["source_hash"]),
            "updated_source_hash": str(plan["updated_source_hash"]),
            "value": str(edit["new_value"]),
            "commit": dict(commit),
        }

    def edit_batch(self, request: Mapping[str, Any] | list[Mapping[str, Any]]) -> dict[str, Any]:
        """Validate a batch completely, then commit once per changed file."""
        self._validate_adapter()
        if isinstance(request, Mapping):
            raw_edits = request.get("edits")
            batch_message = str(request.get("message") or "").strip()[:200]
        else:
            raw_edits = request
            batch_message = ""
        if not isinstance(raw_edits, list):
            raise SourceEditorError("edits must be a list")
        max_edits = _int_setting(self.settings.get("max_batch_edits"), 100, 1, 500)
        if len(raw_edits) > max_edits:
            raise SourceEditorError(f"batch contains too many edits (max {max_edits})")
        target_branch = self._preview_branch()
        edits = [self._normalize_edit(item, target_branch=target_branch) for item in raw_edits]
        if batch_message:
            for edit in edits:
                if not edit["message_explicit"]:
                    edit["message"] = f"{batch_message}: {edit['path']}"[:200]
        plans = self._prepare_plans(edits)
        self._preflight_plans(plans)

        commits: list[dict[str, Any]] = []
        file_results: list[dict[str, Any]] = []
        plan_by_path: dict[str, dict[str, Any]] = {}
        for plan in plans:
            commit = self._commit(
                str(plan["path"]),
                bytes(plan["updated"]),
                str(plan["edits"][0]["message"]),
                str(plan["target_branch"]),
                plan["file_sha"],
            )
            commits.append(commit)
            plan_by_path[str(plan["path"])] = plan
            file_results.append({
                "path": str(plan["path"]),
                "branch": str(plan["target_branch"]),
                "source_branch": str(plan["source_branch"]),
                "field_ids": [str(item["field_id"]) for item in plan["edits"] if item.get("field_id")],
                "source_hash": str(plan["source_hash"]),
                "updated_source_hash": str(plan["updated_source_hash"]),
                "commit": dict(commit),
            })
        edit_results = []
        for edit in edits:
            plan = plan_by_path[str(edit["path"])]
            result = self._single_result(edit, plan, {})
            result.pop("commit", None)
            edit_results.append(result)
        return {
            "ok": True,
            "batch": True,
            "edits": edit_results,
            "files": file_results,
            "commits": commits,
        }

    def edit(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Preserve single-edit requests and dispatch ``{\"edits\": [...]}`` batches."""
        if not isinstance(request, Mapping):
            raise SourceEditorError("source edit body must be an object")
        if "edits" in request:
            return self.edit_batch(request)
        self._validate_adapter()
        target_branch = self._preview_branch()
        edit = self._normalize_edit(request, target_branch=target_branch)
        plan = self._prepare_plans([edit])[0]
        self._preflight_plans([plan])
        commit = self._commit(
            str(plan["path"]),
            bytes(plan["updated"]),
            str(edit["message"]),
            str(plan["target_branch"]),
            plan["file_sha"],
        )
        return self._single_result(edit, plan, commit)


__all__ = ["SourceConflictError", "SourceEditorError", "SourceEditorService"]
