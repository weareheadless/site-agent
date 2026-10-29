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
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

from .conversation import chat_completion, opencode_completion
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
    run.add_argument(
        "--ledger",
        help="JSON file recording the one test site this harness owns; the next run removes it",
    )
    run.add_argument(
        "--allow-destructive",
        action="store_true",
        help="permit removing the previously recorded test site (test/local targets only)",
    )
    run.add_argument(
        "--owner-model",
        default=os.environ.get("SITE_AGENT_QA_OWNER_MODEL", "openai/gpt-6-luna"),
        help="owner model (default: openai/gpt-6-luna via the runner's OpenCode auth)",
    )
    run.add_argument(
        "--owner-backend", choices=("opencode", "compatible-api"),
        default=os.environ.get("SITE_AGENT_QA_OWNER_BACKEND", "opencode"),
        help="opencode reuses runner authentication; compatible-api is explicit opt-in",
    )
    run.add_argument(
        "--owner-api-key-env",
        default=os.environ.get("SITE_AGENT_QA_OWNER_KEY_ENV", "OPENROUTER_API_KEY"),
        help="environment variable holding the owner model's key (default: OPENROUTER_API_KEY)",
    )
    run.add_argument(
        "--owner-base-url",
        default=os.environ.get("SITE_AGENT_QA_OWNER_BASE_URL", "https://openrouter.ai/api/v1"),
    )
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
    # Validate the owner backend before any destructive test-target cleanup.
    owner_complete = _owner_completer(args) if any(
        step.action == "converse" for flow in flows for step in flow.steps
    ) else None
    if args.ledger:
        purged, problem = purge_ledger(
            args.ledger,
            base_url=args.base_url,
            environment=args.environment,
            allow_destructive=args.allow_destructive,
        )
        if problem:
            print(f"error: {problem}", file=sys.stderr)
            return EXIT_ERROR
        if purged:
            print(f"removed {len(purged)} previous test site(s): {', '.join(purged)}")
    probe = probe_target(args.base_url)
    for flow in flows:
        try:
            driver = PlaywrightDriver(
                base_url=args.base_url,
                artifacts_dir=Path(args.artifacts_dir) / flow.id,
                timeout_ms=args.timeout_ms,
                viewport={"width": int(width), "height": int(height)},
                screenshots=not args.no_screenshots,
                owner_complete=owner_complete,
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
                    **probe,
                },
                started_at=started,
            )
            if owner_complete is not None:
                bundle["test_owner"] = {"backend": args.owner_backend, "model": args.owner_model}
            path = write_bundle(bundle, Path(args.evidence_dir) / f"{flow.id}.json")
            bundles.append(bundle)
            if args.ledger and result.incubation_id:
                record_ledger(
                    args.ledger,
                    {
                        "incubation_id": result.incubation_id,
                        "flow": flow.id,
                        "sha": args.sha,
                        "status": result.status,
                        "recorded_at": bundle["finished_at"],
                    },
                )
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


def purge_ledger(
    path: str | Path,
    *,
    base_url: str,
    environment: str,
    allow_destructive: bool,
) -> tuple[list[str], str | None]:
    """Remove the test site the previous run left live.

    The harness never guesses which site is disposable. It only removes what its
    own ledger says it created, and only against a target that is declared
    non-production. One live test site at a time, by construction.
    """

    if environment not in ("test", "local"):
        return [], f"refusing to remove a test site against environment {environment!r}"
    if not allow_destructive:
        return [], "removing the previous test site requires --allow-destructive"
    ledger = Path(path)
    entries = _read_ledger(ledger)
    removed: list[str] = []
    for entry in entries:
        identifier = str(entry.get("incubation_id") or "")
        if not identifier:
            continue
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/incubations/{identifier}", method="DELETE"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if 200 <= response.status < 300:
                    removed.append(identifier)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                removed.append(identifier)
        except OSError as exc:
            return removed, f"could not remove {identifier}: {exc}"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("[]\n", encoding="utf-8")
    return removed, None


def record_ledger(path: str | Path, entry: dict) -> None:
    ledger = Path(path)
    entries = _read_ledger(ledger)
    entries.append(entry)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def _read_ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def probe_target(base_url: str) -> dict:
    """Record which model the target actually used, so runs stay comparable."""

    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/lab", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    model = payload.get("model")
    engine = payload.get("engine")
    if not model and isinstance(engine, dict):
        model = engine.get("model")
    return {
        "model": model,
        "provider": payload.get("provider"),
        "site_name": payload.get("site_name"),
    }


def _owner_completer(args: argparse.Namespace):
    """Build the owner model, or nothing when the flow needs no conversation."""

    if not args.owner_model:
        return None
    if args.owner_backend == "opencode":
        return opencode_completion(model=args.owner_model)
    key = os.environ.get(args.owner_api_key_env, "").strip()
    if not key:
        print(
            f"error: --owner-model needs a key in ${args.owner_api_key_env}",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_ERROR)
    model = args.owner_model
    if model.startswith("openrouter/"):
        model = model[len("openrouter/") :]
    return chat_completion(model=model, api_key=key, base_url=args.owner_base_url)


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
    model = (bundle.get("target") or {}).get("model")
    suffix = f"  model={model}" if model else ""
    print(f"[{status}] {bundle['flow']['id']} ({bundle['flow']['tier']}){suffix}")
    for step in bundle["steps"]:
        mark = {"passed": "ok", "failed": "FAIL", "skipped": "skip", "pending": "..."}.get(
            step["status"], step["status"]
        )
        extra = f"  [{step['turns']} turns]" if step.get("turns") else ""
        print(f"  {mark:<5} {step['id']:<28} {step['duration_ms']:>7}ms  {step['detail']}{extra}")
    timings = bundle.get("timings") or {}
    for name, seconds in (timings.get("durations_s") or {}).items():
        print(f"  time  {name:<28} {_human(seconds)}")
    if timings.get("total_s") is not None:
        print(f"  time  {'total':<28} {_human(timings['total_s'])}")
    for reason in bundle["rubric"]["reasons"]:
        print(f"  reason: {reason}")
    print(f"  fingerprint {bundle['fingerprint']}")
    print(f"  evidence    {path}")


def _human(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m {rest:02d}s"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
