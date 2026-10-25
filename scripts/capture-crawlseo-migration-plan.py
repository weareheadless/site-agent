"""Capture a read-only, hash-bound tenant migration plan from HelloAda."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def fetch_plan(api_url: str, website_id: str, token: str, timeout: float = 30) -> dict:
    parsed = urllib.parse.urlsplit(api_url)
    local_http_hosts = {"127.0.0.1", "localhost", "::1"}
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in local_http_hosts)):
        raise ValueError("API URL must use HTTPS (HTTP is allowed only for localhost)")
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("API URL must be an origin without credentials, path, query or fragment")
    base = api_url.rstrip("/")
    url = f"{base}/v1/control-plane/websites/{urllib.parse.quote(website_id, safe='')}/growth/migration-plan"
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Cache-Control": "no-store",
        "User-Agent": "HelloAda/migration-inventory",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"migration plan endpoint returned HTTP {response.status}")
            encoded = response.read(16 * 1024 * 1024 + 1)
            if len(encoded) > 16 * 1024 * 1024:
                raise ValueError("migration plan response exceeded the 16 MiB safety limit")
            body = json.loads(encoded)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"migration plan endpoint returned HTTP {exc.code}") from None
    if not isinstance(body, dict) or not isinstance(body.get("snapshotHash"), str) or not body["snapshotHash"]:
        raise ValueError("migration plan response has no snapshot hash")
    if body.get("tenant") != website_id:
        raise ValueError("migration plan website identity does not match the request")
    return body


def write_exclusive(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="HelloAda API origin, for example https://api.example.com")
    parser.add_argument("--website-id", required=True, help="Exact registered website/tenant ID")
    parser.add_argument("--output", required=True, type=Path, help="New file path; existing files are never overwritten")
    parser.add_argument("--token-env", default="HELLOADA_CONTROL_PLANE_TOKEN", help="Environment variable containing the control-plane token")
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        parser.error(f"required control-plane token environment variable is missing: {args.token_env}")
    try:
        plan = fetch_plan(args.api_url, args.website_id, token)
        write_exclusive(args.output, plan)
    except FileExistsError:
        parser.error("output already exists; choose a new path to preserve prior snapshots")
    except Exception as exc:
        parser.error(f"inventory capture failed ({type(exc).__name__})")
    print(json.dumps({"captured": True, "websiteId": args.website_id,
                      "snapshotHash": plan["snapshotHash"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
