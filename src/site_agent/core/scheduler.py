"""scheduler.py — strict imperative scheduling with persistent state.

A job's schedule comes from config and is a CONTRACT:

    schedule:
      weekly_report: {every: weekly, weekday: monday, at: "08:00"}
      article:       {every: 14, weekday: tuesday, at: "09:00"}
      digest:        {every: daily, at: "09:00"}
      reflect:       {every: monthly}

Accepted forms:
  - "hourly" | "daily" | "weekly" | "monthly"      (named cadence)
  - 14 or {every: 14}                              (every N days)
  - "6h" or "3d"                                   (fixed hour/day interval)
  - {every: ..., at: "HH:MM"}                      (anchored to wall-clock time,
                                                    server-local timezone)
  - {every: weekly|daily, weekday: monday, at: ..} (anchored to a weekday)

Certainty rules:
  - next_run is computed strictly AFTER each execution and persisted, so a
    job that ran late still keeps its full spacing.
  - if the process was down past next_run, the job is OVERDUE and fires on
    the very next cycle — missed deliveries are caught up, never skipped.
  - failed jobs retry with a persisted bounded backoff instead of consuming
    their full cadence, so transient failures do not defer work for a week.
"""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Any, Callable

from .memory import Memory

CADENCE_SECONDS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,
}

FAILURE_RETRY_BASE_SECONDS = 3600
FAILURE_RETRY_MAX_SECONDS = 86400

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class ScheduleError(ValueError):
    pass


def normalize_schedule(spec: str | int | dict[str, Any]) -> dict[str, Any]:
    if isinstance(spec, str):
        spec = {"every": spec}
    elif isinstance(spec, int):
        spec = {"every": spec}
    if not isinstance(spec, dict):
        raise ScheduleError(f"invalid schedule spec: {spec!r}")

    every = spec.get("every", "daily")
    weekday_raw = spec.get("weekday")
    at_raw = spec.get("at")

    weekday = None
    if weekday_raw is not None:
        key = str(weekday_raw).strip().lower()
        if key not in WEEKDAYS:
            raise ScheduleError(f"unknown weekday '{weekday_raw}'")
        weekday = WEEKDAYS[key]

    at_time = None
    if at_raw is not None:
        try:
            parts = str(at_raw).split(":")
            at_time = datetime.time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            raise ScheduleError(f"invalid 'at' time '{at_raw}' (expected HH:MM)")

    interval_seconds: int | None = None
    days: int | None = None
    if isinstance(every, str) and every.lower() in CADENCE_SECONDS:
        interval_seconds = CADENCE_SECONDS[every.lower()]
    elif isinstance(every, str):
        match = re.fullmatch(r"(\d+)\s*([hd])", every.strip().lower())
        if match:
            amount = int(match.group(1))
            if amount < 1:
                raise ScheduleError(f"cadence must be >= 1 interval, got {every}")
            interval_seconds = amount * (3600 if match.group(2) == "h" else 86400)
            days = amount if match.group(2) == "d" else None
        else:
            try:
                days = int(every)
            except (TypeError, ValueError):
                raise ScheduleError(f"unknown cadence '{every}'")
            if days < 1:
                raise ScheduleError(f"cadence must be >= 1 day, got {days}")
            interval_seconds = days * 86400
    else:
        try:
            days = int(every)
        except (TypeError, ValueError):
            raise ScheduleError(f"unknown cadence '{every}'")
        if days < 1:
            raise ScheduleError(f"cadence must be >= 1 day, got {days}")
        interval_seconds = days * 86400

    return {
        "interval_seconds": interval_seconds,
        "days": days,
        "weekday": weekday,
        "at_time": at_time,
        "label": f"{every}" + (f"/{at_raw}" if at_raw else "") + (f"/{weekday_raw}" if weekday_raw else ""),
    }


def compute_next(spec: dict[str, Any], after_ts: float, now_local: Callable[[], datetime.datetime] | None = None) -> float:
    """Next fire time strictly after after_ts, honoring weekday/time anchors."""
    local = now_local or (lambda ts=None: datetime.datetime.fromtimestamp(after_ts if ts is None else ts))
    base = datetime.datetime.fromtimestamp(after_ts)
    at_time = spec["at_time"]
    weekday = spec["weekday"]

    if at_time is None and weekday is None:
        return after_ts + spec["interval_seconds"]

    candidate_date = base.date()
    if weekday is not None:
        delta = (weekday - candidate_date.weekday()) % 7
        candidate_date += datetime.timedelta(days=delta)
        candidate_dt = datetime.datetime.combine(candidate_date, at_time or datetime.time(9, 0))
        if candidate_dt <= base:
            candidate_dt += datetime.timedelta(days=7)
        # "every N days on weekday W": keep skipping whole weeks until the
        # N-day spacing is honored (e.g. every: 14 -> biweekly Tuesdays).
        if spec["days"] is not None and spec["days"] > 7:
            min_ts = after_ts + spec["interval_seconds"]
            while candidate_dt.timestamp() < min_ts:
                candidate_dt += datetime.timedelta(days=7)
        return candidate_dt.timestamp()

    candidate_dt = datetime.datetime.combine(candidate_date, at_time)
    if candidate_dt <= base:
        candidate_dt += datetime.timedelta(days=1)
    return candidate_dt.timestamp()


