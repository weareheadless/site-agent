import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_locale_identity_comes_from_worker_config_not_stale_template_manifest(tmp_path):
    core_version = json.loads(
        (ROOT / 'packages/helloada-payload-core/package.json').read_text()
    )['version']
    site = tmp_path / 'site'
    shutil.copytree(ROOT / 'src/site_agent/templates/next-payload', site,
                    ignore=shutil.ignore_patterns('node_modules', '.next', '.open-next', '.wrangler', '*.tsbuildinfo'))
    (site / 'src/helloada.config.ts').write_text(
        "export const helloAdaSite = {locales: ['es', 'en'], defaultLocale: 'es', "
        "routes: {workspaceApi: '/api/helloada', liveSite: '/', preview: '/site-preview'}}\n")
    manifest_path = site / 'template-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.update(locales=['en'], defaultLocale='en')
    manifest_path.write_text(json.dumps(manifest))
    core = tmp_path / 'core/src'
    (core / 'schema').mkdir(parents=True)
    (core.parent / 'package.json').write_text(json.dumps({'version': core_version}))
    scope = site / 'node_modules/@weareheadless'
    scope.mkdir(parents=True)
    (scope / 'helloada-payload-core').symlink_to(core.parent, target_is_directory=True)
    (core / 'schema/index.ts').write_text('''
export const HELLOADA_CAPABILITIES = {collections: ['pages']}
export const createHelloAdaContentContract = () => ({
  coreVersion: '__CORE_VERSION__', schemaRevision: 9, contract: 'helloada-content-v4', globals: {siteSettings: []}
})
'''.replace('__CORE_VERSION__', core_version))
    (core / 'contract.ts').write_text('''
import {createHash} from 'node:crypto'
export const createHelloAdaContractIdentity = (selection) => ({
  ...selection, locales: [...selection.locales].sort(), schemaIdentity: 'a'.repeat(64),
  configurationIdentity: createHash('sha256').update(JSON.stringify(selection)).digest('hex')
})
''')
    subprocess.run(['node', '--experimental-strip-types', str(site / 'scripts/generate-payload-contract.mjs'), f'--site-root={site}'],
                   cwd=site, check=True, capture_output=True, text=True,
                   env={**os.environ, 'HELLOADA_SHARED_RUNTIME_FINGERPRINT': 'a' * 64})
    generated = json.loads(manifest_path.read_text())
    assert generated['locales'] == ['en', 'es']
    assert generated['defaultLocale'] == 'es'
    assert len(generated['configurationIdentity']) == 64
