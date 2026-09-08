"""Measure approved SEO initiatives without claiming more than the data shows."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any


HORIZONS = (30, 90, 180)


def _as_datetime(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(datetime.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _metric(snapshot: Mapping[str, Any] | None) -> float | None:
    if not isinstance(snapshot, Mapping):
        return None
    data = snapshot.get("data")
    if not isinstance(data, Mapping):
        return None
    current = data.get("current") or data.get("current_week")
    if not isinstance(current, Mapping):
        return None
    value = current.get("clicks")
    if value is None:
        value = current.get("sessions")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _observation(memory: Any) -> dict[str, Any] | None:
    gsc = memory.latest_snapshot("gsc")
    ga4 = memory.latest_snapshot("ga4")
    value = _metric(gsc)
    source = "gsc.clicks"
    if value is None:
        value = _metric(ga4)
        source = "ga4.sessions"
    if value is None:
        return None
    return {"metric": source, "value": value, "gsc": gsc or {}, "ga4": ga4 or {}}


def _assessment(baseline: float | None, observed: float | None) -> tuple[str, str, str]:
    if baseline is None or observed is None:
        return "inconclusive", "low", "Equivalent metric snapshots were not available."
    if baseline == 0:
        return ("positive", "low", "The observed metric is above a zero baseline.") if observed > 0 else ("neutral", "low", "Both baseline and observed metric are zero.")
    delta_pct = ((observed - baseline) / abs(baseline)) * 100
    if delta_pct >= 5:
        return "positive", "medium", f"Observed metric increased {delta_pct:.1f}% from baseline."
    if delta_pct <= -5:
        return "negative", "medium", f"Observed metric decreased {abs(delta_pct):.1f}% from baseline."
    return "neutral", "medium", f"Observed metric changed {delta_pct:.1f}% from baseline."


def run(context: dict[str, Any]) -> int:
    memory = context["memory"]
    now = datetime.datetime.now(datetime.timezone.utc)
    observed = _observation(memory)
    if observed is None:
        memory.record_action("seo_outcome", "skipped: first-party metric snapshots are unavailable")
        return 0

    measured = 0
    for initiative in memory.list_strategy_initiatives(limit=500):
        expected = initiative.get("expected") if isinstance(initiative.get("expected"), Mapping) else {}
        baseline = expected.get("implementation_baseline") if isinstance(expected, Mapping) else None
        if not isinstance(baseline, Mapping):
            continue
        baseline_value = _metric(baseline.get("gsc"))
        if baseline_value is None:
            baseline_value = _metric(baseline.get("ga4"))
        for horizon in HORIZONS:
            due = _as_datetime(initiative.get(f"review_{horizon}_ts"))
            if due is None or due > now or memory.get_strategy_outcome(initiative["id"], horizon) is not None:
                continue
            assessment, confidence, notes = _assessment(baseline_value, observed["value"])
            memory.record_strategy_outcome(
                initiative["id"],
                horizon,
                {"metric": observed["metric"], "value": baseline_value, "snapshots": baseline},
                {"metric": observed["metric"], "value": observed["value"], "snapshots": observed},
                assessment,
                confidence,
                notes,
            )
            measured += 1
    memory.record_action("seo_outcome", f"measured {measured} due initiative horizon(s)")
    return measured


__all__ = ["HORIZONS", "run"]
