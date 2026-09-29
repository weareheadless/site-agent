"""Automatic, resumable SEO bootstrap for Cloudflare-hosted tenants.

This is deliberately separate from the CLI. A tenant entering the shared
workspace is reconciled from its own configuration and durable memory; no
operator needs to run a second command or copy a Google/CrawlSEO credential.
"""

from __future__ import annotations

import copy
import datetime
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..credentials import cloudflare_env_names, credential_environment, credential_profile
from ..hands.cloudflare_worker import CloudflareWorkerError, CloudflareWorkerSecretsClient
from ..hands.crawlseo_provisioning import CrawlSEOProvisioningError
from .seo_provisioning import SeoProvisioningError, SeoProvisioningService, tenant_token_env, write_token_env


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _site_url(config: Mapping[str, Any]) -> str:
    site = _mapping(config.get("site"))
    seo = _mapping(config.get("seo"))
    raw = str(seo.get("site_url") or site.get("preview_url") or "").strip()
    if not raw:
        raise SeoProvisioningError("seo.provisioning requires seo.site_url or site.preview_url")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SeoProvisioningError("seo.site_url must be a public URL")
    return raw.rstrip("/") + "/"


def _meta_content(value: str) -> str:
    value = str(value or "").strip()
    return value.split("=", 1)[1].strip() if value.lower().startswith("google-site-verification=") else value


def _safe_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Remove the one-time CrawlSEO credential before durable diagnostics."""
    value = copy.deepcopy(dict(receipt))
    value.pop("credential_token", None)
    return value


def _worker_client(config: Mapping[str, Any], env: Mapping[str, str]) -> CloudflareWorkerSecretsClient:
    profile = credential_profile(config, "cloudflare")
    token_name, account_name = cloudflare_env_names(config)
    deployment = _mapping(_mapping(config.get("site")).get("source_deployment"))
    worker_name = str(
        deployment.get("worker_name")
        or _mapping(_mapping(config.get("site")).get("cloudflare")).get("worker_name")
        or ""
    ).strip()
    token = str(env.get(str(profile.get("api_token_env") or token_name)) or env.get(token_name) or "")
    account = str(env.get(str(profile.get("account_id_env") or account_name)) or env.get(account_name) or "")
    return CloudflareWorkerSecretsClient(token, account, worker_name)


def _credential_directory(config: Mapping[str, Any]) -> Path:
    data_dir = Path(str(config.get("data_dir") or ".")).expanduser().resolve()
    return data_dir.parent


def load_tenant_environment(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Load host credentials and a previously issued tenant token."""
    resolved = credential_environment(config, os.environ if env is None else env)
    token_file = _credential_directory(config) / "crawlseo.env"
    if token_file.is_file():
        try:
            for line in token_file.read_text(encoding="utf-8").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                name, value = line.split("=", 1)
                if name.strip() and value.strip():
                    resolved[name.strip()] = value.strip()
        except (OSError, UnicodeError):
            pass
    return resolved


