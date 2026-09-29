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
from ..senses import collect
from . import maintenance
from .contracts import ApprovalStatus, ArtifactKind
from .memory import Memory
from .reflect import effective_persona
from .scheduler import Scheduler

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
    "seo_insight": {"every": 7, "weekday": "monday", "at": "08:45"},
    "reindex_memory": {"every": "daily", "at": "03:30"},
    "strategist": {"every": 7, "weekday": "sunday", "at": "18:00"},
    "backup": {"every": 7, "weekday": "sunday", "at": "03:00"},
    "social_post": {"every": "weekly", "weekday": "thursday", "at": "09:00"},
    "seo_research_cycle": {"every": "daily", "at": "13:00"},
    "seo_outcomes": {"every": "daily", "at": "14:00"},
    "seo_site_report_cycle": {"every": "daily", "at": "13:00"},
    "article_research_cycle": {"every": "daily", "at": "13:30"},
}


def _spec(config: dict[str, Any], name: str) -> str | int | dict[str, Any]:
    overrides = config.get("schedule") or {}
    return overrides.get(name, _JOB_DEFAULTS[name])


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


def _journal_enabled(context: dict[str, Any]) -> bool:
    config = context.get("config", {})
    editorial = config.get("atelier_editorial") if isinstance(config, dict) else {}
    configured = bool(
        (config.get("blog") or {}).get("journal_enabled", False)
        or (isinstance(editorial, dict) and editorial.get("enabled", False))
    )
    return bool(context["memory"].kv_get("journal_enabled", configured))


def _article(context: dict[str, Any]) -> None:
    if not _journal_enabled(context):
        context["memory"].record_action("article", "journal is not enabled")
        return
    article_research = ((context.get("config", {}).get("seo") or {}).get("article_research") or {})
    if article_research.get("enabled") and context.get("crawlseo_service"):
        _with_persona(context, brain_article_research.select_and_request, "editorial")
        return
    if article_research.get("enabled"):
        # Reader-led research is the default pipeline, but a missing provider
        # must not silently stop article output: fall back to one editorial
        # draft and leave a visible reason for the owner.
        context["memory"].record_action(
            "article_research",
            "skipped: CrawlSEO provider is unavailable; wrote one editorial draft instead",
        )
    draft_id = _with_persona(context, brain_article.draft_article, "editorial")
    if isinstance(draft_id, int):
        _mirror_article_draft_to_atelier(context, draft_id)


def _mirror_article_drafts(context: dict[str, Any]) -> None:
    """Mirror every research-produced article draft, not only the legacy path."""
    memory = context["memory"]
    for draft in memory.list_drafts(limit=100):
        if draft.get("kind") != "article":
            continue
        try:
            _mirror_article_draft_to_atelier(context, int(draft["id"]))
        except (TypeError, ValueError):
            continue


def _mirror_keyword_research(context: dict[str, Any]) -> None:
    """Keep the complete paid-research trail beside the owner-facing insight."""
    payload = context.get("payload_gateway")
    if payload is None:
        return
    memory = context["memory"]
    tenant_id = context.get("atelier_tenant_id") or context["config"].get("instance_name")
    for idea in memory.list_article_ideas(limit=100):
        idea_data = idea.get("idea_json") if isinstance(idea.get("idea_json"), Mapping) else {}
        note = idea.get("research_note_json") if isinstance(idea.get("research_note_json"), Mapping) else {}
        try:
            payload.upsert_seo_record(
                "keyword_research",
                {
                    "sourceId": f"article-idea:{tenant_id}:{idea.get('id')}",
                    "tenant_id": tenant_id,
                    "idea_key": idea.get("cycle_key") or idea.get("idea_hash") or str(idea.get("id") or ""),
                    "working_title": idea_data.get("working_title") or "",
                    "status": idea.get("status") or "unknown",
                    "selected_keyword": note.get("selected_query") or "",
                    "language": idea_data.get("language") or "",
                    "country": idea_data.get("market") or "",
                    "requested_at": idea.get("created_ts"),
                    "completed_at": idea.get("researched_ts"),
                    "result": idea.get("research_result_json") or {},
                    "serp_evidence": note.get("serp_evidence") or {},
                    "draft_id": idea.get("draft_id"),
                    "cost_micros": idea.get("research_cost_micros"),
                    "error": idea.get("error") or "",
                },
            )
        except Exception as exc:  # noqa: BLE001 - local research remains usable for retry
            memory.record_action("article_research", f"Payload keyword mirror deferred: {str(exc)[:180]}")


