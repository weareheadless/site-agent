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
    export const latestCollectionVersionId = async () => '11'
    export const latestGlobalVersionId = async () => '12'
    export const versionRevision = async () => 'sha256:' + 'a'.repeat(64)
    export const readBookingSettings = async () => { throw new Error('unexpected booking access') }
    export const readBookingTypeById = readBookingSettings
    export const resolveTenantBookingOwner = readBookingSettings
    export default {}
  `)
  const response = path.join(temp, 'response.mjs')
  await writeFile(response, 'export const NextResponse = {json:(body, options) => Response.json(body, options)}')
  const compiled = await build({ entryPoints: [source.pathname], bundle: true, write: false, format: 'esm', platform: 'node', alias: {
    '@payload-config': stub, 'next/server': response, payload: stub,
    '@/helloada.config': stub, '@/lib/service-auth': stub, '@/lib/payload-versions': stub, '@opennextjs/cloudflare': stub,
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

test('a published document can be withdrawn without deleting its content', async (t) => {
  const route = await harness(t)
  let stored = { id: 12, slug: 'withdrawn', title: 'Withdrawn', priceMinor: 100, currency: 'USD', published: true, _status: 'published', updatedAt: '2026-11-04T00:00:00.000Z' }
  const writes = []
  globalThis.__catalogPayload = {
    findByID: async ({ draft }) => {
      if (!draft && stored._status !== 'published') throw Object.assign(new Error('not found'), { status: 404 })
      return stored
    },
    update: async ({ data, draft }) => {
      writes.push({ data, draft })
      stored = { ...stored, ...data }
      return stored
    },
  }
  const { hashJson, withoutPayloadMetadata } = await import('../src/lib/payload-hash.ts')
  const expectedHash = await hashJson(withoutPayloadMetadata(stored))
  assert.equal((await call(route, { operation: 'unpublish', collection: 'products', id: '12', locale: 'en', expectedHash: 'sha256:' + 'b'.repeat(64) })).status, 409)
  assert.equal(writes.length, 0, 'a stale hash never withdraws anything')
  const response = await call(route, { operation: 'unpublish', collection: 'products', id: '12', locale: 'en', expectedHash })
  assert.equal(response.status, 200)
  assert.equal(writes[0].draft, false, 'the live revision is withdrawn, not a draft copy')
  assert.equal(writes[0].data._status, 'draft')
  assert.equal(writes[0].data.title, 'Withdrawn', 'content and history are preserved')
  assert.equal(stored._status, 'draft')
})

test('withdrawal requires an explicit locale before reading or writing', async (t) => {
  const route = await harness(t)
  globalThis.__catalogPayload = {
    findByID: async () => { throw new Error('must not read') },
    update: async () => { throw new Error('must not write') },
  }
  const response = await call(route, { operation: 'unpublish', collection: 'products', id: '12', expectedHash: 'sha256:' + 'a'.repeat(64) })
  assert.equal(response.status, 400)
})

test('a failed live read is not proof of withdrawal', async (t) => {
  const route = await harness(t)
  const { hashJson, withoutPayloadMetadata } = await import('../src/lib/payload-hash.ts')
  const stored = { id: 12, slug: 'withdrawn', title: 'Withdrawn', _status: 'published' }
  let written = false
  globalThis.__catalogPayload = {
    findByID: async ({ draft }) => {
      if (!draft) throw Object.assign(new Error('database unavailable'), { status: 503 })
      return { ...stored, _status: written ? 'draft' : 'published' }
    },
    update: async () => { written = true },
  }
  const expectedHash = await hashJson(withoutPayloadMetadata(stored))
  const response = await call(route, { operation: 'unpublish', collection: 'products', id: '12', locale: 'en', expectedHash })
  assert.equal(response.status, 503)
})
