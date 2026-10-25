"""Issue and privately store a short-lived, read-only CrawlSEO migration token."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request


def issue_credential(api_url: str, site_id: str, idempotency_key: str, control_token: str,
                     output_path: Path, timeout: float = 30) -> dict[str, str | int]:
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password \
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("CrawlSEO API URL must be an HTTPS origin")
    if not site_id.strip() or not idempotency_key.strip() or not control_token:
        raise ValueError("site ID, idempotency key and control credential are required")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    reserved = True
    try:
        url = (f"{api_url.rstrip('/')}/api/internal/sites/"
               f"{urllib.parse.quote(site_id, safe='')}/connector-credentials")
        body = json.dumps({"idempotencyKey": idempotency_key}, separators=(",", ":")).encode()
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {control_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "User-Agent": "HelloAda/migration-credential-issuer",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError(f"credential endpoint returned HTTP {response.status}")
                encoded = response.read(64 * 1024 + 1)
                if len(encoded) > 64 * 1024:
                    raise ValueError("credential response exceeded the size limit")
                result = json.loads(encoded)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"credential endpoint returned HTTP {exc.code}") from None

        if not isinstance(result, dict) or result.get("scopes") != ["connector:read"]:
            raise ValueError("credential response did not confirm the exact read-only scope")
        token = result.get("token")
        credential_id = result.get("credentialId")
        if result.get("reused") is not False or not isinstance(token, str) \
                or not re.fullmatch(r"cseo_[A-Za-z0-9_-]{20,}", token) \
                or len(token) > 512 or not isinstance(credential_id, str) or not credential_id:
            raise ValueError("credential was not newly issued; no token was available for private storage")
        if result.get("expiresInDays") != 30:
            raise ValueError("credential expiry did not match the 30-day migration limit")

        with os.fdopen(fd, "w", encoding="utf-8") as output:
            fd = -1
            output.write(f"CRAWLSEO_CONNECTOR_READ_TOKEN={token}\n")
            output.flush()
            os.fsync(output.fileno())
        reserved = False
        return {"credentialId": credential_id, "expiresInDays": 30, "output": str(output_path)}
    except Exception:
        if fd >= 0:
            os.close(fd)
        if reserved:
            output_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="CrawlSEO API origin; HTTPS required")
    parser.add_argument("--site-id", required=True, help="Exact existing CrawlSEO site ID")
    parser.add_argument("--idempotency-key", required=True, help="Unique key for this one-time credential issuance")
    parser.add_argument("--output", required=True, type=Path, help="New private env file; existing files are never overwritten")
    parser.add_argument("--control-token-env", default="HELLOADA_PROVISIONING_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.control_token_env, "").strip()
    if not token:
        parser.error(f"required control credential environment variable is missing: {args.control_token_env}")
    try:
        result = issue_credential(args.api_url, args.site_id, args.idempotency_key, token, args.output)
    except FileExistsError:
        parser.error("output already exists; choose a new path")
    except Exception as exc:
        parser.error(f"credential issuance failed ({type(exc).__name__})")
    print(json.dumps({"issued": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
