import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = async (path) => readFile(resolve(root, path), 'utf8')

test('shared package is customer-neutral', async () => {
  const files = ['src/components/WebsiteWorkspace.tsx', 'src/components/HelloAdaNav.tsx', 'src/styles/admin.scss']
  const contents = await Promise.all(files.map(source))
  const combined = contents.join('\n')
  assert.doesNotMatch(combined, /Atelier|atelier|OceanicVibes|oceanicvibes|\/api\/atelier/)
  assert.match(combined, /HelloAda/)
})

test('shared package has a tenant configuration boundary', async () => {
  const config = await source('src/config/site.tsx')
  assert.match(config, /defineHelloAdaSite/)
  assert.match(config, /workspaceApi/)
  assert.match(config, /preview/)
  assert.match(config, /previewRouteForTenant/)
  assert.match(config, /tenantId/)
})
