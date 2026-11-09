import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const { build } = require('esbuild')
const source = new URL('../src/app/api/workspace/content/route.ts', import.meta.url)
const schema = require.resolve('@weareheadless/helloada-payload-core/schema')

const harness = async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'workspace-published-read-'))
  t.after(() => rm(temp, { recursive: true, force: true }))
  const stub = path.join(temp, 'boundary.mjs')
  await writeFile(stub, `
    export const serviceAuthorized = request => request.headers.get('authorization') === 'Bearer service-token'
    export const helloAdaSite = { defaultLocale: 'en', locales: ['en'], features: { commerce: true, posts: true } }
    export const getPayload = async () => globalThis.__workspacePayload
    export const getCloudflareContext = async () => ({ env: {} })
    export const latestCollectionVersionId = async () => '11'
    export const latestGlobalVersionId = async () => '12'
    export const versionRevision = async () => 'sha256:' + 'a'.repeat(64)
    export const readBookingSettings = async () => { throw new Error('unexpected booking access') }
    export const readBookingTypeById = readBookingSettings
    export const resolveTenantBookingOwner = readBookingSettings
    export const JWTAuthentication = async () => ({ user: null })
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

const list = (route, collection, draft) => route.GET(new Request(
  `https://tenant.test/api/workspace/content?collection=${collection}&draft=${draft}`,
  { headers: { authorization: 'Bearer service-token' } },
))

// An interrupted create leaves the main-table row behind with no locale or
// version row, so Payload's published read returns a draft-status document with
// no route slug. It is not a published document and must not fail the read.
const interrupted = { id: 2, title: 'Untitled page', slug: '', _status: 'draft' }
const home = { id: 1, title: 'Home', slug: 'home', _status: 'published' }

test('a published list omits an interrupted draft instead of failing the route', async (t) => {
  const route = await harness(t)
  const queries = []
  globalThis.__workspacePayload = {
    find: async (query) => {
      queries.push(query)
      return { docs: query.draft ? [home, interrupted] : [home, interrupted] }
    },
  }

  const response = await list(route, 'pages', false)

  assert.equal(response.status, 200)
  const body = await response.json()
  assert.deepEqual(body.documents.map((document) => document.id), [1])
  assert.equal(body.documents[0].route, '/')
  assert.equal(queries[0].draft, false)
})

test('a draft list still returns an incomplete draft verbatim', async (t) => {
  const route = await harness(t)
  globalThis.__workspacePayload = {
    find: async () => ({ docs: [home, interrupted] }),
  }

  const response = await list(route, 'pages', true)

  assert.equal(response.status, 200)
  const body = await response.json()
  assert.deepEqual(body.documents.map((document) => document.id), [1, 2])
  assert.equal(body.documents[1].slug, '')
})

test('a published document with an unsafe route still fails closed', async (t) => {
  const route = await harness(t)
  globalThis.__workspacePayload = {
    find: async () => ({ docs: [{ ...home, slug: '../private' }] }),
  }

  const response = await list(route, 'pages', false)

  assert.equal(response.status, 409)
  const body = await response.json()
  assert.match(body.message, /route/)
})

test('a catalog child without a route slug is still returned', async (t) => {
  const route = await harness(t)
  globalThis.__workspacePayload = {
    find: async () => ({ docs: [{ id: 5, sku: 'SHIRT-M', _status: 'published' }] }),
  }

  const response = await list(route, 'productVariants', false)

  assert.equal(response.status, 200)
  const body = await response.json()
  assert.deepEqual(body.documents.map((document) => document.id), [5])
})

test('the workspace snapshot derives a route only from a document with a slug', async () => {
  const source = await readFile(new URL('../src/app/api/helloada/[...path]/route.ts', import.meta.url), 'utf8')

  assert.match(source, /documents\.flatMap\(\(document\) => document\.slug \?/)
  assert.match(source, /status === 'published'/)
})

test('the workspace snapshot serializes collection reads for D1', async () => {
  const source = await readFile(new URL('../src/app/api/helloada/[...path]/route.ts', import.meta.url), 'utf8')

  assert.match(source, /for \(const collection of editableCollections\)/)
  assert.doesNotMatch(source, /Promise\.all\(editableCollections/)
  assert.match(source, /const publishedRows = await readAll\(false\)/)
  assert.match(source, /const draft = await readAll\(true, \{ _status: \{ equals: 'draft' \} \}\)/)
})
