"""jobs.py — builtin scheduler jobs for an instance.

Registered today:
  heartbeat     hourly  — proves the loop, marks she's alive
  digest        daily   — senses (reddit/rss) -> scored, deduped observations
  learn         daily   — LLM distills the day's reading into insights + themes
  ga_snapshot   daily   — GA4 weekly summary -> metrics_snapshots
  weekly_report weekly  — HERO: plain-language report draft for the owner
  reflect       monthly — self-review of her own voice (owner approves)
  inner_voice   every 2 days — a mood + self-note (sometimes private)
  dream         weekly  — a private dream from her retained inner material
  awaken        weekly  — on waking, decides if the dream meant anything
  integrate_self every 2 days — decides whether her self-understanding changed
  health_check  daily   — deterministic ledger and operational health scan
   social_post   weekly  — grounded Cicero preparation for owner review (opt-in)

   Later phases register here: brain.article (weekly), editor status checks.
"""

from __future__ import annotations

import datetime
import re
import time
import unicodedata
from collections.abc import Mapping
from typing import Any

from ..brain import article as brain_article
from ..brain import article_research as brain_article_research
from ..brain import digest as brain_digest
from ..brain import dream as brain_dream
from ..brain import inner_voice as brain_inner_voice
from ..brain import report as brain_report
from ..brain import self_model as brain_self_model
from ..brain import social as brain_social
from ..brain import seo as brain_seo
from ..brain import seo_insights as brain_seo_insights
from ..brain import seo_outcomes as brain_seo_outcomes
from ..brain import monthly_seo_report as brain_monthly_seo_report
from ..application.growth_workflow import (
    has_recoverable_growth_replay,
    run_growth_reconciler,
    run_growth_cycle,
    run_pending_growth,
)
from ..senses import collect
from . import maintenance
from .contracts import ActionState, ApprovalStatus, ArtifactKind
from .payload_rich_text import lexical_text, markdown_to_lexical
from .design_contracts import canonical_hash
from .memory import Memory
from .reflect import effective_persona
from .scheduler import Scheduler, compute_next

_SEEN_TTL_DAYS = 30

_JOB_DEFAULTS: dict[str, str | int | dict[str, Any]] = {
    "heartbeat": {"every": "hourly"},
    "digest": {"every": "daily", "at": "09:00"},
    "learn": {"every": "daily", "at": "10:00"},
    "ga_snapshot": {"every": "daily", "at": "11:00"},
    "weekly_report": {"every": "weekly", "weekday": "monday", "at": "08:00"},
    "article": {"every": "weekly", "weekday": "tuesday", "at": "09:00"},
    "reflect": {"every": "monthly"},
    "inner_voice": {"every": 2, "at": "14:00"},
    "dream": {"every": 7, "weekday": "sunday", "at": "05:00"},
    "awaken": {"every": 7, "weekday": "sunday", "at": "06:00"},
    "integrate_self": {"every": 2, "at": "20:00"},
    "compact": {"every": 7, "weekday": "sunday", "at": "04:00"},
    "health_check": {"every": "daily", "at": "12:00"},
    "seo_snapshot": {"every": "daily", "at": "11:30"},
    "seo_provisioning": {"every": "6h"},
    "email_provisioning": {"every": "1h"},
    "seo_insight": {"every": 7, "weekday": "monday", "at": "08:45"},
    "reindex_memory": {"every": "daily", "at": "03:30"},
    "strategist": {"every": 7, "weekday": "sunday", "at": "18:00"},
    "backup": {"every": 7, "weekday": "sunday", "at": "03:00"},
    "social_post": {"every": "weekly", "weekday": "thursday", "at": "09:00"},
    "seo_research_cycle": {"every": "daily", "at": "13:00"},
    "seo_outcomes": {"every": "daily", "at": "14:00"},
    "seo_site_report_cycle": {"every": "daily", "at": "13:00"},
    "article_research_cycle": {"every": "daily", "at": "13:30"},
    "growth_reconciler": {"every": "daily", "at": "07:30"},
}


def _spec(config: dict[str, Any], name: str) -> str | int | dict[str, Any]:
    overrides = config.get("schedule") or {}
    return overrides.get(name, _JOB_DEFAULTS[name])


def _seo_provisioning_enabled(config: Mapping[str, Any]) -> bool:
    """Return whether this tenant should receive the default SEO reconciler."""
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    provisioning = seo.get("provisioning") if isinstance(seo, Mapping) else {}
    return bool(
        seo
        and seo.get("enabled") is not False
        and not (isinstance(provisioning, Mapping) and provisioning.get("auto") is False)
    )


def _heartbeat(context: dict[str, Any]) -> None:
    context["memory"].record_observation("self", "heartbeat")


