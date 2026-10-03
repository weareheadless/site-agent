import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../../../src/site_agent/templates/next-payload/src/app/api/content/route.ts', import.meta.url), 'utf8')
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
  }
  const sandbox = { exports: {}, URL, require: name => modules[name] }
  vm.runInNewContext(compiled, sandbox)
  for (const [requested, expected] of [['1', 1], ['1000', 100], ['-2', 1], ['invalid', 100]]) {
    const response = await sandbox.exports.GET({ url: `https://tenant.test/api/content?collection=pages&limit=${requested}` })
    assert.equal(response.status, 200)
    assert.equal(queries.at(-1).limit, expected)
    assert.equal(response.body.documents.length, 1)
  }
  authorized = false
  const count = queries.length
  assert.equal((await sandbox.exports.GET({ url: 'https://tenant.test/api/content' })).status, 401)
  assert.equal(queries.length, count)
})
