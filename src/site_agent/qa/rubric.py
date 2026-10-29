"""Judgement layer.

Two judges, on purpose:

* :class:`RuleJudge` is deterministic and is the only one allowed to gate a
  merge. It encodes the invariants AGENTS.md already states: console errors,
  failed module or asset requests, page exceptions, a page that never reaches a
  usable state, and raw internal errors leaking into owner-facing text.
* :class:`ModelJudge` answers the question rules cannot -- is the copy coherent,
  does the result reflect the confirmed brief, is the failure message
  actionable. It is advisory. Wiring it to a provider is a deliberate opt-in so
  a gate never depends on a model's mood.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .driver import FlowResult

RUBRIC_VERSION = "site-agent.qa.rubric/1"

# Raw internals that must never be the only thing an owner sees.
_RAW_INTERNAL = (
    re.compile(r"\bTraceback \(most recent call last\)"),
    re.compile(r"\b\w+Error: "),
    re.compile(r"\bis required\b"),
    re.compile(r"\bvalidation failed: \{"),
    re.compile(r"\"[a-z_]+\": (true|false|null)"),
    re.compile(r"\bInternal Server Error\b"),
)


@dataclass
class Check:
    id: str
    ok: bool
    blocking: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "ok": self.ok, "blocking": self.blocking, "detail": self.detail}


@dataclass
class JudgeVerdict:
    verdict: str
    judge: str = "rule"
    checks: list[Check] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[str]:
        return [check.id for check in self.checks if not check.ok and check.blocking]

    @property
    def passed(self) -> bool:
        return not self.failed_checks and self.verdict == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RUBRIC_VERSION,
            "verdict": self.verdict,
            "judge": self.judge,
            "passed": self.passed,
            "failed_checks": self.failed_checks,
            "checks": [check.to_dict() for check in self.checks],
            "findings": list(self.findings),
            "reasons": list(self.reasons),
        }


class RuleJudge:
    """Deterministic rubric. This is the merge gate."""

    name = "rule"

    def review(self, result: FlowResult) -> JudgeVerdict:
        checks = [
            self._steps(result),
            self._console(result),
            self._network(result),
            self._page_errors(result),
            self._ready(result),
            self._no_raw_internals(result),
            self._images(result),
            Check('browser.dialogs', not any(not item.get('expected') for item in result.observations.dialogs),
                  detail='unexpected native dialogs must not be accepted'),
        ]
        failed = [check for check in checks if not check.ok and check.blocking]
        reasons = [f"{check.id}: {check.detail}" for check in failed]
        if result.status == "error":
            reasons.insert(0, f"driver error: {result.error or 'unknown'}")
        return JudgeVerdict(
            verdict="fail" if reasons else "pass",
            judge=self.name,
            checks=checks,
            reasons=reasons,
        )

    # -- checks ---------------------------------------------------------

    def _steps(self, result: FlowResult) -> Check:
        failed = [step for step in result.steps if step.status == "failed"]
        if failed:
            first = failed[0]
            return Check("flow.steps", False, detail=f"step {first.id} failed: {first.detail}")
        if result.status == "error":
            return Check("flow.steps", False, detail=f"driver error: {result.error}")
        if (len(result.steps) != len(result.flow.steps)
                or any(step.status != 'passed' for step in result.steps)):
            return Check('flow.steps', False, detail='flow evidence is incomplete')
        return Check("flow.steps", True, detail=f"{len(result.steps)} steps passed")

    def _console(self, result: FlowResult) -> Check:
        errors = result.observations.console_errors
        if errors:
            first = errors[0]
            return Check(
                "browser.console",
                False,
                detail=f"{len(errors)} console error(s), first at {first.get('step')}: {first.get('text')}",
            )
        return Check("browser.console", True, detail="no console errors")

    def _network(self, result: FlowResult) -> Check:
        failed = result.observations.failed_requests
        if failed:
            first = failed[0]
            return Check(
                "browser.requests",
                False,
                detail=f"{len(failed)} failed request(s), first at {first.get('step')}: {first.get('url')}",
            )
        return Check("browser.requests", True, detail="no failed requests")

    def _page_errors(self, result: FlowResult) -> Check:
        errors = result.observations.page_errors
        if errors:
            return Check(
                "browser.pageerror",
                False,
                detail=f"{len(errors)} uncaught page error(s): {errors[0].get('text')}",
            )
        return Check("browser.pageerror", True, detail="no uncaught page errors")

    def _ready(self, result: FlowResult) -> Check:
        metrics = result.observations.page_metrics or {}
        state = metrics.get("readyState")
        if not state:
            return Check("page.ready", True, blocking=False, detail="no page metrics captured")
        if state != "complete":
            return Check("page.ready", False, detail=f"document.readyState is {state!r}")
        return Check("page.ready", True, detail="document complete")

    def _no_raw_internals(self, result: FlowResult) -> Check:
        """A failed run must still tell the owner something actionable."""

        text = _visible_text(result)
        if not text:
            return Check("owner.error_text", True, blocking=False, detail="no visible text captured")
        leaks = [pattern.pattern for pattern in _RAW_INTERNAL if pattern.search(text)]
        if leaks and result.status == "failed":
            return Check(
                "owner.error_text",
                False,
                detail=f"raw internal detail shown to the owner: {leaks[0]}",
            )
        return Check("owner.error_text", True, detail="no raw internals in owner-facing text")

    def _images(self, result: FlowResult) -> Check:
        broken = (result.observations.page_metrics or {}).get("brokenImages")
        if isinstance(broken, int) and broken > 0:
            return Check("page.images", False, detail=f"{broken} image(s) failed to load")
        return Check("page.images", True, detail="no broken images")


def _visible_text(result: FlowResult) -> str:
    """What the owner could actually read on screen.

    Deliberately excludes the harness's own step details: a DriverError message
    is not something the owner ever saw.
    """

    return str((result.observations.page_metrics or {}).get("bodyText") or "")


def review(result: FlowResult, *, judge: Any | None = None) -> JudgeVerdict:
    return (judge or RuleJudge()).review(result)


_JUDGE_SYSTEM = """You review evidence from an autonomous website-build pipeline.
You never see the product's source. You see what a real browser observed.
Answer only from the evidence. If the evidence is insufficient, say so instead
of guessing.

