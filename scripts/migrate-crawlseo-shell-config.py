#!/usr/bin/env python3
"""Remove CrawlSEO connector settings that belong to the shell from tenant files.

The shell owns one CrawlSEO connection: ``providers.crawlseo.url``,
``connector_url``, ``connector_token_env``, timeouts and response limits live in
``defaults.yaml``. A tenant file keeps only what is genuinely its own - the
research-authority decision and, when it has reached a credential stage that
differs from the shell default, the credential name.

The migration is idempotent and fails closed: it refuses to strip a value that
differs from the shell default, because that would silently change behavior.
Run with ``--check`` to report, ``--apply`` to write.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from site_agent.application.seo_bootstrap import load_tenant_environment
from site_agent.config import CrawlSEOSettings, effective_config

SHELL_KEYS = (
    "enabled",
    "url",
    "token_env",
    "connector_url",
    "timeout_seconds",
    "max_response_bytes",
)
CREDENTIAL_STAGE_KEY = "connector_token_env"
PER_TENANT_KEYS = {"research_authority"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strip(raw: Mapping[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Return the tenant-only config plus the keys removed and retained."""
    document = copy.deepcopy(dict(raw))
    providers = document.get("providers")
    if not isinstance(providers, Mapping):
        return document, [], []
    provider = providers.get("crawlseo")
    if not isinstance(provider, Mapping) or not provider:
        return document, [], []
    shell = effective_config(raw)
    shell_provider = _mapping(_mapping(shell.get("providers")).get("crawlseo"))
    stripped = dict(provider)
    removed: list[str] = []
    for key in SHELL_KEYS:
        if key not in stripped:
            continue
        stripped.pop(key)
        removed.append(key)
    if CREDENTIAL_STAGE_KEY in stripped:
        if stripped[CREDENTIAL_STAGE_KEY] == shell_provider.get(CREDENTIAL_STAGE_KEY):
            stripped.pop(CREDENTIAL_STAGE_KEY)
            removed.append(CREDENTIAL_STAGE_KEY)
    unknown = sorted(set(stripped) - PER_TENANT_KEYS - {CREDENTIAL_STAGE_KEY})
    new_providers = dict(providers)
    if stripped:
        new_providers["crawlseo"] = stripped
    else:
        new_providers.pop("crawlseo", None)
    if new_providers:
        document["providers"] = new_providers
    else:
        document.pop("providers", None)
    return document, removed, unknown


def _settings(config: Mapping[str, Any], env: Mapping[str, str]) -> CrawlSEOSettings:
    return CrawlSEOSettings.from_config(effective_config(config), dict(env))


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, path.stat().st_mode & 0o777)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/SOCIAL/site-agent-api/websites")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.check == args.apply:
        parser.error("choose exactly one of --check or --apply")
    root = Path(args.root).expanduser().resolve()
    index = root / "tenants.json"
    if not index.is_file():
        print(f"tenant registry not found: {index}", file=sys.stderr)
        return 2
    registry = json.loads(index.read_text(encoding="utf-8"))
    if not isinstance(registry, Mapping):
        print("tenant registry must be an object", file=sys.stderr)
        return 2

    changed = 0
    refused = 0
    for tenant_id in sorted(registry):
        entry = _mapping(registry[tenant_id])
        raw_path = str(entry.get("config_path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_file() or path.is_symlink():
            print(f"{tenant_id}: config unavailable at {path}", file=sys.stderr)
            refused += 1
            continue
        raw = yaml.safe_load(path.read_bytes().decode("utf-8")) or {}
        if not isinstance(raw, Mapping) or raw.get("instance_name") != tenant_id:
            print(f"{tenant_id}: config does not declare this tenant", file=sys.stderr)
            refused += 1
            continue
        stripped, removed, unknown = _strip(raw)
        if not removed:
            continue
        env = load_tenant_environment(copy.deepcopy(dict(raw)), os.environ)
        before = _settings(raw, env)
        after = _settings(stripped, env)
        drift = [
            name
            for name in ("enabled", "token_env", "url", "connector_url", "connector_token_env", "research_authority")
            if getattr(before, name) != getattr(after, name)
        ]
        if drift:
            print(
                f"{tenant_id}: refusing to strip {', '.join(removed)}; effective "
                f"{', '.join(drift)} would change. Align the tenant with the shell defaults first.",
                file=sys.stderr,
            )
            refused += 1
            continue
        if unknown:
            print(f"{tenant_id}: warning: unrecognized provider keys kept: {', '.join(unknown)}")
        print(f"{tenant_id}: strip {', '.join(removed)} (mapped={after.enabled}, authority={after.research_authority})")
        if args.apply:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = path.with_name(f"{path.name}.before-crawlseo-shell-{stamp}")
            backup.write_bytes(path.read_bytes())
            _atomic_write(path, yaml.safe_dump(stripped, sort_keys=False, allow_unicode=True).encode("utf-8"))
        changed += 1

    verb = "migrated" if args.apply else "would migrate"
    print(f"{verb} {changed} tenant(s); {refused} refused")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
