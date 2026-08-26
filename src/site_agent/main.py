from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from . import __version__
from .config import ConfigError, data_dir, load, mask_secrets, resolve_env
from .core.jobs import register_builtin
from .core.memory import Memory
from .core.reflect import effective_persona
from .core.scheduler import Scheduler
from .runtime import Runtime
from .site_scaffold import initialize_site


class AdminProcessLock:
    """Exclusive per-instance lock for the long-lived admin process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is None:
            return
        import fcntl

        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


def _cmd_check(args: argparse.Namespace) -> int:
    config, sources = load(args.config)
    print(f"site-agent {__version__}")
    print("config sources:")
    for source in sources:
        print(f"  - {source}")
    env_state = resolve_env(config)
    missing = [name for name, info in env_state.items() if not info["set"]]
    print(f"env: set={[n for n in env_state if env_state[n]['set']]} missing={missing}")
    print(yaml.safe_dump(mask_secrets(config), sort_keys=False))
    return 0


def _cmd_init_site(args: argparse.Namespace) -> int:
    root = initialize_site(args.directory, args.name, args.url)
    print(f"initialized Pelican site: {root}")
    print("created: homepage, about page, contact page, articles collection, Ada theme, and build.sh")
    return 0


def _build_runtime(args: argparse.Namespace):
    from .core.llm import Client

    config, _ = load(args.config)
    memory = Memory(data_dir(config) / "memory.db")
    llm = Client(config, memory)
    scheduler = Scheduler(memory, lock_path=data_dir(config) / "scheduler.lock")
    runtime = Runtime(config, memory, scheduler, llm, effective_persona(config, memory))
    context = runtime.context()
    register_builtin(scheduler, config, context)
    return config, memory, scheduler, context


def _cmd_once(args: argparse.Namespace) -> int:
    config, memory, scheduler, _context = _build_runtime(args)
    try:
        if not scheduler.acquire_lock():
            print("[site-agent] another cycle is already running; skipping", file=sys.stderr)
            return 1
        try:
            ran = scheduler.run_once()
            print(f"[site-agent] instance={config['instance_name']} jobs ran: {ran or '(none due)'}")
            spend = memory.llm_spend()
            print(
                f"[site-agent] 24h llm spend: ${spend['cost_usd']:.4f} "
                f"({spend['prompt_tokens']} in / {spend['completion_tokens']} out)"
            )
        finally:
            scheduler.release_lock()
    finally:
        memory.close()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config, memory, scheduler, _context = _build_runtime(args)
    poll = int(config.get("poll_seconds", 300))
    print(f"[site-agent] instance={config['instance_name']} polling every {poll}s")
    try:
        if not scheduler.acquire_lock():
            print("[site-agent] another cycle is already running", file=sys.stderr)
            return 1
        try:
            import time

            while True:
                scheduler.run_once()
                time.sleep(poll)
        finally:
            scheduler.release_lock()
    except KeyboardInterrupt:
        print("[site-agent] shutting down")
    finally:
        memory.close()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web.server import create_app

    config, memory, scheduler, context = _build_runtime(args)
    lock = AdminProcessLock(data_dir(config) / "admin.lock")
    if not lock.acquire():
        print("[site-agent] another admin server is already running", file=sys.stderr)
        memory.close()
        return 1
    app = create_app(context)
    admin = config.get("admin") or {}
    print(f"[site-agent] admin UI on http://{admin.get('host', '127.0.0.1')}:{admin.get('port', 3011)}")
    try:
        uvicorn.run(app, host=str(admin.get("host", "127.0.0.1")), port=int(admin.get("port", 3011)), log_level="warning")
    finally:
        lock.release()
        memory.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="site-agent", description="Portable AI website content manager")
    parser.add_argument("--version", action="version", version=f"site-agent {__version__}")
    parser.add_argument("--config", help="path to instance config.yaml")
    common = argparse.ArgumentParser(add_help=False)
    # Do not let a subcommand's absent option overwrite a global option that
    # appeared before the subcommand: both CLI forms are documented.
    common.add_argument("--config", default=argparse.SUPPRESS, help="path to instance config.yaml")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", parents=[common], help="print resolved merged config with secrets masked")
    sub.add_parser("once", parents=[common], help="run all due jobs and exit")
    sub.add_parser("run", parents=[common], help="run the scheduler loop (long-lived)")
    sub.add_parser("serve", parents=[common], help="run admin web server (Phase 4)")
    init_parser = sub.add_parser("init-site", help="create the standard Pelican starting point in an empty site directory")
    init_parser.add_argument("--directory", required=True, help="empty customer website directory")
    init_parser.add_argument("--name", default="New Website", help="customer website name")
    init_parser.add_argument("--url", default="", help="public website URL")

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    if getattr(args, "config", None) is None:
        args.config = None
    handlers = {"check": _cmd_check, "once": _cmd_once, "run": _cmd_run, "serve": _cmd_serve,
                "init-site": _cmd_init_site}
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except ConfigError as exc:
        print(f"[site-agent] configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
