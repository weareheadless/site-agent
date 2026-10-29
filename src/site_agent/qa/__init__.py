"""Autonomous end-to-end flow validation.

A *flow* is a declarative, reviewable scenario that drives the real product
surface in a real browser and asserts what actually happened. Flows are the
evidence producers for release gates: they emit a stable evidence bundle that
the project runner can consume without knowing anything about browsers.

Two tiers, deliberately separate:

* **Deterministic tier** -- recorded or stubbed provider responses, a disposable
  workspace, no spend. This is the regression gate and runs on every change.
* **Live tier** -- real generation against a deployed target. This is a release
  gate, never a pull-request check.

The browser driver only reports what it observed. Judgement about whether the
result is *good* lives in :mod:`site_agent.qa.rubric`, and the default rubric is
deterministic so a gate never depends on a model's opinion.
"""

from .driver import DriverError, FlowResult, PlaywrightDriver
from .evidence import EVIDENCE_SCHEMA, build_bundle, fingerprint, write_bundle
from .flow import Expectation, Flow, FlowError, Step, load_flow
from .rubric import JudgeVerdict, ModelJudge, RuleJudge, review

__all__ = [
    "EVIDENCE_SCHEMA",
    "DriverError",
    "Expectation",
    "Flow",
    "FlowError",
    "FlowResult",
    "JudgeVerdict",
    "ModelJudge",
    "PlaywrightDriver",
    "RuleJudge",
    "Step",
    "build_bundle",
    "fingerprint",
    "load_flow",
    "review",
    "write_bundle",
]
