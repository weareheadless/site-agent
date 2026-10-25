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
import json
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
from ..config import crawlseo_research_authority_selected
from .article_routes import public_article_path
from ..application.growth_workflow import (
    _crawlseo_authoritative,
    has_recoverable_growth_replay,
    has_recoverable_historical_noop,
    run_growth_reconciler,
    run_growth_cycle,
    run_pending_growth,
)
from ..senses import collect
from . import maintenance
from .contracts import ActionState, ApprovalStatus, ArtifactKind
from .llm import extract_json
from .payload_rich_text import lexical_text, markdown_to_lexical
from .design_contracts import canonical_hash
from .memory import Memory
from .research_authority import producer_frozen
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
    if _crawlseo_authoritative(context.get("config") or {}):
        context["memory"].record_action(
            "article",
            "local article workflow is disabled while CrawlSEO is the research authority",
        )
        return
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
            if _mirror_article_draft_to_workspace(context, draft_id) is False:
                return
            _sync_strategy_initiative_for_draft(context["memory"], draft_id, context=context)
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
            if _mirror_article_draft_to_workspace(context, int(draft["id"])) is False:
                continue
            _sync_strategy_initiative_for_draft(memory, int(draft["id"]), context=context)
        except Exception as exc:  # noqa: BLE001 - persist a precise blocked state, never a local ready fallback
            _mark_article_payload_blocked(memory, int(draft["id"]), str(exc))


def _sync_strategy_initiative_for_draft(memory: Memory, draft_id: int, *, context: dict[str, Any]) -> None:
    """Move a strategy candidate only after the canonical Payload check passes."""

    with memory.article_draft_lifecycle():
        draft = memory.get_draft(int(draft_id))
        if draft is None or draft.get("status") != "pending":
            return
        _sync_strategy_initiative_for_draft_locked(memory, draft_id, context=context, draft=draft)


def _sync_strategy_initiative_for_draft_locked(
    memory: Memory, draft_id: int, *, context: dict[str, Any], draft: dict[str, Any],
) -> None:

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
            if state == "ready_for_review":
                from ..application.growth_delivery import article_candidate_checkpoint
                from ..application.actions import OwnerActionService
                from ..application.approvals import ApprovalService
                from .contracts import Artifact, ArtifactKind, EffectClass
                current_draft = {**draft, "meta": {**meta, "review_package_hash": review_package_hash}}
                article_candidate_checkpoint(context, initiative, current_draft)
                approval = memory.get_approval_request(int(initiative.get("approval_id") or 0)) if initiative.get("approval_id") else None
                if approval is None or approval.artifact_hash != review_package_hash:
                    artifact = memory.create_artifact(Artifact(
                        kind=ArtifactKind.ARTICLE, title=str(draft.get("title") or "Article"), summary="Exact Payload article candidate",
                        renderer="article", capability_id="growth.publish", provider_id="payload",
                        content_hash=review_package_hash, preview_data={"draftId": draft_id}))
                    approval = ApprovalService(memory, actions=OwnerActionService(memory)).create(artifact,
                        owner_action_label="Publish this exact article", effect_class=EffectClass.SITE_MUTATION)
                    memory.update_strategy_initiative(initiative_id, artifact_id=artifact.artifact_id, approval_id=approval.approval_id)
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
    with memory.article_draft_lifecycle():
        draft = memory.get_draft(int(draft_id))
        if not draft or draft.get("status") != "pending":
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


