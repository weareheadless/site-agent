"""Strict loader and protected installer for the managed read-only CrawlSEO token."""

from __future__ import annotations

import hashlib
import hmac
import fcntl
import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any


CONNECTOR_TOKEN_ENV = "CRAWLSEO_CONNECTOR_READ_TOKEN"
CONNECTOR_RUNTIME_TOKEN_ENV = "CRAWLSEO_CONNECTOR_TOKEN"
_TOKEN = re.compile(r"^cseo_[A-Za-z0-9_-]{20,}$")
_MAX_TOKEN_LENGTH = 512


class CrawlSEOConnectorCredentialError(ValueError):
    """The managed connector credential file is missing or unsafe."""


def connector_credential_path(config: Mapping[str, Any]) -> Path:
    data_dir = Path(str(config.get("data_dir") or "")).expanduser().resolve()
    if not str(config.get("data_dir") or "").strip() or data_dir == Path(data_dir.anchor):
        raise CrawlSEOConnectorCredentialError("tenant data directory is invalid")
    return data_dir.parent / "crawlseo-connector.env"


def _validate_token(token: str) -> str:
    value = str(token or "").strip()
    if len(value) > _MAX_TOKEN_LENGTH or not _TOKEN.fullmatch(value):
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential is invalid")
    return value


def _read_managed_file(path: Path, expected_name: str = CONNECTOR_TOKEN_ENV) -> tuple[str, str] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file is unreadable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file must be a regular non-symlink file")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file must have mode 0600")
    if info.st_size > 4096:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file is too large")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file is unreadable") from exc
    lines = text.splitlines()
    if len(lines) != 1 or lines[0].count("=") != 1:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file must contain exactly one key")
    name, token = lines[0].split("=", 1)
    if name != expected_name:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential file contains an unknown key")
    return name, _validate_token(token)


def load_connector_environment(config: Mapping[str, Any]) -> dict[str, str]:
    """Read the one fixed connector key without changing MCP/provider env values."""
    path = connector_credential_path(config)
    record = _read_managed_file(path)
    provider = (config.get("providers") or {}).get("crawlseo") or {}
    provider = provider if isinstance(provider, Mapping) else {}
    connector_url = str(provider.get("connector_url") or "").strip()
    configured_name = str(provider.get("connector_token_env") or "").strip()
    if record is None:
        if connector_url and configured_name == CONNECTOR_TOKEN_ENV:
            raise CrawlSEOConnectorCredentialError("configured CrawlSEO connector credential is missing")
        return {}
    name, token = record
    if connector_url and configured_name == CONNECTOR_TOKEN_ENV and configured_name != name:
        raise CrawlSEOConnectorCredentialError("configured CrawlSEO connector credential name does not match the managed file")
    return {name: token}


def connector_runtime_credential_path(config: Mapping[str, Any]) -> Path:
    return connector_credential_path(config).with_name("crawlseo-connector-runtime.env")


def load_connector_runtime_environment(config: Mapping[str, Any]) -> dict[str, str]:
    """Load the separate read/write connector credential, never the MCP token."""
    record = _read_managed_file(connector_runtime_credential_path(config), CONNECTOR_RUNTIME_TOKEN_ENV)
    return {record[0]: record[1]} if record is not None else {}


def install_connector_credential(
    config: Mapping[str, Any],
    token_env: str,
    token: str,
    *,
    expected_file_sha256: str | None = None,
) -> dict[str, str | bool]:
    """Atomically install the managed token; never return or log its value.

    A different existing token is preserved unless the caller supplies the
    exact current raw-file SHA-256 as a compare-and-swap authorization.
    """
    if token_env != CONNECTOR_TOKEN_ENV:
        raise CrawlSEOConnectorCredentialError("connector token environment name is not managed")
    validated_token = _validate_token(token)
    path = connector_credential_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = -1
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise CrawlSEOConnectorCredentialError("managed connector credential lock must be a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except OSError as exc:
        if lock_fd >= 0:
            os.close(lock_fd)
        raise CrawlSEOConnectorCredentialError("managed connector credential lock is unavailable") from exc
    try:
        return _install_locked(path, token_env, validated_token, expected_file_sha256)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def install_runtime_connector_credential(config: Mapping[str, Any], token: str, *, expected_file_sha256: str | None = None) -> dict[str, str | bool]:
    """Install the distinct runtime credential while preserving the read-only key."""
    validated_token = _validate_token(token)
    path = connector_runtime_credential_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = -1
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise OSError("lock is not regular")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except OSError as exc:
        if lock_fd >= 0:
            os.close(lock_fd)
        raise CrawlSEOConnectorCredentialError("managed runtime credential lock is unavailable") from exc
    try:
        return _install_locked(path, CONNECTOR_RUNTIME_TOKEN_ENV, validated_token, expected_file_sha256)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _install_locked(path: Path, token_env: str, validated_token: str, expected_file_sha256: str | None) -> dict[str, str | bool]:
    current = _read_managed_file(path, token_env)
    current_bytes = path.read_bytes() if current is not None else None
    current_hash = hashlib.sha256(current_bytes).hexdigest() if current_bytes is not None else None
    if current is not None and hmac.compare_digest(current[1], validated_token):
        return {"installed": False, "idempotent": True, "fileSha256": current_hash or ""}
    if current is not None and (
        expected_file_sha256 is None
        or not re.fullmatch(r"[0-9a-f]{64}", expected_file_sha256)
        or not hmac.compare_digest(current_hash or "", expected_file_sha256)
    ):
        raise CrawlSEOConnectorCredentialError("a different managed connector credential already exists")
    if current is None and expected_file_sha256 is not None:
        raise CrawlSEOConnectorCredentialError("managed connector credential compare-and-swap did not match")

    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    descriptor = -1
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        payload = f"{token_env}={validated_token}\n".encode("utf-8")
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck immediately before replacement so a concurrent installer
        # cannot silently replace a different managed token.
        latest = _read_managed_file(path, token_env)
        latest_bytes = path.read_bytes() if latest is not None else None
        latest_hash = hashlib.sha256(latest_bytes).hexdigest() if latest_bytes is not None else None
        if current_hash != latest_hash:
            raise CrawlSEOConnectorCredentialError("managed connector credential changed during installation")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        installed_bytes = path.read_bytes()
        return {"installed": True, "idempotent": False, "fileSha256": hashlib.sha256(installed_bytes).hexdigest()}
    except CrawlSEOConnectorCredentialError:
        raise
    except OSError as exc:
        raise CrawlSEOConnectorCredentialError("managed CrawlSEO connector credential could not be installed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


__all__ = [
    "CONNECTOR_TOKEN_ENV",
    "CONNECTOR_RUNTIME_TOKEN_ENV",
    "CrawlSEOConnectorCredentialError",
    "connector_credential_path",
    "install_connector_credential",
    "install_runtime_connector_credential",
    "load_connector_environment",
    "load_connector_runtime_environment",
]
