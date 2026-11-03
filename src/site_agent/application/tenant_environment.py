"""One locked writer for the protected, registered tenant environment."""
from __future__ import annotations

import fcntl
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping


class TenantEnvironmentError(ValueError):
    pass


def tenant_environment_path(config_path: str | Path, tenant_id: str) -> Path:
    raw = Path(config_path).expanduser()
    if raw.is_symlink() or raw.parent.is_symlink():
        raise TenantEnvironmentError('The registered tenant secret path cannot contain symbolic links')
    path = raw.resolve(strict=True)
    if path.name != 'config.yaml' or path.parent.name != tenant_id:
        raise TenantEnvironmentError('The registered tenant secret path is not canonical')
    environment = path.with_name('tenant.env')
    if environment.is_symlink() or not environment.is_file():
        raise TenantEnvironmentError('The registered tenant secret file is unavailable')
    return environment


def read_tenant_environment(path: Path) -> dict[str, str]:
    try:
        if path.is_symlink():
            raise TenantEnvironmentError('The tenant environment cannot be a symbolic link')
        values = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            name, separator, value = line.partition('=')
            name = name.strip()
            if not separator or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name) or name in values or '\0' in value:
                raise TenantEnvironmentError('The registered tenant secret file is malformed')
            values[name] = value.strip()
        return values
    except (OSError, UnicodeError) as exc:
        raise TenantEnvironmentError('The registered tenant secret file could not be read') from exc


def write_tenant_environment(path: Path, values: Mapping[str, str]) -> None:
    if any(not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', str(name)) or any(c in str(value) for c in '\r\n\0') for name, value in values.items()):
        raise TenantEnvironmentError('The tenant secret update contains an invalid name or value')
    descriptor = os.open(path.with_name('.tenant-env.lock'), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    temporary = None
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = read_tenant_environment(path)
        current.update({name: str(value) for name, value in values.items()})
        fd, filename = tempfile.mkstemp(prefix='.tenant-env-', suffix='.tmp', dir=path.parent)
        temporary = Path(filename)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            for name, value in sorted(current.items()):
                stream.write(f'{name}={value}\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
