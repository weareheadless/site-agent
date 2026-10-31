"""Stall diagnostics for the shared API.

The API once went unresponsive for twenty-two minutes: the port was open, the
event loop was idle, every worker thread was parked, and ``/healthz`` never
answered. Nothing was recorded, so the cause could only be guessed at after the
fact. This module makes the next stall self-documenting.

Two independent triggers write a full thread dump to one file:

* ``SIGUSR1`` for an operator, so a hung process can be inspected in place
  without elevated permissions and without restarting it;
* a watchdog, which fires on its own when a request has been in flight far
  longer than any healthy request should be.
"""

from __future__ import annotations

import faulthandler
import itertools
import signal
import threading
import time
from pathlib import Path
from typing import Any, TextIO

# A healthy request here is well under a second; a build request can
# legitimately take minutes but never blocks the event loop. Ninety seconds of
# an in-flight request is therefore already abnormal and worth a dump.
STALL_SECONDS = 90.0
CHECK_SECONDS = 15.0


class StallWatchdog:
    """Track in-flight requests and dump every thread when one stalls."""

    def __init__(self, log_path: Path, *, stall_seconds: float = STALL_SECONDS) -> None:
        self.log_path = Path(log_path)
        self.stall_seconds = stall_seconds
        self._inflight: dict[int, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ids = itertools.count(1)
        self._last_report = 0.0
        self._handle: TextIO | None = None

    # -- request tracking -------------------------------------------------
    def begin(self, label: str) -> int:
        key = next(self._ids)
        with self._lock:
            self._inflight[key] = (time.monotonic(), label)
        return key

    def end(self, key: int) -> None:
        with self._lock:
            self._inflight.pop(key, None)

    def stalled(self) -> list[tuple[float, str]]:
        now = time.monotonic()
        with self._lock:
            return [
                (now - started, label)
                for started, label in self._inflight.values()
                if now - started >= self.stall_seconds
            ]

    # -- dumping ----------------------------------------------------------
    def _open(self) -> TextIO:
        if self._handle is None or self._handle.closed:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.log_path.open("a", encoding="utf-8", buffering=1)
        return self._handle

    def dump(self, reason: str, stalled: list[tuple[float, str]] | None = None) -> None:
        try:
            handle = self._open()
        except OSError:
            return
        handle.write(f"\n=== api stall {time.strftime('%Y-%m-%dT%H:%M:%S%z')} :: {reason} ===\n")
        for age, label in stalled or ():
            handle.write(f"  in flight {age:.0f}s :: {label}\n")
        handle.flush()
        faulthandler.dump_traceback(file=handle, all_threads=True)
        handle.flush()

    def register_signal(self) -> bool:
        """Dump on SIGUSR1 so a hung process can be inspected in place."""
        try:
            self._open()
            faulthandler.register(signal.SIGUSR1, file=self._handle, all_threads=True)
        except (OSError, ValueError, AttributeError, RuntimeError):
            return False
        return True

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="api-stall-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(CHECK_SECONDS):
            stalled = self.stalled()
            if not stalled:
                continue
            now = time.monotonic()
            # One dump per stall window, not one per check.
            if now - self._last_report < self.stall_seconds:
                continue
            self._last_report = now
            self.dump(f"{len(stalled)} request(s) in flight", stalled)


def install_stall_diagnostics(app: Any, log_path: Path) -> StallWatchdog:
    """Attach request tracking, the watchdog and the SIGUSR1 dump to ``app``."""
    watchdog = StallWatchdog(log_path)
    watchdog.register_signal()

    @app.middleware("http")
    async def _track_stalls(request, call_next):
        key = watchdog.begin(f"{request.method} {request.url.path}")
        try:
            return await call_next(request)
        finally:
            watchdog.end(key)

    watchdog.start()
    return watchdog