def _effective_source_config(context: dict[str, Any]) -> dict[str, Any]:
    """Use accepted source dispositions when a canonical customer exists."""
    config = context["config"]
    service = context.get("customer_context_service")
    if service is None or service.current() is None:
        return config
    view = service.task_view("research")
    research = view.get("research") if isinstance(view, dict) else {}
    source_rows = research.get("sources") if isinstance(research, dict) else []
    if not isinstance(source_rows, list):
        source_rows = []
    feeds = []
    community_feeds = []
    for source in source_rows:
        if not (
            isinstance(source, dict)
            and not source.get("excluded")
            and str(source.get("trust_state") or "") == "allowed"
            and str(source.get("ongoing_subscription") or "") == "approved"
            and str(source.get("feed_url") or source.get("url") or "").strip()
        ):
            continue
        feed = {
            "name": str(source.get("title") or source.get("source_id") or "approved-source"),
            "url": str(source.get("feed_url") or source.get("url") or ""),
        }
        source_kind = str(source.get("kind") or source.get("source_kind") or source.get("type") or "").lower()
        if source_kind in {"community", "community_feed", "forum", "forum_feed"}:
            community_feeds.append(feed)
        else:
            feeds.append(feed)
    sources = dict(config.get("sources") or {})
    sources["subreddits"] = []
    sources["rss_feeds"] = feeds
    sources["community_feeds"] = community_feeds
    identity = research.get("genesis_identity") if isinstance(research, dict) else {}
    if isinstance(identity, dict) and isinstance(identity.get("subjects"), list):
        sources["keywords"] = [str(item) for item in identity["subjects"] if str(item).strip()]
    return {**config, "sources": sources}


def _with_persona(context: dict[str, Any], fn: Any, task: str = "identity") -> Any:
    context_service = context.get("customer_context_service")
    if context_service is not None and context_service.current() is not None:
        from ..brain.prompts import customer_context_prompt, inner_identity_prompt
        context["persona_prompt"] = inner_identity_prompt(context["config"], context["memory"]) + "\n\n" + customer_context_prompt(
            context_service.task_view(task)
        )
    else:
        context["persona_prompt"] = effective_persona(context["config"], context["memory"])
    return fn(context)


def _with_inner_identity(context: dict[str, Any], fn: Any) -> Any:
    from ..brain.prompts import inner_identity_prompt

    identity = inner_identity_prompt(context["config"], context["memory"])
    context["inner_identity_prompt"] = identity
    context["persona_prompt"] = identity
    return fn(context)


def _editorial_enabled(context: dict[str, Any]) -> bool:
    config = context.get("config", {})
    editorial = config.get("editorial") if isinstance(config, dict) else {}
    configured = bool(isinstance(editorial, dict) and editorial.get("enabled", False))
    return bool(context["memory"].kv_get("editorial_enabled", configured))


def _article(context: dict[str, Any]) -> None:
    if not _editorial_enabled(context):
        context["memory"].record_action("article", "editorial publishing is not enabled")
        return
    article_research = ((context.get("config", {}).get("seo") or {}).get("article_research") or {})
    if article_research.get("enabled"):
        if context.get("crawlseo_service"):
            _with_persona(context, brain_article_research.select_and_request, "editorial")
            return
        # Research-dependent content must remain blocked when its required
        # evidence provider is unavailable. Never silently publish a weaker
        # editorial substitute under the same growth workflow.
        context["memory"].record_action(
            "article_research",
            "blocked: CrawlSEO provider is unavailable; no research-dependent article was drafted",
        )
        return
    draft_id = _with_persona(context, brain_article.draft_article, "editorial")
    if isinstance(draft_id, int):
        try:
            _mirror_article_draft_to_workspace(context, draft_id)
            _sync_strategy_initiative_for_draft(context["memory"], draft_id)
        except Exception as exc:  # noqa: BLE001 - expose the canonical content boundary
            _mark_article_payload_blocked(context["memory"], draft_id, str(exc))


def _mirror_article_drafts(context: dict[str, Any]) -> None:
    """Mirror every article into the canonical Payload draft surface.

    A local ledger row is not a publishable article for a Payload tenant. If
    the canonical draft cannot be prepared, retain the copy for diagnostics but
    mark the owner review as blocked instead of presenting a hidden fallback.
    """
    memory = context["memory"]
    for draft in memory.list_drafts(limit=100):
        if draft.get("kind") != "article" or draft.get("status") != "pending":
            continue
        try:
            _mirror_article_draft_to_workspace(context, int(draft["id"]))
            _sync_strategy_initiative_for_draft(memory, int(draft["id"]))
        except Exception as exc:  # noqa: BLE001 - persist a precise blocked state, never a local ready fallback
            _mark_article_payload_blocked(memory, int(draft["id"]), str(exc))


def _sync_strategy_initiative_for_draft(memory: Memory, draft_id: int) -> None:
    """Move a strategy candidate only after the canonical Payload check passes."""

    draft = next((row for row in memory.list_drafts(limit=200) if int(row.get("id") or 0) == draft_id), None)
    if not draft:
        return
    meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
    sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
    validation = sync.get("validation") if isinstance(sync.get("validation"), Mapping) else {}
    state = (
        "ready_for_review"
        if sync.get("state") == "ready_for_review" and validation.get("status") == "passed"
        else "blocked"
        if validation.get("status") == "blocked"
        else "validating"
    )
    candidate = {
        "draft_id": draft_id,
        "title": draft.get("title"),
        "body": draft.get("body"),
        "meta": {key: value for key, value in meta.items() if key != "review_package_hash"},
        "payload_document": sync.get("document_id"),
        "payload_slug": sync.get("slug"),
        "validation": dict(validation),
    }
    candidate_hash = canonical_hash(candidate)
    review_package_hash = canonical_hash({"candidate": candidate_hash, "payload": sync, "validation": validation})
    if meta.get("review_package_hash") != review_package_hash:
        updated_meta = dict(meta)
        updated_meta["review_package_hash"] = review_package_hash
        memory.update_draft_meta(draft_id, updated_meta)
    validation_manifest = {
        "status": validation.get("status") or "blocked",
        "checks": validation.get("checks") or {},
        "validator": "payload-article-sync-v1",
        "candidateHash": candidate_hash,
        "reviewPackageHash": review_package_hash,
    }
    for initiative in memory.list_strategy_initiatives(limit=500):
        if int(initiative.get("draft_id") or 0) == draft_id and initiative.get("state") in {"preparing", "validating", "ready_for_review"}:
            initiative_id = int(initiative["id"])
            memory.update_strategy_initiative(
                initiative_id,
                candidate_hash=candidate_hash,
                review_package_hash=review_package_hash,
                validation=validation_manifest,
            )
            if initiative.get("state") != state:
                memory.transition_strategy_initiative(initiative_id, state, validation=validation_manifest)


