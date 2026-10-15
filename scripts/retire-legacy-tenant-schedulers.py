#!/usr/bin/env python3
"""Retire the known per-tenant scheduler after the shared API takes ownership."""
from __future__ import annotations

import configparser
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable


UNIT_NAME = "site-agent@.service"
RETIRED_NAME = "site-agent@.service.retired"
INSTANCE_RE = re.compile(r"^site-agent@.+\.service$")
ACTIVE_STATES = {"active", "activating", "reloading", "deactivating"}
ENABLED_STATES = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}
EXPECTED_UNIT = {
    "Unit": {
        "Description": "site-agent (%i)",
        "After": "network-online.target",
        "Wants": "network-online.target",
    },
    "Service": {
        "Environment": "PYTHONUNBUFFERED=1",
        "Type": "simple",
        "User": "admin",
        "WorkingDirectory": "/SOCIAL/configs/%i",
        "EnvironmentFile": "/SOCIAL/configs/%i/.env",
        "ExecStart": "/SOCIAL/site-agent/.venv/bin/python -m site_agent run --config /SOCIAL/configs/%i/config.yaml",
        "Restart": "on-failure",
        "RestartSec": "15",
        "NoNewPrivileges": "true",
        "PrivateTmp": "true",
    },
    "Install": {"WantedBy": "multi-user.target"},
}


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def _verified_template(path: Path) -> bool:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (OSError, configparser.Error) as exc:
        raise RuntimeError(f"cannot validate legacy unit {path.name}") from exc
    actual = {section: dict(parser.items(section)) for section in parser.sections()}
    if actual != EXPECTED_UNIT:
        raise RuntimeError(f"refusing to alter unrecognized unit {path.name}")
    return True


def _unit_instances(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and INSTANCE_RE.fullmatch(fields[0]):
            result[fields[0]] = fields[2]
    return result


def _unit_file_states(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and INSTANCE_RE.fullmatch(fields[0]):
            result[fields[0]] = fields[1]
    return result


def retire_legacy_tenant_schedulers(
    unit_dir: Path = Path("/etc/systemd/system"),
    *,
    runner: Callable[..., str] = run,
) -> dict[str, object]:
    """Stop only registered instances of the exact obsolete tenant unit.

    The unit is renamed, not deleted, so host recovery remains possible. Unknown
    unit contents or a pre-existing backup cause a fail-closed error.
    """
    unit_path = unit_dir / UNIT_NAME
    retired_path = unit_dir / RETIRED_NAME
    instances = _unit_instances(
        runner(["systemctl", "list-units", "--all", "--plain", "--no-legend", "site-agent@*.service"], capture=True)
    )
    file_states = _unit_file_states(
        runner(["systemctl", "list-unit-files", "--plain", "--no-legend", "site-agent@*.service"], capture=True)
    )
    if unit_path.exists():
        _verified_template(unit_path)
        if retired_path.exists():
            raise RuntimeError("legacy unit and its recovery copy both exist")
    elif retired_path.exists():
        _verified_template(retired_path)
    elif instances or file_states:
        raise RuntimeError("tenant scheduler instances exist without a verified unit template")
    else:
        return {"retired": False, "stoppedInstances": []}

    stopped: list[str] = []
    for name in sorted(set(instances) | set(file_states)):
        active = instances.get(name) in ACTIVE_STATES
        enabled = file_states.get(name) in ENABLED_STATES
        if active:
            runner(["systemctl", "stop", name])
            stopped.append(name)
        if enabled:
            runner(["systemctl", "disable", name])

    if unit_path.exists():
        runner(["systemctl", "disable", UNIT_NAME])
        unit_path.rename(retired_path)
        runner(["systemctl", "daemon-reload"])

    remaining_active = _unit_instances(
        runner(["systemctl", "list-units", "--all", "--plain", "--no-legend", "site-agent@*.service"], capture=True)
    )
    remaining_files = _unit_file_states(
        runner(["systemctl", "list-unit-files", "--plain", "--no-legend", "site-agent@*.service"], capture=True)
    )
    if any(state in ACTIVE_STATES for state in remaining_active.values()):
        raise RuntimeError("a tenant scheduler instance remains active")
    if any(state in ENABLED_STATES for state in remaining_files.values()):
        raise RuntimeError("a tenant scheduler instance remains enabled")
    return {"retired": unit_path.exists() is False and retired_path.exists(), "stoppedInstances": stopped}


def main() -> int:
    try:
        print(json.dumps(retire_legacy_tenant_schedulers(), sort_keys=True))
    except Exception as exc:  # keep host details out of standard output
        print(f"legacy scheduler retirement failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
