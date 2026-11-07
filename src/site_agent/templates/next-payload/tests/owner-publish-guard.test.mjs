import assert from 'node:assert/strict'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const { Miniflare } = require('miniflare')
const { build } = require('esbuild')

const SOURCE = new URL('../src/app/api/helloada/[...path]/route.ts', import.meta.url)

const loadRoute = async (mutations) => {
  let source = await readFile(SOURCE, 'utf8')
  for (const [pattern, replacement] of mutations) source = source.replaceAll(pattern, replacement)
  return source
}

/** Bundle the real owner-publish route; only its platform/IO adapters are replaced. */
const harness = async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'owner-publish-'))
  const mf = new Miniflare({ workers: [{ config: {
    type: 'worker', name: 'publish-test',
    compatibilityDate: JSON.parse(await readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8')).compatibility_date,
    manifest: { mainModule: 'index.js', modules: {
      'index.js': { type: 'esm', contents: 'export default { fetch() { return new Response("ok") } }' },
    } },
    env: { D1: { type: 'd1', id: 'D1' } },
  } }] })
  const mutations = [
    ["import { NextResponse } from 'next/server'", 'const NextResponse = { json: (body, options) => Response.json(body, {status:options?.status || 200}) }'],
    ["import { getCloudflareContext } from '@opennextjs/cloudflare'", 'const getCloudflareContext = () => ({ ctx: { waitUntil: () => {} } })'],
    ["import { getPayload } from 'payload'", ''],
    ["import { getCloudflareContext } from '@opennextjs/cloudflare'", ''],
  ]
  const source = await loadRoute(mutations)
  const entry = path.join(temp, 'route.ts')
  await writeFile(entry, source)
  const stub = path.join(temp, 'adapters.mjs')
  const stubs = `
    export const authenticateHelloAdaRequest = async (request) => {
      const principal = (globalThis.__auth) && (globalThis.__auth)(request)
      if (!principal) return undefined
      return principal
    }
    export const internalMailflareRoute = async () => false
    export const fetchHelloAdaUpstream = async () => undefined
    export const growthGet = async () => undefined
    export const growthPost = async () => undefined
    export const applyHelloAdaBindingEdits = () => ({ data: {} })
    export const helloAdaContentBindings = () => ({})
    export const helloAdaConnection = async () => ({})
    export const helloAdaRuntime = () => ({ configured: true, url: '', token: '' })
    export const helloAdaRuntimeStatus = async () => ({})
    export const helloAdaSite = { defaultLocale: 'es', locales: ['es','en'], routes: {} }
    export const articleIndexPath = () => '/blog'
    export const pathForDocument = () => '/'
    export const hashJson = async (v) => (globalThis.__hashJson)(v)
    export const stableJson = (v) => JSON.stringify(v)
    export const withoutPayloadMetadata = (v) => { const r = { ...v }; for (const k of ['id','updatedAt','createdAt','_status','globalType']) delete r[k]; return r }
    export const asObject = (v) => v && typeof v === 'object' ? v : {}
    export const claimOperation = async (key, documentKey, packageHash) => (globalThis.__contract).claim(key, documentKey, packageHash)
    export const completeOperation = async (key, result) => (globalThis.__contract).complete(key, result)
    export const failOperation = async (key, result) => (globalThis.__contract).fail(key, result)
    export const operationByKey = async (key) => (globalThis.__contract).byKey(key)
    export const operationContext = (req, key) => { req.context = { ...req.context, helloAdaGrowthOperation: key } }
    export const operationResult = (row) => row?.result_json ? JSON.parse(row.result_json) : undefined
    export const prepareOperation = async (key, intent) => (globalThis.__contract).prepare(key, intent)
    export const reconcileOperation = async (key, result) => (globalThis.__contract).reconcile(key, result)
    export const tenantId = () => 'tenant-a'
    export default {}
    export const serviceAuthorized = () => false
    export const createHelloAdaPreviewToken = async () => 'signed-preview-token'
    export const latestCollectionVersionId = async () => '11'
    export const latestGlobalVersionId = async () => '12'
    export const versionRevision = async () => 'sha256:' + 'a'.repeat(64)
    export const helloAdaPreviewLifetime = () => 3600
    export const withRecoveredWrite = async (payload, target, action) => action()
    export const withPayloadWriteGuard = async (req, action) => {
            await (globalThis.__guard).acquire(req)
      try { const value = await action(); await (globalThis.__guard).settle(req, false); return value }
      catch (error) { await (globalThis.__guard).settle(req, true); throw error }
    }
  `
  await writeFile(stub, stubs)
  const bundled = await build({
    entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node',
    alias: Object.fromEntries(['@payload-config','@/lib/service-auth','@/lib/helloada-auth','@/lib/mailflare-provisioning-api','@/lib/helloada-upstream','@/lib/growth-operations','@/lib/content-routes','@/lib/helloada-preview','@/lib/helloada-preview-claims','@/lib/payload-versions','@/lib/payload-hash','@/lib/growth-contract','@/lib/runtime-env','@weareheadless/helloada-payload-core/bindings','@/admin/server/runtime-env','@/helloada.config'].map(specifier => [specifier, stub])),
  })
  const bundlePath = path.join(temp, 'route.mjs')
  await writeFile(bundlePath, bundled.outputFiles[0].text)
  t.after(async () => { await mf.dispose(); await rm(temp, { recursive: true, force: true }) })
  const route = await import(`file://${bundlePath}`)
  assert.match(bundled.outputFiles[0].text, /withPayloadWriteGuard/, 'the stub is bundled, not a real growth-contract copy')
  const ROUTE_POST = route.POST
  return { mf, ROUTE_POST }
}

