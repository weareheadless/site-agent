#!/usr/bin/env python3
"""Require immutable shared Payload package version bumps for source changes."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "helloada-payload-admin": ("packages/helloada-payload-admin", "src/version.ts", "HELLOADA_PAYLOAD_ADMIN_VERSION", "payload-admin"),
    "helloada-payload-core": ("packages/helloada-payload-core", "src/schema/index.ts", "HELLOADA_CORE_VERSION", "helloada-payload-core"),
}
TEMPLATE_PIN = "src/site_agent/templates/next-payload/package.json"

def changed_files(base: str) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"], cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.splitlines()

def marker_version(path: Path, marker: str) -> str | None:
    if not path.is_file():
        return None
    match = re.search(rf"\b{re.escape(marker)}\s*=\s*['\"]([^'\"]+)['\"]", path.read_text())
    return match.group(1) if match else None

def validate(files: list[str], base: str) -> list[str]:
    errors = []
    changed = set(files)
    for _, (directory, marker_file, marker, tag) in PACKAGES.items():
        if not any(path.startswith(f"{directory}/src/") for path in changed):
            continue
        old_text = subprocess.run(["git", "show", f"{base}:{directory}/package.json"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        old_version = json.loads(old_text)["version"]
        new_version = json.loads((ROOT / directory / "package.json").read_text()).get("version")
        marker_path = ROOT / directory / marker_file
        if not marker_path.is_file():
            errors.append(f"{directory}: required version marker file `{marker_file}` is missing.")
            continue
        marker_value = marker_version(marker_path, marker)
        if not new_version or new_version == old_version or marker_value != new_version:
            errors.append(f"{directory}/src/** changed: bump package.json version and {marker_file} marker to the same new value. Publish tag `{tag}-v{new_version}` and update the template pin in `{TEMPLATE_PIN}` to point at the new artifact.")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    errors = validate(changed_files(args.base), args.base)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Shared Payload package versions are valid.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
