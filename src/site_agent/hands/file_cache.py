"""file_cache.py — in-process cache of site file contents.

The CSS/HTML is the map the model already understands; the waste was
re-fetching whole files over the GitHub API on every read (and every hop, and
every message). Keep recently-read file bytes per process so repeated reads are
instant. Cleared whenever the site mutates through the admin
(approve/decline/discard/preview/revert), so it never serves stale content
after a change.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

_MAX_ENTRIES = 60

_cache: dict[tuple[str, str, str], bytes] = {}
_lock = threading.Lock()


def get(config: dict[str, Any], adapter: Any, path: str, branch: str | None = None) -> bytes | None:
    """Return cached bytes for a repo+path, or fetch via adapter.get_file."""
    repo = str((config.get("site") or {}).get("repository", "")).strip() or "?"
    key = (repo, str(branch or ""), str(path).lstrip("/"))
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        _, blob = adapter.get_file(str(path).lstrip("/"), branch=branch)
    except TypeError:
        _, blob = adapter.get_file(str(path).lstrip("/"))
    if blob is None:
        return None
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            _cache.pop(next(iter(_cache)))
        _cache[key] = blob
    return blob


def has(config: dict[str, Any], path: str, branch: str | None = None) -> bool:
    """True when the file is already in cache (served without a fetch)."""
    repo = str((config.get("site") or {}).get("repository", "")).strip() or "?"
    key = (repo, str(branch or ""), str(path).lstrip("/"))
    with _lock:
        return key in _cache


def clear() -> None:
    with _lock:
        _cache.clear()
