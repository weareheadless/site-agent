import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const { build } = require('esbuild')
const source = new URL('../src/app/api/workspace/content/route.ts', import.meta.url)
const schema = require.resolve('@weareheadless/helloada-payload-core/schema')

const harness = async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'catalog-gateway-'))
  t.after(() => rm(temp, { recursive: true, force: true }))
  const stub = path.join(temp, 'boundary.mjs')
  await writeFile(stub, `
    export const serviceAuthorized = request => request.headers.get('authorization') === 'Bearer service-token'
    export const helloAdaSite = { defaultLocale: 'en', locales: ['es','en'], features: { commerce: true } }
    export const getPayload = async () => globalThis.__catalogPayload
    export const JWTAuthentication = async () => ({user:null})
    export const getCloudflareContext = async () => ({env:{}})
    export const readBookingSettings = async () => { throw new Error('unexpected booking access') }
    export const readBookingTypeById = readBookingSettings
    export const resolveTenantBookingOwner = readBookingSettings
    export default {}
  `)
  const response = path.join(temp, 'response.mjs')
  await writeFile(response, 'export const NextResponse = {json:(body, options) => Response.json(body, options)}')
  const compiled = await build({ entryPoints: [source.pathname], bundle: true, write: false, format: 'esm', platform: 'node', alias: {
    '@payload-config': stub, 'next/server': response, payload: stub,
    '@/helloada.config': stub, '@/lib/service-auth': stub, '@opennextjs/cloudflare': stub,
    '@weareheadless/helloada-payload-core/schema': schema,
  }, plugins: [{ name: 'mailflare-boundary', setup(build) {
    build.onResolve({ filter: /mailflare-booking-service$/ }, () => ({ path: stub }))
  } }] })
  const file = path.join(temp, 'route.mjs')
  await writeFile(file, compiled.outputFiles[0].text)
  return import(`file://${file}`)
}
const call = (route, body, authorized = true) => route.POST(new Request('https://tenant.test/api/workspace/content', {
  method: 'POST', headers: { 'content-type': 'application/json', ...(authorized ? { authorization: 'Bearer service-token' } : {}) }, body: JSON.stringify(body),
}))

test('catalog gateway uses canonical child identity and exact-draft guards', async (t) => {
  const route = await harness(t)
  const { hashJson, withoutPayloadMetadata } = await import('../src/lib/payload-hash.ts')
  let document
  let writes = 0
  let corrupt = false
  const queries = []
  globalThis.__catalogPayload = {
    find: async query => { queries.push(query); return { docs: document ? [document] : [] } },
    findByID: async () => document,
    create: async ({ data, draft }) => { assert.equal(draft, true); writes++; return document = { ...data, id: 7, sourceId: 'attribute:7', _status: 'draft' } },
    update: async options => {
      assert.ok(options.context.helloAdaExpectedRevision.hash)
      writes++
      document = { ...document, ...options.data, ...(corrupt ? { label: 'Concurrent change' } : {}), _status: options.draft ? 'draft' : 'published' }
      return document
    },
  }
  const create = { operation: 'create', collection: 'productAttributes', locale: 'en', data: { product: 1, key: 'beds', label: 'Beds', valueType: 'number', valueNumber: 2 } }
  assert.equal((await call(route, create, false)).status, 401)
  assert.equal((await call(route, create)).status, 201)
  assert.deepEqual(queries[0].where, { and: [{ product: { equals: 1 } }, { key: { equals: 'beds' } }] })
  assert.equal((await call(route, create)).status, 200)
  assert.equal(writes, 1, 'an identical lost-response retry is idempotent')
  assert.equal((await call(route, { ...create, data: { ...create.data, valueNumber: 3 } })).status, 409)
  const expectedHash = await hashJson(withoutPayloadMetadata(document))
  assert.equal((await call(route, { operation: 'publish', collection: 'productAttributes', id: '7', locale: 'en', expectedHash: 'sha256:' + 'a'.repeat(64) })).status, 409)
  assert.equal(writes, 1)
  assert.equal((await call(route, { operation: 'publish', collection: 'productAttributes', id: '7', locale: 'en', expectedHash })).status, 200)
  const read = await route.GET(new Request('https://tenant.test/api/workspace/content?collection=productAttributes&id=7&locale=en', { headers: { authorization: 'Bearer service-token' } }))
  assert.equal(read.status, 200)
  assert.equal((await read.json()).document.route, undefined, 'a child never receives a fabricated page URL')
  corrupt = true
  assert.equal((await call(route, { operation: 'publish', collection: 'productAttributes', id: '7', locale: 'en', expectedHash })).status, 409)
})

test('variants are created by SKU; malformed prices and child slug selectors are rejected', async (t) => {
  const route = await harness(t)
  let writes = 0
  globalThis.__catalogPayload = {
    find: async ({ where }) => { assert.deepEqual(where, { sku: { equals: 'SHIRT-M' } }); return { docs: [] } },
    create: async ({ data }) => { writes++; return { id: 9, ...data } },
  }
  const create = { operation: 'create', collection: 'productVariants', locale: 'en', data: { product: 1, sku: 'SHIRT-M', priceMinor: 1250, options: [{ option: 'size', value: 'm' }] } }
  assert.equal((await call(route, { ...create, data: { ...create.data, priceMinor: 12.5 } })).status, 400)
  assert.equal(writes, 0)
  assert.equal((await call(route, create)).status, 201)
  const read = await route.GET(new Request('https://tenant.test/api/workspace/content?collection=productVariants&slug=shirt&locale=en', { headers: { authorization: 'Bearer service-token' } }))
  assert.equal(read.status, 400)
})
