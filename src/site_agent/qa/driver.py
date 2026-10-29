"""Browser driver for declarative flows.

The driver observes; it does not judge. Every step records what it did, how long
it took, and what the browser reported -- console errors, page exceptions and
failed requests included, because AGENTS.md treats those as failures rather than
noise.

Playwright is an optional dependency (the ``design-lab`` extra), so it is
imported lazily and a missing install produces a clear error instead of an
import-time crash.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .flow import Expectation, Flow, Step


class DriverError(RuntimeError):
    """The flow could not be driven at all (browser, target, or transport)."""


@dataclass
class AssertionResult:
    expectation: Expectation
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.expectation.kind,
            "selector": self.expectation.selector,
            "text": self.expectation.text,
            "path": self.expectation.path,
            "step": self.expectation.step,
            "op": self.expectation.op,
            "expected": self.expectation.value,
            "passed": self.passed,
            "detail": self.detail,
            "description": self.expectation.description,
        }


@dataclass
class StepResult:
    id: str
    action: str
    status: str = "pending"
    duration_ms: int = 0
    detail: str = ""
    assertions: list[AssertionResult] = field(default_factory=list)
    screenshot: str | None = None
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "assertions": [item.to_dict() for item in self.assertions],
            "screenshot": self.screenshot,
            "http_status": self.http_status,
        }


@dataclass
class Observations:
    console_errors: list[dict[str, Any]] = field(default_factory=list)
    page_errors: list[dict[str, Any]] = field(default_factory=list)
    failed_requests: list[dict[str, Any]] = field(default_factory=list)
    page_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "console_errors": list(self.console_errors),
            "page_errors": list(self.page_errors),
            "failed_requests": list(self.failed_requests),
            "page_metrics": dict(self.page_metrics),
        }


@dataclass
class FlowResult:
    flow: Flow
    base_url: str
    status: str = "passed"
    steps: list[StepResult] = field(default_factory=list)
    observations: Observations = field(default_factory=Observations)
    artifacts: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_step(self) -> str | None:
        for step in self.steps:
            if step.status == "failed":
                return step.id
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow": self.flow.to_dict(),
            "base_url": self.base_url,
            "status": self.status,
            "error": self.error,
            "steps": [step.to_dict() for step in self.steps],
            "observations": self.observations.to_dict(),
            "artifacts": list(self.artifacts),
        }


class PlaywrightDriver:
    """Runs a flow against a live target with a real Chromium browser."""

    def __init__(
        self,
        *,
        base_url: str,
        artifacts_dir: str | Path,
        timeout_ms: int = 30_000,
        viewport: Mapping[str, int] | None = None,
        screenshots: bool = True,
        browser_channel: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.artifacts_dir = Path(artifacts_dir)
        self.timeout_ms = timeout_ms
        self.viewport = dict(viewport or {"width": 1280, "height": 900})
        self.screenshots = screenshots
        self.browser_channel = browser_channel
        self._current_step = "setup"

    # -- public ---------------------------------------------------------

    def run(self, flow: Flow) -> FlowResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise DriverError(
                "playwright is not installed; install the design-lab extra "
                "(pip install -e '.[design-lab]') and run 'playwright install chromium'"
            ) from exc

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        result = FlowResult(flow=flow, base_url=self.base_url)
        context: dict[str, Any] = {}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=self.browser_channel)
                try:
                    page = browser.new_page(viewport=self.viewport)
                    page.set_default_timeout(self.timeout_ms)
                    self._attach_listeners(page, result.observations)
                    self._run_steps(page, flow, result, context)
                    self._capture_page_metrics(page, result.observations)
                finally:
                    browser.close()
        except DriverError:
            raise
        except Exception as exc:  # pragma: no cover - browser launch/transport
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"
        return result

    # -- steps ----------------------------------------------------------

    def _run_steps(
        self,
        page: Any,
        flow: Flow,
        result: FlowResult,
        context: dict[str, Any],
    ) -> None:
        failed = False
        for index, step in enumerate(flow.steps):
            self._current_step = step.id
            if failed:
                result.steps.append(StepResult(id=step.id, action=step.action, status="skipped"))
                continue
            outcome = self._run_step(page, step, result, context, index)
            result.steps.append(outcome)
            if outcome.status == "failed":
                failed = True
                result.status = "failed"
                result.error = outcome.detail or f"step {step.id} failed"
        if result.status == "passed" and any(step.status == "failed" for step in result.steps):
            result.status = "failed"

    def _run_step(
        self,
        page: Any,
        step: Step,
        result: FlowResult,
        context: dict[str, Any],
        index: int,
    ) -> StepResult:
        outcome = StepResult(id=step.id, action=step.action)
        started = time.monotonic()
        try:
            self._perform(page, step, outcome, context)
            for expectation in step.expect:
                item = self._evaluate(page, expectation, context)
                outcome.assertions.append(item)
                if not item.passed:
                    break
            if any(not item.passed for item in outcome.assertions):
                outcome.status = "failed"
                outcome.detail = "; ".join(
                    item.detail for item in outcome.assertions if not item.passed
                ) or "assertion failed"
            else:
                outcome.status = "passed"
        except Exception as exc:
            outcome.status = "failed"
            outcome.detail = f"{type(exc).__name__}: {exc}"
        finally:
            outcome.duration_ms = int((time.monotonic() - started) * 1000)
            if self.screenshots and step.screenshot:
                shot = self._screenshot(page, index, step.id, result.artifacts)
                outcome.screenshot = shot
        return outcome

    def _perform(
        self,
        page: Any,
        step: Step,
        outcome: StepResult,
        context: dict[str, Any],
    ) -> None:
        if step.action == "goto":
            page.goto(self._absolute(step.url or "/"), wait_until="load")
            outcome.detail = f"opened {page.url}"
        elif step.action == "click":
            page.locator(step.selector or "").first.click()
            outcome.detail = f"clicked {step.selector}"
        elif step.action == "fill":
            page.locator(step.selector or "").first.fill(step.text or "")
            outcome.detail = f"filled {step.selector}"
        elif step.action == "press":
            if step.selector:
                page.locator(step.selector).first.press(step.key or "")
            else:
                page.keyboard.press(step.key or "")
            outcome.detail = f"pressed {step.key}"
        elif step.action == "wait_for":
            page.locator(step.selector or "").first.wait_for(
                state="visible", timeout=step.expect[0].timeout_ms if step.expect else self.timeout_ms
            )
            outcome.detail = f"{step.selector} visible"
        elif step.action == "assert":
            outcome.detail = "assertions evaluated"
        elif step.action == "screenshot":
            outcome.detail = "captured"
        elif step.action == "http":
            self._http(step, outcome, context)
        else:  # pragma: no cover - guarded by flow validation
            raise DriverError(f"unsupported action {step.action!r}")

    def _http(self, step: Step, outcome: StepResult, context: dict[str, Any]) -> None:
        url = self._absolute(step.path or "/")
        data = None
        headers = {"Accept": "application/json", **step.headers}
        if step.body is not None:
            data = json.dumps(step.body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=data, headers=headers, method=step.method or "GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_ms / 1000) as response:
                raw = response.read().decode("utf-8", "replace")
                outcome.http_status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            outcome.http_status = exc.code
        parsed: Any = None
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
        context[step.id] = {"status": outcome.http_status, "json": parsed, "text": raw}
        outcome.detail = f"{step.method} {step.path} -> {outcome.http_status}"

    # -- expectations ---------------------------------------------------

    def _evaluate(
        self,
        page: Any,
        expectation: Expectation,
        context: dict[str, Any],
    ) -> AssertionResult:
        kind = expectation.kind
        try:
            if kind == "visible":
                return self._poll(expectation, lambda: self._visible(page, expectation.selector or ""))
            if kind == "hidden":
                return self._poll(expectation, lambda: not self._visible(page, expectation.selector or ""))
            if kind == "text":
                return self._poll(
                    expectation,
                    lambda: (expectation.text or "") in self._text(page, expectation.selector or ""),
                )
            if kind == "text_absent":
                return self._poll(
                    expectation,
                    lambda: (expectation.text or "") not in self._text(page, expectation.selector or ""),
                )
            if kind == "count":
                return self._poll(
                    expectation,
                    lambda: _compare(
                        page.locator(expectation.selector or "").count(), expectation.value, expectation.op
                    ),
                )
            if kind == "url_contains":
                return self._poll(
                    expectation, lambda: (expectation.text or "") in page.url
                )
            if kind in ("console_clean", "network_clean", "no_page_errors"):
                return AssertionResult(expectation, True, "evaluated by rubric")
            if kind == "status":
                record = context.get(expectation.step or "", {})
                actual = record.get("status")
                passed = _compare(actual, expectation.value, expectation.op)
                return AssertionResult(expectation, passed, f"http status {actual} {expectation.op} {expectation.value}")
            if kind == "json":
                record = context.get(expectation.step or "", {})
                actual = _dig(record.get("json"), expectation.path or "")
                passed = _compare(actual, expectation.value, expectation.op)
                return AssertionResult(
                    expectation,
                    passed,
                    f"{expectation.path} = {actual!r} ({expectation.op} {expectation.value!r})",
                )
        except Exception as exc:
            return AssertionResult(expectation, False, f"{type(exc).__name__}: {exc}")
        return AssertionResult(expectation, False, f"unsupported expectation {kind!r}")

    def _poll(self, expectation: Expectation, predicate: Any) -> AssertionResult:
        deadline = time.monotonic() + expectation.timeout_ms / 1000
        last = False
        while time.monotonic() < deadline:
            try:
                last = bool(predicate())
            except Exception:
                last = False
            if last:
                return AssertionResult(expectation, True, expectation.description or "observed")
            time.sleep(0.15)
        return AssertionResult(
            expectation,
            False,
            expectation.description
            or f"not observed within {expectation.timeout_ms}ms: {expectation.kind}",
        )

    # -- helpers --------------------------------------------------------

    def _visible(self, page: Any, selector: str) -> bool:
        locator = page.locator(selector).first
        return bool(locator.count() and locator.is_visible())

    def _text(self, page: Any, selector: str) -> str:
        locator = page.locator(selector).first
        if not locator.count():
            return ""
        return locator.inner_text(timeout=2_000) or ""

    def _absolute(self, value: str) -> str:
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return f"{self.base_url}/{value.lstrip('/')}"

    def _screenshot(self, page: Any, index: int, step_id: str, artifacts: list[str]) -> str | None:
        name = f"{index:02d}-{step_id}.png"
        target = self.artifacts_dir / name
        try:
            page.screenshot(path=str(target), full_page=True)
        except Exception:
            return None
        artifacts.append(name)
        return name

    def _attach_listeners(self, page: Any, observations: Observations) -> None:
        def on_console(message: Any) -> None:
            if getattr(message, "type", "") == "error":
                observations.console_errors.append(
                    {"step": self._current_step, "text": message.text, "location": _location(message)}
                )

        def on_page_error(error: Any) -> None:
            observations.page_errors.append({"step": self._current_step, "text": str(error)})

        def on_request_failed(request: Any) -> None:
            failure = getattr(request, "failure", None)
            observations.failed_requests.append(
                {
                    "step": self._current_step,
                    "url": request.url,
                    "method": request.method,
                    "reason": failure if isinstance(failure, str) else str(failure or ""),
                }
            )

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("requestfailed", on_request_failed)

    def _capture_page_metrics(self, page: Any, observations: Observations) -> None:
        try:
            observations.page_metrics = page.evaluate(
                """() => ({
                    url: location.href,
                    title: document.title,
                    readyState: document.readyState,
                    viewport: {width: innerWidth, height: innerHeight},
                    scrollHeight: document.documentElement.scrollHeight,
                    headings: Array.from(document.querySelectorAll('h1,h2')).slice(0, 12).map(n => n.textContent.trim()).filter(Boolean),
                    controls: document.querySelectorAll('button,a,input,textarea,select').length,
                    forms: document.querySelectorAll('form').length,
                    images: document.querySelectorAll('img').length,
                    brokenImages: Array.from(document.querySelectorAll('img')).filter(i => i.complete && i.naturalWidth === 0).length,
                    bodyText: (document.body && document.body.innerText ? document.body.innerText : "").slice(0, 4000),
                })"""
            )
        except Exception as exc:  # pragma: no cover - page already closed
            observations.page_metrics = {"error": str(exc)}


def _location(message: Any) -> str:
    try:
        return str(message.location)
    except Exception:  # pragma: no cover - playwright internals
        return ""


def _dig(value: Any, path: str) -> Any:
    current = value
    for part in [piece for piece in path.split(".") if piece]:
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _compare(actual: Any, expected: Any, op: str) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "contains":
            return expected in actual
        if op == "len_eq":
            return len(actual) == expected
        if op == "len_gte":
            return len(actual) >= expected
        if op == "len_lte":
            return len(actual) <= expected
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
    except TypeError:
        return False
    return False
