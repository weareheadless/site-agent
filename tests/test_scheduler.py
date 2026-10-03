import datetime

import pytest

from site_agent.core.memory import Memory
from site_agent.core.scheduler import (
    ScheduleError,
    Scheduler,
    compute_next,
    normalize_schedule,
)


class FakeClock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now


@pytest.fixture
def setup(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    clock = FakeClock()
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", clock=clock)
    yield memory, clock, scheduler
    memory.close()


def test_normalize_accepts_named_int_and_dict_forms():
    assert normalize_schedule("daily")["interval_seconds"] == 86400
    assert normalize_schedule(14)["days"] == 14
    assert normalize_schedule("6h")["interval_seconds"] == 6 * 3600
    assert normalize_schedule("3d")["interval_seconds"] == 3 * 86400
    spec = normalize_schedule({"every": "weekly", "weekday": "Monday", "at": "08:00"})
    assert spec["weekday"] == 0 and spec["at_time"] == datetime.time(8, 0)
    with pytest.raises(ScheduleError):
        normalize_schedule("sometimes")
    with pytest.raises(ScheduleError):
        normalize_schedule({"every": 0})
    with pytest.raises(ScheduleError):
        normalize_schedule({"every": "weekly", "weekday": "funday"})
    with pytest.raises(ScheduleError):
        normalize_schedule({"every": "daily", "at": "25:99"})


def test_pure_interval_next_is_after_plus_interval():
    spec = normalize_schedule({"every": 3})
    assert compute_next(spec, 1_000_000.0) == 1_000_000.0 + 3 * 86400


def test_weekday_anchor_picks_next_occurrence():
    base = datetime.datetime(2026, 8, 22, 12, 0)  # saturday
    spec = normalize_schedule({"every": "weekly", "weekday": "monday", "at": "09:00"})
    nxt = datetime.datetime.fromtimestamp(compute_next(spec, base.timestamp()))
    assert nxt.weekday() == 0 and nxt.hour == 9
    assert nxt == datetime.datetime(2026, 8, 24, 9, 0)

    same_day_before = datetime.datetime(2026, 8, 24, 8, 0)
    nxt2 = datetime.datetime.fromtimestamp(compute_next(spec, same_day_before.timestamp()))
    assert nxt2 == datetime.datetime(2026, 8, 24, 9, 0)

    same_day_after = datetime.datetime(2026, 8, 24, 10, 0)
    nxt3 = datetime.datetime.fromtimestamp(compute_next(spec, same_day_after.timestamp()))
    assert nxt3 == datetime.datetime(2026, 8, 31, 9, 0)


def test_biweekly_weekday_anchor_skips_alternate_weeks():
    base = datetime.datetime(2026, 8, 22, 12, 0)  # saturday
    spec = normalize_schedule({"every": 14, "weekday": "tuesday", "at": "09:00"})
    nxt = datetime.datetime.fromtimestamp(compute_next(spec, base.timestamp()))
    # next plain tuesday is Aug 25, but 14-day spacing pushes to Sep 8
    assert nxt == datetime.datetime(2026, 8, 25, 9, 0) + datetime.timedelta(days=14)


def test_daily_at_anchor_rolls_to_tomorrow_when_passed():
    base = datetime.datetime(2026, 8, 22, 11, 0)
    spec = normalize_schedule({"every": "daily", "at": "09:00"})
    nxt = datetime.datetime.fromtimestamp(compute_next(spec, base.timestamp()))
    assert nxt == datetime.datetime(2026, 8, 23, 9, 0)


def test_first_run_is_immediately_due(setup):
    memory, _, scheduler = setup
    calls = []
    scheduler.job("heartbeat", {"every": "hourly"}, lambda: calls.append(1))
    assert scheduler.due("heartbeat") is True
    ran = scheduler.run_once()
    assert ran == ["heartbeat"] and calls == [1]


def test_interval_job_not_due_until_spacing_elapses(setup):
    memory, clock, scheduler = setup
    calls = []
    scheduler.job("heartbeat", {"every": "hourly"}, lambda: calls.append(1))
    scheduler.run_once()
    clock.now += 1800
    assert scheduler.run_once() == []
    clock.now += 1801
    assert scheduler.run_once() == ["heartbeat"]


def test_late_run_keeps_full_spacing(setup):
    memory, clock, scheduler = setup
    scheduler.job("digest", {"every": 7}, lambda: None)
    scheduler.run_once()
    clock.now += 9 * 86400 + 3600  # run again well past due
    scheduler.run_once()
    second_next = memory.kv_get("next_run:digest")
    assert abs((second_next - clock.now) - 7 * 86400) < 1


def test_overdue_job_is_caught_up_with_marker(setup):
    memory, clock, scheduler = setup
    scheduler.job("report", {"every": "weekly"}, lambda: None)
    scheduler.run_once()
    clock.now += 9 * 86400  # process down for 9 days
    ran = scheduler.run_once()
    assert ran == ["report"]
    actions = [a for a in memory.recent_actions() if a["kind"] == "job" and "report" in a["detail"]]
    assert any("caught up" in a["detail"] for a in actions)


def test_failed_job_records_error_and_retries_before_full_cadence(setup):
    memory, clock, scheduler = setup
    calls = []

    def boom():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("source exploded")

    scheduler.job("digest", {"every": 2}, boom)
    scheduler.run_once()
    errors = [a for a in memory.recent_actions() if a["kind"] == "job_error"]
    assert any("source exploded" in e["detail"] for e in errors)
    first_retry = memory.kv_get("next_run:digest")
    assert first_retry == pytest.approx(clock.now + 3600)
    clock.now += 60
    assert scheduler.run_once() == []
    clock.now = first_retry
    assert scheduler.run_once() == ["digest"]
    assert memory.kv_get("next_run:digest") == pytest.approx(clock.now + 2 * 86400)


def test_upcoming_reports_state(setup):
    _, _, scheduler = setup
    scheduler.job("heartbeat", {"every": "hourly"}, lambda: None)
    upcoming = {u["job"]: u for u in scheduler.upcoming()}
    assert upcoming["heartbeat"]["overdue"] is True
    scheduler.run_once()
    upcoming = {u["job"]: u for u in scheduler.upcoming()}
    assert upcoming["heartbeat"]["overdue"] is False
    assert isinstance(upcoming["heartbeat"]["next_run"], float)


def test_lockfile_blocks_second_runner_and_reclaims_stale(setup):
    _, _, scheduler = setup
    assert scheduler.acquire_lock() is True
    other = Scheduler(scheduler.memory, lock_path=scheduler.lock_path)
    assert other.acquire_lock() is False
    scheduler.release_lock()
    scheduler.lock_path.write_text("999999999")
    assert other.acquire_lock() is True


def test_config_driven_spec_flows_through(setup):
    from site_agent.core.jobs import _spec

    config = {"schedule": {"article": {"every": 21, "weekday": "friday"}}}
    assert _spec(config, "article") == {"every": 21, "weekday": "friday"}
    assert _spec(config, "digest") == {"every": "daily", "at": "09:00"}


def test_monthly_schedule_is_calendar_anchored_and_survives_short_month():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/Cancun")
    spec = normalize_schedule({"every": "monthly", "day": 31, "at": "09:00"})
    start = datetime.datetime(2026, 1, 31, 12, tzinfo=zone)
    february = compute_next(spec, start.timestamp(), timezone_name="America/Cancun")
    assert datetime.datetime.fromtimestamp(february, zone) == datetime.datetime(2026, 2, 28, 9, tzinfo=zone)
    march = compute_next(spec, february, timezone_name="America/Cancun")
    assert datetime.datetime.fromtimestamp(march, zone) == datetime.datetime(2026, 3, 31, 9, tzinfo=zone)
