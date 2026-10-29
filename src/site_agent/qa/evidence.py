"""Evidence bundles: the contract between the harness and the release gate.

The project runner must be able to decide without understanding browsers, flows
or Playwright. So a run produces one JSON document with a versioned schema, a
stable fingerprint for deduplication, and content hashes for every artifact it
references.

Schema changes are additive and bump ``EVIDENCE_SCHEMA``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .driver import FlowResult
from .rubric import JudgeVerdict

EVIDENCE_SCHEMA = "site-agent.qa.evidence/1"
_RUN_ID = re.compile(r"[^a-z0-9]+")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(result: FlowResult, verdict: JudgeVerdict | None = None) -> str:
    """Stable identity for a failure, so repeated runs dedupe to one issue.

    Deliberately excludes timestamps, URLs that carry ids, and message text that
    embeds generated values.
    """

    failing = next((step for step in result.steps if step.status == "failed"), None)
    parts = [
        "flow=" + result.flow.id,
        "step=" + (failing.id if failing else "none"),
        "error=" + _error_class(result.error or (failing.detail if failing else "")),
    ]
    if failing:
        kinds = ",".join(
            sorted(item.expectation.kind for item in failing.assertions if not item.passed)
        )
        parts.append("expect=" + (kinds or "none"))
    if verdict is not None:
        parts.append("rubric=" + ",".join(sorted(verdict.failed_checks)))
    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _error_class(message: str) -> str:
    text = (message or "").strip().splitlines()[0] if message else ""
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120] or "unknown"


def timings(
    result: FlowResult,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    """Wall-clock cost of each named mark, and of the run.

    Marks are what the owner feels: how long the conversation took, how long the
    build took, how long provisioning took. Seconds, not opinions.
    """

    def parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    ordered = sorted(
        ((name, parse(stamp)) for name, stamp in result.marks.items() if parse(stamp)),
        key=lambda item: item[1],
    )
    durations: dict[str, float] = {}
    previous: datetime | None = parse(started_at)
    for name, stamp in ordered:
        if previous is not None and stamp is not None:
            durations[name] = round((stamp - previous).total_seconds(), 1)
        previous = stamp
    total: float | None = None
    start, end = parse(started_at), parse(finished_at)
    if start and end:
        total = round((end - start).total_seconds(), 1)
    return {
        "marks": {name: stamp.strftime("%Y-%m-%dT%H:%M:%SZ") for name, stamp in ordered},
        "durations_s": durations,
        "total_s": total,
    }


def run_id(flow_id: str, stamp: str | None = None) -> str:
    raw = f"{flow_id}-{stamp or utcnow()}".lower()
    identifier = _RUN_ID.sub("-", raw).strip("-")
    return identifier if stamp else identifier + '-' + uuid.uuid4().hex[:12]


def build_bundle(
    result: FlowResult,
    *,
    verdict: JudgeVerdict,
    artifacts_dir: str | Path,
    target: Mapping[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    finished_at = finished_at or utcnow()
    started_at = started_at or finished_at
    root = Path(artifacts_dir)
    files = []
    for name in result.artifacts:
        path = root / name
        if path.is_file():
            files.append({"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {
        "schema": EVIDENCE_SCHEMA,
        "run_id": run_id(result.flow.id),
        "fingerprint": fingerprint(result, verdict),
        "flow": {
            "id": result.flow.id,
            "title": result.flow.title,
            "tier": result.flow.tier,
            "source": result.flow.source_path,
            "requires": list(result.flow.requires),
            "tags": list(result.flow.tags),
        },
        "target": {
            "base_url": result.base_url,
            "sha": (target or {}).get("sha"),
            "deployed_sha": (target or {}).get("deployed_sha"),
            "environment": (target or {}).get("environment"),
            "model": (target or {}).get("model"),
            "provider": (target or {}).get("provider"),
        },
        "started_at": started_at or utcnow(),
        "finished_at": finished_at or utcnow(),
        "status": result.status,
        "failure_kind": result.failure_kind,
        "error": result.error,
        "failed_step": result.failed_step,
        "incubation_id": result.incubation_id,
        "timings": timings(result, started_at, finished_at),
        "steps": [step.to_dict() for step in result.steps],
        "observations": result.observations.to_dict(),
        "rubric": verdict.to_dict(),
        "artifacts": {"dir": str(root), "files": files},
    }


def write_bundle(bundle: Mapping[str, Any], destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(bundle, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path