def _article_slug(title: str, draft_id: int) -> str:
    normalized = unicodedata.normalize("NFKD", str(title or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:100]
    return slug or f"ada-article-{draft_id}"





def _mark_article_payload_blocked(memory: Memory, draft_id: int, reason: str) -> None:
    draft = next((item for item in memory.list_drafts(limit=100) if int(item.get("id") or 0) == int(draft_id)), None)
    if not draft:
        return
    meta = dict(draft.get("meta") or {}) if isinstance(draft.get("meta"), Mapping) else {}
    previous_sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
    meta["payload_sync"] = {
        **previous_sync,
        "state": "blocked",
        "validation": {"status": "blocked", "reason": str(reason or "Payload article preparation failed")[:500]},
    }
    memory.update_draft_meta(int(draft_id), meta)
    for action in memory.list_owner_actions(states=("open", "started"), limit=500):
        if action.draft_id == int(draft_id):
            memory.transition_owner_action(action.id, ActionState.WAITING)
    memory.record_action("article", f"draft #{draft_id} blocked: {str(reason or 'Payload article preparation failed')[:240]}")


def _article_image_preview(value: Any) -> dict[str, Any] | None:
    """Keep only safe, owner-visible fields from Payload's main image relation."""
    if isinstance(value, Mapping):
        image = value.get("value") if isinstance(value.get("value"), Mapping) else value
        raw_url = str(image.get("url") or "").strip()
        safe_url = raw_url if (raw_url.startswith("/") and not raw_url.startswith("//")) or raw_url.startswith("https://") else ""
        preview = {
            key: image[key]
            for key in ("id", "alt", "filename", "width", "height")
            if image.get(key) is not None and isinstance(image.get(key), (str, int, float))
        }
        if safe_url:
            preview["url"] = safe_url
        return preview
    if isinstance(value, (str, int)) and str(value).strip():
        return {"id": str(value)}
    return None


def _mirror_article_draft_to_workspace(context: dict[str, Any], draft_id: int) -> None:
    """Put one Ada article into Payload and validate the returned draft."""
    payload = context.get("payload_gateway")
    if payload is None:
        raise RuntimeError("Payload gateway is required to prepare an editorial draft")
    memory = context["memory"]
    draft = next((item for item in memory.list_drafts(limit=100) if int(item.get("id") or 0) == draft_id), None)
    if not draft:
        raise RuntimeError(f"editorial draft #{draft_id} is missing from the owner review ledger")
    title = str(draft.get("title") or "Ada draft").strip()[:300]
    slug = _article_slug(title, draft_id)
    site = context.get("config", {}).get("site") or {}
    site_url = str(site.get("url") or site.get("preview_url") or "").rstrip("/")
    authoring_contract = payload.require_authoring_contract()
    enabled_locales = authoring_contract.get("locales")
    language = str(authoring_contract.get("defaultLocale") or "").strip()
    if not language or not isinstance(enabled_locales, list) or language not in enabled_locales:
        raise RuntimeError("The canonical Payload authoring contract has no enabled default locale")
    # Payload owns the immutable source identity. The shared schema derives it
    # as `posts:<slug>` in its collection hook; sourceId is deliberately not an
    # Ada-editable authoring field and must never be required from that contract.
    source_id = f"posts:{slug}"
    body = str(draft.get("body") or "")
    if not body.strip():
        raise RuntimeError("The article draft has no body to sync into Payload")
    lexical_body = markdown_to_lexical(body)
    plain = lexical_text(lexical_body)
    summary = plain[:500]
    meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
    research_note = meta.get("research_note") if isinstance(meta.get("research_note"), Mapping) else {}
    primary_keyword = str(meta.get("primary_keyword") or research_note.get("selected_query") or "").strip()[:200]
    description = str(meta.get("meta_description") or plain).strip()[:320]
    enabled_collections = (authoring_contract.get("enabled") or {}).get("collections")
    if not isinstance(enabled_collections, list) or "posts" not in enabled_collections:
        raise RuntimeError("The canonical Payload authoring contract does not enable the posts collection")
    contract_fields = set(payload.authoring_fields("collection", "posts", authoring_contract=authoring_contract))
    required_fields = {"slug", "title", "summary", "body", "seo"}
    missing_contract = sorted(required_fields - set(contract_fields))
    if missing_contract:
        raise RuntimeError("Payload posts contract is missing required fields: " + ", ".join(missing_contract))
    seo = {"title": title[:300], "description": description}
    if primary_keyword:
        seo["focusKeyword"] = primary_keyword
    candidate = {
        "slug": slug,
        "title": title,
        "summary": summary,
        "body": lexical_body,
        "seo": seo,
        "canonicalUrl": f"{site_url}/post/{slug}" if site_url else f"/post/{slug}",
        "modifiedAt": str(draft.get("updated_ts") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")),
        "author": str((context.get("config", {}).get("persona") or {}).get("name") or "Ada"),
        "published": False,
    }
    image_id = meta.get("featuredImage") or meta.get("featured_image_id") or meta.get("featured_image")
    if image_id is not None and "featuredImage" in contract_fields:
        candidate["featuredImage"] = image_id
    if meta.get("media_asset_ids") and "gallery" in contract_fields:
        candidate["gallery"] = list(meta["media_asset_ids"])
    post = {key: value for key, value in candidate.items() if key in contract_fields}
    previous_sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
    source_content_hash = canonical_hash({"locale": language, "post": {key: value for key, value in post.items() if key != "modifiedAt"}})
    modified_at = (
        str(previous_sync.get("modified_at") or "")
        if previous_sync.get("source_content_hash") == source_content_hash
        else str(draft.get("updated_ts") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    )
    if "modifiedAt" in post:
        post["modifiedAt"] = modified_at
    source_hash = canonical_hash({"locale": language, "post": post})
    existing = next(
        (item for item in payload.list("posts", draft=True, limit=100) if str(item.get("sourceId") or "") == source_id),
        None,
    )
    if existing and existing.get("id") is not None:
        document_id = str(existing["id"])
        if str(previous_sync.get("document_id") or "") != document_id:
            raise RuntimeError("An existing Payload post is not linked to Ada's exact sync record; it must be reviewed before any update.")
        current = payload.read("posts", identifier=document_id, identifier_kind="id", draft=True, locale=language)
        current_revision = str(current.get("_helloadaRevision") or "")
        if not current_revision or str(previous_sync.get("draft_hash") or "") != current_revision:
            raise RuntimeError("The Payload article draft changed after Ada's last sync; it must be reconciled before approval.")
        if str(previous_sync.get("source_hash") or "") == source_hash:
            document = current
        else:
            document = payload.update(
                "posts", document_id, post, locale=language,
                expected_hash=current_revision,
            )
    elif previous_sync.get("document_id"):
        raise RuntimeError("The previously linked Payload article is missing; Ada must reconcile it before creating another post.")
    else:
        document = payload.create("posts", post, locale=language)
    document_id = str(document.get("id") or "").strip()
    if not document_id:
        raise RuntimeError("Payload did not return the article draft identifier")
    verified = payload.read("posts", identifier=document_id, identifier_kind="id", draft=True, locale=language)
    verified_seo = verified.get("seo") if isinstance(verified.get("seo"), Mapping) else {}
    metadata_value = verified_seo.get("description")
    checks = {
        "document": bool(verified.get("id")),
        "identity": str(verified.get("sourceId") or "") == source_id,
        "slug": str(verified.get("slug") or "") == slug,
        "title": str(verified.get("title") or "").strip() == title,
        "summary": str(verified.get("summary") or "").strip() == summary,
        "body": lexical_text(verified.get("body")) == plain,
        "metadata": str(metadata_value or "").strip() == description,
        "mainImage": bool(verified.get("featuredImage")) if image_id is not None else True,
    }
    state = "ready_for_review" if all(checks.values()) else "blocked"
    reason = "" if state == "ready_for_review" else "Payload article validation is incomplete: " + ", ".join(key for key, passed in checks.items() if not passed)
    next_meta = dict(meta)
    next_meta.update({
        "payload_sync": {
            "state": state,
            "collection": "posts",
            "document_id": document_id,
            "draft_hash": str(verified.get("_helloadaRevision") or ""),
            "source_hash": source_hash,
            "source_content_hash": source_content_hash,
            "modified_at": modified_at,
            "source_id": source_id,
            "slug": slug,
            "locale": language,
            "excerpt": str(verified.get("summary") or "").strip()[:500],
            "meta_description": str(metadata_value or "").strip()[:320],
            "primary_keyword": primary_keyword,
            "featured_image": _article_image_preview(verified.get("featuredImage")),
            "validation": {"status": "passed" if state == "ready_for_review" else "blocked", "checks": checks, "reason": reason},
        },
        "payload_post_id": document_id,
        "payload_source_id": source_id,
        "payload_slug": slug,
    })
    memory.update_draft_meta(draft_id, next_meta)
    memory.record_action(
        "article",
        f"draft #{draft_id} mirrored to the Payload blog as a {state.replace('_', ' ')} draft",
    )


def _prune_seen(seen: dict[str, float], now: float) -> dict[str, float]:
    cutoff = now - _SEEN_TTL_DAYS * 86400
    return {key: stamp for key, stamp in seen.items() if stamp >= cutoff}


def _digest(context: dict[str, Any]) -> None:
    config = _effective_source_config(context)
    memory: Memory = context["memory"]
    sources = config.get("sources") or {}
    items = collect(config, max_total=int(sources.get("max_per_run", 25)))
    min_score = float(sources.get("min_score", 0.0))
    seen = _prune_seen(memory.kv_get("seen_items", {}), time.time())
    recorded = 0
    skipped_errors = 0
    for item in items:
        if item.source == "error":
            skipped_errors += 1
            continue
        if item.score < min_score:
            continue
        if item.identity_keys & set(seen):
            continue
        memory.record_observation(
            item.source,
            f"{item.title}. {item.clean_summary}".strip(),
            meta={"link": item.link, "score": round(item.score, 3), "matched": item.matched},
        )
        seen.update({key: time.time() for key in item.identity_keys})
        recorded += 1
    memory.kv_set("seen_items", seen)
    detail = f"{recorded} new ({skipped_errors} feed errors)" if skipped_errors else f"{recorded} new"
    memory.record_action("digest", detail)


def _seo_insight(context: dict[str, Any]) -> None:
    """Write one owner-facing synthesis from the tenant's own SEO evidence."""
    config = context.get("config") or {}
    enabled = bool((config.get("seo") or {}).get("enabled") or (config.get("ga") or {}).get("enabled"))
    if not enabled:
        return
    from ..brain.seo_insights import generate as generate_seo_insight

    _with_persona(context, generate_seo_insight, "editorial")


def _ga_snapshot(context: dict[str, Any]) -> None:
    from ..senses import ga as ga_sense

    config = context["config"]
    memory: Memory = context["memory"]
    if not (config.get("ga") or {}).get("enabled"):
        return
    if str((config.get("ga") or {}).get("source", "ga4")).lower() == "crawlseo":
        summary = ga_sense.weekly_summary(config, crawlseo_service=context.get("crawlseo_service"))
    else:
        summary = ga_sense.weekly_summary(config)
    memory.snapshot_metrics("ga4", summary)
    # Growth reads the tenant's durable Memory history through the workspace
    # API. Payload owns website content, not a second analytics database.


def _seo_snapshot(context: dict[str, Any]) -> None:
    from ..senses import seo as seo_sense

    config = context["config"]
    memory: Memory = context["memory"]
    if not (config.get("seo") or {}).get("enabled"):
        return
    if str((config.get("seo") or {}).get("source", "gsc")).lower() == "crawlseo":
        summary = seo_sense.summary(config, crawlseo_service=context.get("crawlseo_service"))
    else:
        summary = seo_sense.summary(config)
    memory.snapshot_metrics("gsc", summary)


def _seo_provisioning(context: dict[str, Any]) -> None:
    """Retry the automatic tenant bootstrap and attach a newly issued client."""
    from ..application.seo_bootstrap import auto_provision_seo

    tenant_id = str(context.get("tenant_id") or context["config"].get("instance_name") or "")
    state, env = auto_provision_seo(
        context["config"],
        tenant_id=tenant_id,
        memory=context["memory"],
        env=context.get("env"),
    )
    runtime = context.get("runtime")
    if runtime is not None and state.get("state") == "ready":
        service = runtime.refresh_crawlseo(env)
        context["env"] = env
        context["crawlseo_client"] = runtime.crawlseo_client
        context["crawlseo_service"] = service
    context["seo_provisioning_state"] = state


def _email_provisioning_enabled(config: Mapping[str, Any]) -> bool:
    messages = config.get("messages") if isinstance(config.get("messages"), Mapping) else {}
    email = messages.get("email") if isinstance(messages, Mapping) else {}
    provisioning = email.get("provisioning") if isinstance(email, Mapping) else {}
    return bool(
        isinstance(email, Mapping)
        and email.get("enabled") is True
        and isinstance(provisioning, Mapping)
        and provisioning.get("auto") is True
    )


def _email_provisioning(context: dict[str, Any]) -> dict[str, str]:
    """Retry tenant email setup after a newly released Worker becomes ready."""
    from ..application.email_bootstrap import auto_provision_email

    tenant_id = str(context.get("tenant_id") or context["config"].get("instance_name") or "")
    state, env = auto_provision_email(
        context["config"],
        tenant_id=tenant_id,
        tenant_config_path=context["tenant_config_path"],
        memory=context["memory"],
        env=context.get("env"),
    )
    context["email_provisioning_state"] = state
    context["env"] = env
    if state.get("state") == "failed":
        raise RuntimeError(str(state.get("error") or "email provisioning failed")[:300])
    return {"status": "pending" if state.get("state") in {"domain_required", "waiting_for_worker_release"} else "ok"}


def register_email_provisioning_job(
    scheduler: Scheduler,
    config: Mapping[str, Any],
    context: dict[str, Any],
    schedule: str | int | dict[str, Any] | None = None,
) -> bool:
    """Register tenant email setup and persist its initial due time if absent."""
    if not _email_provisioning_enabled(config):
        return False
    if any(name == "email_provisioning" for name, _spec, _fn in scheduler.jobs):
        return True
    scheduler.job(
        "email_provisioning",
        schedule if schedule is not None else _JOB_DEFAULTS["email_provisioning"],
        lambda: _email_provisioning(context),
    )
    next_run_key = "next_run:email_provisioning"
    next_run = scheduler.memory.kv_get(next_run_key)
    last_run = scheduler.memory.kv_get("last_run:email_provisioning")
    state = scheduler.memory.kv_get("email_provisioning_state", {})
    needs_initial_run = (
        last_run is None
        and not (isinstance(state, Mapping) and state.get("state") == "active")
    )
    if not isinstance(next_run, (int, float)) or needs_initial_run:
        scheduler.memory.kv_set(next_run_key, round(scheduler.clock(), 3))
    return True


def _strategist(context: dict[str, Any]) -> None:
    from ..brain.strategist import run as strategist_run

    _with_persona(context, strategist_run, "strategy")


def _seo_research_cycle(context: dict[str, Any]) -> None:
    brain_seo.run(context)


def _seo_site_report_cycle(context: dict[str, Any]) -> None:
    brain_monthly_seo_report.run(context)


def _article_research_cycle(context: dict[str, Any]) -> None:
    # Reconciliation culminates in a reader-facing article, so it needs the
    # complete editorial/business context as well as the research evidence.
    _with_persona(context, brain_article_research.reconcile, "article_research")
    _mirror_article_drafts(context)


def _has_recoverable_article_sync(memory: Memory) -> bool:
    """Wake only pending articles blocked by a now-corrected shared contract."""
    for draft in memory.list_drafts(limit=None):
        if draft.get("kind") != "article" or draft.get("status") != "pending":
            continue
        meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
        sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
        validation = sync.get("validation") if isinstance(sync.get("validation"), Mapping) else {}
        reason = str(validation.get("reason") or "").lower()
        source_identity_contract = reason == "payload posts contract is missing required fields: sourceid"
        disabled_site_locale = "requested locale" in reason and "not enabled for this website" in reason
        if (
            sync.get("state") == "blocked"
            and validation.get("status") == "blocked"
            and (source_identity_contract or disabled_site_locale)
        ):
            return True
    return False


def _wake_persisted_job(scheduler: Scheduler, name: str) -> None:
    """Make an exact, safely recoverable persisted job due on activation."""
    key = f"next_run:{name}"
    next_run = scheduler.memory.kv_get(key)
    now = round(scheduler.clock(), 3)
    if isinstance(next_run, (int, float)) and next_run > now:
        scheduler.memory.kv_set(key, now)


def register_growth_jobs(scheduler: Scheduler, config: dict[str, Any], context: dict[str, Any]) -> bool:
    """Both runtime entry points consume this one production growth contract."""
    site = config.get("site") or {}
    if not (site.get("website_present") and (site.get("payload") or {}).get("enabled")):
        return False
    settings = config.get("scheduler") or {}
    overrides = settings.get("schedule") or {}
    register_email_provisioning_job(
        scheduler,
        config,
        context,
        overrides.get("email_provisioning", _JOB_DEFAULTS["email_provisioning"]),
    )
    growth_policy = config.get("growth") or {}
    if growth_policy.get("enabled", True) is False:
        return True  # Email bootstrap remains operational when Growth is explicitly paused.
    schedules = {
        "growth_initial": {"every": "daily", "at": "07:00"},
        "growth_daily": {"every": "daily", "at": "07:30"},
        "growth_weekly": {"every": "weekly", "weekday": "monday", "at": "08:30"},
        "growth_monthly": {"every": "monthly", "day": 1, "at": "09:00"},
        "growth_pending": {"every": "1h"},
        "growth_article_sync": {"every": "1h"},
    }
    for name, spec in schedules.items():
        if name == "growth_pending":
            # Scheduled tenant execution owns scheduler.lock; only this
            # exclusive path may reclaim a lease left by a dead API process.
            operation = lambda: run_pending_growth(context, recover_interrupted_runs=True)
        elif name == "growth_article_sync":
            operation = lambda: _mirror_article_drafts(context)
        else:
            trigger = name.removeprefix("growth_")
            operation = lambda trigger=trigger: run_growth_cycle(context, trigger=trigger)
        scheduler.job(name, overrides.get(name, spec), operation)
        # Run initial review and reconciliation once on activation; subsequent
        # strategy work follows its real calendar slot without catch-up runs.
        if scheduler.memory.kv_get(f"next_run:{name}") is None:
            next_run = scheduler.clock() if name in {"growth_initial", "growth_pending", "growth_article_sync"} else compute_next(scheduler.jobs[-1][1], scheduler.clock(), timezone_name=scheduler.timezone_name)
            scheduler.memory.kv_set(f"next_run:{name}", next_run)
        if name == "growth_pending" and has_recoverable_growth_replay(scheduler.memory):
            _wake_persisted_job(scheduler, name)
        elif name == "growth_article_sync" and _has_recoverable_article_sync(scheduler.memory):
            _wake_persisted_job(scheduler, name)
    # These are independent maintenance/measurement operations, not competing
    # recommendation producers. Inventory failure must not stop either one.
    maintenance = []
    if _seo_provisioning_enabled(config):
        maintenance.append(("seo_provisioning", {"every": "6h"}, lambda: _seo_provisioning(context)))
    if context.get("llm") is not None:
        maintenance.append(("seo_outcomes", {"every": "daily", "at": "13:00"}, lambda: _with_persona(context, brain_seo_outcomes.run, "seo_outcomes")))
    for name, spec, operation in maintenance:
        scheduler.job(name, overrides.get(name, spec), operation)
        if scheduler.memory.kv_get(f"next_run:{name}") is None:
            scheduler.memory.kv_set(f"next_run:{name}", compute_next(scheduler.jobs[-1][1], scheduler.clock(), timezone_name=scheduler.timezone_name))
    return True


def register_jobs(scheduler: Scheduler, config: dict[str, Any], context: dict[str, Any]) -> None:
    """Register Ada's reusable reading/editorial loop for a shared tenant API.

    The normal CLI activation path already calls :func:`register_builtin`. The
    shared tenant API deliberately keeps tenant activation separate, so it
    uses this small selection of the same digest, learning, and article jobs
    instead of silently dropping Ada's original news loop.
    """
    if register_growth_jobs(scheduler, config, context):
        return
    settings = config.get("scheduler") or {}
    if not isinstance(settings, dict):
        settings = {}
    schedule = settings.get("schedule") if isinstance(settings.get("schedule"), dict) else {}
    register_email_provisioning_job(
        scheduler, config, context, schedule.get("email_provisioning", _JOB_DEFAULTS["email_provisioning"])
    )
    if not bool(settings.get("enabled", False)):
        return
    scheduler.job(
        "growth_reconciler",
        schedule.get("growth_reconciler", _JOB_DEFAULTS["growth_reconciler"]),
        lambda: run_growth_reconciler(context),
    )
    sources = (_effective_source_config(context).get("sources") or {})
    has_sources = bool(sources.get("subreddits") or sources.get("rss_feeds") or sources.get("community_feeds"))
    if has_sources:
        scheduler.job("digest", schedule.get("digest", {"every": "weekly", "weekday": "monday", "at": "08:00"}), lambda: _digest(context))
    if context.get("llm") and (has_sources or bool(settings.get("learning_enabled", False))):
        scheduler.job("learn", schedule.get("learn", {"every": "weekly", "weekday": "monday", "at": "08:20"}), lambda: _with_persona(context, brain_digest.learn, "research"))
    article_research_enabled = bool(((config.get("seo") or {}).get("article_research") or {}).get("enabled", False))
    seo_config = config.get("seo") if isinstance(config.get("seo"), dict) else {}
    seo_enabled = bool(seo_config.get("enabled") or (config.get("ga") or {}).get("enabled"))
    if _seo_provisioning_enabled(config):
        scheduler.job(
            "seo_provisioning",
            schedule.get("seo_provisioning", {"every": "6h"}),
            lambda: _seo_provisioning(context),
        )
    if context.get("payload_gateway") is not None:
        _mirror_article_drafts(context)
    if seo_enabled:
        scheduler.job(
            "ga_snapshot",
            schedule.get("ga_snapshot", {"every": "daily", "at": "11:00"}),
            lambda: _ga_snapshot(context),
        )
        scheduler.job(
            "seo_snapshot",
            schedule.get("seo_snapshot", {"every": "daily", "at": "11:30"}),
            lambda: _seo_snapshot(context),
        )
    if context.get("llm") and (bool((config.get("editorial") or {}).get("enabled", False)) or article_research_enabled):
        scheduler.job("article", schedule.get("article", {"every": "weekly", "weekday": "tuesday", "at": "09:00"}), lambda: _article(context))
    if context.get("llm") and seo_enabled:
        scheduler.job(
            "seo_insight",
            schedule.get("seo_insight", {"every": 7}),
            lambda: _seo_insight(context),
        )
    if context.get("llm") and article_research_enabled and context.get("crawlseo_service"):
        # Selection and reconciliation are two stages of one paid flow: the
        # weekly article job requests the overview, this daily job adopts the
        # result, requests one SERP, and drafts.
        scheduler.job(
            "article_research_cycle",
            schedule.get("article_research_cycle", {"every": "daily", "at": "13:30"}),
            lambda: _article_research_cycle(context),
        )
    if seo_enabled:
        scheduler.job(
            "seo_outcomes",
            schedule.get("seo_outcomes", _JOB_DEFAULTS["seo_outcomes"]),
            lambda: brain_seo_outcomes.run(context),
        )
    intake = context.get("intake_coordinator")
    if intake is not None and bool(getattr(intake, "research_enabled", False)):
        scheduler.job(
            "research_recovery",
            schedule.get("research_recovery", {"every": "daily", "at": "08:40"}),
            intake.recover_research_after_restart,
        )
    if context.get("llm") and bool(settings.get("weekly_report", False)):
        scheduler.job("weekly_report", schedule.get("weekly_report", {"every": "weekly", "weekday": "monday", "at": "09:00"}), lambda: _with_persona(context, brain_report.weekly_report, "strategy"))
    scheduler.job("health_check", schedule.get("health_check", {"every": "daily", "at": "12:00"}), lambda: maintenance.health_check(context))
    scheduler.job("reindex_memory", schedule.get("reindex_memory", {"every": "daily", "at": "03:30"}), lambda: _reindex_memory(context))


def _social_post(context: dict[str, Any]) -> None:
    """Prepare at most one owner-reviewable social post per scheduled run."""
    config = context["config"]
    memory: Memory = context["memory"]
    social_config = config.get("social") or {}
    try:
        max_pending = max(1, int(social_config.get("max_pending", 2)))
    except (TypeError, ValueError):
        max_pending = 2
    pending = 0
    for approval in memory.list_approval_requests(status=ApprovalStatus.PENDING, limit=500):
        artifact = memory.get_artifact(approval.artifact_id)
        if artifact is not None and artifact.kind is ArtifactKind.SOCIAL_POST:
            pending += 1
    if pending >= max_pending:
        memory.record_action("social_post", f"skipped: {pending} pending approval(s) reaches max_pending={max_pending}")
        return
    result = _with_persona(context, brain_social.run, "editorial")
    memory.record_action("social_post", f"queued owner review for approval #{result.approval.approval_id}")


def _reindex_memory(context: dict[str, Any]) -> None:
    from .memory_store import index_count, reindex as index_observations

    memory = context["memory"]
    added = index_observations(memory)
    detail = f"{added} new memories indexed" if added else "no new memories"
    memory.record_action("memory_index", detail + f" (total {index_count(memory)})")


def register_builtin(scheduler: Scheduler, config: dict[str, Any], context: dict[str, Any]) -> None:
    if register_growth_jobs(scheduler, config, context):
        scheduler.job("health_check", _spec(config, "health_check"), lambda: maintenance.health_check(context))
        scheduler.job("backup", _spec(config, "backup"), lambda: maintenance.backup_data(context))
        return
    register_email_provisioning_job(scheduler, config, context, _spec(config, "email_provisioning"))
    scheduler.job("heartbeat", _spec(config, "heartbeat"), lambda: _heartbeat(context))
    scheduler.job("growth_reconciler", _spec(config, "growth_reconciler"), lambda: run_growth_reconciler(context))
    scheduler.job("health_check", _spec(config, "health_check"), lambda: maintenance.health_check(context))
    sources = (_effective_source_config(context).get("sources") or {})
    if sources.get("subreddits") or sources.get("rss_feeds") or sources.get("community_feeds"):
        scheduler.job("digest", _spec(config, "digest"), lambda: _digest(context))
    if context.get("llm"):
        scheduler.job("learn", _spec(config, "learn"), lambda: _with_persona(context, brain_digest.learn, "research"))
        scheduler.job(
            "weekly_report", _spec(config, "weekly_report"), lambda: _with_persona(context, brain_report.weekly_report, "strategy")
        )
        scheduler.job("article", _spec(config, "article"), lambda: _article(context))
        scheduler.job("reflect", _spec(config, "reflect"), lambda: _with_persona(context, reflect_job))
        scheduler.job("strategist", _spec(config, "strategist"), lambda: _strategist(context))
        social_config = config.get("social") or {}
        if social_config.get("enabled") and context.get("social_post_service"):
            scheduler.job("social_post", _spec(config, "social_post"), lambda: _social_post(context))
        scheduler.job("inner_voice", _spec(config, "inner_voice"), lambda: _with_inner_identity(context, brain_inner_voice.think))
        dream_enabled = (config.get("dream") or {}).get("enabled", True)
        if dream_enabled:
            scheduler.job("dream", _spec(config, "dream"), lambda: _with_inner_identity(context, brain_dream.dream))
            scheduler.job("awaken", _spec(config, "awaken"), lambda: _with_inner_identity(context, brain_dream.awaken))
        if (config.get("self_model") or {}).get("enabled", True):
            scheduler.job("integrate_self", _spec(config, "integrate_self"), lambda: _with_inner_identity(context, brain_self_model.integrate))
        scheduler.job("compact", _spec(config, "compact"), lambda: maintenance.compact_memory(context))
    scheduler.job("ga_snapshot", _spec(config, "ga_snapshot"), lambda: _ga_snapshot(context))
    scheduler.job("seo_snapshot", _spec(config, "seo_snapshot"), lambda: _seo_snapshot(context))
    if context.get("llm"):
        scheduler.job("seo_insight", _spec(config, "seo_insight"), lambda: _seo_insight(context))
    research_config = ((config.get("seo") or {}).get("research") or {})
    site_report_config = ((config.get("seo") or {}).get("site_report") or {})
    article_research_config = ((config.get("seo") or {}).get("article_research") or {})
    if site_report_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("seo_site_report_cycle", _spec(config, "seo_site_report_cycle"), lambda: _seo_site_report_cycle(context))
    if article_research_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("article_research_cycle", _spec(config, "article_research_cycle"), lambda: _article_research_cycle(context))
    if research_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("seo_research_cycle", _spec(config, "seo_research_cycle"), lambda: _seo_research_cycle(context))
    if research_config.get("enabled") or site_report_config.get("enabled") or article_research_config.get("enabled") or bool((config.get("seo") or {}).get("enabled") or (config.get("ga") or {}).get("enabled")):
        scheduler.job("seo_outcomes", _spec(config, "seo_outcomes"), lambda: brain_seo_outcomes.run(context))
    if _seo_provisioning_enabled(config):
        scheduler.job("seo_provisioning", _spec(config, "seo_provisioning"), lambda: _seo_provisioning(context))
    scheduler.job("reindex_memory", _spec(config, "reindex_memory"), lambda: _reindex_memory(context))
    scheduler.job("backup", _spec(config, "backup"), lambda: maintenance.backup_data(context))


def reflect_job(context: dict[str, Any]) -> None:
    from .reflect import reflect

    reflect(context)
