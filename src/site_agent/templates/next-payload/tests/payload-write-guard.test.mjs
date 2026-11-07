import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const { Miniflare } = require('miniflare')
const { build } = require('esbuild')

test('all native Payload writers participate in the existing D1 write guard', async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'payload-write-guard-'))
  const worker = JSON.parse(await readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8'))
  const mf = new Miniflare({ workers: [{ config: {
    type: 'worker', name: 'test', compatibilityDate: worker.compatibility_date,
    manifest: { mainModule: 'index.js', modules: {
      'index.js': { type: 'esm', contents: 'export default { fetch() { return new Response("ok") } }' },
    } },
    env: { D1: { type: 'd1', id: 'D1' } },
  } }] })
  try {
    const db = await mf.getD1Database('D1')
    await db.prepare(`CREATE TABLE helloada_growth_operations (
      operation_key text PRIMARY KEY NOT NULL, document_key text NOT NULL, tenant_id text NOT NULL,
      package_hash text NOT NULL, state text NOT NULL, result_json text,
      created_at text NOT NULL, updated_at text NOT NULL
    )`).run()
    await db.prepare(`CREATE UNIQUE INDEX helloada_growth_writing_document
      ON helloada_growth_operations(document_key) WHERE state = 'writing'`).run()
    const contextStub = path.join(temp, 'cloudflare-context.mjs')
    await writeFile(contextStub, `export const getPayloadCloudflareContext = async () => ({env:{D1:globalThis.__nativeGuardD1}});
      export const runtimeValue = name => name === 'HELLOADA_TENANT_ID' ? 'tenant-a' : '';`)
    const bundled = await build({
      entryPoints: [new URL('../src/lib/growth-contract.ts', import.meta.url).pathname],
      bundle: true, write: false, format: 'esm', platform: 'node',
      alias: { '@/lib/cloudflare-context': contextStub,
        '@/lib/runtime-env': contextStub,
        '@/lib/payload-hash': new URL('../src/lib/payload-hash.ts', import.meta.url).pathname },
    })
    const bundlePath = path.join(temp, 'growth-contract.mjs')
    await writeFile(bundlePath, bundled.outputFiles[0].text)
    globalThis.__nativeGuardD1 = db
    const { assertNativeWriteAllowed: guard } = await import(`file://${bundlePath}`)
    const blocked = /being prepared|write.*progress|operation|writing|concurrent/i
    t.beforeEach(async () => { await db.prepare('DELETE FROM helloada_growth_operations').run() })

    await t.test('an active Ada operation also blocks a native bulk writer', async () => {
      await db.prepare(`INSERT INTO helloada_growth_operations
        (operation_key,document_key,tenant_id,package_hash,state,created_at,updated_at)
        VALUES ('ada:first','pages:1','tenant-a','package','writing','now','now')`).run()
      await assert.rejects(guard('pages', '1', { context: {} }, 'update', {}), blocked)
      await assert.rejects(guard('pages', undefined, { context: {} }, 'update', {}), blocked)
    })

    for (const id of ['1', undefined]) {
      await t.test(`independent native writers serialize (${id ? 'by id' : 'bulk'})`, async () => {
        const requests = [{ context: {} }, { context: {} }]
        const results = await Promise.allSettled(requests.map(req => guard('pages', id, req, 'update', {})))
        assert.equal(results.filter(result => result.status === 'fulfilled').length, 1)
        assert.equal(results.filter(result => result.status === 'rejected').length, 1)
        const winner = results.findIndex(result => result.status === 'fulfilled')
        await guard('pages', undefined, requests[winner], 'complete')
        const next = { context: {} }
        await guard('pages', id, next, 'update', {})
        await guard('pages', undefined, next, 'complete')
      })
    }

    await t.test('an unknown failed write never silently permits an overwrite', async () => {
      const request = { context: {} }
      await guard('pages', '1', request, 'update', {})
      await guard('pages', undefined, request, 'failed')
      await assert.rejects(guard('pages', '1', { context: {} }, 'update', {}), blocked)
    })

    await t.test('a stranded write on one page never blocks another page or the menu', async () => {
      await db.prepare(`INSERT INTO helloada_growth_operations
        (operation_key,document_key,tenant_id,package_hash,state,created_at,updated_at)
        VALUES ('ada:stuck','pages:1','tenant-a','package','uncertain','now','now')`).run()
      const other = { context: {} }
      await guard('pages', '2', other, 'update', {})
      await guard('pages', undefined, other, 'complete')
      const menu = { context: {} }
      await guard('global:navigation', 'navigation', menu, 'update', {})
      await guard('global:navigation', undefined, menu, 'complete')
      // The stranded page still refuses its own next write.
      await assert.rejects(guard('pages', '1', { context: {} }, 'update', {}), blocked)
    })

    await t.test('a failed page create leaves no lease behind', async () => {
      const request = { context: {} }
      await guard('pages', undefined, request, 'create', {})
      await guard('pages', undefined, request, 'failed')
      const rows = await db.prepare('SELECT COUNT(*) AS total FROM helloada_growth_operations').first()
      assert.equal(Number(rows.total), 0)
      const update = { context: {} }
      await guard('pages', '1', update, 'update', {})
      await guard('pages', undefined, update, 'complete')
    })
  } finally {
    delete globalThis.__nativeGuardD1
    await mf.dispose()
    await rm(temp, { recursive: true, force: true })
  }
})
