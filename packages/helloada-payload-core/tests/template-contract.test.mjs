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
const corePackage = JSON.parse(readFileSync(path.join(repositoryRoot, 'packages/helloada-payload-core/package.json'), 'utf8'))
const adminPackage = JSON.parse(readFileSync(path.join(repositoryRoot, 'packages/helloada-payload-admin/package.json'), 'utf8'))

test('template manifest package versions match the canonical packages', () => {
  assert.equal(manifest.payloadCore, corePackage.version)
  assert.equal(manifest.payloadAdmin, adminPackage.version)
})

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
