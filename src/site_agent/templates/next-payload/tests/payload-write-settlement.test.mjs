import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const { Miniflare } = require('miniflare')
const { build } = require('esbuild')

const loadRevision = async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'payload-revision-'))
  t.after(() => rm(temp, { recursive: true, force: true }))
  const stub = path.join(temp, 'hash.mjs')
  await writeFile(stub, `export const hashJson = async (value) => globalThis.__hash(value)
    export const withoutPayloadMetadata = (value) => { const r = { ...value }; for (const k of ['id','createdAt','updatedAt','_status','globalType']) delete r[k]; return r }`)
  const bundled = await build({
    entryPoints: [new URL('../src/lib/payload-revision.ts', import.meta.url).pathname],
    bundle: true, write: false, format: 'esm', platform: 'node',
    alias: { '@/lib/payload-hash': stub },
  })
  const file = path.join(temp, 'revision.mjs')
  await writeFile(file, bundled.outputFiles[0].text)
  globalThis.__hash = async (value) => `sha256:${Buffer.from(JSON.stringify(value)).toString('hex').padEnd(64, '0').slice(0, 64)}`
  const module = await import(`file://${file}`)
  return { ...module, hashOf: module.revisionHash }
}

test('a reviewed revision is compared inside the write, not before it', async (t) => {
  const { collectionRevisionGuard, hashOf } = await loadRevision(t)
  const stored = { id: 4, title: 'Reviewed', body: 'A' }
  const expected = await hashOf(stored)
  const payload = { findByID: async () => stored }
  const hook = collectionRevisionGuard('pages')
  const args = (hash, extra = {}) => ({
    req: { payload, locale: 'en', context: { helloAdaExpectedRevision: { kind: 'collection', collection: 'pages', id: '4', hash, locale: 'en' } } },
    originalDoc: { id: 4 },
    operation: 'update',
    data: { title: 'Changed' },
    ...extra,
  })

  assert.deepEqual(await hook(args(expected)), args(expected).data, 'the reviewed revision may be written')

  stored.title = 'Someone else wrote this'
  await assert.rejects(hook(args(expected)), (error) => error.status === 409)
  assert.equal(stored.title, 'Someone else wrote this', 'a stale revision never overwrites the newer one')

  stored.title = 'Reviewed'
  await assert.rejects(hook(args('sha256:' + 'a'.repeat(64))), (error) => error.status === 409)
  await assert.rejects(hook(args(expected, { originalDoc: { id: 9 } })), /identity/)
  await assert.rejects(hook(args(expected, { operation: 'create' })), /no reviewed revision/)
  await assert.rejects(collectionRevisionGuard('products')(args(expected)), /different document/)
})

test('a malformed revision marker fails closed instead of becoming an unconditional write', async (t) => {
  const { collectionRevisionGuard, hashOf } = await loadRevision(t)
  const hook = collectionRevisionGuard('pages')
  const payload = { findByID: async () => ({ id: 1 }) }
  const base = { req: { payload, locale: 'en' }, originalDoc: { id: 1 }, operation: 'update', data: {} }
  for (const marker of [null, 'reviewed', {}, { kind: 'collection', collection: 'pages', id: '1' }, { kind: 'other', hash: 'sha256:' + 'b'.repeat(64) }]) {
    await assert.rejects(hook({ ...base, req: { payload, locale: 'en', context: { helloAdaExpectedRevision: marker } } }), (error) => error.status === 409)
  }
  assert.deepEqual(await hook(base), base.data, 'an absent marker is an ordinary native write')
})

test('a global write is compared against the global revision in the same locale', async (t) => {
  const { globalRevisionGuard, hashOf } = await loadRevision(t)
  const stored = { siteName: 'Casamigo' }
  const expected = await hashOf(stored)
  const payload = { findGlobal: async () => stored }
  const hook = globalRevisionGuard('siteSettings')
  const args = (hash, locale = 'en') => ({
    req: { payload, locale, context: { helloAdaExpectedRevision: { kind: 'global', global: 'siteSettings', hash, locale: 'en' } } },
    data: { siteName: 'New' },
  })
  assert.deepEqual(await hook(args(expected)), args(expected).data)
  stored.siteName = 'Changed elsewhere'
  await assert.rejects(hook(args(expected)), (error) => error.status === 409)
  stored.siteName = 'Casamigo'
  await assert.rejects(hook(args(expected, 'es')), /different locale/)
})

