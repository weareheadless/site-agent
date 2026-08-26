"""media.py — Cloudflare R2 uploads for site images.

Small S3-compatible PUT client (AWS SigV4) using only the stdlib, so the admin
UI can offer "upload an image" without pulling in boto3. R2 credentials come
from config (`site.media`), resolved via the instance env mapping.

The client returns the public URL (from `site.media.public_url`) so images can
be dropped straight into pages — the URL is the deliverable, not the R2 internals.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import urllib.error
import urllib.request
from typing import Any


class MediaError(RuntimeError):
    pass


def _secret(config: dict[str, Any], name: str) -> str:
    import os

    from ..config import resolve_secret

    return resolve_secret(config, name, os.environ)


def _settings(config: dict[str, Any]) -> dict[str, Any]:
    m = dict((config.get("site") or {}).get("media") or {})
    m["account_id"] = str(m.get("account_id") or _secret(config, "r2_account_id"))
    m["access_key_id"] = str(m.get("access_key_id") or _secret(config, "r2_access_key_id"))
    m["secret_access_key"] = str(m.get("secret_access_key") or _secret(config, "r2_secret_access_key"))
    return m


def media_configured(config: dict[str, Any]) -> bool:
    m = _settings(config)
    return bool(m.get("account_id") and m.get("bucket") and m.get("access_key_id") and m.get("secret_access_key"))


def _sign(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sigkey(secret: str, datestamp: str, region: str) -> bytes:
    kdate = _sign(("AWS4" + secret).encode(), datestamp.encode())
    kregion = _sign(kdate, region.encode())
    kservice = _sign(kregion, b"s3")
    return _sign(kservice, b"aws4_request")


def _hexsha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upload(config: dict[str, Any], name: str, data: bytes, content_type: str | None = None) -> dict[str, Any]:
    """Upload bytes as `name` (key) to R2 via SigV4 PUT. Returns public URL."""
    if not media_configured(config):
        raise MediaError("site.media (R2) is not configured — set account_id, bucket, access keys, public_url")
    m = _settings(config)
    account_id = str(m["account_id"])
    bucket = str(m["bucket"])
    access_key = str(m.get("access_key_id") or "")
    secret = str(m.get("secret_access_key") or "")
    region = "auto"
    host = f"{bucket}.{account_id}.r2.cloudflarestorage.com"
    key = name.strip("/")
    if not key:
        raise MediaError("empty object key")

    if not content_type:
        content_type = "application/octet-stream"
    ctype = content_type

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    canonical_uri = "/" + key
    canonical_headers = (
        f"content-type:{ctype}\n"
        f"host:{host}\n"
        f"x-amz-content-sha256:{_hexsha(data)}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([
        "PUT", canonical_uri, "",
        canonical_headers,
        signed_headers,
        _hexsha(data),
    ])

    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope, _hexsha(canonical_request.encode()),
    ])
    signature = hmac.new(_sigkey(secret, datestamp, region), string_to_sign.encode(), hashlib.sha256).hexdigest()

    url = f"https://{host}/{key}"
    headers = {
        "Content-Type": ctype,
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": _hexsha(data),
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        raise MediaError(f"R2 upload failed ({exc.code}): {exc.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MediaError(f"R2 upload error: {exc}")

    public_url = str(m.get("public_url") or "").rstrip("/")
    if public_url:
        url = f"{public_url}/{key}"

    return {"ok": status in (200, 201), "url": url, "key": key, "size": len(data), "content_type": ctype}


def guess_content_type(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "webp": "image/webp", "gif": "image/gif", "avif": "image/avif",
        "svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
