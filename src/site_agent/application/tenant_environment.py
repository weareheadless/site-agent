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


def auto_email_provisioning_enabled(config_path: str | Path) -> bool:
    """Return the registered policy that permits a first Mailflare bootstrap release."""
    import yaml

    path = Path(config_path).expanduser()
    try:
        tenant_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise TenantEnvironmentError("registered tenant email provisioning policy is unavailable") from error
    if not isinstance(tenant_config, dict):
        raise TenantEnvironmentError("registered tenant configuration is invalid")
    messages = tenant_config.get("messages")
    email = messages.get("email") if isinstance(messages, dict) else None
    provisioning = email.get("provisioning") if isinstance(email, dict) else None
    return bool(
        isinstance(email, dict)
        and email.get("enabled") is True
        and isinstance(provisioning, dict)
        and provisioning.get("auto") is True
    )


def worker_runtime_secrets(
    values: Mapping[str, str],
    tenant_id: str,
    customer: Mapping[str, object],
    *,
    auto_email_setup: bool,
    mailflare_enabled: bool | None = None,
) -> dict[str, str]:
    """Select the exact Worker secrets one registered tenant may receive.

    The tenant environment file stays the credential authority; this function
    only decides which of its values are bound into the Worker, and refuses an
    incomplete Mailflare/Resend set instead of deploying half a configuration.
    """
    from .tenant_registration import WORKER_SITE_AGENT_TOKEN_ENV, tenant_token_env

    if WORKER_SITE_AGENT_TOKEN_ENV != "HELLOADA_SITE_AGENT_TOKEN":
        raise TenantEnvironmentError("canonical Worker token binding differs from the tenant registration contract")
    token_name = tenant_token_env(tenant_id)
    if not values.get("PAYLOAD_SECRET") or not values.get(token_name):
        raise TenantEnvironmentError("registered tenant runtime secrets are incomplete")
    mailflare_names = ("MAILFLARE_ADDRESS", "MAILFLARE_ZONE_ID", "MAILFLARE_ROUTING_STATUS")
    mailflare_values = {name: str(values.get(name) or "").strip() for name in mailflare_names}
    mailflare_present = [bool(value) for value in mailflare_values.values()]
    if mailflare_enabled is None:
        mailflare_enabled = bool(customer.get("mailflareD1DatabaseId")) or bool(values.get("MAILFLARE_ADDRESS"))
    if any(mailflare_present) and not all(mailflare_present):
        raise TenantEnvironmentError("registered tenant Mailflare runtime settings are incomplete")
    if auto_email_setup and not mailflare_enabled:
        raise TenantEnvironmentError("automatic email provisioning requires registered Mailflare resources")
    if mailflare_enabled and not all(mailflare_present) and not auto_email_setup:
        raise TenantEnvironmentError("registered Mailflare tenant runtime settings are incomplete")
    if any(mailflare_present) and not mailflare_enabled:
        raise TenantEnvironmentError("Mailflare runtime settings exist without registered Mailflare resources")
    if bool(values.get("RESEND_API_KEY")) != bool(values.get("RESEND_API_KEY_ID")):
        raise TenantEnvironmentError("registered tenant Resend sender credential is incomplete")
    if bool(values.get("RESEND_API_KEY")) != bool(values.get("RESEND_API_KEY_DOMAIN_ID")):
        raise TenantEnvironmentError("registered tenant Resend sender key is not bound to an exact domain")
    result = {
        "PAYLOAD_SECRET": values["PAYLOAD_SECRET"],
        WORKER_SITE_AGENT_TOKEN_ENV: values[token_name],
    }
    if values.get("RESEND_API_KEY"):
        result["RESEND_API_KEY"] = values["RESEND_API_KEY"]
    if values.get("HELLOADA_TURNSTILE_SECRET_KEY"):
        result["HELLOADA_TURNSTILE_SECRET_KEY"] = values["HELLOADA_TURNSTILE_SECRET_KEY"]
    if all(mailflare_present):
        result.update(mailflare_values)
    for name in ("GA_MEASUREMENT_ID", "GOOGLE_SITE_VERIFICATION"):
        if values.get(name):
            result[name] = values[name]
    return result