def auto_provision_seo(
    config: Mapping[str, Any],
    *,
    tenant_id: str,
    memory: Any,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Converge one tenant to GA4 + verified GSC + CrawlSEO.

    The operation is safe to run at startup and on every scheduler recovery:
    Google property/stream and CrawlSEO project creation are idempotent, while
    the one-time CrawlSEO token is written before the ready state is recorded.
    """
    seo = _mapping(config.get("seo"))
    provisioning = _mapping(seo.get("provisioning"))
    resolved_env = load_tenant_environment(config, env)
    existing = memory.kv_get("seo_provisioning_state", {}) if memory is not None else {}
    state = dict(existing) if isinstance(existing, Mapping) else {}
    if not bool(provisioning.get("auto", False)):
        return state, resolved_env

    site_url = _site_url(config)
    domain = str(urlsplit(site_url).hostname or "").lower().rstrip(".")
    project_name = str(
        provisioning.get("project_name")
        or config.get("display_name")
        or (_mapping(config.get("customer_profile")).get("business") or {}).get("name")
        or tenant_id
    ).strip()[:200]
    method = str(provisioning.get("verification_method") or "meta").strip().lower()
    gsc_property = str(
        provisioning.get("gsc_property")
        or seo.get("gsc_property")
        or state.get("gsc_property")
        or site_url
    ).strip()
    ga = _mapping(config.get("ga"))
    ga_property = str(
        provisioning.get("ga4_property_id")
        or ga.get("property_id")
        or state.get("ga4_property_id")
        or ""
    ).strip()
    organization_id = str(provisioning.get("organization_id") or "helloada").strip()
    idempotency_key = str(provisioning.get("idempotency_key") or f"site-agent:{tenant_id}:v1").strip()
    token_env = str(state.get("token_env") or tenant_token_env(tenant_id)).strip()
    recover_service_credential = not bool(str(resolved_env.get(token_env) or "").strip())

    service = SeoProvisioningService(config, resolved_env)
    attempt: dict[str, Any] = {"state": "running", "last_attempt_at": _now(), **_safe_receipt(state)}
    try:
        receipt = service.provision(
            tenant_id=tenant_id,
            domain=domain,
            project_name=project_name,
            organization_id=organization_id,
            site_url=site_url,
            gsc_property=gsc_property,
            ga4_property_id=ga_property,
            time_zone=str(provisioning.get("time_zone") or "UTC"),
            currency_code=str(provisioning.get("currency_code") or "EUR"),
            verification_method=method,
            domain_verification_method="verified_gsc",
            idempotency_key=idempotency_key,
            recover_service_credential=recover_service_credential,
        )
        # Persist the receipt before any external follow-up. Google property
        # creation is not safely repeatable if the process dies while the
        # Worker secret or the one-time CrawlSEO credential is being written.
        attempt.update(_safe_receipt(receipt))
        if memory is not None:
            memory.kv_set("seo_provisioning_state", attempt)

        if receipt.get("gsc_pending"):
            worker = _worker_client(config, resolved_env)
            tag = _meta_content(str(receipt.get("gsc_meta_tag") or ""))
            if not tag:
                raise SeoProvisioningError("Google did not return a meta verification token")
            worker.put_secret("GOOGLE_SITE_VERIFICATION", tag)
            # The Worker serves the tag at runtime. Re-enter the same
            # idempotent chain so GSC is verified before CrawlSEO queues jobs.
            receipt = service.provision(
                tenant_id=tenant_id,
                domain=domain,
                project_name=project_name,
                organization_id=organization_id,
                site_url=site_url,
                gsc_property=gsc_property,
                ga4_property_id=str(receipt.get("ga4_property_id") or ga_property),
                time_zone=str(provisioning.get("time_zone") or "UTC"),
                currency_code=str(provisioning.get("currency_code") or "EUR"),
                verification_method=method,
                domain_verification_method="verified_gsc",
                idempotency_key=idempotency_key,
                recover_service_credential=recover_service_credential,
            )
            attempt.update(_safe_receipt(receipt))
            if memory is not None:
                memory.kv_set("seo_provisioning_state", attempt)

        measurement_id = str(receipt.get("ga4_measurement_id") or "").strip()
        if measurement_id:
            _worker_client(config, resolved_env).put_secret("GA_MEASUREMENT_ID", measurement_id)

        token = str(receipt.get("credential_token") or "").strip()
        if token:
            token_env = str(receipt.get("token_env") or "").strip()
            if not token_env:
                raise SeoProvisioningError("CrawlSEO returned a token without an environment name")
            write_token_env(_credential_directory(config), token_env, token)
            resolved_env[token_env] = token

        sanitized = _safe_receipt(receipt)
        sanitized.update({
            "state": "ready" if receipt.get("provisioning_state") == "ready" else str(receipt.get("provisioning_state") or "pending"),
            "last_attempt_at": _now(),
            "credential_file": str(_credential_directory(config) / "crawlseo.env"),
        })
        if memory is not None:
            memory.kv_set("seo_provisioning_state", sanitized)
        return sanitized, resolved_env
    except (SeoProvisioningError, CrawlSEOProvisioningError, CloudflareWorkerError, OSError) as exc:
        attempt.update({"state": "error", "error": str(exc)[:500], "last_attempt_at": _now()})
        if memory is not None:
            memory.kv_set("seo_provisioning_state", attempt)
        return attempt, resolved_env
    except Exception as exc:  # noqa: BLE001 - startup automation must leave a durable retry state
        attempt.update({"state": "error", "error": str(exc)[:500], "last_attempt_at": _now()})
        if memory is not None:
            memory.kv_set("seo_provisioning_state", attempt)
        return attempt, resolved_env


__all__ = ["auto_provision_seo", "load_tenant_environment"]
