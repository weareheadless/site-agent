"""Host-owned source inventory fallback for compiled tenant previews.

Customer repositories may be older than the optional TypeScript inventory
script.  Preview validation still needs a deterministic inventory receipt, but
it must not require a customer repo to carry site-agent tooling.  This module
intentionally reports repository-level facts only; Payload remains the source
of truth for editable content.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


_IGNORED_DIRS = frozenset({".git", ".next", ".open-next", "node_modules", "out", "coverage"})
_TEXT_SUFFIXES = frozenset({
    ".css", ".html", ".js", ".jsx", ".json", ".md", ".mjs", ".scss", ".ts", ".tsx", ".yaml", ".yml",
})


def inventory(root: str | Path) -> dict[str, object]:
    """Return a bounded, non-content inventory for a source checkout."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("source inventory root is not a directory")
    files_scanned = 0
    warnings: list[str] = []
    for path in directory.rglob("*"):
        if not path.is_file() or any(part in _IGNORED_DIRS for part in path.relative_to(directory).parts):
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        files_scanned += 1
    warnings.append("host-owned fallback inventory; Payload is the editable content source")
    return {
        "version": 1,
        "root": str(directory),
        "filesScanned": files_scanned,
        "editableCount": 0,
        "dynamicCount": 0,
        "fields": [],
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory a tenant source checkout for site-agent preview validation")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    print(json.dumps(inventory(args.root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