def _payload_relation_id(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("value", value)
        if isinstance(value, Mapping):
            value = value.get("id")
    return str(value).strip() if value is not None else ""


def _payload_field_matches(field: str, actual: Any, expected: Any) -> bool:
    if field == "featuredImage":
        return _payload_relation_id(actual) == _payload_relation_id(expected)
    if field == "gallery":
        actual_rows = actual if isinstance(actual, list) else ([] if actual is None else [actual])
        expected_rows = expected if isinstance(expected, list) else ([] if expected is None else [expected])
        return [_payload_relation_id(value) for value in actual_rows] == [
            _payload_relation_id(value) for value in expected_rows
        ]
    if field == "seo":
        return isinstance(actual, Mapping) and isinstance(expected, Mapping) and all(
            canonical_hash(actual.get(key)) == canonical_hash(value)
            for key, value in expected.items()
        )
    return canonical_hash(actual) == canonical_hash(expected)


def _payload_value_is_empty(value: Any) -> bool:
    """Ignore Lexical's structural metadata while detecting truly empty content."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return all(_payload_value_is_empty(item) for item in value)
    if isinstance(value, Mapping):
        structural = {
            "type", "version", "direction", "format", "indent", "detail",
            "mode", "style", "textFormat", "textStyle", "listType", "tag",
        }
        return all(
            str(key) in structural or _payload_value_is_empty(item)
            for key, item in value.items()
        )
    return False


def _is_empty_unlinked_article_draft(
    document: Mapping[str, Any],
    post: Mapping[str, Any],
    source_id: str,
) -> bool:
    """Recognize only a versioned, content-empty Payload shell at the exact route."""
    revision = str(document.get("_helloadaRevision") or "")
    if (
        not str(document.get("id") or "").strip()
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", revision)
        or str(document.get("sourceId") or "").strip() != source_id
        or str(document.get("slug") or "") != str(post.get("slug") or "")
        or str(document.get("_status") or "") != "draft"
        or not _payload_value_is_empty(document.get("publishedAt"))
    ):
        return False
    owner_content_fields = (
        "title", "summary", "sections", "body", "seo",
        "featuredImage", "gallery", "author", "category",
    )
    return all(_payload_value_is_empty(document.get(field)) for field in owner_content_fields)


def _is_exact_unlinked_article_draft(document: Mapping[str, Any], post: Mapping[str, Any]) -> bool:
    """Prove an orphaned Payload draft is the exact unpublished Ada candidate."""
    revision = str(document.get("_helloadaRevision") or "")
    if (
        document.get("id") is None
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", revision)
        or not str(document.get("sourceId") or "").strip()
        or document.get("published") is not False
        or str(document.get("slug") or "") != str(post.get("slug") or "")
    ):
        return False
    required_fields = {"slug", "title", "summary", "body", "seo", "published"}
    if not required_fields.issubset(post):
        return False
    system_fields = {"canonicalUrl", "modifiedAt"}
    return all(
        field == "featuredImage" and _payload_value_is_empty(document.get(field))
        or _payload_field_matches(field, document.get(field), expected)
        for field, expected in post.items()
        if field not in system_fields
    )


def _normalized_article_title(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.translate(str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "＇": "'"}))
    return " ".join(normalized.casefold().split())


def _read_article_draft_by_slug(payload: Any, slug: str, language: str) -> dict[str, Any] | None:
    try:
        return payload.read(
            "posts", identifier=slug, identifier_kind="slug", draft=True, locale=language
        )
    except Exception as exc:  # noqa: BLE001 - only an exact not-found permits a create
        if getattr(exc, "status_code", None) == 404:
            return None
        raise


def _article_cover_image(
    context: dict[str, Any],
    payload: Any,
    draft: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Select one analyzed tenant-library image and pin its exact revision."""
    saved = meta.get("article_image_selection")
    saved = saved if isinstance(saved, Mapping) else {}
    explicit_id = (
        saved.get("media_id")
        or meta.get("featuredImage")
        or meta.get("featured_image_id")
        or meta.get("featured_image")
    )
    if explicit_id is not None:
        media = payload.read_media(str(explicit_id), identifier_kind="id", draft=True)
        if saved and str(media.get("_helloadaRevision") or "") != str(saved.get("media_revision") or ""):
            raise RuntimeError("The selected Payload cover image changed after Ada chose it; the article needs a fresh image review.")
        reason = str(saved.get("reason") or "Selected from the tenant's Payload Library for this article.")
        if not saved:
            revision = str(media.get("_helloadaRevision") or "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
                raise RuntimeError("The selected Payload cover image has no exact revision and cannot be attached safely.")
            saved = {
                "media_id": str(explicit_id),
                "media_revision": revision,
                "reason": reason,
            }
            next_meta = dict(meta)
            next_meta["article_image_selection"] = saved
            context["memory"].update_draft_meta(int(draft["id"]), next_meta)
    else:
        assets = payload.list_media(draft=True, limit=100)
        eligible = []
        for asset in assets:
            if not isinstance(asset, Mapping) or str(asset.get("analysisStatus") or "").lower() != "ready":
                continue
            if not str(asset.get("id") or "").strip() or not str(asset.get("sourceId") or "").strip():
                continue
            if not str(asset.get("alt") or "").strip():
                continue
            image_url = str(asset.get("url") or asset.get("originalUrl") or "").strip()
            if not (image_url.startswith("https://") or image_url.startswith("/") and not image_url.startswith("//")):
                continue

            def values(field: str) -> list[str]:
                raw = asset.get(field)
                rows = raw if isinstance(raw, list) else []
                return [
                    str(item.get("value") or "").strip()[:180]
                    for item in rows
                    if isinstance(item, Mapping) and str(item.get("value") or "").strip()
                ][:8]

            eligible.append({
                "id": str(asset["id"]),
                "alt": str(asset.get("alt") or "")[:300],
                "filename": str(asset.get("filename") or "")[:180],
                "description": str(asset.get("description") or "")[:400],
                "tags": values("tags"),
                "suggested_uses": values("suggestedUses"),
                "source_kind": str(asset.get("sourceKind") or "")[:80],
                "source_url": str(asset.get("sourceUrl") or asset.get("originalUrl") or "")[:500],
            })
        if not eligible:
            raise RuntimeError(
                "Ada cannot prepare this article for review because the Payload Library has no analyzed image with alt text and a public URL. Add and analyze a suitable image in Gallery."
            )
        llm = context.get("llm")
        if llm is None:
            raise RuntimeError("Ada cannot select the article cover because the configured AI service is unavailable.")
        brief = {
            "title": str(draft.get("title") or "")[:300],
            "article": str(draft.get("body") or "")[:1800],
            "keyword": str(meta.get("primary_keyword") or "")[:200],
        }
        raw = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Choose one existing tenant-owned Payload Library image only when its supplied metadata makes it "
                        "a genuinely suitable cover for the article. Do not invent an image, infer unsupported facts, "
                        "or choose a generic logo/decorative asset. If none is suitable, return media_id as null and "
                        "state the exact missing need. Return JSON with media_id and reason."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"article": brief, "available_images": eligible},
                        ensure_ascii=False,
                    ),
                },
            ],
            json_mode=True,
            temperature=0.0,
            max_tokens=500,
        )
        decision = extract_json(raw)
        if not isinstance(decision, Mapping):
            raise RuntimeError("Ada's cover-image selection did not return valid structured data.")
        selected_id = str(decision.get("media_id") or "").strip()
        candidate = next((item for item in eligible if item["id"] == selected_id), None)
        reason = " ".join(str(decision.get("reason") or "").split())[:500]
        if candidate is None or not reason:
            raise RuntimeError(
                "Ada found no suitable analyzed Payload Library image for this article. Add and analyze a relevant image in Gallery."
            )
        media = payload.read_media(selected_id, identifier_kind="id", draft=True)
        saved = {
            "media_id": selected_id,
            "media_revision": str(media.get("_helloadaRevision") or ""),
            "reason": reason,
        }
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", saved["media_revision"]):
            raise RuntimeError("The selected Payload cover image has no exact revision and cannot be attached safely.")
        next_meta = dict(meta)
        next_meta["article_image_selection"] = saved
        context["memory"].update_draft_meta(int(draft["id"]), next_meta)
    alt = str(media.get("alt") or "").strip()
    source_id = str(media.get("sourceId") or "").strip()
    image_url = str(media.get("url") or media.get("originalUrl") or "").strip()
    if (
        not str(media.get("id") or "").strip()
        or str(media.get("analysisStatus") or "").lower() != "ready"
        or not alt
        or not source_id
        or not (image_url.startswith("https://") or image_url.startswith("/") and not image_url.startswith("//"))
    ):
        raise RuntimeError("The selected Payload cover image must have a stable identity, completed analysis, alt text and a public URL.")
    return str(media["id"]), media, {
        **dict(saved),
        "reason": reason,
        "source_id": source_id,
        "alt": alt,
    }


