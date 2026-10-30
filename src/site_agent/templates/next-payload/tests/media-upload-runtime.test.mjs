import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const source = readFileSync(new URL('../src/app/api/helloada/[...path]/route.ts', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"][^'"]+['"];?\s*$/gm, '')
  .replace(/export /g, '')
const javascript = stripTypeScriptTypes(source, { mode: 'transform' })

function bridge(authenticated = true) {
  const pending = [], calls = []
  const media = { id: 41, filename: 'logo.png', url: '/api/media/file/logo.png', mimeType: 'image/png',
    analysisStatus: 'ready', tags: [{ value: 'logo' }], description: 'Owner logo' }
  const payload = {
    create: async (options) => { calls.push({ create: options }); return media },
    find: async () => ({ docs: [media] }),
  }
  const sandbox = {
    URL, URLSearchParams, Request, Response, Headers, File, FormData, Buffer, console,
    process: { env: {} }, crypto: globalThis.crypto,
    NextResponse: { json: (body, options) => Response.json(body, options) },
    getCloudflareContext: () => ({ ctx: { waitUntil: (promise) => pending.push(promise) } }),
    authenticateHelloAdaRequest: async () => authenticated ? { payload, req: {}, user: { id: 7 } } : undefined,
    helloAdaRuntime: () => ({ configured: true, url: 'https://shared.example/v1', token: 'fixture-tenant-token' }),
    helloAdaSite: { tenantId: 'fixture' }, tenantId: () => 'fixture',
    fetch: async (url, options) => { calls.push({ url, options }); return Response.json({ ok: true }) },
  }
  vm.runInNewContext(javascript + '\nglobalThis.handlers = { GET, POST };', sandbox)
  return { ...sandbox.handlers, pending, calls }
}

test('canonical upload persists the file before scheduling tenant-scoped analysis', async () => {
  const route = bridge()
  const form = new FormData()
  form.append('file', new File(['fixture'], 'logo.png', { type: 'image/png' }))
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 201)
  assert.equal((await result.json()).attachment.asset_id, 41)
  assert.equal(route.calls[0].create.collection, 'media')
  assert.equal(route.calls[0].create.file.mimetype, 'image/png')
  assert.equal(route.pending.length, 1)
  await Promise.all(route.pending)
  assert.equal(route.calls[1].url, 'https://shared.example/v1/workspace/media/analyze')
  assert.equal(route.calls[1].options.headers.Authorization, 'Bearer fixture-tenant-token')
  assert.deepEqual(JSON.parse(route.calls[1].options.body), { media_id: '41' })
})

test('embedded gallery receives canonical analysis status and tags', async () => {
  const route = bridge()
  const result = await route.GET(new Request('https://owner.example/api/helloada/media-library'), {
    params: Promise.resolve({ path: ['media-library'] }),
  })
  const body = await result.json()
  assert.equal(body.media[0].analysisStatus, 'ready')
  assert.deepEqual(body.media[0].tags, ['logo'])
})

test('unauthenticated uploads cannot store files or trigger analysis', async () => {
  const route = bridge(false)
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', { method: 'POST' }), {
    params: Promise.resolve({ path: ['media', 'upload'] }),
  })
  assert.equal(result.status, 401)
  assert.equal(route.calls.length, 0)
  assert.equal(route.pending.length, 0)
})
