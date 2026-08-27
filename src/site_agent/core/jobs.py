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

Later phases register here: brain.article (weekly), editor status checks.
"""

from __future__ import annotations

import time
from typing import Any

from ..brain import article as brain_article
from ..brain import digest as brain_digest
from ..brain import dream as brain_dream
from ..brain import inner_voice as brain_inner_voice
from ..brain import report as brain_report
from ..brain import self_model as brain_self_model
from ..senses import collect
from . import maintenance
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
    "article": {"every": 14, "weekday": "tuesday", "at": "09:00"},
    "reflect": {"every": "monthly"},
    "inner_voice": {"every": 2, "at": "14:00"},
    "dream": {"every": 7, "weekday": "sunday", "at": "05:00"},
    "awaken": {"every": 7, "weekday": "sunday", "at": "06:00"},
    "integrate_self": {"every": 2, "at": "20:00"},
    "compact": {"every": 7, "weekday": "sunday", "at": "04:00"},
    "health_check": {"every": "daily", "at": "12:00"},
    "seo_snapshot": {"every": "daily", "at": "11:30"},
    "reindex_memory": {"every": "daily", "at": "03:30"},
    "strategist": {"every": 7, "weekday": "sunday", "at": "18:00"},
    "backup": {"every": 7, "weekday": "sunday", "at": "03:00"},
}


def _spec(config: dict[str, Any], name: str) -> str | int | dict[str, Any]:
    overrides = config.get("schedule") or {}
    return overrides.get(name, _JOB_DEFAULTS[name])


def _heartbeat(context: dict[str, Any]) -> None:
    context["memory"].record_observation("self", "heartbeat")


def _with_persona(context: dict[str, Any], fn: Any) -> Any:
    context["persona_prompt"] = effective_persona(context["config"], context["memory"])
    return fn(context)


def _with_inner_identity(context: dict[str, Any], fn: Any) -> Any:
    from ..brain.prompts import inner_identity_prompt

    identity = inner_identity_prompt(context["config"], context["memory"])
    context["inner_identity_prompt"] = identity
    context["persona_prompt"] = identity
    return fn(context)


def _journal_enabled(context: dict[str, Any]) -> bool:
    configured = bool((context.get("config", {}).get("blog") or {}).get("journal_enabled", False))
    return bool(context["memory"].kv_get("journal_enabled", configured))


def _article(context: dict[str, Any]) -> None:
    if not _journal_enabled(context):
        context["memory"].record_action("article", "journal is not enabled")
        return
    _with_persona(context, brain_article.draft_article)


def _prune_seen(seen: dict[str, float], now: float) -> dict[str, float]:
    cutoff = now - _SEEN_TTL_DAYS * 86400
    return {key: stamp for key, stamp in seen.items() if stamp >= cutoff}


def _digest(context: dict[str, Any]) -> None:
    config = context["config"]
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


def _ga_snapshot(context: dict[str, Any]) -> None:
    from ..senses import ga as ga_sense

    config = context["config"]
    memory: Memory = context["memory"]
    if not (config.get("ga") or {}).get("enabled"):
        return
    summary = ga_sense.weekly_summary(config)
    memory.snapshot_metrics("ga4", summary)


def _seo_snapshot(context: dict[str, Any]) -> None:
    from ..senses import seo as seo_sense

    config = context["config"]
    memory: Memory = context["memory"]
    if not (config.get("seo") or {}).get("enabled"):
        return
    memory.snapshot_metrics("gsc", seo_sense.summary(config))


def _strategist(context: dict[str, Any]) -> None:
    from ..brain.strategist import run as strategist_run

    _with_persona(context, strategist_run)


def _reindex_memory(context: dict[str, Any]) -> None:
    from .memory_store import index_count, reindex as index_observations

    memory = context["memory"]
    added = index_observations(memory)
    detail = f"{added} new memories indexed" if added else "no new memories"
    memory.record_action("memory_index", detail + f" (total {index_count(memory)})")


def register_builtin(scheduler: Scheduler, config: dict[str, Any], context: dict[str, Any]) -> None:
    scheduler.job("heartbeat", _spec(config, "heartbeat"), lambda: _heartbeat(context))
    scheduler.job("health_check", _spec(config, "health_check"), lambda: maintenance.health_check(context))
    sources = config.get("sources") or {}
    if sources.get("subreddits") or sources.get("rss_feeds"):
        scheduler.job("digest", _spec(config, "digest"), lambda: _digest(context))
    if context.get("llm"):
        scheduler.job("learn", _spec(config, "learn"), lambda: _with_persona(context, brain_digest.learn))
        scheduler.job(
            "weekly_report", _spec(config, "weekly_report"), lambda: _with_persona(context, brain_report.weekly_report)
        )
        scheduler.job("article", _spec(config, "article"), lambda: _article(context))
        scheduler.job("reflect", _spec(config, "reflect"), lambda: _with_persona(context, reflect_job))
        scheduler.job("strategist", _spec(config, "strategist"), lambda: _strategist(context))
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
    scheduler.job("reindex_memory", _spec(config, "reindex_memory"), lambda: _reindex_memory(context))
    scheduler.job("backup", _spec(config, "backup"), lambda: maintenance.backup_data(context))


def reflect_job(context: dict[str, Any]) -> None:
    from .reflect import reflect

    reflect(context)
