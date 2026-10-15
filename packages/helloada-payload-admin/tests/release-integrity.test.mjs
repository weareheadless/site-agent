import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(packageRoot, '../..')

test('the source artifact identity and default template release pin are internally consistent', () => {
  const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
  const lock = JSON.parse(readFileSync(path.join(repositoryRoot, 'src/site_agent/templates/next-payload/package-lock.json'), 'utf8'))
  const template = JSON.parse(readFileSync(path.join(repositoryRoot, 'src/site_agent/templates/next-payload/package.json'), 'utf8'))
  const manifest = JSON.parse(readFileSync(path.join(repositoryRoot, 'src/site_agent/templates/next-payload/template-manifest.json'), 'utf8'))
  const worker = JSON.parse(readFileSync(path.join(repositoryRoot, 'src/site_agent/templates/next-payload/wrangler.jsonc'), 'utf8'))
  const output = mkdtempSync(path.join(tmpdir(), 'helloada-admin-pack-'))

  try {
    const [artifact] = JSON.parse(execFileSync('npm', ['pack', '--json', '--pack-destination', output], {
      cwd: packageRoot,
      encoding: 'utf8',
    }))
    const pinned = lock.packages['node_modules/@weareheadless/helloada-payload-admin']
    const templatePinUrl = template.dependencies['@weareheadless/helloada-payload-admin']

    assert.equal(artifact.version, pkg.version)
    assert.equal(artifact.filename, `weareheadless-helloada-payload-admin-${pkg.version}.tgz`)
    assert.match(artifact.integrity, /^sha512-[A-Za-z0-9+/]+=*$/)
    assert.equal(templatePinUrl, pinned.resolved)
    assert.equal(lock.packages[''].dependencies['@weareheadless/helloada-payload-admin'], templatePinUrl)
    assert.equal(manifest.payloadAdmin, pinned.version)
    assert.match(templatePinUrl, new RegExp(`payload-admin-v${pinned.version}/`))
    assert.match(pinned.integrity, /^sha512-[A-Za-z0-9+/]+=*$/)
    assert.equal(worker.observability.enabled, true)
    assert.equal(worker.observability.issues.enabled, true)
    assert.equal(worker.observability.head_sampling_rate, 1)
  } finally {
    rmSync(output, { recursive: true, force: true })
  }
})
