import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/app/api/workspace/content/route.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const fieldMatchSource = readFileSync(new URL('../src/lib/payload-field-match.ts', import.meta.url), 'utf8')
const fieldMatchCompiled = ts.transpileModule(fieldMatchSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const fieldMatchModule = { exports: {} }
vm.runInNewContext(fieldMatchCompiled, fieldMatchModule)

// Test double for the shared schema module. It mirrors only the names the
// gateway imports; the real catalog identity and validation are exercised
// against the actual package in the core suite.
const schemaModule = {
  HELLOADA_AUTHORING_CAPABILITIES: { collections: ['pages', 'posts', 'products', 'productAttributes', 'productVariants'] },
  isCatalogChildCollection: value => value === 'productAttributes' || value === 'productVariants',
  helloAdaContentCreateKey: (collection, data) => ({ where: { slug: { equals: String(data.slug || '') } }, effectKey: `${collection}:${String(data.slug || '')}` }),
  validateHelloAdaAuthoringData: () => true,
}


// The gateway imports the shared runtime modules; the doubles below mirror the
// current imports so the test verifies the route rather than a snapshot of it.
const runtimeModules = (hashJson, revisionHash) => ({
  '@opennextjs/cloudflare': { getCloudflareContext: () => ({ env: {} }) },
  '@/lib/growth-contract': { withRecoveredWrite: async (_payload, _target, action) => action() },
  '@/lib/payload-revision': {
    REVISION_DEPTH: 0,
    revisionHash,
    readCollectionRevision: async (payload, options) => payload.findByID(options),
  },
  '@/lib/payload-versions': {
    latestCollectionVersionId: async () => undefined,
    versionRevision: async () => undefined,
  },
  '../../../../../mailflare-booking-service': {
    readBookingSettings: async () => ({}),
    readBookingTypeById: async () => undefined,
    resolveTenantBookingOwner: () => undefined,
  },
  '@/lib/payload-hash': { hashJson, withoutPayloadMetadata: ({ id, title }) => ({ id, title }) },
})

test('the default content gateway bounds requested lists and requires service authentication', async () => {
  let authorized = true
  const queries = []
  const payload = { find: async options => { queries.push(options); return { docs: [{ id: 1, slug: 'fixture' }] } } }
  const modules = {
    'next/server': { NextResponse: { json: (body, options) => ({ body, status: options?.status || 200 }) } },
    payload: { getPayload: async () => payload },
    '@payload-config': { default: {} },
    '@/lib/service-auth': { serviceAuthorized: () => authorized },
    '@/helloada.config': { helloAdaSite: { locales: ['en'] } },
    '@/lib/payload-locale': { resolvePayloadLocale: () => undefined },
    '@/lib/payload-field-match': fieldMatchModule.exports,
    '@/lib/public-content-route': { withPublicRoute: (_collection, document) => ({ ...document, route: '/fixture' }) },
    '@weareheadless/helloada-payload-core/schema': schemaModule,
    ...runtimeModules(async () => 'unused', () => 'unused'),
  }
  const sandbox = { exports: {}, URL, require: name => modules[name] }
  vm.runInNewContext(compiled, sandbox)
  for (const [requested, expected] of [['1', 1], ['1000', 100], ['-2', 1], ['invalid', 100]]) {
    const response = await sandbox.exports.GET({ url: `https://tenant.test/api/workspace/content?collection=pages&limit=${requested}` })
    assert.equal(response.status, 200)
    assert.equal(queries.at(-1).limit, expected)
    assert.equal(response.body.documents.length, 1)
  }
  authorized = false
  const count = queries.length
  assert.equal((await sandbox.exports.GET({ url: 'https://tenant.test/api/workspace/content' })).status, 401)
  assert.equal(queries.length, count)
})

test('draft updates require the exact current Payload revision', async () => {
  const revision = `sha256:${'a'.repeat(64)}`
  const writes = []
  const payload = {
    findByID: async () => ({ id: 'page-1', title: 'Before', updatedAt: 'transport-only' }),
    update: async options => {
      writes.push(options)
      return { id: options.id, title: options.data.title, updatedAt: 'new-transport-only' }
    },
  }
  const modules = {
    'next/server': { NextResponse: { json: (body, options) => ({ body, status: options?.status || 200 }) } },
    payload: { getPayload: async () => payload },
    '@payload-config': { default: {} },
    '@/lib/service-auth': { serviceAuthorized: () => true },
    '@/helloada.config': { helloAdaSite: { locales: ['en'] } },
    '@/lib/payload-locale': { resolvePayloadLocale: () => undefined },
    '@/lib/payload-field-match': fieldMatchModule.exports,
    '@weareheadless/helloada-payload-core/schema': schemaModule,
    ...runtimeModules(async () => revision, () => revision),
  }
  const sandbox = { exports: {}, URL, require: name => modules[name] }
  vm.runInNewContext(compiled, sandbox)
  const post = body => sandbox.exports.POST({ json: async () => body })

  assert.equal((await post({ operation: 'update', collection: 'pages', id: 'page-1', data: { title: 'After' } })).status, 400)
  assert.equal((await post({ operation: 'update', collection: 'pages', id: 'page-1', locale: 'en', expectedHash: `sha256:${'b'.repeat(64)}`, data: { title: 'After' } })).status, 409)
  const accepted = await post({ operation: 'update', collection: 'pages', id: 'page-1', locale: 'en', expectedHash: revision, data: { title: 'After' } })
  assert.equal(accepted.status, 200)
  assert.deepEqual(writes.map(({ data, draft }) => ({ data, draft })), [{ data: { title: 'After' }, draft: true }])
  assert.equal(accepted.body.documentHash, revision)
})