def _article_slug(title: str, draft_id: int) -> str:
    normalized = unicodedata.normalize("NFKD", str(title or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:100]
    return slug or f"ada-article-{draft_id}"


def _article_html(markdown_body: str) -> str:
    try:
        import markdown

        return markdown.markdown(
            str(markdown_body or ""),
            extensions=["extra", "sane_lists"],
            output_format="html5",
        )
    except Exception:  # noqa: BLE001 - a local draft remains useful if rendering is unavailable
        return f"<p>{str(markdown_body or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</p>"


def _mirror_article_draft_to_atelier(context: dict[str, Any], draft_id: int) -> None:
    """Put the existing Ada article draft into Payload without publishing it."""
    payload = context.get("payload_gateway")
    if payload is None:
        return
    memory = context["memory"]
    draft = next((item for item in memory.list_drafts(limit=100) if int(item.get("id") or 0) == draft_id), None)
    if not draft:
        return
    title = str(draft.get("title") or "Ada draft").strip()[:300]
    slug = _article_slug(title, draft_id)
    site = context.get("config", {}).get("site") or {}
    site_url = str(site.get("preview_url") or (context.get("config", {}).get("blog") or {}).get("site_url") or "").rstrip("/")
    language = str(
        ((context.get("config", {}).get("customer_profile") or {}).get("brand") or {}).get("observed_language")
        or (context.get("config", {}).get("site") or {}).get("language")
        or "fr"
    ).strip().lower().split("-", 1)[0]
    source_id = f"ada-article-{draft_id}"
    body = str(draft.get("body") or "")
    plain = re.sub(r"[#*_>`]", "", body)
    plain = " ".join(plain.split())[:240]
    post = {
        "sourceId": source_id,
        "slug": slug,
        "title": title,
        "sourceUrl": f"{site_url}/post/{slug}" if site_url else f"/post/{slug}",
        "excerpt": plain,
        "content": [{"html": _article_html(body)}],
        "modifiedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "author": str((context.get("config", {}).get("persona") or {}).get("name") or "Ada"),
    }
    seo_meta = meta if isinstance((meta := draft.get("meta")), Mapping) else {}
    research_note = seo_meta.get("research_note") if isinstance(seo_meta.get("research_note"), Mapping) else {}
    primary_keyword = str(
        seo_meta.get("primary_keyword")
        or research_note.get("selected_query")
        or ""
    ).strip()[:200]
    if primary_keyword:
        post["seo"] = {
            "focusKeyword": primary_keyword,
            "title": title[:300],
            "description": plain[:320],
        }
    try:
        existing = next(
            (item for item in payload.list("posts", draft=True, limit=100) if str(item.get("sourceId") or "") == source_id),
            None,
        )
        if existing and existing.get("id") is not None:
            document = payload.update("posts", str(existing["id"]), post, locale=language)
        else:
            document = payload.create("posts", post, locale=language)
        meta = dict(draft.get("meta") or {})
        meta.update({"payload_post_id": document.get("id"), "payload_source_id": source_id, "payload_slug": slug})
        memory.save_draft(title, body, kind=str(draft.get("kind") or "article"), meta=meta, draft_id=draft_id)
        memory.record_action("article", f"draft #{draft_id} mirrored to the Payload blog as a draft")
    except Exception as exc:  # noqa: BLE001 - Payload failure must not lose the local owner-review draft
        memory.record_action("article", f"draft #{draft_id} kept locally; Payload mirror deferred: {str(exc)[:240]}")


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

    insight_id = _with_persona(context, generate_seo_insight, "editorial")
    payload = context.get("payload_gateway")
    if payload is not None and isinstance(insight_id, int):
        insight = context["memory"].latest_seo_insight()
        if insight:
            try:
                payload.upsert_seo_record(
                    "insight",
                    {**insight, "tenant_id": context.get("atelier_tenant_id") or context["config"].get("instance_name")},
                )
            except Exception as exc:  # noqa: BLE001 - local insight remains authoritative for retry
                context["memory"].record_action("seo_insight", f"Payload mirror deferred: {str(exc)[:240]}")


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
    payload = context.get("payload_gateway")
    if payload is not None:
        tenant_id = context.get("atelier_tenant_id") or context["config"].get("instance_name")
        captured_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        period = str(summary.get("period") or summary.get("period_days") or captured_at[:10]) if isinstance(summary, Mapping) else captured_at[:10]
        payload.upsert_seo_record(
            "snapshot",
            {
                "sourceId": f"snapshot:{tenant_id}:ga4:{captured_at[:10]}",
                "source": "ga4",
                "period": period,
                "captured_at": captured_at,
                "data": summary,
                "tenant_id": tenant_id,
            },
        )


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
    payload = context.get("payload_gateway")
    if payload is not None:
        tenant_id = context.get("atelier_tenant_id") or context["config"].get("instance_name")
        captured_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        period = str(summary.get("period") or summary.get("period_days") or captured_at[:10]) if isinstance(summary, Mapping) else captured_at[:10]
        payload.upsert_seo_record(
            "snapshot",
            {
                "sourceId": f"snapshot:{tenant_id}:gsc:{captured_at[:10]}",
                "source": "gsc",
                "period": period,
                "captured_at": captured_at,
                "data": summary,
                "tenant_id": tenant_id,
            },
        )


def _seo_provisioning(context: dict[str, Any]) -> None:
    """Retry the automatic tenant bootstrap and attach a newly issued client."""
    from ..application.seo_bootstrap import auto_provision_seo

    tenant_id = str(context.get("atelier_tenant_id") or context["config"].get("instance_name") or "")
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
    payload = context.get("payload_gateway")
    if payload is not None and state:
        payload.upsert_seo_record("integration", state)


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
    _mirror_keyword_research(context)


def register_atelier_jobs(scheduler: Scheduler, config: dict[str, Any], context: dict[str, Any]) -> None:
    """Register Ada's reusable reading/editorial loop for a shared tenant API.

    The normal CLI activation path already calls :func:`register_builtin`. The
    shared Atelier API deliberately keeps tenant activation separate, so it
    uses this small selection of the same digest, learning, and article jobs
    instead of silently dropping Ada's original news loop.
    """
    settings = config.get("atelier_scheduler") or {}
    if not isinstance(settings, dict) or not bool(settings.get("enabled", False)):
        return
    schedule = settings.get("schedule") if isinstance(settings.get("schedule"), dict) else {}
    sources = (_effective_source_config(context).get("sources") or {})
    has_sources = bool(sources.get("subreddits") or sources.get("rss_feeds") or sources.get("community_feeds"))
    if has_sources:
        scheduler.job("digest", schedule.get("digest", {"every": "weekly", "weekday": "monday", "at": "08:00"}), lambda: _digest(context))
    if context.get("llm") and (has_sources or bool(settings.get("learning_enabled", False))):
        scheduler.job("learn", schedule.get("learn", {"every": "weekly", "weekday": "monday", "at": "08:20"}), lambda: _with_persona(context, brain_digest.learn, "research"))
    article_research_enabled = bool(((config.get("seo") or {}).get("article_research") or {}).get("enabled", False))
    seo_config = config.get("seo") if isinstance(config.get("seo"), dict) else {}
    provisioning = seo_config.get("provisioning") if isinstance(seo_config, dict) else {}
    seo_enabled = bool(seo_config.get("enabled") or (config.get("ga") or {}).get("enabled"))
    if isinstance(provisioning, dict) and bool(provisioning.get("auto", False)):
        scheduler.job(
            "seo_provisioning",
            schedule.get("seo_provisioning", {"every": "6h"}),
            lambda: _seo_provisioning(context),
        )
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
    if context.get("llm") and (bool((config.get("atelier_editorial") or {}).get("enabled", False)) or article_research_enabled):
        scheduler.job("article", schedule.get("article", {"every": "weekly", "weekday": "tuesday", "at": "09:00"}), lambda: _article(context))
    if context.get("llm") and seo_enabled:
        scheduler.job(
            "seo_insight",
            schedule.get("seo_insight", {"every": 7, "weekday": "monday", "at": "08:45"}),
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
    intake = context.get("atelier_intake")
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
    scheduler.job("heartbeat", _spec(config, "heartbeat"), lambda: _heartbeat(context))
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
    replacement_workflow = site_report_config.get("enabled") or article_research_config.get("enabled")
    if site_report_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("seo_site_report_cycle", _spec(config, "seo_site_report_cycle"), lambda: _seo_site_report_cycle(context))
    if article_research_config.get("enabled") and context.get("crawlseo_service"):
        scheduler.job("article_research_cycle", _spec(config, "article_research_cycle"), lambda: _article_research_cycle(context))
    if research_config.get("enabled") and context.get("crawlseo_service") and not replacement_workflow:
        scheduler.job("seo_research_cycle", _spec(config, "seo_research_cycle"), lambda: _seo_research_cycle(context))
    if research_config.get("enabled") and not replacement_workflow:
        scheduler.job("seo_outcomes", _spec(config, "seo_outcomes"), lambda: brain_seo_outcomes.run(context))
    scheduler.job("reindex_memory", _spec(config, "reindex_memory"), lambda: _reindex_memory(context))
    scheduler.job("backup", _spec(config, "backup"), lambda: maintenance.backup_data(context))


def reflect_job(context: dict[str, Any]) -> None:
    from .reflect import reflect

    reflect(context)
