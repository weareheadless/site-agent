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
import urllib.error
import urllib.request
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
from .. import __version__
from ..hands.cloudflare_resources import CloudflareResourceProvisioner
from ..hands.cloudflare_r2 import CloudflareR2Provisioner
from ..hands.github_provisioning import GitHubRepositoryProvisioner, GitHubRepositoryReceipt
from .tenant_registration import (
    WORKER_SITE_AGENT_TOKEN_ENV,
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
            return self._public_state(self._read_state(normalized))

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
            deployment = self._run_step(
                state,
                "deploying_shell",
                lambda: self._deploy(tenant_id, config_path, worker),
            )
            self._run_step(
                state,
                "ready",
                lambda: self._verify(deployment.get("worker_url") or worker.get("worker_url")),
            )
            state["status"] = "done"
            state["step"] = "ready"
            state["diagnostic"] = ""
            state["updated_at"] = _now()
            self._write_state(state)
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
        return {"worker": worker, "repo": repo, "d1": d1, "r2": r2}

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
        self._materialize_template(site_dir)
        self._configure_template(site_dir, tenant_id, display_name)
        self._git_init_and_push(site_dir, receipt)
        return {**receipt.to_dict(), "site_dir": str(site_dir), "worker_name": names["worker"]}

    def _data_resources(self, tenant_id: str) -> Mapping[str, Any]:
        _env, _github_token, cloudflare_token, account_id = self._credentials()
        names = self._names(tenant_id)
        cloudflare = CloudflareResourceProvisioner(account_id, cloudflare_token)
        d1 = cloudflare.ensure_d1(names["d1"], location=str(self.settings.get("d1_location") or "") or None)
        r2 = CloudflareR2Provisioner(account_id, cloudflare_token)
        r2_created = r2.ensure_bucket(names["r2"], location=str(self.settings.get("r2_location") or "") or None)
        return {
            "d1": d1.to_dict(),
            "r2": {"bucket": names["r2"], "created": bool(r2_created)},
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
        if site_dir.exists() and (site_dir / ".git").is_dir():
            # A neutral registration scaffold is replaced exactly once. A real
            # bootstrap checkout is left alone so retries do not destroy edits.
            try:
                proc = subprocess.run(
                    ["git", "-C", str(site_dir), "remote"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return
            except (OSError, subprocess.TimeoutExpired):
                pass
            shutil.rmtree(site_dir)
        site_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template, site_dir, dirs_exist_ok=False)

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
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise BootstrapError("tenant config root must be an object")
        token_env = tenant_token_env(tenant_id)
        site = raw.setdefault("site", {})
        if not isinstance(site, dict):
            raise BootstrapError("tenant site config must be an object")
        site.update({
            "adapter": "github_static",
            "repository": str(repository.get("full_name") or ""),
            "clone_path": str(site_dir),
            "branch": "main",
            "preview_branch": "preview",
            "url": worker_url,
            "preview_url": worker_url,
            "public_url": public_origin,
            "custom_domain": "",
            "website_present": True,
            "payload": {
                "enabled": True,
                "url": worker_url,
                "token_env": token_env,
                "api_prefix": "/api",
                "contract": {
                    "version": "helloada-content-v1",
                    "collections": {
                        "pages": ["sourceId", "title", "slug", "summary", "body", "sections", "featuredImage", "canonicalUrl", "seo", "published"],
                        "posts": ["sourceId", "title", "slug", "summary", "body", "featuredImage", "gallery", "author", "publishedAt", "modifiedAt", "category", "canonicalUrl", "seo", "published"],
                        "products": ["sourceId", "title", "slug", "summary", "body", "featuredImage", "price", "category", "published"],
                        "productCategories": ["sourceId", "title", "slug", "description", "featuredImage", "published"],
                    },
                    "globals": {
                        "navigation": ["items", "groups", "footer", "footerGroups"],
                        "siteSettings": ["siteName", "description", "tagline", "logo", "email", "telephone", "facebookUrl", "instagramUrl", "defaultSeoTitle", "defaultSeoDescription", "defaultSocialImage", "journalTitle", "journalDescription", "address"],
                    },
                    "media_fields": ["alt", "description", "tags", "dominantColors", "suggestedUses", "qualityNotes", "analysisStatus", "analysis", "sourceId"],
                },
            },
            "source_deployment": {
                "clone_path": str(site_dir),
                "worker_name": names["worker"],
                "verification_timeout_seconds": 180,
                "verification_request_timeout_seconds": 10,
            },
        })
        raw["display_name"] = display_name or raw.get("display_name") or tenant_id
        raw["scheduler"] = {**_mapping(raw.get("scheduler")), "enabled": True}
        raw["blog"] = {**_mapping(raw.get("blog")), "engine": "payload", "journal_enabled": True}
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

        self._configure_wranger(site_dir, names, worker_url, site_agent_url, data, display_name, tenant_id)
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
    def _configure_wranger(
        site_dir: Path,
        names: Mapping[str, str],
        worker_url: str,
        site_agent_url: str,
        data: Mapping[str, Any],
        display_name: str,
        tenant_id: str,
    ) -> None:
        path = site_dir / "wrangler.jsonc"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BootstrapError("Payload site wrangler.jsonc is invalid") from exc
        vars_section = document.setdefault("vars", {})
        d1 = _mapping(data.get("d1"))
        vars_section.update({
            "SITE_AGENT_URL": site_agent_url,
            "NEXT_PUBLIC_SITE_URL": worker_url,
            "HELLOADA_SITE_NAME": display_name or tenant_id,
            "HELLOADA_TENANT_ID": tenant_id,
            "HELLOADA_SITE_AGENT_VERSION": __version__,
            "HELLOADA_TEMPLATE_SCHEMA": "4",
            "HELLOADA_PAYLOAD_ADMIN_VERSION": "0.8.6",
            "HELLOADA_PAYLOAD_CORE_VERSION": "0.1.0",
            "HELLOADA_CONTENT_CONTRACT_VERSION": "helloada-content-v1",
        })
        document["name"] = names["worker"]
        document["d1_databases"] = [{
            "binding": "D1",
            "database_id": str(d1.get("database_id") or ""),
            "database_name": str(d1.get("name") or ""),
        }]
        document["r2_buckets"] = [{"binding": "R2", "bucket_name": names["r2"]}]
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def _command(
        self,
        site_dir: Path,
        command: list[str],
        *,
        input_text: str | None = None,
        production: bool = False,
        local_build: bool = True,
    ) -> str:
        env = credential_environment(self.config, self.env)
        values = self._read_env(site_dir.parent / "tenant.env")
        env.update(values)
        env["CLOUDFLARE_API_TOKEN"] = cloudflare_api_token(self.config, env)
        _token_name, account_name = cloudflare_env_names(self.config)
        env["CLOUDFLARE_ACCOUNT_ID"] = env.get(account_name, "")
        if local_build:
            env["PAYLOAD_LOCAL_BUILD"] = "1"
        else:
            env.pop("PAYLOAD_LOCAL_BUILD", None)
        if production:
            env["NODE_ENV"] = "production"
        try:
            result = subprocess.run(
                command,
                cwd=str(site_dir),
                env=env,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=1_800,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BootstrapError(f"command failed: {' '.join(command[:3])}: {type(exc).__name__}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "command failed").strip()[-1_500:]
            raise BootstrapError(f"{' '.join(command[:3])}: {detail}")
        return result.stdout.strip()

    def _deploy(self, tenant_id: str, config_path: Path, worker: Mapping[str, Any]) -> Mapping[str, Any]:
        site_dir = Path(str(worker.get("site_dir") or config_path.parent / "site"))
        self._command(site_dir, ["npm", "install", "--no-audit", "--no-fund"])
        migrations = site_dir / "src" / "migrations"
        has_migration = migrations.exists() and any(
            path.suffix in {".ts", ".json"} and path.name != "index.ts"
            for path in migrations.glob("*")
        )
        if not has_migration:
            self._command(site_dir, ["npx", "payload", "migrate:create", "initial"], production=True)
        self._command(site_dir, ["npx", "payload", "migrate"], production=True, local_build=False)
        self._command(site_dir, ["npm", "run", "typecheck"])
        self._command(site_dir, ["npm", "run", "build"])
        self._command(site_dir, ["npx", "opennextjs-cloudflare", "build"])
        self._git(site_dir, "add", "-A")
        if self._git(site_dir, "status", "--porcelain"):
            self._git(site_dir, "commit", "-qm", "Configure managed Payload runtime")
            self._git(site_dir, "push", "origin", "main")
        env_values = self._read_env(config_path.parent / "tenant.env")
        payload_secret = env_values.get("PAYLOAD_SECRET")
        tenant_token = env_values.get(tenant_token_env(tenant_id))
        if not payload_secret or not tenant_token:
            raise BootstrapError("runtime secrets are unavailable")
        for name, value in (("PAYLOAD_SECRET", payload_secret), (WORKER_SITE_AGENT_TOKEN_ENV, tenant_token)):
            self._command(site_dir, ["npx", "wrangler", "secret", "put", name, "--config", "wrangler.jsonc"], input_text=value + "\n")
        self._command(site_dir, ["npx", "wrangler", "deploy", "--config", "wrangler.jsonc"], production=True)
        return {"worker_name": worker.get("worker_name"), "worker_url": worker.get("worker_url"), "commit": self._git(site_dir, "rev-parse", "HEAD")}

    @staticmethod
    def _verify(worker_url: Any) -> Mapping[str, Any]:
        url = str(worker_url or "").rstrip("/") + "/api/health"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "helloada-bootstrap"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read(32 * 1024).decode("utf-8", "replace")
                if int(response.status) != 200:
                    raise BootstrapError(f"live site health check returned {response.status}")
                return {"worker_url": str(worker_url), "status": int(response.status), "body": body[:500]}
        except urllib.error.HTTPError as exc:
            raise BootstrapError(f"live site health check returned {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BootstrapError(f"live site health check failed: {type(exc).__name__}") from exc


__all__ = ["BootstrapError", "WebsiteBootstrapService"]