def _utcnow() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


class Scheduler:
    def __init__(self, memory: Memory, lock_path: str | Path, clock: Callable[[], float] = _utcnow):
        self.memory = memory
        self.lock_path = Path(lock_path)
        self.clock = clock
        self.jobs: list[tuple[str, dict[str, Any], Callable[[], Any]]] = []

    def job(self, name: str, schedule: str | int | dict[str, Any], fn: Callable[[], Any]) -> None:
        self.jobs.append((name, normalize_schedule(schedule), fn))

    def _next_run_key(self, name: str) -> str:
        return f"next_run:{name}"

    def _failure_count_key(self, name: str) -> str:
        return f"job_failures:{name}"

    def _record_failure(self, name: str, spec: dict[str, Any]) -> int:
        failures = self.memory.kv_get(self._failure_count_key(name), 0)
        failures = failures if isinstance(failures, int) and failures >= 0 else 0
        failures += 1
        retry_seconds = min(
            spec["interval_seconds"],
            FAILURE_RETRY_MAX_SECONDS,
            FAILURE_RETRY_BASE_SECONDS * (2 ** min(failures - 1, 5)),
        )
        self.memory.kv_set(self._failure_count_key(name), failures)
        return retry_seconds

    def due(self, name: str) -> bool:
        nxt = self.memory.kv_get(self._next_run_key(name))
        if not isinstance(nxt, (int, float)):
            return True
        return self.clock() >= nxt

    def overdue_by_hours(self, name: str) -> float:
        nxt = self.memory.kv_get(self._next_run_key(name))
        if not isinstance(nxt, (int, float)):
            return 0.0
        return max(0.0, (self.clock() - nxt) / 3600)

    def acquire_lock(self) -> bool:
        if self.lock_path.exists():
            try:
                pid = int(self.lock_path.read_text().strip())
            except ValueError:
                return self._claim()
            try:
                alive = Path(f"/proc/{pid}").exists()
            except OSError:
                alive = False
            if alive:
                return False
        return self._claim()

    def _claim(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(str(os.getpid()))
        return True

    def release_lock(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def run_once(self) -> list[str]:
        ran = []
        for name, spec, fn in self.jobs:
            if not self.due(name):
                continue
            late_hours = round(self.overdue_by_hours(name), 1)
            succeeded = False
            try:
                fn()
                succeeded = True
                detail = f"{spec['label']} ok" + (f" (caught up, {late_hours}h late)" if late_hours else "")
                self.memory.record_action("job", f"{name}: {detail}")
            except Exception as exc:  # noqa: BLE001 — jobs must never kill the loop
                retry_seconds = self._record_failure(name, spec)
                self.memory.record_action("job_error", f"{name}: {exc} (retry in {retry_seconds}s)")
            finally:
                fired_at = self.clock()
                self.memory.kv_set(f"last_run:{name}", round(fired_at, 3))
                if succeeded:
                    self.memory.kv_set(self._failure_count_key(name), 0)
                    next_run = compute_next(spec, fired_at)
                else:
                    next_run = fired_at + retry_seconds
                self.memory.kv_set(self._next_run_key(name), round(next_run, 3))
                ran.append(name)
        return ran

    def upcoming(self) -> list[dict[str, Any]]:
        out = []
        for name, spec, _fn in self.jobs:
            nxt = self.memory.kv_get(self._next_run_key(name))
            out.append(
                {
                    "job": name,
                    "schedule": spec["label"],
                    "next_run": nxt if isinstance(nxt, (int, float)) else None,
                    "overdue": self.due(name),
                }
            )
        return out

    def run_forever(self, poll_seconds: int = 300) -> None:
        if not self.acquire_lock():
            raise RuntimeError(f"another cycle is running ({self.lock_path})")
        try:
            import time

            while True:
                self.run_once()
                time.sleep(poll_seconds)
        finally:
            self.release_lock()
