"""Command line entry point.

The project runner only needs three things from this: an exit code, one JSON
bundle, and a stable fingerprint. Everything else is for humans.

    python -m site_agent.qa list
    python -m site_agent.qa run flows/intake-to-preview.flow.yaml \\
        --base-url http://127.0.0.1:3012 \\
        --sha "$GITHUB_SHA" \\
        --evidence-dir .tick/site-agent/evidence
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .driver import DriverError, PlaywrightDriver
from .evidence import build_bundle, utcnow, write_bundle
from .flow import Flow, FlowError, load_flow, load_flows
from .rubric import RuleJudge

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        return _list(args)
    if args.command == "run":
        return _run(args)
    parser.print_help()
    return EXIT_ERROR


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="site-agent-qa",
        description="Drive declarative end-to-end flows in a real browser.",
    )
    sub = parser.add_subparsers(dest="command")

    listing = sub.add_parser("list", help="list available flows")
    listing.add_argument("--root", default="flows", help="flow directory (default: flows)")

    run = sub.add_parser("run", help="run one flow or every flow in a directory")
    run.add_argument("flow", help="flow file, or a directory of flows")
    run.add_argument("--base-url", required=True, help="target origin, e.g. http://127.0.0.1:3012")
    run.add_argument("--sha", help="source revision under test")
    run.add_argument("--deployed-sha", help="revision actually serving the target")
    run.add_argument("--environment", default="local", help="local | staging | production")
    run.add_argument("--evidence-dir", default=".qa/evidence", help="where evidence JSON is written")
    run.add_argument("--artifacts-dir", default=".qa/artifacts", help="where screenshots are written")
    run.add_argument("--timeout-ms", type=int, default=30_000)
    run.add_argument("--viewport", default="1280x900", help="WIDTHxHEIGHT")
    run.add_argument("--no-screenshots", action="store_true")
    run.add_argument("--json", action="store_true", help="print the bundle instead of a summary")
    return parser


def _list(args: argparse.Namespace) -> int:
    try:
        flows = load_flows(args.root)
    except FlowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not flows:
        print(f"no flows found under {args.root}", file=sys.stderr)
        return EXIT_ERROR
    for flow in flows:
        print(f"{flow.id:<32} {flow.tier:<14} {flow.title}")
    return EXIT_PASS


def _run(args: argparse.Namespace) -> int:
    try:
        flows = _resolve(args.flow)
    except FlowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    width, _, height = args.viewport.partition("x")
    exit_code = EXIT_PASS
    bundles = []
    for flow in flows:
        try:
            driver = PlaywrightDriver(
                base_url=args.base_url,
                artifacts_dir=Path(args.artifacts_dir) / flow.id,
                timeout_ms=args.timeout_ms,
                viewport={"width": int(width), "height": int(height)},
                screenshots=not args.no_screenshots,
            )
            started = utcnow()
            result = driver.run(flow)
            verdict = RuleJudge().review(result)
            bundle = build_bundle(
                result,
                verdict=verdict,
                artifacts_dir=Path(args.artifacts_dir) / flow.id,
                target={
                    "sha": args.sha,
                    "deployed_sha": args.deployed_sha,
                    "environment": args.environment,
                },
                started_at=started,
            )
            path = write_bundle(bundle, Path(args.evidence_dir) / f"{flow.id}.json")
            bundles.append(bundle)
        except DriverError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        if args.json:
            print(json.dumps(bundle, indent=2))
        else:
            _print_summary(bundle, path)
        if not bundle["rubric"]["passed"] or bundle["status"] != "passed":
            exit_code = EXIT_FAIL
    return exit_code


def _resolve(target: str) -> tuple[Flow, ...]:
    path = Path(target)
    if path.is_dir():
        flows = load_flows(path)
        if not flows:
            raise FlowError(f"no flows found under {path}")
        return flows
    return (load_flow(path),)


def _print_summary(bundle: dict, path: Path) -> None:
    status = "PASS" if bundle["status"] == "passed" and bundle["rubric"]["passed"] else "FAIL"
    print(f"[{status}] {bundle['flow']['id']} ({bundle['flow']['tier']})")
    for step in bundle["steps"]:
        mark = {"passed": "ok", "failed": "FAIL", "skipped": "skip", "pending": "..."}.get(
            step["status"], step["status"]
        )
        print(f"  {mark:<5} {step['id']:<28} {step['duration_ms']:>5}ms  {step['detail']}")
    for reason in bundle["rubric"]["reasons"]:
        print(f"  reason: {reason}")
    print(f"  fingerprint {bundle['fingerprint']}")
    print(f"  evidence    {path}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
