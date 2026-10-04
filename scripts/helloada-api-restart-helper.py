#!/usr/bin/env python3
"""Fixed-function systemd restart broker for the shared site-agent API."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import BinaryIO, Callable


COMMAND = ["/usr/bin/systemctl", "restart", "site-agent-api.service"]
REQUEST = b"restart\n"
RESPONSE_OK = b"restarted\n"


def serve(reader: BinaryIO, writer: BinaryIO, *,
          run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> int:
    request = reader.readline(16)
    if request != REQUEST or reader.read(1):
        writer.write(b"invalid\n")
        writer.flush()
        return 2

    try:
        result = run_command(
            COMMAND,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"fixed API restart failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        writer.write(b"error\n")
        writer.flush()
        return 1

    if result.returncode:
        if result.stderr:
            print(result.stderr[:2048], file=sys.stderr, end="", flush=True)
        writer.write(b"error\n")
        writer.flush()
        return 1

    writer.write(RESPONSE_OK)
    writer.flush()
    return 0


def main() -> int:
    if os.geteuid() != 0:
        print("restart broker must run as root", file=sys.stderr)
        return 1
    return serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
