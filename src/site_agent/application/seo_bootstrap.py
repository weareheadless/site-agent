"""Automatic, resumable SEO bootstrap for Cloudflare-hosted tenants.

This is deliberately separate from the CLI. A tenant entering the shared
workspace is reconciled from its own configuration and durable memory; no
operator needs to run a second command or copy a Google/CrawlSEO credential.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..credentials import credential_environment, credential_profile
from ..hands.crawlseo import CrawlSEOClient
from ..hands.crawlseo_connector_credentials import load_connector_environment, load_connector_runtime_environment
from ..hands.cloudflare_worker import CloudflareWorkerError
from ..hands.crawlseo_provisioning import CrawlSEOProvisioningError
from .site_origin import SiteOriginError, normalize_site_origin, origins_equal
from .seo_provisioning import (
    SeoProvisioningError,
    SeoProvisioningService,
    tenant_token_env,
    write_connector_runtime_token,
    write_token_env,
)
from .runtime_binding_delivery import deliver_runtime_bindings, RuntimeBindingError


def _persist_credentials(config, receipt, resolved_env):
    """Keep one-time credentials before crossing any external delivery boundary."""
    token = str(receipt.get("credential_token") or "").strip()
    if token:
        name = str(receipt.get("token_env") or "").strip()
        if not name:
            raise SeoProvisioningError("CrawlSEO returned a token without an environment name")
        write_token_env(_credential_directory(config), name, token)
        resolved_env[name] = token
    connector = str(receipt.get("connector_credential_token") or "").strip()
    if connector:
        write_connector_runtime_token(_credential_directory(config), connector)
        resolved_env["CRAWLSEO_CONNECTOR_TOKEN"] = connector


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
    if value.lower().startswith("<meta"):
        match = re.search(r"\bcontent\s*=\s*([\"'])(.*?)\1", value, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(2).strip()
    return value.split("=", 1)[1].strip() if value.lower().startswith("google-site-verification=") else value


def _safe_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Remove the one-time CrawlSEO credential before durable diagnostics."""
    value = copy.deepcopy(dict(receipt))
    value.pop("credential_token", None)
    value.pop("connector_credential_token", None)
    return value


def _credential_directory(config: Mapping[str, Any]) -> Path:
    data_dir = Path(str(config.get("data_dir") or ".")).expanduser().resolve()
    return data_dir.parent


def _profile_text(value: Any, limit: int) -> str | None:
    text_value = str(value or "").strip()
    return text_value[:limit] if text_value else None


