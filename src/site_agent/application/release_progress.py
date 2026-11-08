"""Owner-facing progress for one approved production release.

The VPS release runner writes a receipt after every stage. The owner does not
need the pipeline's internal vocabulary: they need to know whether their change
is still being built, is going live, is verified, or stopped and why. This
module is the single translation from receipt stage to that answer, so the
admin, the API and any future surface describe a release the same way.
"""

from __future__ import annotations

from typing import Any, Mapping

# Ordered stages the release runner can report, with the fraction of the work
# each one completes. Values are cumulative and monotonic: a stage that repeats
# (verification runs before and after promotion) never moves the bar backwards.
_STAGE_PROGRESS: tuple[tuple[str, float], ...] = (
    ("queued_on_vps", 0.03),
    ("preflight", 0.05),
    ("credentials", 0.07),
    ("checkout", 0.10),
    ("shared-runtime-overlay", 0.14),
    ("dependencies", 0.22),
    ("generate-payload-contract", 0.27),
    ("initialize-schema", 0.30),
    ("migrate-schema", 0.30),
    ("verify-workspace-bootstrap-contract", 0.31),
    ("verify-payload-contract", 0.32),
    ("typecheck", 0.38),
    ("build", 0.52),
    ("artifact-verified", 0.58),
    ("provision-mailflare-resources", 0.60),
    ("migrate-mailflare-schema", 0.62),
    ("provision-turnstile", 0.64),
    ("deploy-durable-object-lifecycle", 0.68),
    ("upload", 0.74),
    ("promote", 0.82),
    ("reconcile-cron-triggers", 0.85),
    ("reconcile-queue-consumers", 0.87),
    ("verify-deployment", 0.90),
    ("enable-workers-dev", 0.92),
    ("verify-preview", 0.93),
    ("verify-connection", 0.95),
    ("awaiting-browser-verification", 0.98),
)

_PHASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("queued", "Queued", ("queued_on_vps",)),
    (
        "preparing",
        "Preparing the build",
        (
            "preflight",
            "credentials",
            "checkout",
            "shared-runtime-overlay",
            "dependencies",
            "generate-payload-contract",
            "initialize-schema",
            "migrate-schema",
            "verify-workspace-bootstrap-contract",
            "verify-payload-contract",
        ),
    ),
    ("building", "Building the site", ("typecheck", "build", "artifact-verified")),
    ("uploading", "Uploading", ("upload",)),
    (
        "going_live",
        "Switching the live site",
        (
            "provision-mailflare-resources",
            "migrate-mailflare-schema",
            "provision-turnstile",
            "deploy-durable-object-lifecycle",
            "promote",
            "reconcile-cron-triggers",
            "reconcile-queue-consumers",
        ),
    ),
    (
        "verifying",
        "Verifying the live site",
        ("verify-deployment", "enable-workers-dev", "verify-preview", "verify-connection"),
    ),
)

_STAGE_PHASE = {
    stage: phase
    for phase, _label, stages in _PHASES
    for stage in stages
}

_STAGE_LABELS = {
    "queued_on_vps": "Waiting for the release runner",
    "preflight": "Checking the release",
    "credentials": "Checking release access",
    "checkout": "Reading the approved code",
    "shared-runtime-overlay": "Applying the shared runtime",
    "dependencies": "Installing dependencies",
    "generate-payload-contract": "Generating the Payload contract",
    "initialize-schema": "Initialising the database",
    "migrate-schema": "Migrating the database",
    "verify-workspace-bootstrap-contract": "Verifying the workspace",
    "verify-payload-contract": "Verifying the content contract",
    "typecheck": "Type checking",
    "build": "Compiling the site",
    "artifact-verified": "Checking the build artifact",
    "provision-mailflare-resources": "Provisioning mail resources",
    "migrate-mailflare-schema": "Migrating mail storage",
    "provision-turnstile": "Provisioning form protection",
    "deploy-durable-object-lifecycle": "Deploying the durable object",
    "upload": "Uploading the new version",
    "promote": "Switching traffic to the new version",
    "reconcile-cron-triggers": "Registering scheduled jobs",
    "reconcile-queue-consumers": "Registering message consumers",
    "verify-deployment": "Verifying the deployment",
    "enable-workers-dev": "Enabling the preview origin",
    "verify-preview": "Verifying the owner-visible pages",
    "verify-connection": "Verifying the workspace connection",
    "awaiting-browser-verification": "Waiting for the owner-visible check",
}


def _stage_fraction(stage: str) -> float:
    for name, fraction in _STAGE_PROGRESS:
        if name == stage:
            return fraction
    return 0.0


def release_progress(stage: Any, status: Any) -> dict[str, Any]:
    """Describe one receipt state as owner-facing phase and progress."""
    normalized_stage = str(stage or "").strip()
    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"deployed", "verified"}:
        return {
            "phase": "live",
            "phaseLabel": "Live",
            "stage": normalized_stage or "deployed",
            "step": "The approved change is live.",
            "progress": 1.0,
            "complete": True,
            "failed": False,
        }
    if normalized_status in {"failed", "interrupted"}:
        return {
            "phase": "failed",
            "phaseLabel": "Stopped",
            "stage": normalized_stage or normalized_status,
            "step": _STAGE_LABELS.get(normalized_stage, "The release stopped."),
            "progress": _stage_fraction(normalized_stage),
            "complete": True,
            "failed": True,
        }
    phase = _STAGE_PHASE.get(normalized_stage, "preparing")
    label = next((item[1] for item in _PHASES if item[0] == phase), "Preparing the build")
    return {
        "phase": phase,
        "phaseLabel": label,
        "stage": normalized_stage or "queued_on_vps",
        "step": _STAGE_LABELS.get(normalized_stage, label),
        "progress": max(_stage_fraction(normalized_stage), 0.03),
        "complete": False,
        "failed": False,
    }


def phase_steps() -> list[dict[str, str]]:
    """The ordered owner-facing steps, for rendering the progress rail."""
    return [{"phase": phase, "label": label} for phase, label, _stages in _PHASES]


__all__ = ["phase_steps", "release_progress"]