def _mirror_article_draft_to_workspace(context: dict[str, Any], draft_id: int) -> bool:
    """Serialize one external preparation against an operator archive."""
    memory = context["memory"]
    with memory.article_draft_lifecycle():
        draft = memory.get_draft(int(draft_id))
        if draft is None:
            raise RuntimeError(f"editorial draft #{draft_id} is missing from the owner review ledger")
        if draft.get("kind") != "article" or draft.get("status") != "pending":
            return False
        _mirror_article_draft_to_workspace_locked(context, int(draft_id))
    return True


def _mirror_article_draft_to_workspace_locked(context: dict[str, Any], draft_id: int) -> None:
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
    required_fields = {"slug", "title", "summary", "body", "seo", "featuredImage"}
    missing_contract = sorted(required_fields - set(contract_fields))
    if missing_contract:
        raise RuntimeError("Payload posts contract is missing required fields: " + ", ".join(missing_contract))
    seo = {"title": title[:300], "description": description}
    if primary_keyword:
        seo["focusKeyword"] = primary_keyword
    article_path = public_article_path(slug)
    public_base = str(site_url or "").rstrip("/")
    candidate = {
        "slug": slug,
        "title": title,
        "summary": summary,
        "body": lexical_body,
        "seo": seo,
        "canonicalUrl": f"{public_base}{article_path}" if public_base else article_path,
        "modifiedAt": str(draft.get("updated_ts") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")),
        "author": str((context.get("config", {}).get("persona") or {}).get("name") or "Ada"),
        "published": False,
    }
    if meta.get("media_asset_ids") and "gallery" in contract_fields:
        candidate["gallery"] = list(meta["media_asset_ids"])
    post = {key: value for key, value in candidate.items() if key in contract_fields}
    previous_sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
    previous_document_id = str(previous_sync.get("document_id") or "").strip()
    normalized_title = _normalized_article_title(title)
    if normalized_title:
        # A title collision at a different public route needs owner review.
        # Title equality is only a conflict signal; it does not prove that the
        # two articles have interchangeable content.
        listed_drafts = payload.list("posts", draft=True, limit=100, locale=language)
        listed_published = payload.list("posts", draft=False, limit=100, locale=language)
        if not isinstance(listed_drafts, list) or not isinstance(listed_published, list):
            raise RuntimeError("The canonical Payload posts inventory could not be verified before article preparation.")
        if len(listed_drafts) >= 100 or len(listed_published) >= 100:
            raise RuntimeError("The canonical Payload posts inventory is incomplete; article preparation is held for owner review.")
        for document_row in [*listed_drafts, *listed_published]:
            if not isinstance(document_row, Mapping):
                raise RuntimeError("The canonical Payload posts inventory contains an invalid row; article preparation is held for review.")
            row_id = str(document_row.get("id") or "").strip()
            row_slug = str(document_row.get("slug") or "").strip()
            row_title = document_row.get("title")
            if not row_id or not row_slug:
                raise RuntimeError("The canonical Payload posts inventory lacks a stable ID or route; article preparation is held for review.")
            if row_id == previous_document_id or row_slug == slug and not previous_document_id:
                continue
            if not isinstance(row_title, str) or not row_title.strip():
                raise RuntimeError("The canonical Payload posts inventory lacks a locale title; article preparation is held for review.")
            if _normalized_article_title(row_title) != normalized_title:
                continue
            raise RuntimeError(
                "A Payload post with the same normalized title exists at another route; the existing post and this article remain unchanged for owner review."
            )
    route_document: dict[str, Any] | None = None
    if not previous_document_id:
        route_document = _read_article_draft_by_slug(payload, slug, language)
        if route_document is not None and not (
            _is_exact_unlinked_article_draft(route_document, post)
            or _is_empty_unlinked_article_draft(route_document, {"slug": slug}, source_id)
        ):
            raise RuntimeError(
                "An existing Payload post at this route is not linked to Ada's exact sync record; its content differs and it is neither Ada's exact draft nor an empty schema draft, so it remains unchanged for owner review."
            )
    image_id, _selected_media, image_selection = _article_cover_image(context, payload, draft, meta)
    meta = {
        **dict(meta),
        "article_image_selection": {
            "media_id": image_id,
            "media_revision": str(image_selection.get("media_revision") or ""),
            "reason": str(image_selection.get("reason") or ""),
        },
    }
    post["featuredImage"] = image_id
    source_content_hash = canonical_hash({"locale": language, "post": {key: value for key, value in post.items() if key != "modifiedAt"}})
    modified_at = (
        str(previous_sync.get("modified_at") or "")
        if previous_sync.get("source_content_hash") == source_content_hash
        else str(draft.get("updated_ts") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    )
    if "modifiedAt" in post:
        post["modifiedAt"] = modified_at
    source_hash = canonical_hash({"locale": language, "post": post})
    adopted_unlinked = False
    existing: dict[str, Any] | None = None
    if previous_document_id:
        try:
            existing = payload.read(
                "posts", identifier=previous_document_id, identifier_kind="id", draft=True, locale=language
            )
        except Exception as exc:  # noqa: BLE001 - a previously linked ID must never create a duplicate
            if getattr(exc, "status_code", None) == 404:
                raise RuntimeError(
                    "The previously linked Payload article is missing; Ada must reconcile it before creating another post."
                ) from exc
            raise
        recorded_source_id = str(previous_sync.get("source_id") or source_id)
        if (
            str(existing.get("sourceId") or "") != recorded_source_id
            or str(existing.get("slug") or "") != slug
        ):
            raise RuntimeError("The previously linked Payload article identity changed and must be reconciled before any update.")
        if existing.get("published") is not False:
            raise RuntimeError("The linked Payload article is no longer an unpublished draft; Ada will not modify published content.")
    else:
        existing = route_document
        if existing is not None:
            exact_candidate = _is_exact_unlinked_article_draft(existing, post)
            empty_shell = _is_empty_unlinked_article_draft(existing, post, source_id)
            if not (exact_candidate or empty_shell):
                raise RuntimeError(
                    "An existing Payload post at this route is not linked to Ada's exact sync record; its content differs and it is neither Ada's exact draft nor an empty schema draft, so it remains unchanged for owner review."
                )
            adopted_unlinked = True

    document: dict[str, Any] | None = None
    if existing is None:
        try:
            document = payload.create("posts", post, locale=language)
        except Exception as exc:  # noqa: BLE001 - resolve only an exact route-conflict race
            if getattr(exc, "status_code", None) != 409:
                raise
            existing = _read_article_draft_by_slug(payload, slug, language)
            if existing is None or not (
                _is_exact_unlinked_article_draft(existing, post)
                or _is_empty_unlinked_article_draft(existing, post, source_id)
            ):
                raise RuntimeError(
                    "The Payload route conflict is not an exact draft or empty schema draft; its content remains unchanged for owner review."
                ) from exc
            adopted_unlinked = True

    if existing is not None:
        document_id = str(existing.get("id") or "").strip()
        current_revision = str(existing.get("_helloadaRevision") or "")
        if not document_id or not re.fullmatch(r"sha256:[0-9a-f]{64}", current_revision):
            raise RuntimeError("Payload article draft has no stable identifier and revision; it cannot be reconciled safely.")
        if adopted_unlinked:
            document = (
                existing
                if all(_payload_field_matches(key, existing.get(key), value) for key, value in post.items())
                else payload.update(
                    "posts", document_id, post, locale=language, expected_hash=current_revision,
                )
            )
        else:
            if str(previous_sync.get("draft_hash") or "") != current_revision:
                raise RuntimeError("The Payload article draft changed after Ada's last sync; it must be reconciled before approval.")
            document = (
                existing
                if str(previous_sync.get("source_hash") or "") == source_hash
                else payload.update(
                    "posts", document_id, post, locale=language, expected_hash=current_revision,
                )
            )
    if document is None:
        raise RuntimeError("Payload did not create or reconcile the article draft")
    document_id = str(document.get("id") or "").strip()
    if not document_id:
        raise RuntimeError("Payload did not return the article draft identifier")
    verified = payload.read("posts", identifier=document_id, identifier_kind="id", draft=True, locale=language)
    verified_media = payload.read_media(image_id, identifier_kind="id", draft=True)
    verified_seo = verified.get("seo") if isinstance(verified.get("seo"), Mapping) else {}
    metadata_value = verified_seo.get("description")
    actual_source_id = str(document.get("sourceId") or "").strip()
    checks = {
        "document": bool(verified.get("id")),
        "identity": bool(actual_source_id) and str(verified.get("sourceId") or "") == actual_source_id,
        "slug": str(verified.get("slug") or "") == slug,
        "title": str(verified.get("title") or "").strip() == title,
        "summary": str(verified.get("summary") or "").strip() == summary,
        "body": lexical_text(verified.get("body")) == plain,
        "metadata": str(metadata_value or "").strip() == description,
        "mainImage": (
            _payload_relation_id(verified.get("featuredImage")) == image_id
            and str(verified_media.get("_helloadaRevision") or "") == str(image_selection.get("media_revision") or "")
            and bool(str(verified_media.get("alt") or "").strip())
            and bool(str(verified_media.get("sourceId") or "").strip())
            and str(verified_media.get("analysisStatus") or "").lower() == "ready"
        ),
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
            "source_id": actual_source_id,
            "slug": slug,
            "locale": language,
            "excerpt": str(verified.get("summary") or "").strip()[:500],
            "meta_description": str(metadata_value or "").strip()[:320],
            "primary_keyword": primary_keyword,
            "featured_image": {
                **(_article_image_preview(verified_media) or {}),
                "revision": str(verified_media.get("_helloadaRevision") or ""),
                "source_id": str(verified_media.get("sourceId") or ""),
                "source_kind": str(verified_media.get("sourceKind") or ""),
                "source_url": str(verified_media.get("sourceUrl") or verified_media.get("originalUrl") or ""),
                "selection_reason": str(image_selection.get("reason") or ""),
            },
            "validation": {"status": "passed" if state == "ready_for_review" else "blocked", "checks": checks, "reason": reason},
        },
        "payload_post_id": document_id,
        "payload_source_id": actual_source_id,
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
    if producer_frozen(context["memory"]):
        return
    config = context.get("config") or {}
    if crawlseo_research_authority_selected(config):
        context["memory"].record_action("seo_insight", "skipped: CrawlSEO owns SEO recommendations for this site")
        return
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
    if producer_frozen(context["memory"]):
        return
    if _crawlseo_authoritative(context.get("config") or {}):
        context["memory"].record_action("seo_research_cycle", "skipped: CrawlSEO owns research for this site")
        return
    brain_seo.run(context)


def _seo_site_report_cycle(context: dict[str, Any]) -> None:
    if producer_frozen(context["memory"]):
        return
    if _crawlseo_authoritative(context.get("config") or {}):
        context["memory"].record_action("seo_site_report_cycle", "skipped: CrawlSEO owns research reporting for this site")
        return
    brain_monthly_seo_report.run(context)


def _article_research_cycle(context: dict[str, Any]) -> None:
    if producer_frozen(context["memory"]):
        return
    if _crawlseo_authoritative(context.get("config") or {}):
        context["memory"].record_action("article_research_cycle", "skipped: CrawlSEO owns article research for this site")
        return
    # Reconciliation culminates in a reader-facing article, so it needs the
    # complete editorial/business context as well as the research evidence.
    _with_persona(context, brain_article_research.reconcile, "article_research")
    _mirror_article_drafts(context)


def _seo_outcomes_cycle(context: dict[str, Any]) -> None:
    if producer_frozen(context["memory"]):
        return
    if _crawlseo_authoritative(context.get("config") or {}):
        context["memory"].record_action("seo_outcomes", "skipped: CrawlSEO owns SEO outcome analysis for this site")
        return
    brain_seo_outcomes.run(context)


def _has_recoverable_article_sync(memory: Memory) -> bool:
    """Wake only pending drafts with an exact structural recovery path."""
    recoverable_reasons = {"payload posts contract is missing required fields: sourceid"}
    for draft in memory.list_drafts(limit=None):
        if draft.get("kind") != "article" or draft.get("status") != "pending":
            continue
        meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
        sync = meta.get("payload_sync") if isinstance(meta.get("payload_sync"), Mapping) else {}
        validation = sync.get("validation") if isinstance(sync.get("validation"), Mapping) else {}
        reason = str(validation.get("reason") or "").strip().lower()
        exact_contract_recovery = reason in recoverable_reasons or (
            "requested locale" in reason and "not enabled for this website" in reason
        )
        unlinked_draft_recovery = (
            reason in {
                "an existing payload post is not linked to ada's exact sync record; it must be reviewed before any update.",
                "an existing payload post is not linked to ada's exact sync record; its content differs, so it remains blocked for owner review.",
                "the payload route conflict could not be proven to be ada's exact unpublished draft; it remains blocked for owner review.",
                "payload gateway returned 409: a payload document already uses this route; read and update that exact draft instead.",
            }
            and not str(sync.get("document_id") or "").strip()
        )
        if (
            sync.get("state") == "blocked"
            and validation.get("status") == "blocked"
            and (exact_contract_recovery or unlinked_draft_recovery)
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
    crawlseo_settings = (config.get("providers") or {}).get("crawlseo") or {}
    crawlseo_authoritative = _crawlseo_authoritative(config)
    if not (site.get("website_present") and (site.get("payload") or {}).get("enabled")):
        if crawlseo_authoritative:
            raise ValueError("CrawlSEO research authority requires a provisioned HelloAda Payload execution connector")
        return False
    settings = config.get("scheduler") or {}
    overrides = settings.get("schedule") or {}
    register_email_provisioning_job(
        scheduler,
        config,
        context,
        overrides.get("email_provisioning", _JOB_DEFAULTS["email_provisioning"]),
    )
    if producer_frozen(scheduler.memory) and not crawlseo_authoritative:
        # The frozen pending path only reconciles existing exact delivery and
        # Payload revision receipts; it never resumes legacy preparation runs.
        scheduler.job(
            "growth_pending",
            overrides.get("growth_pending", {"every": "1h"}),
            lambda: run_pending_growth(context, recover_interrupted_runs=True),
        )
        if scheduler.memory.kv_get("next_run:growth_pending") is None:
            scheduler.memory.kv_set("next_run:growth_pending", scheduler.clock())
        if _seo_provisioning_enabled(config):
            scheduler.job(
                "seo_provisioning",
                overrides.get("seo_provisioning", _JOB_DEFAULTS["seo_provisioning"]),
                lambda: _seo_provisioning(context),
            )
            if scheduler.memory.kv_get("next_run:seo_provisioning") is None:
                scheduler.memory.kv_set(
                    "next_run:seo_provisioning",
                    compute_next(scheduler.jobs[-1][1], scheduler.clock(), timezone_name=scheduler.timezone_name),
                )
        return True
    growth_policy = config.get("growth") or {}
    if growth_policy.get("enabled", True) is False:
        return True  # Email bootstrap remains operational when Growth is explicitly paused.
    schedules = {"growth_pending": {"every": "1h"}} if crawlseo_authoritative else {
        "growth_initial": {"every": "daily", "at": "07:00"},
        "growth_daily": {"every": "daily", "at": "07:30"},
        "growth_weekly": {"every": "weekly", "weekday": "monday", "at": "08:30"},
        "growth_monthly": {"every": "monthly", "day": 1, "at": "09:00"},
        "growth_pending": {"every": "1h"},
    }
    if not crawlseo_authoritative:
        schedules["growth_article_sync"] = {"every": "1h"}
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
        if name == "growth_pending" and (
            has_recoverable_growth_replay(scheduler.memory)
            or has_recoverable_historical_noop(scheduler.memory)
        ):
            _wake_persisted_job(scheduler, name)
        elif name == "growth_article_sync" and _has_recoverable_article_sync(scheduler.memory):
            _wake_persisted_job(scheduler, name)
    # These are independent maintenance/measurement operations, not competing
    # recommendation producers. Inventory failure must not stop either one.
    maintenance = []
    if _seo_provisioning_enabled(config) and not crawlseo_authoritative:
        maintenance.append(("seo_provisioning", {"every": "6h"}, lambda: _seo_provisioning(context)))
    if context.get("llm") is not None and not crawlseo_authoritative:
        maintenance.append(("seo_outcomes", {"every": "daily", "at": "13:00"}, lambda: _with_persona(context, _seo_outcomes_cycle, "seo_outcomes")))
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
    frozen = producer_frozen(scheduler.memory)
    settings = config.get("scheduler") or {}
    if not isinstance(settings, dict):
        settings = {}
    schedule = settings.get("schedule") if isinstance(settings.get("schedule"), dict) else {}
    register_email_provisioning_job(
        scheduler, config, context, schedule.get("email_provisioning", _JOB_DEFAULTS["email_provisioning"])
    )
    if not bool(settings.get("enabled", False)):
        return
    if not frozen:
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
    crawlseo_settings = (config.get("providers") or {}).get("crawlseo") or {}
    crawlseo_authoritative = _crawlseo_authoritative(config)
    article_research_enabled = bool(((config.get("seo") or {}).get("article_research") or {}).get("enabled", False)) and not crawlseo_authoritative
    seo_config = config.get("seo") if isinstance(config.get("seo"), dict) else {}
    seo_enabled = bool(seo_config.get("enabled") or (config.get("ga") or {}).get("enabled"))
    if _seo_provisioning_enabled(config) and not crawlseo_authoritative:
        scheduler.job(
            "seo_provisioning",
            schedule.get("seo_provisioning", {"every": "6h"}),
            lambda: _seo_provisioning(context),
        )
    if context.get("payload_gateway") is not None and not crawlseo_authoritative:
        _mirror_article_drafts(context)
    if seo_enabled and not crawlseo_authoritative:
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
    if context.get("llm") and not crawlseo_authoritative and (
        bool((config.get("editorial") or {}).get("enabled", False)) or article_research_enabled
    ):
        scheduler.job("article", schedule.get("article", {"every": "weekly", "weekday": "tuesday", "at": "09:00"}), lambda: _article(context))
    if context.get("llm") and seo_enabled and not crawlseo_authoritative and not frozen:
        scheduler.job(
            "seo_insight",
            schedule.get("seo_insight", {"every": 7}),
            lambda: _seo_insight(context),
        )
    if context.get("llm") and not frozen and article_research_enabled and context.get("crawlseo_service"):
        # Selection and reconciliation are two stages of one paid flow: the
        # weekly article job requests the overview, this daily job adopts the
        # result, requests one SERP, and drafts.
        scheduler.job(
            "article_research_cycle",
            schedule.get("article_research_cycle", {"every": "daily", "at": "13:30"}),
            lambda: _article_research_cycle(context),
        )
    if seo_enabled and not crawlseo_authoritative and not frozen:
        scheduler.job(
            "seo_outcomes",
            schedule.get("seo_outcomes", _JOB_DEFAULTS["seo_outcomes"]),
            lambda: _seo_outcomes_cycle(context),
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
        # Historical local reconciliation may still be invoked manually, but
        # it must not remain a second scheduled source of current growth data.
        return
    register_email_provisioning_job(scheduler, config, context, _spec(config, "email_provisioning"))
    frozen = producer_frozen(scheduler.memory)
    scheduler.job("heartbeat", _spec(config, "heartbeat"), lambda: _heartbeat(context))
    if not _crawlseo_authoritative(config) and not frozen:
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
    crawlseo_settings = (config.get("providers") or {}).get("crawlseo") or {}
    crawlseo_authoritative = _crawlseo_authoritative(config)
    if context.get("llm") and not crawlseo_authoritative and not frozen:
        scheduler.job("seo_insight", _spec(config, "seo_insight"), lambda: _seo_insight(context))
    research_config = ((config.get("seo") or {}).get("research") or {})
    site_report_config = ((config.get("seo") or {}).get("site_report") or {})
    article_research_config = ((config.get("seo") or {}).get("article_research") or {})
    if not frozen and not crawlseo_authoritative and site_report_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("seo_site_report_cycle", _spec(config, "seo_site_report_cycle"), lambda: _seo_site_report_cycle(context))
    if not frozen and not crawlseo_authoritative and article_research_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("article_research_cycle", _spec(config, "article_research_cycle"), lambda: _article_research_cycle(context))
    if not frozen and not crawlseo_authoritative and research_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("seo_research_cycle", _spec(config, "seo_research_cycle"), lambda: _seo_research_cycle(context))
    if not frozen and not crawlseo_authoritative and (research_config.get("enabled") or site_report_config.get("enabled") or article_research_config.get("enabled") or bool((config.get("seo") or {}).get("enabled") or (config.get("ga") or {}).get("enabled"))):
        scheduler.job("seo_outcomes", _spec(config, "seo_outcomes"), lambda: _seo_outcomes_cycle(context))
    if _seo_provisioning_enabled(config) and not crawlseo_authoritative:
        scheduler.job("seo_provisioning", _spec(config, "seo_provisioning"), lambda: _seo_provisioning(context))
    scheduler.job("reindex_memory", _spec(config, "reindex_memory"), lambda: _reindex_memory(context))
    scheduler.job("backup", _spec(config, "backup"), lambda: maintenance.backup_data(context))


def reflect_job(context: dict[str, Any]) -> None:
    from .reflect import reflect

    reflect(context)
