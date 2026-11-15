#!/usr/bin/env python3
"""Prove a lane on a disposable tenant through the control-plane gateway.

The proof tenant comes from the canonical registry and must be declared
disposable; a customer site is refused before any request is made. Evidence is
written next to the release receipts so a lane change carries proof instead of
an anecdote. A failure is a refusal, not a warning.

    scripts/prove-lane.py --lane growth
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from site_agent.application.lane_proof import (  # noqa: E402
    LANES, LaneProofError, proof_tenant, prove_lane,
)


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=sorted(LANES), required=True)
    parser.add_argument("--tenant", help="a disposable tenant; defaults to the first registered one")
    parser.add_argument("--registry", type=Path, default=ROOT / "deploy/payload-customers.json")
    parser.add_argument("--api-url", default="https://api.helloada.app/v1")
    parser.add_argument("--env-file", type=Path, default=Path("/SOCIAL/configs/site-agent-api/.env"))
    parser.add_argument("--out", type=Path, default=Path("/SOCIAL/payload-releases/proofs"))
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    try:
        tenant = proof_tenant(registry, args.tenant)
        token = ""
        if args.env_file.is_file():
            token = _read_env(args.env_file).get("HELLOADA_CONTROL_PLANE_TOKEN", "")
        token = token or os.environ.get("HELLOADA_CONTROL_PLANE_TOKEN", "")
        evidence = prove_lane(args.lane, tenant=tenant, api_url=args.api_url, token=token)
    except LaneProofError as error:
        print(f"[lane-proof] refused: {error}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.lane}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
