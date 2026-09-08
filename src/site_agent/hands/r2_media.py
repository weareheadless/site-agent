"""Private Cloudflare R2 storage adapter for media assets."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request

from ..core.media_contracts import MediaStore


class R2MediaError(RuntimeError):
    pass


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str) -> bytes:
    date_key = _sign(("AWS4" + secret).encode(), date)
    region_key = _sign(date_key, "auto")
    service_key = _sign(region_key, "s3")
    return _sign(service_key, "aws4_request")


def _encoded_key(key: str) -> str:
    key = key.strip("/")
    if not key or "\x00" in key or any(part in {"", ".", ".."} for part in key.split("/")):
        raise R2MediaError("invalid R2 object key")
    return "/" + urllib.parse.quote(key, safe="/-_.~")


class R2MediaStore(MediaStore):
    def __init__(self, account_id: str, bucket: str, access_key_id: str, secret_access_key: str, timeout: float = 60) -> None:
        self.account_id = account_id.strip().lower()
        self.bucket = bucket.strip().lower()
        self.access_key_id = access_key_id.strip()
        self.secret_access_key = secret_access_key.strip()
        self.timeout = timeout
        self.host = f"{self.bucket}.{self.account_id}.r2.cloudflarestorage.com"

    def _url(self, key: str) -> str:
        return f"https://{self.host}{_encoded_key(key)}"

    def _request(self, method: str, key: str, data: bytes = b"", content_type: str = "") -> bytes:
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(data).hexdigest()
        uri = _encoded_key(key)
        headers = {"Host": self.host, "X-Amz-Date": amz_date, "X-Amz-Content-Sha256": payload_hash}
        if content_type:
            headers["Content-Type"] = content_type
        canonical_headers = "".join(f"{name.lower()}:{value.strip()}\n" for name, value in sorted(headers.items(), key=lambda item: item[0].lower()))
        signed_headers = ";".join(name.lower() for name in sorted(headers, key=str.lower))
        canonical_request = "\n".join([method, uri, "", canonical_headers, signed_headers, payload_hash])
        scope = f"{date}/auto/s3/aws4_request"
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
        signature = hmac.new(_signing_key(self.secret_access_key, date), string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
        request = urllib.request.Request(self._url(key), data=data or None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read(16 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise R2MediaError(f"R2 {method} failed ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise R2MediaError(f"R2 {method} failed") from exc

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._request("PUT", key, data, content_type)

    def get(self, key: str) -> bytes:
        return self._request("GET", key)

    def delete(self, key: str) -> None:
        self._request("DELETE", key)

    def signed_get_url(self, key: str, ttl_seconds: int) -> str:
        if not 1 <= ttl_seconds <= 3600:
            raise R2MediaError("signed URL TTL must be between 1 and 3600 seconds")
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        scope = f"{date}/auto/s3/aws4_request"
        params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.access_key_id}/{scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(ttl_seconds),
            "X-Amz-SignedHeaders": "host",
        }
        query = urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)
        canonical_request = "\n".join([
            "GET", _encoded_key(key), query, f"host:{self.host}\n", "host", "UNSIGNED-PAYLOAD",
        ])
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
        params["X-Amz-Signature"] = hmac.new(_signing_key(self.secret_access_key, date), string_to_sign.encode(), hashlib.sha256).hexdigest()
        return f"https://{self.host}{_encoded_key(key)}?{urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)}"


__all__ = ["R2MediaError", "R2MediaStore"]
