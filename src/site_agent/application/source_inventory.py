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
            locations = [
                f"{item.get('path')}:{item.get('line')} ({item.get('reason')})"
                for item in violations[:8]
                if isinstance(item, dict)
            ]
            more = len(violations) - len(locations)
            suffix = f" and {more} more" if more > 0 else ""
            raise ValueError("presentation violates the Payload content/binding contract: " + ", ".join(locations) + suffix)
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
        print(json.dumps(inventory(args.root), ensure_ascii=False, sort_keys=True))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
