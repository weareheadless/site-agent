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
from .site_origin import SiteOriginError, normalize_site_origin, origins_equal
from .seo_provisioning import SeoProvisioningError, SeoProvisioningService, tenant_token_env, write_token_env


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _site_url(config: Mapping[str, Any]) -> str:
    site = _mapping(config.get("site"))
    seo = _mapping(config.get("seo"))
    raw = str(
        site.get("public_url")
        or site.get("custom_domain")
        or seo.get("site_url")
        or site.get("url")
        or site.get("preview_url")
        or ""
    ).strip()
    if not raw:
        raise SeoProvisioningError("seo.provisioning requires seo.site_url or site.preview_url")
    try:
        return normalize_site_origin(raw)
    except SiteOriginError as exc:
        raise SeoProvisioningError(str(exc)) from exc


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
    site = _mapping(config.get("site"))
    deployment = _mapping(site.get("source_deployment"))
    worker_name = str(
        deployment.get("worker_name")
        or _mapping(site.get("cloudflare")).get("worker_name")
        or ""
    ).strip()
    # Older tenant configs did not persist the Worker name. Recover it only
    # from the platform preview origin; custom domains never determine the
    # deployment target.
    if not worker_name:
        preview_host = str(urlsplit(str(site.get("preview_url") or "")).hostname or "").lower()
        if preview_host.endswith(".workers.dev"):
            worker_name = preview_host.split(".", 1)[0]
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
    previous_site_url = str(state.get("site_url") or "").strip()
    origin_changed = bool(previous_site_url and not origins_equal(previous_site_url, site_url))
    configured_gsc_property = str(
        provisioning.get("gsc_property")
        or seo.get("gsc_property")
        or ""
    ).strip()
    # A URL-prefix property belongs to the current public origin. Never carry
    # a previous domain's property into a new-domain verification attempt.
    gsc_property = site_url if origin_changed else str(
        configured_gsc_property
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
    history = list(state.get("origin_history") or []) if isinstance(state.get("origin_history"), list) else []
    if origin_changed and previous_site_url:
        previous_record = {
            key: state.get(key)
            for key in ("site_url", "domain", "gsc_property", "gsc_verified", "gsc_verified_at", "provisioning_state")
            if state.get(key) not in (None, "")
        }
        previous_record["retired_at"] = _now()
        if previous_record and not any(
            isinstance(item, Mapping) and str(item.get("site_url") or "") == previous_site_url
            for item in history
        ):
            history.append(previous_record)
    attempt: dict[str, Any] = {
        **_safe_receipt(state),
        "state": "running",
        "last_attempt_at": _now(),
        "site_url": site_url,
        "origin_changed": origin_changed,
        "origin_history": history,
    }
    if origin_changed:
        for key in ("gsc_verified", "gsc_verified_at", "gsc_pending", "gsc_meta_tag", "gsc_meta_identifier", "crawlseo", "crawlseo_pending"):
            attempt.pop(key, None)
        attempt["gsc_property"] = site_url
        attempt["provisioning_state"] = "origin_changed"
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
        attempt["site_url"] = site_url
        attempt["origin_changed"] = origin_changed
        attempt["origin_history"] = history
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
            attempt["site_url"] = site_url
            attempt["origin_changed"] = origin_changed
            attempt["origin_history"] = history
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
            "site_url": site_url,
            "origin_changed": origin_changed,
            "origin_history": history,
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