Return strict JSON:
{"verdict": "pass" | "fail" | "needs_review",
 "findings": [{"severity": "blocking" | "advisory", "summary": "...", "evidence": "..."}]}

Judge these, and nothing else:
1. Would the owner understand what happened and what to do next?
2. Does the result reflect the brief the owner confirmed, or a generic template?
3. Is anything visibly broken, empty, or contradictory?
"""


class ModelJudge:
    """Advisory model review. Never a gate.

    ``complete`` is any callable taking the prompt and returning the model's
    text, so this module needs no provider dependency and the same seam works
    for a recorded response in the deterministic tier.
    """

    name = "model"

    def __init__(self, complete: Callable[[str], str], *, model: str | None = None) -> None:
        self.complete = complete
        self.model = model

    def review(self, result: FlowResult) -> JudgeVerdict:
        prompt = _JUDGE_SYSTEM + "\n\nEVIDENCE\n" + json.dumps(_digest(result), indent=2)
        try:
            raw = self.complete(prompt)
        except Exception as exc:
            return JudgeVerdict(
                verdict="needs_review",
                judge=self.name,
                reasons=[f"judge unavailable: {type(exc).__name__}: {exc}"],
            )
        parsed = _parse(raw)
        if parsed is None:
            return JudgeVerdict(
                verdict="needs_review",
                judge=self.name,
                reasons=["judge did not return parseable JSON"],
            )
        verdict = str(parsed.get("verdict") or "needs_review")
        if verdict not in ("pass", "fail", "needs_review"):
            verdict = "needs_review"
        return JudgeVerdict(
            verdict=verdict,
            judge=self.name,
            findings=[item for item in parsed.get("findings") or () if isinstance(item, Mapping)],
            reasons=[str(parsed.get("summary"))] if parsed.get("summary") else [],
        )


def _digest(result: FlowResult) -> dict[str, Any]:
    return {
        "flow": {"id": result.flow.id, "title": result.flow.title, "tier": result.flow.tier},
        "status": result.status,
        "error": result.error,
        "steps": [
            {
                "id": step.id,
                "action": step.action,
                "status": step.status,
                "detail": step.detail,
                "screenshot": step.screenshot,
            }
            for step in result.steps
        ],
        "observations": result.observations.to_dict(),
    }


def _parse(raw: str) -> Mapping[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, Mapping) else None
