import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(packageRoot, '../..')

test('the default Payload template locks the exact reproducible admin artifact', () => {
  const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
  const lock = JSON.parse(readFileSync(path.join(repositoryRoot, 'src/site_agent/templates/next-payload/package-lock.json'), 'utf8'))
  const output = mkdtempSync(path.join(tmpdir(), 'helloada-admin-pack-'))

  try {
    const [artifact] = JSON.parse(execFileSync('npm', ['pack', '--json', '--pack-destination', output], {
      cwd: packageRoot,
      encoding: 'utf8',
    }))
    const pinned = lock.packages['node_modules/@weareheadless/helloada-payload-admin']
    const expectedUrl = `https://github.com/weareheadless/site-agent/releases/download/payload-admin-v${pkg.version}/${artifact.filename}`

    assert.equal(artifact.version, pkg.version)
    assert.equal(pinned.version, artifact.version)
    assert.equal(pinned.resolved, expectedUrl)
    assert.equal(pinned.integrity, artifact.integrity,
      `Update the template lock's admin integrity to the reproducible package value: ${artifact.integrity}`)
  } finally {
    rmSync(output, { recursive: true, force: true })
  }
})
