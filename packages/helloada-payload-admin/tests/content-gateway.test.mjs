import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../../../src/site_agent/templates/next-payload/src/app/api/workspace/content/route.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

test('the default content gateway bounds requested lists and requires service authentication', async () => {
  let authorized = true
  const queries = []
  const payload = { find: async options => { queries.push(options); return { docs: [{ id: 1 }] } } }
  const modules = {
    'next/server': { NextResponse: { json: (body, options) => ({ body, status: options?.status || 200 }) } },
    payload: { getPayload: async () => payload },
    '@payload-config': { default: {} },
    '@/lib/service-auth': { serviceAuthorized: () => authorized },
    '@/helloada.config': { helloAdaSite: { locales: ['en'] } },
    '@/lib/payload-locale': { resolvePayloadLocale: () => undefined },
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
    '@weareheadless/helloada-payload-core/schema': { validateHelloAdaAuthoringData: () => true },
    '@/lib/payload-hash': {
      hashJson: async () => revision,
      withoutPayloadMetadata: ({ id, title }) => ({ id, title }),
    },
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