def _profile_list(value: Any, limit: int, item_limit: int, max_items: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text_value = str(item or "").strip()
        if text_value and text_value[:item_limit] not in out:
            out.append(text_value[:item_limit])
        if len(out) >= max_items:
            break
    return out


def build_research_profile(
    config: Mapping[str, Any],
    *,
    site_id: str,
    tenant_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Build the single research profile Ada owns from the confirmed tenant context."""
    seo = _mapping(config.get("seo"))
    research = _mapping(seo.get("research"))
    site = _mapping(config.get("site"))
    brand = _mapping(site.get("brand"))
    persona = _mapping(config.get("persona"))
    languages = research.get("languages") if isinstance(research.get("languages"), list) else []
    primary = next(
        (item for item in languages if isinstance(item, Mapping) and item.get("primary") is True),
        languages[0] if languages else {},
    )
    primary = primary if isinstance(primary, Mapping) else {}
    markets = primary.get("markets") if isinstance(primary.get("markets"), list) else []
    market = _profile_text(", ".join(str(item) for item in markets if str(item).strip()), 120)
    language = _profile_text(primary.get("code") or research.get("language"), 16) or "en"
    audience = _profile_text(
        research.get("audience")
        or persona.get("audience")
        or site.get("audience")
        or brand.get("audience"), 300
    )
    topics = _profile_list(
        research.get("anchor_topics") or research.get("topics"), 120, 120, 12
    )
    goals = _profile_list(research.get("business_goals") or research.get("goals"), 300, 300, 12)
    exclusions = _profile_list(research.get("exclusions"), 200, 200, 30)
    sources = _mapping(config.get("sources"))
    providers: list[str] = []
    if sources.get("subreddits"):
        providers.append("reddit")
    if sources.get("rss_feeds"):
        providers.append("news")
    if not providers:
        providers = ["reddit", "news"]
    article = _mapping(seo.get("article_research"))
    seo_research = _mapping(seo.get("seo_research"))
    payload = {
        "siteId": site_id,
        "expectedRevision": max(0, int(expected_revision)),
        "profile": {
            "topics": topics,
            "audience": audience,
            "market": market,
            "language": language,
            "goals": goals,
            "exclusions": exclusions,
        },
        "researchPolicy": {
            "enabled": research.get("enabled") is not False,
            "cadence": str(research.get("cadence") or "weekly"),
            "providers": providers,
            "maxSources": int(research.get("max_sources") or 30),
            "monthlyBudget": int(research.get("monthly_budget") or 9),
            "recencyDays": int(research.get("recency_days") or 90),
            "autoDraft": bool(research.get("auto_draft") is True),
            "autoAgent": bool(research.get("auto_agent") is True),
        },
        "seoResearch": {
            "enabled": seo_research.get("enabled") is not False,
            "monthlyTaskLimit": int(seo_research.get("monthly_task_limit") or 9),
            "keywordSeedLimit": int(seo_research.get("keyword_seed_limit") or 5),
            "competitorLimit": int(seo_research.get("competitor_limit") or 1),
            "packageVersion": str(seo_research.get("package_version") or "standard-v1"),
            "articleResearchEnabled": article.get("enabled") is not False,
            "articleTaskLimitPerMonth": int(article.get("article_task_limit_per_month") or 5),
            "articleMinIntervalDays": int(article.get("min_interval_days") or 7),
        },
    }
    if payload["researchPolicy"]["cadence"] not in {"daily", "weekly", "monthly", "manual"}:
        payload["researchPolicy"]["cadence"] = "weekly"
    digest = hashlib.sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key not in {"expectedRevision", "idempotencyKey"}},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    payload["idempotencyKey"] = f"site-agent:{tenant_id}:research-profile:{digest}"
    return payload


def sync_research_profile(
    config: Mapping[str, Any],
    env: Mapping[str, str],
    receipt: Mapping[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """Push the confirmed research profile to CrawlSEO without changing authority."""
    crawlseo = _mapping(receipt.get("crawlseo"))
    site_id = str(crawlseo.get("site_id") or "").strip()
    if not site_id:
        return {"state": "skipped", "reason": "crawlseo_site_missing"}
    profile = credential_profile(config, "crawlseo")
    provider = dict(_mapping(_mapping(config.get("providers")).get("crawlseo")))
    connector_url = str(provider.get("connector_url") or profile.get("connector_url") or "").strip()
    if not connector_url:
        return {"state": "skipped", "reason": "connector_url_not_configured"}
    provider["connector_url"] = connector_url
    provider["connector_token_env"] = "CRAWLSEO_CONNECTOR_TOKEN"
    effective = {
        **dict(config),
        "providers": {**_mapping(config.get("providers")), "crawlseo": provider},
    }
    try:
        client = CrawlSEOClient.from_config(effective, dict(env))
        if client is None:
            return {"state": "skipped", "reason": "crawlseo_disabled"}
        current = client.connector_policy(site_id)
        policy_view = current.get("policy") if isinstance(current.get("policy"), Mapping) else current
        payload = build_research_profile(
            effective,
            site_id=site_id,
            tenant_id=tenant_id,
            expected_revision=int(policy_view.get("revision") or 0),
        )
        result = client.connector_update_research_profile(payload)
        return {
            "state": "configured",
            "siteId": site_id,
            "revision": result.get("revision"),
            "topics": len(payload["profile"]["topics"]),
            "providers": payload["researchPolicy"]["providers"],
        }
    except Exception as exc:  # noqa: BLE001 - provisioning records a named retryable state
        return {"state": "error", "error": str(exc)[:300]}


def load_tenant_environment(
    config: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    *,
    require_connector: bool = True,
) -> dict[str, str]:
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
    # Keep the narrowly managed connector credential separate from, and
    # authoritative over, the legacy CrawlSEO MCP credential file.
    if require_connector:
        resolved.update(load_connector_environment(config))
    resolved.update(load_connector_runtime_environment(config))
    return resolved


def auto_provision_seo(
    config: Mapping[str, Any],
    *,
    tenant_id: str,
    memory: Any,
    env: Mapping[str, str] | None = None,
    tenant_config_path: str | Path | None = None,
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
    if state.get("gsc_secret_pending_fingerprint"):
        state.update({
            "state": "error",
            "error": "A prior Cloudflare GSC secret update has an unresolved outcome; operator reconciliation is required.",
            "last_attempt_at": _now(),
        })
        if memory is not None:
            memory.kv_set("seo_provisioning_state", state)
        return state, resolved_env
    # SEO provisioning is the platform default for every enabled public site.
    # A tenant may explicitly opt out with seo.provisioning.auto: false, but
    # omission must not silently leave a customer disconnected.
    if seo.get("enabled") is False or provisioning.get("auto") is False:
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
        _persist_credentials(config, receipt, resolved_env)
        # Persist the receipt before any external follow-up. Google property
        # creation is not safely repeatable if the process dies while the
        # one-time CrawlSEO credential is written or a runtime release is
        # queued.
        attempt.update(_safe_receipt(receipt))
        attempt["crawlseo"] = _safe_receipt(receipt.get("crawlseo") or {})
        attempt["site_url"] = site_url
        attempt["origin_changed"] = origin_changed
        attempt["origin_history"] = history
        if memory is not None:
            memory.kv_set("seo_provisioning_state", attempt)

        desired = {}
        if receipt.get("ga4_measurement_id"):
            desired["GA_MEASUREMENT_ID"] = str(receipt["ga4_measurement_id"])
        if receipt.get("gsc_pending"):
            tag = _meta_content(str(receipt.get("gsc_meta_tag") or ""))
            if not tag:
                raise SeoProvisioningError("Google did not return a meta verification token")
            desired["GOOGLE_SITE_VERIFICATION"] = tag
        if desired:
            delivery = deliver_runtime_bindings(config, resolved_env, memory, tenant_config_path, desired)
            attempt["runtime_delivery"] = delivery
            if delivery["state"] != "delivered":
                attempt["state"] = "awaiting_runtime_release"
                memory.kv_set("seo_provisioning_state", attempt)
                return attempt, resolved_env
        if receipt.get("gsc_pending"):
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
            _persist_credentials(config, receipt, resolved_env)
            attempt.update(_safe_receipt(receipt))
            attempt["crawlseo"] = _safe_receipt(receipt.get("crawlseo") or {})
            attempt["site_url"] = site_url
            attempt["origin_changed"] = origin_changed
            attempt["origin_history"] = history
            if memory is not None:
                memory.kv_set("seo_provisioning_state", attempt)

        measurement_id = str(receipt.get("ga4_measurement_id") or "").strip()
        if measurement_id and measurement_id != desired.get("GA_MEASUREMENT_ID"):
            delivery = deliver_runtime_bindings(config, resolved_env, memory, tenant_config_path, {"GA_MEASUREMENT_ID": measurement_id})
            attempt["runtime_delivery"] = delivery
            if delivery["state"] != "delivered":
                attempt["state"] = "awaiting_runtime_release"
                memory.kv_set("seo_provisioning_state", attempt)
                return attempt, resolved_env
        if measurement_id:
            attempt["ga4_secret_measurement_id"] = measurement_id

        connector_token = str(receipt.get("connector_credential_token") or "").strip()
        if connector_token:
            try:
                attempt["research_profile"] = sync_research_profile(config, resolved_env, receipt, tenant_id)
            except (SeoProvisioningError, OSError) as exc:
                attempt["research_profile"] = {"state": "error", "error": str(exc)[:300]}

        sanitized = _safe_receipt(receipt)
        if attempt.get("runtime_delivery"):
            sanitized["runtime_delivery"] = attempt["runtime_delivery"]
        if measurement_id:
            sanitized["ga4_secret_measurement_id"] = measurement_id
        if attempt.get("research_profile"):
            sanitized["research_profile"] = attempt["research_profile"]
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
    except (SeoProvisioningError, CrawlSEOProvisioningError, CloudflareWorkerError, RuntimeBindingError, OSError) as exc:
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
