"""Compile the real new-tenant starter in a disposable, credential-free build."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from site_agent.application.release_dependencies import prepare_release_dependencies
from site_agent.credentials import github_api_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    credentials = parser.add_mutually_exclusive_group(required=True)
    credentials.add_argument('--credential-profile')
    credentials.add_argument('--github-token-env')
    args = parser.parse_args()
    npm = shutil.which('npm')
    if not npm:
        raise RuntimeError('The pinned npm toolchain is required')
    manifest = json.loads((ROOT / 'deploy/payload-customers.json').read_text())
    for command, expected in ((['node', '--version'], 'v' + manifest['nodeVersion']),
                              ([npm, '--version'], manifest['npmVersion'])):
        if subprocess.check_output(command, text=True).strip() != expected:
            raise RuntimeError('Starter verification requires the release-pinned Node/npm versions')
    token = (github_api_token({'credentials': {'profile_file': args.credential_profile}})
             if args.credential_profile else os.environ.get(args.github_token_env, ''))
    if not token:
        raise RuntimeError('The declared GitHub release credential is unavailable')
    with tempfile.TemporaryDirectory(prefix='helloada-starter-check-', dir=ROOT) as temporary:
        root = Path(temporary)
        source = root / 'source'
        shutil.copytree(ROOT / 'src/site_agent/templates/next-payload', source,
                        ignore=shutil.ignore_patterns('node_modules', '.next', '.open-next', '.wrangler', '.env*'))
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ}
        env.update(CI='1', TMPDIR=str(root), npm_config_cache=str(root / 'npm-cache'),
                   PAYLOAD_LOCAL_BUILD='1', PAYLOAD_CLI='1',
                   PAYLOAD_SECRET='isolated-starter-check-not-a-production-secret',
                   NEXT_TELEMETRY_DISABLED='1', CLOUDFLARE_REMOTE_BINDINGS='0')

        def run(command: list[str], directory: Path) -> None:
            print('[starter-check] ' + ' '.join(command[:3]), flush=True)
            result = subprocess.run(command, cwd=directory, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
            if result.returncode:
                print(result.stdout[-12000:], flush=True)
                raise RuntimeError(f'Starter check failed: {command[:3]}')

        prepare_release_dependencies(source, token, npm, root, run)
        run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--prefer-offline'], source)
        run([npm, 'run', 'typecheck'], source)
        run([npm, 'run', 'build'], source)
        if not (source / '.next/BUILD_ID').is_file():
            raise RuntimeError('Starter produced no Next.js build artifact')
        print('[starter-check] canonical starter typecheck and build passed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
