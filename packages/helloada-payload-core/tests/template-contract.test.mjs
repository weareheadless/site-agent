import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { createHelloAdaContractIdentity } from '../src/contract.ts'
import { HELLOADA_CAPABILITIES } from '../src/schema/index.ts'

const repositoryRoot = path.resolve(fileURLToPath(new URL('../../../', import.meta.url)))
const templatePath = (...parts) => path.join(repositoryRoot, 'src/site_agent/templates/next-payload', ...parts)
const manifest = JSON.parse(readFileSync(templatePath('template-manifest.json'), 'utf8'))

test('new-site health checks the same full schema identity as the bootstrap manifest', () => {
  const expectedIdentity = createHelloAdaContractIdentity({
    locales: manifest.locales,
    defaultLocale: manifest.defaultLocale,
    collections: HELLOADA_CAPABILITIES.collections,
    globals: HELLOADA_CAPABILITIES.globals,
  }).schemaIdentity
  const healthRoute = readFileSync(templatePath('src/app/api/health/route.ts'), 'utf8')

  assert.equal(expectedIdentity, manifest.schemaIdentity)
  assert.match(healthRoute, /globals:\s*HELLOADA_CAPABILITIES\.globals/)
})