const loadGuard = async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'write-settlement-'))
  const worker = JSON.parse(await readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8'))
  const mf = new Miniflare({ workers: [{ config: {
    type: 'worker', name: 'settlement', compatibilityDate: worker.compatibility_date,
    manifest: { mainModule: 'index.js', modules: {
      'index.js': { type: 'esm', contents: 'export default { fetch() { return new Response("ok") } }' },
    } },
    env: { D1: { type: 'd1', id: 'D1' } },
  } }] })
  const db = await mf.getD1Database('D1')
  await db.prepare(`CREATE TABLE helloada_growth_operations (
    operation_key text PRIMARY KEY NOT NULL, document_key text NOT NULL, tenant_id text NOT NULL,
    package_hash text NOT NULL, state text NOT NULL, result_json text,
    created_at text NOT NULL, updated_at text NOT NULL
  )`).run()
  await db.prepare(`CREATE UNIQUE INDEX helloada_growth_writing_document
    ON helloada_growth_operations(document_key) WHERE state = 'writing'`).run()
  const stub = path.join(temp, 'boundary.mjs')
  await writeFile(stub, `export const getPayloadCloudflareContext = async () => ({ env: { D1: globalThis.__settlementD1 } })
    export const runtimeValue = (name) => name === 'HELLOADA_TENANT_ID' ? 'tenant-a' : ''
    export const hashJson = async (value) => globalThis.__settlementHash(value)
    export const stableJson = (value) => JSON.stringify(value)
    export const withoutPayloadMetadata = (value) => { const r = { ...value }; for (const k of ['id','createdAt','updatedAt','_status','globalType']) delete r[k]; return r }
    export const fieldValueMatches = (document, data) => Object.entries(data).every(([key, value]) => JSON.stringify(document[key]) === JSON.stringify(value))
    export const readCollectionRevision = async (payload, options) => payload.findByID({ ...options, draft: true })
    export const readGlobalRevision = async (payload, options) => payload.findGlobal(options)
    export const isRevisionHash = (value) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
    export const revisionHash = async (document) => globalThis.__settlementHash(withoutPayloadMetadata(document))
    export const expectedRevisionOf = () => undefined`)
  const bundled = await build({
    entryPoints: [new URL('../src/lib/growth-contract.ts', import.meta.url).pathname],
    bundle: true, write: false, format: 'esm', platform: 'node',
    alias: {
      '@/lib/cloudflare-context': stub, '@/lib/runtime-env': stub, '@/lib/payload-hash': stub,
      '@/lib/payload-revision': stub, '@/lib/payload-field-match': stub,
    },
  })
  const file = path.join(temp, 'guard.mjs')
  await writeFile(file, bundled.outputFiles[0].text)
  globalThis.__settlementD1 = db
  globalThis.__settlementHash = async (value) => `sha256:${Buffer.from(JSON.stringify(value)).toString('hex').padEnd(64, '0').slice(0, 64)}`
  t.after(async () => { delete globalThis.__settlementD1; await mf.dispose(); await rm(temp, { recursive: true, force: true }) })
  const guard = await import(`file://${file}`)
  return { guard, db, hash: (value) => globalThis.__settlementHash(value) }
}

const rows = async (db) => (await db.prepare('SELECT * FROM helloada_growth_operations ORDER BY created_at').all()).results
const expectedHash = 'sha256:' + 'c'.repeat(64)

test('a rejected Local API write releases its lease instead of stranding the tenant', async (t) => {
  const { guard, db, hash } = await loadGuard(t)
  const stored = { id: 1, title: 'Before' }
  const payload = { findByID: async () => stored, findGlobal: async () => stored }
  const req = { context: {}, locale: 'en', payload }
  await assert.rejects(guard.withRecoveredWrite(payload, { collection: 'pages', id: '1', locale: 'en', expectedHash: await hash(stored) }, async () => {
    await guard.assertNativeWriteAllowed('pages', '1', req, 'update')
    throw Object.assign(new Error('title is required'), { status: 400 })
  }), /title is required/)
  const settled = await rows(db)
  assert.equal(settled.length, 1)
  assert.equal(settled[0].state, 'completed', 'a pre-persistence rejection is proven harmless')
  await guard.assertNativeWriteAllowed('pages', '1', { context: {}, locale: 'en', payload }, 'update')
})

test('an unprovable failure stays blocked and cannot be overwritten', async (t) => {
  const { guard, db, hash } = await loadGuard(t)
  const payload = {
    findByID: async () => { throw new Error('database unavailable') },
    findGlobal: async () => { throw new Error('database unavailable') },
  }
  const req = { context: {}, locale: 'en', payload }
  await assert.rejects(guard.withRecoveredWrite(payload, { collection: 'pages', id: '1', locale: 'en', expectedHash: await hash({ title: 'Before' }) }, async () => {
    await guard.assertNativeWriteAllowed('pages', '1', req, 'update')
    throw Object.assign(new Error('connection reset'), { status: 500 })
  }), /connection reset/)
  const [row] = await rows(db)
  assert.equal(row.state, 'uncertain')
  await assert.rejects(guard.assertNativeWriteAllowed('pages', '1', { context: {}, locale: 'en', payload }, 'update'), /unverified outcome/)
})

test('a write that actually landed is proven by its intended data', async (t) => {
  const { guard, db, hash } = await loadGuard(t)
  const stored = { id: 1, title: 'After' }
  const payload = { findByID: async () => stored, findGlobal: async () => stored }
  const req = { context: {}, locale: 'en', payload }
  await assert.rejects(guard.withRecoveredWrite(
    payload,
    { collection: 'pages', id: '1', locale: 'en', expectedHash, data: { title: 'After' } },
    async () => {
      await guard.assertNativeWriteAllowed('pages', '1', req, 'update')
      throw Object.assign(new Error('readback timeout'), { status: 503 })
    },
  ))
  const [row] = await rows(db)
  assert.equal(row.state, 'completed', 'a landed write is settled, not left blocking')
  assert.match(row.result_json, /applied/)
})

