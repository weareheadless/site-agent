"""Host-owned source inventory for compiled tenant previews.

The inventory implementation is part of site-agent, never loaded from or
executed out of a customer repository. It reports repository-level facts only;
Payload remains the source of truth for editable content.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def inventory(root: str | Path) -> dict[str, object]:
    """Run the host-owned TypeScript AST inventory over presentation source."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("source inventory root is not a directory")
    node = shutil.which("node")
    analyzer = Path(__file__).with_name("source_inventory_ast.mjs").resolve()
    if not node or not analyzer.is_file():
        raise ValueError("host TypeScript source inventory runtime is unavailable")
    safe_env = {
        key: str(os.environ[key])
        for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR")
        if os.environ.get(key)
    }
    try:
        result = subprocess.run(
            [node, str(analyzer), "--root", str(directory)],
            cwd=str(directory),
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"host TypeScript source inventory failed: {str(exc)[:250]}") from exc
    if result.returncode:
        try:
            decoded = json.loads(result.stdout)
        except json.JSONDecodeError:
            decoded = {}
        violations = decoded.get("violations") if isinstance(decoded, dict) else None
        if isinstance(violations, list) and violations:
            # A violation is a failed gate, not a tooling error: return the
            # report so the caller can name exact paths and lines. main() turns
            # it into a non-zero exit for the hard pre-build gate.
            if not isinstance(decoded.get("fields"), list):
                raise ValueError("host TypeScript source inventory returned an invalid shape")
            return decoded
        raise ValueError((result.stderr or "host TypeScript source inventory returned an invalid result")[:500].strip())
    try:
        decoded = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("host TypeScript source inventory did not return JSON") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("fields"), list) or not isinstance(decoded.get("violations"), list):
        raise ValueError("host TypeScript source inventory returned an invalid shape")
    return decoded


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory a tenant source checkout for site-agent preview validation")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        report = inventory(args.root)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)[:2_000]}, ensure_ascii=False, sort_keys=True))
        print(f"source inventory failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    # Violations are a failed gate, but the machine-readable report must always
    # reach the caller so the repair brief can name exact paths and lines.
    return 1 if report.get("violations") else 0


if __name__ == "__main__":
    raise SystemExit(main())
