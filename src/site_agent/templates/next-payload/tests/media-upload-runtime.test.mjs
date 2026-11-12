import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const source = readFileSync(new URL('../src/app/api/helloada/[...path]/route.ts', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"][^'"]+['"];?\s*$/gm, '')
  .replace(/export /g, '')
const javascript = stripTypeScriptTypes(source, { mode: 'transform' })

function bridge(authenticated = true, service = false, existing = [], mediaOverride) {
  const pending = [], calls = []
  const media = mediaOverride || { id: 41, filename: 'logo.png', url: '/api/media/file/logo.png', mimeType: 'image/png',
    analysisStatus: 'ready', tags: [{ value: 'logo' }], description: 'Owner logo' }
  const payload = {
    create: async (options) => { calls.push({ create: options }); return media },
    find: async (options) => ({ docs: options?.where?.sourceId ? existing : [media] }),
  }
  const sandbox = {
    URL, URLSearchParams, Request, Response, Headers, File, FormData, Buffer, console,
    process: { env: {} }, crypto: globalThis.crypto,
    NextResponse: { json: (body, options) => Response.json(body, options) },
    getCloudflareContext: () => ({ ctx: { waitUntil: (promise) => pending.push(promise) } }),
    authenticateHelloAdaRequest: async () => authenticated ? { payload, req: {}, user: { id: 7 } } : undefined,
    getPayload: async () => payload,
    config: { collections: [] },
    serviceAuthorized: () => service,
    helloAdaRuntime: () => ({ configured: true, url: 'https://shared.example/v1', token: 'fixture-tenant-token' }),
    helloAdaSite: { tenantId: 'fixture' }, tenantId: () => 'fixture',
    withRecoveredWrite: async (payload, target, action) => action(),
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

test('a video is stored with analysis skipped and no vision call', async () => {
  const route = bridge(true, false, [], {
    id: 42, filename: 'clip.mp4', url: '/api/media/file/clip.mp4', mimeType: 'video/mp4', analysisStatus: 'skipped',
  })
  const form = new FormData()
  form.append('file', new File(['fixture'], 'clip.mp4', { type: 'video/mp4' }))
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 201)
  const body = await result.json()
  assert.equal(body.attachment.asset_id, 42)
  assert.equal(body.attachment.mime_type, 'video/mp4')
  const create = route.calls.find((call) => call.create).create
  assert.equal(create.collection, 'media')
  assert.equal(create.data.analysisStatus, 'skipped')
  assert.equal(create.file.mimetype, 'video/mp4')
  assert.equal(route.pending.length, 0, 'a video must not be sent to the image analyzer')
})

test('a file that is neither image nor video is rejected before storage', async () => {
  const route = bridge()
  const form = new FormData()
  form.append('file', new File(['fixture'], 'notes.pdf', { type: 'application/pdf' }))
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 415)
  assert.match((await result.json()).message, /Only images and videos/)
  assert.equal(route.calls.filter((call) => call.create).length, 0)
})

test('a video with no browser MIME is recognised from its own bytes', async () => {
  const route = bridge(true, false, [], {
    id: 43, filename: 'clip.mp4', url: '/api/media/file/clip.mp4', mimeType: 'video/mp4', analysisStatus: 'skipped',
  })
  const header = new Uint8Array([0, 0, 0, 0x18, 0x66, 0x74, 0x79, 0x70, 0x69, 0x73, 0x6f, 0x6d, 0, 0, 2, 0])
  const body = new Uint8Array([...header, ...new TextEncoder().encode('fixture')])
  const form = new FormData()
  form.append('file', new File([body], 'clip.mp4', { type: 'application/octet-stream' }))
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 201)
  const create = route.calls.find((call) => call.create).create
  assert.equal(create.data.analysisStatus, 'skipped')
  assert.equal(create.file.mimetype, 'video/mp4')
  assert.equal(route.pending.length, 0)
})

test('a renamed download is not trusted by its extension alone', async () => {
  const route = bridge()
  const form = new FormData()
  form.append('file', new File([new TextEncoder().encode('%PDF-1.7 fixture')], 'clip.mp4', { type: 'application/octet-stream' }))
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 415)
  assert.equal(route.calls.filter((call) => call.create).length, 0)
})

test('an oversized clip is refused with the limit in the message', async () => {
  const route = bridge()
  const form = new FormData()
  form.append('file', new File([new Uint8Array(25 * 1024 * 1024 + 1)], 'clip.mp4', { type: 'video/mp4' }))
  const result = await route.POST(new Request('https://owner.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 413)
  assert.match((await result.json()).message, /25 MB/)
  assert.equal(route.calls.filter((call) => call.create).length, 0)
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

test('the service token may drive the same canonical upload path', async () => {
  const route = bridge(false, true)
  const form = new FormData()
  form.append('file', new File(['fixture'], 'photo.png', { type: 'image/png' }))
  form.append('sourceId', 'article:example:1')
  form.append('alt', 'Article photo')
  const result = await route.POST(new Request('https://tenant.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 201)
  const create = route.calls.find((call) => call.create).create
  assert.equal(create.collection, 'media')
  assert.equal(create.overrideAccess, true, 'A service caller has no owner user to satisfy media create access')
  assert.equal(create.data.sourceId, 'article:example:1')
  assert.equal(create.data.alt, 'Article photo')
})

test('a service re-upload of the same sourceId returns the existing media', async () => {
  const existing = { id: 99, filename: 'photo.png', url: '/api/media/file/photo.png', mimeType: 'image/png' }
  const route = bridge(false, true, [existing])
  const form = new FormData()
  form.append('file', new File(['fixture'], 'photo.png', { type: 'image/png' }))
  form.append('sourceId', 'article:example:1')
  const result = await route.POST(new Request('https://tenant.example/api/helloada/media/upload', {
    method: 'POST', body: form,
  }), { params: Promise.resolve({ path: ['media', 'upload'] }) })
  assert.equal(result.status, 200)
  assert.equal(route.calls.filter((call) => call.create).length, 0)
})

test('a service token cannot use other owner routes', async () => {
  const route = bridge(false, true)
  const result = await route.POST(new Request('https://tenant.example/api/helloada/publish', {
    method: 'POST', body: '{}',
  }), { params: Promise.resolve({ path: ['publish'] }) })
  assert.equal(result.status, 401)
})
