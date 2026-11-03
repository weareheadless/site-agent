"""Provisioning binds runtime settings only through the canonical release queue.

tenant.env remains the credential authority. SQLite retains only queue intent
and secret-free evidence; Cloudflare script-secrets mutation is not a path.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any, Mapping

import yaml

from .release_queue import request_release, release_root, ReleaseQueueError
from .runtime_activation import RuntimeActivation
from .tenant_environment import tenant_environment_path, write_tenant_environment, read_tenant_environment, TenantEnvironmentError

RUNTIME_BINDING_NAMES = frozenset({'GOOGLE_SITE_VERIFICATION', 'GA_MEASUREMENT_ID', 'RESEND_API_KEY',
                                 'MAILFLARE_ADDRESS', 'MAILFLARE_ZONE_ID', 'MAILFLARE_ROUTING_STATUS'})


class RuntimeBindingError(RuntimeError):
    pass


def binding_hashes(values: Mapping[str, str]) -> dict[str, str]:
    return {name: hashlib.sha256(value.encode()).hexdigest() for name, value in values.items()
            if name in RUNTIME_BINDING_NAMES and value}


def _receipt(root: Path, tenant: str, release_id: str) -> dict:
    if not isinstance(release_id, str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', release_id):
        raise RuntimeBindingError('Runtime binding release identity is invalid')
    path = root / 'runs' / tenant / release_id / 'receipt.json'
    if not path.is_file():
        return {}
    value = json.loads(path.read_text())
    if value.get('tenant') != tenant or value.get('releaseId') != release_id:
        raise RuntimeBindingError('Runtime binding release receipt belongs to a different tenant or release')
    return value


def deliver_runtime_bindings(config: Mapping[str, Any], env: Mapping[str, str], memory: Any,
                             tenant_config_path: str | Path | None, values: Mapping[str, str]) -> dict:
    if not memory or not tenant_config_path:
        raise RuntimeBindingError('Registered tenant configuration and durable state are required for runtime binding delivery')
    if not values or any(name not in RUNTIME_BINDING_NAMES or not isinstance(value, str) or not value or value != value.strip() for name, value in values.items()):
        raise RuntimeBindingError('Unsupported or empty provisioning runtime binding')
    tenant = str(config.get('instance_name') or '')
    try:
        path = tenant_environment_path(tenant_config_path, tenant)
        registry = json.loads((path.parent.parent / 'tenants.json').read_text())
        if Path(registry[tenant]['config_path']).resolve() != path.with_name('config.yaml'):
            raise RuntimeBindingError('Runtime binding delivery target is not the registered tenant')
        descriptor = os.open(path.with_name('.runtime-binding.lock'), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current_config = yaml.safe_load(path.with_name('config.yaml').read_text())
            if current_config.get('instance_name') != tenant:
                raise RuntimeBindingError('Registered tenant configuration identity changed')
            binding = (current_config.get('site') or {}).get('payload', {}).get('runtime_activation')
            if not binding:
                # A tenant with no verified activation has not completed a
                # release under this contract. That is a pending state, not a
                # defect: stage nothing and retry once a release is verified.
                return {'state': 'awaiting_runtime_release', 'reason': 'no verified runtime activation'}
            try:
                activation = RuntimeActivation.from_mapping(binding)
            except ValueError as exc:
                raise RuntimeBindingError('Registered runtime activation binding is invalid') from exc
            if activation.tenant_id != tenant:
                raise RuntimeBindingError('Runtime activation belongs to another tenant')
            root = release_root(config)
            active = _receipt(root, tenant, activation.release_id)
            if active.get('sourceSha') != activation.source_sha or active.get('uploadedVersion') != activation.uploaded_version:
                raise RuntimeBindingError('Runtime activation does not match its canonical release receipt')
            future = {**read_tenant_environment(path), **values}
            mailbox = [bool(future.get(name)) for name in ('MAILFLARE_ADDRESS', 'MAILFLARE_ZONE_ID', 'MAILFLARE_ROUTING_STATUS')]
            if any(mailbox) and not all(mailbox):
                raise RuntimeBindingError('Partial mailbox runtime settings cannot be staged or released')
            if future.get('RESEND_API_KEY') and not all(future.get(name) for name in ('RESEND_API_KEY_ID', 'RESEND_API_KEY_DOMAIN_ID')):
                raise RuntimeBindingError('A restricted sender key must retain its exact provider and domain identity')
            write_tenant_environment(path, values)
            # Prove only the bindings this producer owns. Another reconciler
            # may stage its own settings concurrently and must not make this
            # producer's proof fail or loop.
            desired = binding_hashes({name: future[name] for name in values})
            if active.get('status') in {'running', 'queued'}:
                return {'state': 'awaiting_active_release', 'release_id': activation.release_id}
            if active.get('status') not in {'deployed', 'verified'} or not active.get('connectionVerifiedAt'):
                raise RuntimeBindingError('Active runtime release is not successfully verified')
            versions = active.get('deployment', {}).get('versions', [])
            if versions != [{'version_id': activation.uploaded_version, 'percentage': 100}]:
                raise RuntimeBindingError('Runtime binding proof requires the exact uploaded version at 100%')
            if all(active.get('runtimeBindings', {}).get(name) == digest for name, digest in desired.items()):
                delivered = {'state': 'delivered', 'release_id': activation.release_id, 'bindings': desired}
                if memory.kv_get('runtime_binding_delivery') != delivered:
                    memory.record_action('runtime_bindings_delivered', activation.release_id)
                memory.kv_set('runtime_binding_delivery', delivered)
                return delivered
            previous = memory.kv_get('runtime_binding_delivery', {}) or {}
            if previous.get('state') == 'delivered':
                previous = {}
            release_id = previous.get('release_id')
            if release_id:
                outcome = _receipt(root, tenant, release_id)
                if outcome.get('status') in {'failed', 'interrupted'}:
                    # The failed ID is terminal and is never retried. A new
                    # intent is allowed only once an operator has promoted a
                    # different verified release, which proves the cause was
                    # addressed through the canonical queue.
                    if previous.get('activation_release_id') == activation.release_id:
                        raise RuntimeBindingError(
                            f'Runtime binding release {release_id} failed; an operator must reconcile and promote a new release'
                        )
                    previous = {}
                    release_id = None
                if outcome.get('status') in {'deployed', 'verified'}:
                    # A completed release did not attach these exact settings.
                    # One retry covers a reconcile that landed while the build
                    # was already reading tenant.env; a second identical
                    # outcome means the runner never uploads these names, so
                    # stop rather than loop releases.
                    retries = int(previous.get('completed_retries') or 0)
                    if retries >= 1:
                        raise RuntimeBindingError(
                            f'Release {release_id} completed without attaching the staged runtime bindings; '
                            'an operator must reconcile the tenant environment and release runner'
                        )
                    previous = {'completed_retries': retries + 1}
                    release_id = None
                elif previous.get('queued'):
                    return {'state': 'awaiting_release', 'release_id': release_id}
            if not release_id:
                release_id = datetime.now(timezone.utc).strftime('rel-%Y%m%d%H%M%S-') + token_hex(4)
                previous = {**previous, 'release_id': release_id, 'source_sha': activation.source_sha,
                            'activation_release_id': activation.release_id, 'queued': False,
                            'staged': desired}
                memory.kv_set('runtime_binding_delivery', previous)
                memory.record_action('runtime_bindings_requested', release_id)
            if previous.get('source_sha') != activation.source_sha:
                raise RuntimeBindingError('Runtime source advanced during an unresolved binding delivery')
            # The stable intent precedes the external queue operation. An
            # ambiguous response retries this same idempotent queue identity,
            # never a new release ID or a direct Cloudflare mutation.
            request_release(config, env, activation.source_sha, release_id=release_id)
            memory.kv_set('runtime_binding_delivery', {**previous, 'queued': True})
            return {'state': 'awaiting_release', 'release_id': release_id}
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
    except RuntimeBindingError:
        raise
    except (OSError, ValueError, KeyError, TypeError, TenantEnvironmentError, ReleaseQueueError) as exc:
        raise RuntimeBindingError('Provisioning runtime bindings could not be delivered through the canonical queue') from exc
