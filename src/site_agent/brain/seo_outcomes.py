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


def _metric(snapshot: Mapping[str, Any] | None, metric: str, scope: Mapping[str, Any] | None = None) -> float | None:
    if not isinstance(snapshot, Mapping):
        return None
    data = snapshot.get("data")
    if not isinstance(data, Mapping):
        return None
    scope = scope if isinstance(scope, Mapping) else {}
    path = str(scope.get("path") or "").strip()
    if path:
        pages = data.get("top_pages") if isinstance(data.get("top_pages"), list) else []
        matching = [row for row in pages if isinstance(row, Mapping) and str(row.get("path") or "") == path]
        if not matching:
            return None
        key = "clicks" if metric == "gsc.clicks" else "sessions" if metric == "ga4.sessions" else ""
        values = [row.get(key) for row in matching if row.get(key) is not None]
        try:
            return float(sum(float(value) for value in values)) if values else None
        except (TypeError, ValueError):
            return None
    current = data.get("current") or data.get("current_week")
    if not isinstance(current, Mapping):
        return None
    value = current.get("clicks") if metric == "gsc.clicks" else current.get("sessions") if metric == "ga4.sessions" else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _observation(memory: Any, metric: str, scope: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    gsc = memory.latest_snapshot("gsc")
    ga4 = memory.latest_snapshot("ga4")
    snapshot = gsc if metric == "gsc.clicks" else ga4 if metric == "ga4.sessions" else None
    value = _metric(snapshot, metric, scope)
    if value is None:
        return None
    return {"metric": metric, "value": value, "gsc": gsc or {}, "ga4": ga4 or {}}


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
    measured = 0
    for initiative in memory.list_strategy_initiatives(limit=500):
        expected = initiative.get("expected") if isinstance(initiative.get("expected"), Mapping) else {}
        baseline = expected.get("implementation_baseline") if isinstance(expected, Mapping) else None
        if not isinstance(baseline, Mapping):
            continue
        metric = str(baseline.get("metric") or "").strip()
        if metric not in {"gsc.clicks", "ga4.sessions"}:
            # Legacy baselines did not record the selected source. Select from
            # the baseline only, never by whichever source happens to be live
            # when the outcome is measured.
            metric = "gsc.clicks" if _metric(baseline.get("gsc"), "gsc.clicks") is not None else "ga4.sessions"
        scope = baseline.get("scope") if isinstance(baseline.get("scope"), Mapping) else {}
        baseline_value = _metric(baseline.get("gsc"), metric, scope) if metric == "gsc.clicks" else _metric(baseline.get("ga4"), metric, scope)
        observed = _observation(memory, metric, scope)
        for horizon in HORIZONS:
            due = _as_datetime(initiative.get(f"review_{horizon}_ts"))
            if due is None or due > now or memory.get_strategy_outcome(initiative["id"], horizon) is not None:
                continue
            observed_value = observed["value"] if observed is not None else None
            assessment, confidence, notes = _assessment(baseline_value, observed_value)
            if observed is None:
                notes = f"{metric} data for the approved scope is unavailable; no site-wide or alternate source was substituted."
            memory.record_strategy_outcome(
                initiative["id"],
                horizon,
                {"metric": metric, "value": baseline_value, "snapshots": baseline},
                {"metric": metric, "value": observed_value, "snapshots": observed or {}, "state": "missing" if observed is None else "available"},
                assessment,
                confidence,
                notes,
            )
            if initiative.get("state") == "measuring":
                memory.transition_strategy_initiative(int(initiative["id"]), "reviewed")
            measured += 1
    memory.record_action("seo_outcome", f"measured {measured} due initiative horizon(s)")
    return measured


__all__ = ["HORIZONS", "run"]