test('owner publication acquires the document write guard and records exact receipts', async (t) => {
  const { mf, ROUTE_POST } = await harness(t)
  const db = await mf.getD1Database('D1')
  await db.prepare(`CREATE TABLE helloada_growth_operations (
    operation_key text PRIMARY KEY NOT NULL, document_key text NOT NULL, tenant_id text NOT NULL,
    package_hash text NOT NULL, state text NOT NULL, result_json text,
    created_at text NOT NULL, updated_at text NOT NULL
  )`).run()
  await db.prepare(`CREATE UNIQUE INDEX helloada_growth_writing_document
    ON helloada_growth_operations(document_key) WHERE state = 'writing'`).run()

  const live = { id: '1', title: 'Before', updatedAt: 'base' }
  const draft = { id: '1', title: 'After', updatedAt: 'candidate' }
  const requests = []
  let writes = 0
  const payload = {
    findByID: async (options) => (options.draft ? draft : live),
    update: async () => { writes += 1; Object.assign(live, { title: draft.title, updatedAt: 'published' }) },
  }
  const operations = new Map()
  const contract = {
    claim: async (key) => {
      if (operations.has(key)) return { inserted: false, row: operations.get(key) }
      const row = { operation_key: key, document_key: 'pages:1', state: 'writing', result_json: null }
      operations.set(key, row); return { inserted: true, row }
    },
    byKey: async (key) => operations.get(key),
    prepare: async (key, intent) => { Object.assign(operations.get(key), { result_json: JSON.stringify(intent) }) },
    complete: async (key, result) => { Object.assign(operations.get(key), { state: 'completed', result_json: JSON.stringify(result) }) },
    fail: async (key, result) => { Object.assign(operations.get(key), { state: 'uncertain', result_json: JSON.stringify(result) }) },
    reconcile: async (key, result) => { Object.assign(operations.get(key), { state: 'completed', result_json: JSON.stringify(result) }) },
  }
  let guardCalls = 0
  const guard = {
    acquire: async () => {
      const result = await db.prepare(`INSERT INTO helloada_growth_operations
      (operation_key,document_key,tenant_id,package_hash,state,created_at,updated_at)
      VALUES ('write:' || hex(randomblob(8)), 'payload:content','tenant-a','pkg','writing','now','now')`).run()
      guardCalls += 1
      return result
    },
    settle: async (req, failed) => {
      await db.prepare(`UPDATE helloada_growth_operations SET state = ?1, result_json = ?2
        WHERE document_key = 'payload:content' AND state = 'writing'`).bind(failed ? 'uncertain' : 'completed',
        JSON.stringify({ settled: true })).run()
    },
  }
  ;(globalThis).__auth = (request) => ({ user: { id: 'owner-1' }, req: request.__helloadaReq || { context: {} }, payload })
  ;(globalThis).__payload = payload
  ;(globalThis).__contract = contract
  ;(globalThis).__guard = guard
  ;(globalThis).__guardCalls = () => guardCalls
  ;(globalThis).__hashJson = async (value) => 'hash:' + JSON.stringify(value)
  const stripped = { ...draft }; for (const key of ['id','updatedAt','createdAt','_status','globalType']) delete stripped[key]
  const publishBody = { documents: [{ collection: 'pages', documentId: '1', expectedDraftHash: 'hash:' + JSON.stringify(stripped) }] }
  const publish = async () => {
    const request = { context: {} }
    requests.push(request)
    const response = await ROUTE_POST({ json: async () => publishBody, headers: new Headers(), url: 'https://tenant.example', __helloadaReq: request }, { params: Promise.resolve({ path: ['publish'] }) })
    return response
  }

  await t.test('the reviewed draft publishes exactly once through the shared guard', async () => {
    const response = await publish()
    assert.equal(guardCalls, 1, 'the publish action acquires the shared guard once')
    assert.equal(response.status, 200)
    assert.equal((await response.json()).published[0].documentId, '1')
    assert.equal(writes, 1)
    const receipt = [...operations.values()].find(row => row.state === 'completed')
    assert.ok(receipt, 'the exact publish receipt is recorded')
    const guarded = (await db.prepare("SELECT * FROM helloada_growth_operations WHERE document_key = 'payload:content'").all()).results
    assert.equal(guarded.length, 1, 'exactly one content lease is acquired and settled')
    assert.equal(guarded[0].state, 'completed')
  })

  await t.test('a live draft with an active foreign lease cannot publish a new write', async () => {
    const changed = { ...draft, title: 'Second change', updatedAt: 'candidate-2' }
    publishBody.documents[0] = { collection: 'pages', documentId: '1', expectedDraftHash: 'hash:' + JSON.stringify({ ...changed, id: undefined, updatedAt: undefined, createdAt: undefined, _status: undefined, globalType: undefined }) }
    await db.prepare(`INSERT INTO helloada_growth_operations
      (operation_key,document_key,tenant_id,package_hash,state,created_at,updated_at)
      VALUES ('blocking','payload:content','tenant-a','pkg','writing','now','now')`).run()
    const response = await publish()
    assert.equal(response.status, 409, 'an active guard lease blocks a second publish')
    assert.equal(writes, 1, 'a blocked publication must not write')
    await db.prepare("DELETE FROM helloada_growth_operations WHERE operation_key='blocking'").run()
  })

  await t.test('a verified draft mismatch is refused before any write', async () => {
    const before = writes
    const stale = await ROUTE_POST({ json: async () => ({ documents: [{ collection: 'pages', documentId: '1', expectedDraftHash: 'hash:stale' }] }), headers: new Headers(), url: 'https://tenant.example' }, { params: Promise.resolve({ path: ['publish'] }) })
    assert.equal(stale.status, 409)
    assert.equal(writes, before)
  })
})
