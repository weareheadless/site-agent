"""Read-only release gate. No tenant initialization, model calls or provisioning."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.request

from site_agent.config import load, load_env_file
from site_agent.application.tenant_registration import load_provisioned_tenants, tenant_token_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--api-url', required=True, help='Shared API base including /v1')
    parser.add_argument('--tenant', action='append', help='Limit to an explicitly selected deployed customer; repeatable')
    args = parser.parse_args()
    env = load_env_file(args.env_file, dict(os.environ)) if args.env_file else dict(os.environ)
    config, _ = load(args.config, env, validate_integrations=False)
    extra, extra_env = load_provisioned_tenants(config, env)
    env = {**env, **extra_env}
    declared = {**config.get('workspace_api', {}).get('tenants', {}), **extra}
    if args.tenant:
        if any(name not in declared for name in args.tenant):
            print(json.dumps({'connection': 'failed', 'failureType': 'UnknownTenant'}))
            return 1
        declared = {name: declared[name] for name in args.tenant}
    failures = 0
    for name, spec in declared.items():
        token_name = spec.get('api_token_env') or tenant_token_env(name)
        try:
            tenant, _ = load(Path(spec['config_path']), env, validate_integrations=False)
            payload = tenant.get('site', {}).get('payload', {})
            if not payload.get('enabled') or payload.get('token_env') != token_name:
                raise ValueError('Payload registry/token contract mismatch')
            token = env.get(token_name)
            if not token:
                raise ValueError('missing tenant service credential')
            req = urllib.request.Request(args.api_url.rstrip('/') + '/workspace/connection', headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'site-agent/readiness'})
            with urllib.request.urlopen(req, timeout=25) as response:
                body = json.load(response)
            if body.get('tenant') != name or body.get('connected') is not True or body.get('ready') is not True:
                raise ValueError('tenant identity/readiness mismatch')
            print(json.dumps({'tenant': name, 'connection': 'ready'}))
        except Exception as exc:
            failures += 1
            # No response body, exception text, tokens or environment values.
            print(json.dumps({'tenant': name, 'connection': 'failed', 'failureType': type(exc).__name__, 'httpStatus': getattr(exc, 'code', None)}))
    return 1 if failures or not declared else 0


if __name__ == '__main__':
    raise SystemExit(main())
