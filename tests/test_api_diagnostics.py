import signal
import time

from site_agent.web.diagnostics import StallWatchdog, install_stall_diagnostics


def test_stalled_requests_are_dumped_with_their_threads(tmp_path):
    log = tmp_path / "logs" / "api-stalls.log"
    watchdog = StallWatchdog(log, stall_seconds=0.05)

    key = watchdog.begin("GET /v1/workspace/site")
    time.sleep(0.1)

    stalled = watchdog.stalled()
    assert [label for _, label in stalled] == ["GET /v1/workspace/site"]

    watchdog.dump("test stall", stalled)
    watchdog.end(key)

    body = log.read_text()
    assert "GET /v1/workspace/site" in body
    assert 'File "' in body  # faulthandler writes the live thread stacks
    assert watchdog.stalled() == []


def test_signal_registration_is_optional_and_never_raises(tmp_path):
    watchdog = StallWatchdog(tmp_path / "api-stalls.log")

    assert isinstance(watchdog.register_signal(), bool)


def test_diagnostics_attach_to_an_app_without_touching_its_routes(tmp_path):
    class App:
        def __init__(self):
            self.middleware_added = []
            self.middleware = self._middleware

        def _middleware(self, kind):
            def register(fn):
                self.middleware_added.append((kind, fn.__name__))
                return fn
            return register

    app = App()
    watchdog = install_stall_diagnostics(app, tmp_path / "api-stalls.log")
    try:
        assert app.middleware_added == [("http", "_track_stalls")]
    finally:
        watchdog.stop()
