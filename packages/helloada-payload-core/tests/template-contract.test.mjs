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
const templatePackage = JSON.parse(readFileSync(templatePath('package.json'), 'utf8'))
const templateLock = JSON.parse(readFileSync(templatePath('package-lock.json'), 'utf8'))

test('template manifest versions match the canonical core package', () => {
  assert.equal(manifest.payloadCore, corePackage.version)

  const coreDependency = templatePackage.dependencies['@weareheadless/helloada-payload-core']

  assert.equal('payloadAdmin' in manifest, false)
  assert.equal(templateLock.packages['node_modules/@weareheadless/helloada-payload-core'].version, manifest.payloadCore)
  assert.equal(templateLock.packages[''].dependencies['@weareheadless/helloada-payload-core'], coreDependency)
  assert.equal('@weareheadless/helloada-payload-admin' in templatePackage.dependencies, false)
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
