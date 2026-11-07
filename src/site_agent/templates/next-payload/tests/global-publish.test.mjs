import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const { build } = require('esbuild')

const SOURCE = new URL('../src/app/api/workspace/global/route.ts', import.meta.url)

/** Bundle the real service global route; only the platform/Payload boundary is replaced. */
const harness = async (t) => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'global-publish-'))
  const stub = path.join(temp, 'stub.mjs')
  await writeFile(stub, `
    export const helloAdaRuntime = () => ({ token: 'service-token' })
    export const serviceAuthorized = (request) =>
      request.headers.get('authorization') === 'Bearer service-token'
    export const helloAdaSite = { defaultLocale: 'es', locales: ['es', 'en'] }
    export const validateHelloAdaAuthoringData = () => undefined
    export const getPayload = async () => globalThis.__payload
    export const latestCollectionVersionId = async () => '11'
    export const latestGlobalVersionId = async () => '12'
    export const versionRevision = async () => 'sha256:' + 'a'.repeat(64)
  `)
  const configStub = path.join(temp, 'config.mjs')
  await writeFile(configStub, 'export default {}')
  const nextStub = path.join(temp, 'next-server.mjs')
  await writeFile(nextStub, 'export const NextResponse = { json: (body, options) => Response.json(body, { status: options?.status || 200 }) }')
  const bundled = await build({
    entryPoints: [SOURCE.pathname],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
    alias: {
      '@payload-config': configStub,
      'next/server': nextStub,
      'payload': stub,
      '@/helloada.config': stub,
      '@/lib/service-auth': stub,
      '@/lib/payload-versions': stub,
      '@weareheadless/helloada-payload-core/schema': stub,
    },
  })
  const bundlePath = path.join(temp, 'route.mjs')
  await writeFile(bundlePath, bundled.outputFiles[0].text)
  t.after(async () => { await rm(temp, { recursive: true, force: true }) })
  return import(`file://${bundlePath}`)
}

const call = (route, body) => route.POST(new Request('https://tenant.example/api/workspace/global', {
  method: 'POST',
  headers: { authorization: 'Bearer service-token', 'content-type': 'application/json' },
  body: JSON.stringify(body),
}))

test('the service gateway publishes exactly the reviewed global revision', async (t) => {
  const route = await harness(t)
  const { hashJson, withoutPayloadMetadata } = await import('../src/lib/payload-hash.ts')
  const draft = { siteName: 'Astrid Rincón', tagline: 'Una sola persona', _status: 'draft' }
  const revision = await hashJson(withoutPayloadMetadata(draft))
  const calls = []
  let published = { siteName: '', tagline: '' }
  globalThis.__payload = {
    findGlobal: async (options) => {
      calls.push({ find: options.draft })
      if (options.draft) return draft
      return published
    },
    updateGlobal: async (options) => {
      calls.push({ update: options.draft })
      if (options.draft === false) {
        // Simulate an independent writer that lands a different revision.
        published = globalThis.__corruptPublished
          ? { siteName: 'Another writer', tagline: '' }
          : { siteName: draft.siteName, tagline: draft.tagline }
      }
      return { ...options.data, globalType: 'siteSettings' }
    },
  }

  await t.test('a stale draft revision is refused before any write', async () => {
    const response = await call(route, { operation: 'publish', global: 'siteSettings', locale: 'es',
      expectedHash: 'sha256:' + 'a'.repeat(64) })
    assert.equal(response.status, 409)
    assert.equal(calls.filter((item) => item.update !== undefined).length, 0)
  })

  await t.test('publish writes the reviewed draft and returns the exact revision', async () => {
    const response = await call(route, { operation: 'publish', global: 'siteSettings', locale: 'es',
      expectedHash: revision })
    assert.equal(response.status, 200, await response.clone().text())
    const body = await response.json()
    assert.equal(body.globalHash, revision)
    assert.deepEqual(calls.filter((item) => item.update !== undefined), [{ update: false }])
  })

  await t.test('a publication that lands a different revision is reported as a failure', async () => {
    globalThis.__corruptPublished = true
    const response = await call(route, { operation: 'publish', global: 'siteSettings', locale: 'es',
      expectedHash: revision })
    globalThis.__corruptPublished = false
    assert.equal(response.status, 409)
    assert.match((await response.json()).message, /different global revision/)
  })

  await t.test('draft updates remain available through the same gateway', async () => {
    const response = await call(route, { operation: 'update', global: 'siteSettings', locale: 'es',
      expectedHash: revision, data: { siteName: 'Astrid Rincón' } })
    assert.equal(response.status, 200, await response.clone().text())
    assert.deepEqual(calls.filter((item) => item.update !== undefined).pop(), { update: true })
  })
})
