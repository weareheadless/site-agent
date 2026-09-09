"""Private filesystem media store for the isolated Intake Lab."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from ..core.media_contracts import MediaStore


class LocalMediaError(RuntimeError):
    pass


class LocalMediaStore(MediaStore):
    """Keep uploaded bytes inside one validated Lab workspace."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if self.root == Path(self.root.anchor):
            raise LocalMediaError("local media root is too broad")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        value = str(key or "").replace("\\", "/").strip("/")
        parts = value.split("/")
        if not value or any(part in {"", ".", ".."} for part in parts) or "\x00" in value:
            raise LocalMediaError("invalid local media key")
        path = (self.root / Path(*parts)).resolve()
        if path != self.root and self.root not in path.parents:
            raise LocalMediaError("local media key is outside the store")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(data))

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except OSError as exc:
            raise LocalMediaError("local media object is unavailable") from exc

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise LocalMediaError("local media object could not be removed") from exc

    def signed_get_url(self, key: str, ttl_seconds: int) -> str:
        if not 1 <= int(ttl_seconds) <= 3600:
            raise LocalMediaError("signed URL TTL must be between 1 and 3600 seconds")
        # The Lab is loopback-only; the route still validates the key through
        # this store before serving bytes.
        return f"/api/intake/media/object?key={quote(str(key), safe='')}"

    def content_type(self, key: str) -> str:
        guessed = mimetypes.guess_type(str(key))[0]
        if guessed:
            return guessed
        suffix = Path(str(key)).suffix.lower()
        return {
            ".avif": "image/avif",
            ".gif": "image/gif",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")


__all__ = ["LocalMediaError", "LocalMediaStore"]