test('a stranded lease is released only when its recorded intent proves no effect', async (t) => {
  const { guard, db, hash } = await loadGuard(t)
  await db.prepare(`INSERT INTO helloada_growth_operations
    (operation_key,document_key,tenant_id,package_hash,state,result_json,created_at,updated_at)
    VALUES ('stranded','payload:content','tenant-a','pkg','writing',?1,'now','now')`)
    .bind(JSON.stringify({ state: 'write-intent', collection: 'pages', id: '1', locale: 'en', expectedHash: await hash({ title: 'Before' }) })).run()
  const unchanged = { id: 1, title: 'Before' }
  const matching = { findByID: async () => unchanged, findGlobal: async () => unchanged }
  const req = { context: {}, locale: 'en', payload: matching }
  // The stored revision is the one the interrupted write started from.
  await guard.assertNativeWriteAllowed('pages', '1', req, 'update')
  const released = (await db.prepare("SELECT * FROM helloada_growth_operations WHERE operation_key = 'stranded'").all()).results[0]
  assert.equal(released.state, 'completed', 'the stranded lease is settled only after proof')

  await db.prepare('DELETE FROM helloada_growth_operations').run()
  await db.prepare(`INSERT INTO helloada_growth_operations
    (operation_key,document_key,tenant_id,package_hash,state,result_json,created_at,updated_at)
    VALUES ('stranded','payload:content','tenant-a','pkg','writing',?1,'now','now')`)
    .bind(JSON.stringify({ state: 'write-intent', collection: 'pages', id: '1', locale: 'en', expectedHash: await hash({ title: 'Before' }) })).run()
  const changed = { findByID: async () => ({ id: 1, title: 'Something else' }), findGlobal: async () => ({ id: 1, title: 'Something else' }) }
  await assert.rejects(
    guard.assertNativeWriteAllowed('pages', '1', { context: {}, locale: 'en', payload: changed }, 'update'),
    /Another website write is in progress|unverified outcome/,
  )
  const stillBlocked = (await db.prepare("SELECT * FROM helloada_growth_operations WHERE operation_key = 'stranded'").all()).results[0]
  assert.equal(stillBlocked.state, 'writing', 'an unproven outcome is never silently released')
})

test('the schema composes the settling error hook before every existing one', async (t) => {
  const { guard } = await loadGuard(t)
  const existingError = () => {}
  const existingChange = () => {}
  const items = [{ slug: 'pages', hooks: { afterError: [existingError], beforeChange: [existingChange] } }]
  const [wrapped] = guard.withWriteFailureSettlement(items)
  assert.equal(wrapped.hooks.afterError[0] === existingError, false, 'the settling hook runs first')
  assert.equal(typeof wrapped.hooks.afterError[0], 'function')
  assert.deepEqual(wrapped.hooks.afterError.slice(1), [existingError], 'existing error hooks are preserved')
  assert.deepEqual(wrapped.hooks.beforeChange, [existingChange], 'unrelated hooks are untouched')
  assert.deepEqual(items[0].hooks.afterError, [existingError], 'the input schema is not mutated')
})

test('every collection and global gains the revision check without losing its own hooks', async (t) => {
  const { withCollectionRevisionGuard, withGlobalRevisionGuard } = await loadRevision(t)
  const ownChange = () => {}
  const [collection] = withCollectionRevisionGuard([{ slug: 'pages', hooks: { beforeChange: [ownChange] } }])
  assert.deepEqual(collection.hooks.beforeChange[0], ownChange, 'existing hooks keep their order')
  assert.equal(typeof collection.hooks.beforeChange[1], 'function', 'the revision check is appended')
  const [global] = withGlobalRevisionGuard([{ slug: 'siteSettings', hooks: {} }])
  assert.equal(typeof global.hooks.beforeChange[0], 'function')
})

test('a lease from another document is never settled by this write', async (t) => {
  const { guard, db, hash } = await loadGuard(t)
  await db.prepare(`INSERT INTO helloada_growth_operations
    (operation_key,document_key,tenant_id,package_hash,state,result_json,created_at,updated_at)
    VALUES ('other','payload:content','tenant-a','pkg','writing',?1,'now','now')`)
    .bind(JSON.stringify({ state: 'write-intent', collection: 'pages', id: '99', locale: 'en', expectedHash: await hash({ title: 'Other' }) })).run()
  const payload = { findByID: async () => ({ id: 1, title: 'Before' }), findGlobal: async () => ({}) }
  await assert.rejects(guard.withRecoveredWrite(payload, { collection: 'pages', id: '1', locale: 'en' }, async () => {
    throw Object.assign(new Error('title is required'), { status: 400 })
  }), /title is required/)
  const other = (await db.prepare("SELECT * FROM helloada_growth_operations WHERE operation_key = 'other'").all()).results[0]
  assert.equal(other.state, 'writing', 'another document\'s lease is left for its own reconciliation')
})
