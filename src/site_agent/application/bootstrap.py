"""Idempotent external bootstrap for a newly registered HelloAda website.

Registration creates the local tenant first.  This service then owns the
long-running, retryable boundary that turns that tenant into a real
Next/React/Payload site.  Every completed step is recorded beside the tenant so
an interrupted request can resume without guessing which provider mutations
already happened.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from ..credentials import (
    cloudflare_api_token,
    cloudflare_env_names,
    credential_environment,
    github_api_token,
    github_ssh_command,
)
from ..config import deep_merge
from .. import __version__
from ..hands.cloudflare_resources import CloudflareResourceProvisioner
from ..hands.cloudflare_r2 import CloudflareR2Provisioner
from ..hands.github_provisioning import GitHubRepositoryProvisioner, GitHubRepositoryReceipt
from ..payload_contract import PayloadContractError, validate_payload_migrations
from ..site_scaffold import payload_template_copy_ignore
from .release_queue import ReleaseQueueError, request_release, release_root
from .tenant_registration import (
    TenantRegistrationError,
    TenantRegistrationService,
    tenant_token_env,
)


class BootstrapError(RuntimeError):
    """A customer website cannot be bootstrapped safely."""


_SAFE_COMPONENT = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SECRET_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRIVATE_RECEIPT_KEYS = frozenset({"site_dir", "config_path", "account_id", "ssh_url", "clone_url"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _component(value: str, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SAFE_COMPONENT.fullmatch(normalized):
        raise BootstrapError(f"{label} is invalid")
    return normalized


class WebsiteBootstrapService:
    """Start and inspect one durable bootstrap saga per tenant."""

    def __init__(
        self,
        config: Mapping[str, Any],
        env: Mapping[str, str],
        *,
        registration: TenantRegistrationService,
        registry: Any,
    ) -> None:
        self.config = dict(config)
        self.env = dict(env or {})
        self.registration = registration
        self.registry = registry
        self.root = registration.root
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="helloada-bootstrap")
        self._futures: dict[str, Future[None]] = {}

    @property
    def settings(self) -> Mapping[str, Any]:
        return _mapping(self.config.get("bootstrap"))

    def _state_path(self, tenant_id: str) -> Path:
        return (self.root / tenant_id / "bootstrap.json").resolve()

    def _read_state(self, tenant_id: str) -> dict[str, Any]:
        path = self._state_path(tenant_id)
        if not path.is_file():
            return {
                "version": 1,
                "tenant_id": tenant_id,
                "status": "queued",
                "step": "requested",
                "steps": {},
                "resource_receipts": {},
                "diagnostic": "",
                "created_at": _now(),
                "updated_at": _now(),
            }
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise BootstrapError("bootstrap receipt is unreadable") from exc
        if not isinstance(raw, dict) or str(raw.get("tenant_id") or "") != tenant_id:
            raise BootstrapError("bootstrap receipt belongs to another tenant")
        if not isinstance(raw.get("steps"), dict):
            raw["steps"] = {}
        if not isinstance(raw.get("resource_receipts"), dict):
            raw["resource_receipts"] = {}
        return raw

    def _write_state(self, state: Mapping[str, Any]) -> None:
        path = self._state_path(str(state.get("tenant_id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(dict(state), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    @staticmethod
    def _public_state(state: Mapping[str, Any]) -> dict[str, Any]:
        steps = state.get("steps") if isinstance(state.get("steps"), Mapping) else {}

        def public_value(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {
                    str(key): public_value(item)
                    for key, item in value.items()
                    if str(key) not in _PRIVATE_RECEIPT_KEYS
                }
            if isinstance(value, list):
                return [public_value(item) for item in value]
            return value

        return {
            "tenant_id": state.get("tenant_id"),
            "status": state.get("status", "queued"),
            "step": state.get("step", "requested"),
            "diagnostic": state.get("diagnostic", ""),
            "workspace_ready": bool(state.get("workspace_ready", False)),
            "website_live": bool(state.get("website_live", False)),
            "resource_receipts": public_value(state.get("resource_receipts", {})),
            "steps": {
                str(key): {
                    "status": value.get("status"),
                    "updated_at": value.get("updated_at"),
                }
                for key, value in steps.items()
                if isinstance(value, Mapping)
            },
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
        }

    def status(self, tenant_id: str) -> dict[str, Any]:
        normalized = _component(tenant_id, "website id")
        with self._lock:
            state = self._read_state(normalized)
            self._refresh_release_state(state)
            return self._public_state(state)

    def start(self, tenant_id: str, *, display_name: str = "") -> dict[str, Any]:
        normalized = _component(tenant_id, "website id")
        if not bool(self.settings.get("enabled", True)):
            raise BootstrapError("website bootstrap is disabled")
        try:
            self.registration.register(normalized, display_name=display_name, env=self.env)
        except TenantRegistrationError as exc:
            raise BootstrapError(str(exc)) from exc
        with self._lock:
            state = self._read_state(normalized)
            if state.get("status") == "done" and state.get("step") == "ready":
                return self._public_state(state)
            current = self._futures.get(normalized)
            if current is not None and not current.done():
                return self._public_state(state)
            state["status"] = "queued"
            state["step"] = "requested"
            state["diagnostic"] = ""
            state["updated_at"] = _now()
            self._write_state(state)
            self._futures[normalized] = self._executor.submit(self._run, normalized, display_name)
            return self._public_state(state)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_step(
        self,
        state: dict[str, Any],
        name: str,
        operation: Callable[[], Mapping[str, Any]],
    ) -> dict[str, Any]:
        existing = state.get("steps", {}).get(name) if isinstance(state.get("steps"), Mapping) else None
        if isinstance(existing, Mapping) and existing.get("status") == "done":
            receipt = existing.get("receipt")
            return dict(receipt) if isinstance(receipt, Mapping) else {}
        state["status"] = "running"
        state["step"] = name
        state["diagnostic"] = ""
        state["updated_at"] = _now()
        self._write_state(state)
        try:
            receipt = dict(operation())
        except Exception as exc:  # noqa: BLE001 - saga reaches a durable failure state
            state["status"] = "failed"
            state["step"] = "needs_attention"
            state["diagnostic"] = str(exc)[:1_000]
            state["steps"][name] = {"status": "failed", "updated_at": _now()}
            state["updated_at"] = _now()
            self._write_state(state)
            raise
        state["steps"][name] = {"status": "done", "receipt": receipt, "updated_at": _now()}
        state["resource_receipts"][name] = receipt
        state["updated_at"] = _now()
        self._write_state(state)
        return receipt

    def _run(self, tenant_id: str, display_name: str) -> None:
        try:
            state = self._read_state(tenant_id)
            tenant = self.registry.for_tenant_id(tenant_id)
            if tenant is None:
                raise BootstrapError("registered tenant is unavailable")
            config_path = Path(str(state.get("config_path") or "") or str(self._state_path(tenant_id).parent / "config.yaml"))
            state["config_path"] = str(config_path)
            self._write_state(state)

            repository = self._run_step(state, "creating_repository", lambda: self._repository(tenant_id, display_name, config_path))
            data = self._run_step(state, "creating_data", lambda: self._data_resources(tenant_id))
            worker = self._run_step(
                state,
                "creating_worker",
                lambda: self._configure_source(tenant_id, display_name, config_path, repository, data),
            )
            release = self._run_step(
                state,
                "queueing_shell_release",
                lambda: self._queue_release(tenant_id, config_path, worker),
            )
            state["status"] = "awaiting_release"
            state["step"] = "deploying_shell"
            state["release"] = release
            state["workspace_ready"] = False
            state["website_live"] = False
            state["updated_at"] = _now()
            self._write_state(state)
            self._refresh_release_state(state)
        except Exception:
            # _run_step already records the useful failure.  This guard handles
            # failures before the first step and keeps the async future quiet.
            try:
                state = self._read_state(tenant_id)
                if state.get("status") != "failed":
                    state.update(status="failed", step="needs_attention", diagnostic="bootstrap failed", updated_at=_now())
                    self._write_state(state)
            except Exception:
                pass
        finally:
            with self._lock:
                self._futures.pop(tenant_id, None)

    def _refresh_release_state(self, state: dict[str, Any]) -> None:
        if state.get("step") not in {"deploying_shell", "ready"}:
            return
        release = state.get("release")
        if not isinstance(release, Mapping):
            return
        tenant_id = str(state.get("tenant_id") or "")
        release_id = str(release.get("release_id") or "")
        source_sha = str(release.get("source_sha") or "")
        if not tenant_id or not release_id or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
            state.update(status="failed", step="needs_attention", diagnostic="release request identity is invalid", updated_at=_now())
            self._write_state(state)
            return
        try:
            receipt_path = release_root(self.config) / "runs" / tenant_id / release_id / "receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            state.update(status="awaiting_release", workspace_ready=False, website_live=False)
            return
        except (OSError, UnicodeError, ValueError, ReleaseQueueError):
            state.update(status="failed", step="needs_attention", diagnostic="central release receipt is unreadable", updated_at=_now())
            self._write_state(state)
            return
        if (
            receipt.get("tenant") != tenant_id
            or receipt.get("releaseId") != release_id
            or receipt.get("sourceSha") != source_sha
            or receipt.get("approvalId") is not None
        ):
            state.update(status="failed", step="needs_attention", diagnostic="central release receipt does not match this bootstrap", updated_at=_now())
        elif receipt.get("status") in {"deployed", "verified"} and receipt.get("connectionVerifiedAt"):
            state.update(
                status="done",
                step="ready",
                diagnostic="",
                workspace_ready=True,
                website_live=False,
                deployment_receipt={
                    key: receipt.get(key)
                    for key in ("pipelineSha", "uploadedVersion", "connectionVerifiedAt", "finishedAt")
                    if receipt.get(key) is not None
                },
                updated_at=_now(),
            )
        elif receipt.get("status") in {"failed", "interrupted"}:
            state.update(
                status="failed",
                step="needs_attention",
                diagnostic=str(receipt.get("error") or "central VPS release failed")[:1_000],
                updated_at=_now(),
            )
        else:
            state.update(status="awaiting_release", workspace_ready=False, website_live=False)
        self._write_state(state)

    def _credentials(self) -> tuple[dict[str, str], str, str, str]:
        env = credential_environment(self.config, self.env)
        github_token = github_api_token(self.config, env)
        cloudflare_token = cloudflare_api_token(self.config, env)
        _token_name, account_name = cloudflare_env_names(self.config)
        account_id = str(env.get(account_name) or "").strip()
        if not github_token:
            raise BootstrapError("GitHub API credentials are not configured")
        if not cloudflare_token or not account_id:
            raise BootstrapError("Cloudflare account credentials are not configured")
        return env, github_token, cloudflare_token, account_id

    def _names(self, tenant_id: str) -> dict[str, str]:
        prefix = str(self.settings.get("resource_prefix") or "helloada").strip().lower()
        prefix = _component(prefix, "bootstrap resource prefix")
        worker = _component(f"{prefix}-{tenant_id}", "Worker name")
        repo = _component(f"{prefix}-{tenant_id}", "repository name")
        d1 = _component(f"{prefix}-{tenant_id}", "D1 database name")
        r2 = _component(f"{prefix}-{tenant_id}-media", "R2 bucket name")
        email_r2 = _component(f"{prefix}-{tenant_id}-email", "private email bucket name")
        messages_queue = _component(f"{prefix}-{tenant_id}-messages", "message Queue name")
        messages_dlq = _component(f"{prefix}-{tenant_id}-messages-dlq", "message dead-letter Queue name")
        return {
            "worker": worker, "repo": repo, "d1": d1, "r2": r2,
            "email_r2": email_r2, "messages_queue": messages_queue, "messages_dlq": messages_dlq,
        }

    def _repository(self, tenant_id: str, display_name: str, config_path: Path) -> Mapping[str, Any]:
        _env, github_token, _cloudflare_token, _account_id = self._credentials()
        names = self._names(tenant_id)
        owner = str(self.settings.get("github_owner") or "weareheadless").strip()
        provisioner = GitHubRepositoryProvisioner(github_token)
        receipt = provisioner.ensure_repository(
            owner,
            names["repo"],
            description=f"Managed HelloAda website: {display_name or tenant_id}"[:350],
            private=bool(self.settings.get("repository_private", True)),
        )
        tenant_dir = config_path.parent
        site_dir = tenant_dir / "site"
        if site_dir.exists() and (site_dir / ".git").is_dir():
            remotes = self._git(site_dir, "remote").splitlines()
            if "origin" in remotes:
                origin = self._git(site_dir, "remote", "get-url", "origin")
                if origin != receipt.ssh_url:
                    raise BootstrapError("existing site checkout points at a different repository; refusing to change it")
                self._verify_existing_repository(site_dir, tenant_id)
                return {**receipt.to_dict(), "site_dir": str(site_dir), "worker_name": names["worker"]}
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            site_config = _mapping(raw.get("site"))
            baseline_sha = str(site_config.get("platform_baseline_sha") or "")
            if not re.fullmatch(r"[0-9a-f]{40}", baseline_sha):
                raise BootstrapError("tenant has no recorded canonical Payload baseline; refusing scaffold replacement")
            if self._git(site_dir, "status", "--porcelain"):
                raise BootstrapError("remote-free site workspace contains edits; refusing to replace or publish them")
            if self._git(site_dir, "rev-parse", "HEAD") != baseline_sha:
                raise BootstrapError("remote-free site workspace differs from its recorded baseline; reconcile it before bootstrap")
            self._load_payload_contract(site_dir)
        elif site_dir.exists() and any(site_dir.iterdir()):
            raise BootstrapError("site path contains files but no managed Git baseline; refusing to overwrite it")
        else:
            self._materialize_template(site_dir)
        self._load_payload_contract(site_dir)
        self._configure_template(site_dir, tenant_id, display_name)
        self._git_init_and_push(site_dir, receipt)
        return {**receipt.to_dict(), "site_dir": str(site_dir), "worker_name": names["worker"]}

    def _verify_existing_repository(self, site_dir: Path, tenant_id: str) -> None:
        if self._git(site_dir, "status", "--porcelain"):
            raise BootstrapError("existing customer repository has uncommitted files; refusing to modify it")
        if self._git(site_dir, "branch", "--show-current") != "main":
            raise BootstrapError("existing customer checkout is not on main; refusing implicit branch changes")
        try:
            marker = json.loads((site_dir / ".helloada-managed.json").read_text(encoding="utf-8"))
            manifest = json.loads((site_dir / "template-manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BootstrapError("existing customer repository has no valid HelloAda ownership marker") from exc
        expected = {
            "tenantId": tenant_id,
            "templateSchema": manifest.get("templateSchema"),
            "payloadAdmin": manifest.get("payloadAdmin"),
            "payloadCore": manifest.get("payloadCore"),
            "contentContract": manifest.get("contentContract"),
            "schemaRevision": manifest.get("schemaRevision"),
            "schemaIdentity": manifest.get("schemaIdentity"),
            "migrationHead": manifest.get("migrationHead"),
        }
        if marker != expected:
            raise BootstrapError("existing customer repository belongs to a different tenant or Payload contract")

    def _data_resources(self, tenant_id: str) -> Mapping[str, Any]:
        _env, _github_token, cloudflare_token, account_id = self._credentials()
        names = self._names(tenant_id)
        cloudflare = CloudflareResourceProvisioner(account_id, cloudflare_token)
        d1 = cloudflare.ensure_d1(names["d1"], location=str(self.settings.get("d1_location") or "") or None)
        messages_queue = cloudflare.ensure_queue(names["messages_queue"])
        messages_dlq = cloudflare.ensure_queue(names["messages_dlq"])
        r2 = CloudflareR2Provisioner(account_id, cloudflare_token)
        r2_created = r2.ensure_bucket(names["r2"], location=str(self.settings.get("r2_location") or "") or None)
        email_bucket_created = r2.ensure_bucket(names["email_r2"], location=str(self.settings.get("r2_location") or "") or None)
        return {
            "d1": d1.to_dict(),
            "r2": {"bucket": names["r2"], "created": bool(r2_created)},
            "private_email_r2": {"bucket": names["email_r2"], "created": bool(email_bucket_created)},
            "queues": {"messages": messages_queue.to_dict(), "dead_letter": messages_dlq.to_dict()},
            "account_id": account_id,
        }

    def _worker_url(self, worker_name: str) -> str:
        configured = str(self.settings.get("worker_url_template") or "").strip()
        template = configured or "https://{worker_name}.workers.dev"
        try:
            url = template.format(worker_name=worker_name).rstrip("/")
        except (KeyError, ValueError) as exc:
            raise BootstrapError("bootstrap worker_url_template is invalid") from exc
        if not re.fullmatch(r"https://[^/?#]+", url):
            raise BootstrapError("bootstrap worker URL must be an HTTPS origin")
        return url

    def _materialize_template(self, site_dir: Path) -> None:
        template_raw = str(
            self.settings.get("template_path")
            or self.env.get("HELLOADA_SITE_TEMPLATE_DIR")
            or (Path(__file__).resolve().parents[1] / "templates" / "next-payload")
        ).strip()
        template = Path(template_raw).expanduser().resolve()
        if not template.is_dir() or not (template / "package.json").is_file():
            raise BootstrapError(f"Payload site template is unavailable: {template}")
        if site_dir.exists() and any(site_dir.iterdir()):
            raise BootstrapError("refusing to replace an existing site workspace; use its recorded canonical baseline")
        site_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            template,
            site_dir,
            dirs_exist_ok=True,
            ignore=payload_template_copy_ignore,
        )

    @staticmethod
    def _configure_template(site_dir: Path, tenant_id: str, display_name: str) -> None:
        """Bind only non-secret tenant identity into the copied Payload template.

        The template keeps the shared package and wrappers identical for every
        customer. This file is the one deliberate per-tenant substitution; it
        is written before the first customer commit so a generated repository
        never contains the template sentinels.
        """
        path = site_dir / "src" / "helloada.config.ts"
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BootstrapError("Payload template is missing src/helloada.config.ts") from exc
        encoded_tenant = json.dumps(str(tenant_id).strip())
        encoded_name = json.dumps(str(display_name or tenant_id).strip())
        if source.count("'__HELLOADA_TENANT_ID__'") != 1 or source.count("'__HELLOADA_SITE_NAME__'") != 1:
            raise BootstrapError("tenant identity can only be bound to an unconfigured canonical template")
        source = source.replace("'__HELLOADA_TENANT_ID__'", encoded_tenant)
        source = source.replace("'__HELLOADA_SITE_NAME__'", encoded_name)
        wrangler = site_dir / "wrangler.jsonc"
        if wrangler.exists():
            wrangler_source = wrangler.read_text(encoding="utf-8")
            wrangler_source = wrangler_source.replace('"__TENANT_ID__"', encoded_tenant)
            wrangler_source = wrangler_source.replace('"__SITE_NAME__"', encoded_name)
            wrangler_source = wrangler_source.replace('"__SITE_AGENT_VERSION__"', json.dumps(__version__))
            wrangler.write_text(wrangler_source, encoding="utf-8")
        if "__HELLOADA_" in source:
            raise BootstrapError("Payload template identity placeholders were not fully configured")
        try:
            manifest = json.loads((site_dir / "template-manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BootstrapError("Payload template identity manifest is missing or invalid") from exc
        marker = {
            "tenantId": str(tenant_id),
            "templateSchema": manifest["templateSchema"],
            "payloadAdmin": manifest["payloadAdmin"],
            "payloadCore": manifest["payloadCore"],
            "contentContract": manifest["contentContract"],
            "schemaRevision": manifest["schemaRevision"],
            "schemaIdentity": manifest["schemaIdentity"],
            "migrationHead": manifest["migrationHead"],
        }
        (site_dir / ".helloada-managed.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        path.write_text(source, encoding="utf-8")

    def _git_env(self) -> dict[str, str]:
        env = credential_environment(self.config, self.env)
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
        ssh = github_ssh_command(self.config, env)
        if ssh:
            env["GIT_SSH_COMMAND"] = ssh
        return env

    def _git(self, site_dir: Path, *args: str, input_text: str | None = None) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(site_dir), *args],
                capture_output=True,
                text=True,
                input=input_text,
                env=self._git_env(),
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BootstrapError(f"git command failed: {type(exc).__name__}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "git command failed").strip()[-800:]
            raise BootstrapError(f"git {' '.join(args[:3])}: {detail}")
        return result.stdout.strip()

    def _git_init_and_push(self, site_dir: Path, receipt: GitHubRepositoryReceipt) -> None:
        if not (site_dir / ".git").is_dir():
            self._git(site_dir, "init", "-q", "-b", "main")
            self._git(site_dir, "config", "user.email", "helloada-bootstrap@localhost")
            self._git(site_dir, "config", "user.name", "HelloAda Bootstrap")
        remote = self._git(site_dir, "remote", "get-url", "origin") if "origin" in self._git(site_dir, "remote").splitlines() else ""
        if remote != receipt.ssh_url:
            if remote:
                self._git(site_dir, "remote", "set-url", "origin", receipt.ssh_url)
            else:
                self._git(site_dir, "remote", "add", "origin", receipt.ssh_url)
        self._git(site_dir, "add", "-A")
        status = self._git(site_dir, "status", "--porcelain")
        if status:
            self._git(site_dir, "commit", "-qm", "HelloAda Payload site baseline")
        self._git(site_dir, "push", "-u", "origin", "main")

    @staticmethod
    def _read_env(path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        if not path.is_file():
            return result
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    result[key.strip()] = value.strip()
        except (OSError, UnicodeError):
            return {}
        return result

    @staticmethod
    def _write_env(path: Path, values: Mapping[str, str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            "# Server-side HelloAda runtime secrets.\n" + "".join(
                f"{key}={value}\n" for key, value in sorted(values.items()) if _SECRET_ENV.fullmatch(key)
            ),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def _configure_source(
        self,
        tenant_id: str,
        display_name: str,
        config_path: Path,
        repository: Mapping[str, Any],
        data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        names = self._names(tenant_id)
        worker_url = self._worker_url(names["worker"])
        public_origin = worker_url.rstrip("/") + "/"
        tenant_dir = config_path.parent
        site_dir = Path(str(repository.get("site_dir") or tenant_dir / "site")).resolve()
        site_agent_url = str(
            self.settings.get("site_agent_url")
            or self.env.get("HELLOADA_SITE_AGENT_URL")
            or "https://api.helloada.app/v1"
        ).strip().rstrip("/")
        if not re.fullmatch(r"https://[^/?#]+(?:/[^?#]*)?", site_agent_url):
            raise BootstrapError("bootstrap site_agent_url must be an HTTPS URL")
        payload_contract = self._load_payload_contract(site_dir)
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise BootstrapError("tenant config root must be an object")
        token_env = tenant_token_env(tenant_id)
        site = raw.setdefault("site", {})
        if not isinstance(site, dict):
            raise BootstrapError("tenant site config must be an object")
        site.update({
            "adapter": "payload_gateway",
            "repository": str(repository.get("full_name") or ""),
            "clone_path": str(site_dir),
            "branch": "main",
            "preview_branch": "preview",
            "url": worker_url,
            "preview_url": worker_url,
            "public_url": public_origin,
            "custom_domain": "",
            "website_present": False,
            "payload": {
                "enabled": True,
                "url": worker_url,
                "token_env": token_env,
                "api_prefix": "/api/workspace",
                "contract": payload_contract,
            },
            "source_deployment": {
                "clone_path": str(site_dir),
                "worker_name": names["worker"],
                "verification_timeout_seconds": 180,
                "verification_request_timeout_seconds": 10,
            },
        })
        raw["display_name"] = display_name or raw.get("display_name") or tenant_id
        messages = _mapping(raw.get("messages"))
        email_settings = _mapping(messages.get("email"))
        messages = {
            **messages,
            "email": {
                **email_settings,
                "enabled": True,
                "local_part": str(email_settings.get("local_part") or "hello"),
                "provisioning": {
                    **_mapping(email_settings.get("provisioning")),
                    "auto": True,
                },
            },
        }
        raw["messages"] = messages
        raw["scheduler"] = {**_mapping(raw.get("scheduler")), "enabled": True}
        raw["editorial"] = {**_mapping(raw.get("editorial")), "enabled": True}
        raw["ga"] = {
            **_mapping(raw.get("ga")),
            "enabled": True,
            "source": "crawlseo",
        }
        existing_seo = _mapping(raw.get("seo"))
        existing_provisioning = _mapping(existing_seo.get("provisioning"))
        raw["seo"] = {
            **existing_seo,
            "enabled": True,
            "source": "crawlseo",
            "site_url": public_origin,
            "gsc_property": public_origin,
            "provisioning": {
                **existing_provisioning,
                "auto": True,
                "verification_method": str(existing_provisioning.get("verification_method") or "meta"),
                "gsc_property": public_origin,
            },
        }
        TenantRegistrationService._replace_config(config_path, raw)

        env_path = tenant_dir / "tenant.env"
        values = self._read_env(env_path)
        values.setdefault("PAYLOAD_SECRET", os.urandom(36).hex())
        self._write_env(env_path, values)

        self._configure_wranger(site_dir, names, worker_url, site_agent_url, data, display_name, tenant_id, payload_contract)
        try:
            self.registry.reload_tenant(
                tenant_id,
                str(config_path),
                api_token=values.get(token_env, ""),
                api_token_env=token_env,
                env={**self.env, **values},
            )
        except Exception as exc:  # noqa: BLE001 - keep bootstrap receipt bounded
            raise BootstrapError(f"tenant runtime could not be reloaded: {str(exc)[:400]}") from exc
        return {"worker_name": names["worker"], "worker_url": worker_url, "repository": repository.get("full_name", "")}

    @staticmethod
    def _load_payload_contract(site_dir: Path) -> Mapping[str, Any]:
        contract_path = site_dir / "helloada-content-contract.json"
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BootstrapError("canonical Payload capability contract is missing or invalid") from exc
        if (
            not isinstance(contract, dict)
            or not re.fullmatch(r"helloada-content-v\d+", str(contract.get("contract") or ""))
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(contract.get("coreVersion") or ""))
            or not isinstance(contract.get("schemaRevision"), int)
            or not isinstance(contract.get("collections"), dict)
            or not isinstance(contract.get("globals"), dict)
            or not isinstance(contract.get("contentBlocks"), list)
            or not {"pages", "posts", "media"}.issubset(contract["collections"])
            or not {"siteSettings", "navigation"}.issubset(contract["globals"])
        ):
            raise BootstrapError("canonical Payload capability contract is incomplete")
        try:
            template = validate_payload_migrations(site_dir)
        except (OSError, UnicodeError, ValueError, PayloadContractError) as exc:
            raise BootstrapError("canonical Payload template manifest is missing or invalid") from exc
        if (
            not isinstance(template, dict)
            or template.get("payloadCore") != contract["coreVersion"]
            or template.get("contentContract") != contract["contract"]
            or template.get("schemaRevision") != contract["schemaRevision"]
            or not isinstance(template.get("templateSchema"), int)
            or not isinstance(template.get("payloadAdmin"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(template.get("schemaIdentity") or ""))
            or not isinstance(template.get("locales"), list)
            or not template["locales"]
            or any(not isinstance(locale, str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale) for locale in template["locales"])
            or len(set(template["locales"])) != len(template["locales"])
            or template.get("defaultLocale") not in template["locales"]
            or not isinstance(template.get("migrations"), list)
            or not template["migrations"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(template.get("migrationHead") or ""))
        ):
            raise BootstrapError("Payload package, template, and schema identities do not agree")
        return {
            **contract,
            "adminVersion": template["payloadAdmin"],
            "locales": template["locales"],
            "defaultLocale": template["defaultLocale"],
            "schemaIdentity": template["schemaIdentity"],
            "migrationHead": template["migrationHead"],
        }

    @staticmethod
    def _configure_wranger(
        site_dir: Path,
        names: Mapping[str, str],
        worker_url: str,
        site_agent_url: str,
        data: Mapping[str, Any],
        display_name: str,
        tenant_id: str,
        payload_contract: Mapping[str, Any],
    ) -> None:
        path = site_dir / "wrangler.jsonc"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            template = json.loads((site_dir / "template-manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BootstrapError("Payload site wrangler.jsonc is invalid") from exc
        vars_section = document.setdefault("vars", {})
        d1 = _mapping(data.get("d1"))
        queues = _mapping(data.get("queues"))
        messages_queue = _mapping(queues.get("messages"))
        messages_dlq = _mapping(queues.get("dead_letter"))
        private_email = _mapping(data.get("private_email_r2"))
        vars_section.update({
            "SITE_AGENT_URL": site_agent_url,
            "NEXT_PUBLIC_SITE_URL": worker_url,
            "HELLOADA_MESSAGES_QUEUE_NAME": str(messages_queue.get("name") or names["messages_queue"]),
            "HELLOADA_MESSAGES_DLQ_NAME": str(messages_dlq.get("name") or names["messages_dlq"]),
            "HELLOADA_SITE_NAME": display_name or tenant_id,
            "HELLOADA_TENANT_ID": tenant_id,
            "HELLOADA_SITE_AGENT_VERSION": __version__,
            "HELLOADA_TEMPLATE_SCHEMA": str(template.get("templateSchema") or ""),
            "HELLOADA_PAYLOAD_ADMIN_VERSION": str(template.get("payloadAdmin") or ""),
            "HELLOADA_PAYLOAD_CORE_VERSION": str(payload_contract.get("coreVersion") or ""),
            "HELLOADA_PAYLOAD_SCHEMA_REVISION": str(payload_contract.get("schemaRevision") or ""),
            "HELLOADA_CONTENT_CONTRACT_VERSION": str(payload_contract.get("contract") or ""),
            "HELLOADA_SCHEMA_IDENTITY": str(template.get("schemaIdentity") or ""),
            "HELLOADA_PAYLOAD_MIGRATION_HEAD": str(template.get("migrationHead") or ""),
        })
        document["name"] = names["worker"]
        document["d1_databases"] = [{
            "binding": "D1",
            "database_id": str(d1.get("database_id") or ""),
            "database_name": str(d1.get("name") or ""),
        }]
        document["r2_buckets"] = [
            {"binding": "R2", "bucket_name": names["r2"]},
            {"binding": "PRIVATE_EMAIL", "bucket_name": str(private_email.get("bucket") or names["email_r2"]), "preview_bucket_name": str(private_email.get("bucket") or names["email_r2"])},
        ]
        document["queues"] = {
            "producers": [{"binding": "HELLOADA_MESSAGES_QUEUE", "queue": str(messages_queue.get("name") or names["messages_queue"])}],
            "consumers": [{
                "queue": str(messages_queue.get("name") or names["messages_queue"]),
                "max_batch_size": 1,
                "max_batch_timeout": 5,
                "max_retries": 8,
                "retry_delay": 30,
                "max_concurrency": 1,
                "dead_letter_queue": str(messages_dlq.get("name") or names["messages_dlq"]),
            }, {
                "queue": str(messages_dlq.get("name") or names["messages_dlq"]),
                "max_batch_size": 1,
                "max_batch_timeout": 5,
                "max_retries": 3,
                "retry_delay": 30,
                "max_concurrency": 1,
            }],
        }
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def _queue_release(
        self,
        tenant_id: str,
        config_path: Path,
        worker: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        site_dir = Path(str(worker.get("site_dir") or config_path.parent / "site"))
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, Mapping) or str(raw.get("instance_name") or "") != tenant_id:
                raise BootstrapError("tenant source identity does not match its registration")
            site = _mapping(raw.get("site"))
            repository = str(site.get("repository") or "")
            match = re.fullmatch(r"https://github\.com/(weareheadless/[A-Za-z0-9_.-]+)\.git", repository)
            if not match:
                raise BootstrapError("managed tenant repository identity is invalid")
            expected_remote = f"git@github.com:{match.group(1)}.git"
            if self._git(site_dir, "remote", "get-url", "origin") != expected_remote:
                raise BootstrapError("managed tenant checkout remote differs from its registered GitHub repository")
            if self._git(site_dir, "branch", "--show-current") != "main":
                raise BootstrapError("managed tenant checkout must be on main before bootstrap release")
            changed = self._git(site_dir, "status", "--porcelain").splitlines()
            if any(line[3:] != "wrangler.jsonc" for line in changed):
                raise BootstrapError("bootstrap found source changes outside the declared Worker configuration")
            if changed:
                self._git(site_dir, "add", "--", "wrangler.jsonc")
                staged = self._git(site_dir, "diff", "--cached", "--name-only").splitlines()
                if staged != ["wrangler.jsonc"]:
                    raise BootstrapError("bootstrap staging contains files outside the declared Worker configuration")
                self._git(site_dir, "commit", "-qm", "Configure canonical Payload Worker bindings")
                self._git(site_dir, "push", "origin", "main")
            commit = self._git(site_dir, "rev-parse", "HEAD").lower()
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise BootstrapError("canonical site source has no exact Git revision")
            request_config = deep_merge(self.config, dict(raw))
            request = request_release(request_config, self.env, commit, initialize_schema=True)
            root = release_root(self.config)
        except (OSError, UnicodeError, yaml.YAMLError, ReleaseQueueError) as exc:
            raise BootstrapError(str(exc)[:500]) from exc
        return {
            **request,
            "tenant_id": tenant_id,
            "worker_name": worker.get("worker_name"),
            "worker_url": worker.get("worker_url"),
            "release_root": str(root),
        }


__all__ = ["BootstrapError", "WebsiteBootstrapService"]
