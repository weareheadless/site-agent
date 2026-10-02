import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/server/runtime-env.ts', import.meta.url), 'utf8').replace(/import \{ getCloudflareContext \} from [^\n]+\n/, '')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
function runtime(bindings, env = {}) {
  const sandbox = { exports: {}, process: { env }, getCloudflareContext: () => {
    if (bindings === undefined) throw new Error('Not in a Worker')
    return { env: bindings }
  } }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports
}

test('request-time Worker bindings win over stale process environment', () => {
  const api = runtime({ SITE_AGENT_URL: 'https://api.example/v1/', HELLOADA_SITE_AGENT_TOKEN: 'worker-token' }, { HELLOADA_SITE_AGENT_TOKEN: 'wrong-tenant-token' })
  assert.equal(api.helloAdaRuntime().token, 'worker-token')
  assert.equal(api.helloAdaRuntime().source, 'cloudflare')
  assert.equal(api.helloAdaRuntime().url, 'https://api.example/v1')
})

test('missing Worker bindings fail closed, not against a local/other tenant token', () => {
  const api = runtime({}, { SITE_AGENT_URL: 'https://api.example/v1', HELLOADA_SITE_AGENT_TOKEN: 'stale' })
  assert.equal(api.helloAdaRuntime().configured, false)
  assert.equal(api.helloAdaConnection('demo').body.error, 'runtime_unconfigured')
})

test('local Node execution uses canonical process variables', () => {
  assert.equal(runtime(undefined, { SITE_AGENT_URL: 'https://api.example/v1', HELLOADA_SITE_AGENT_TOKEN: 'local' }).helloAdaRuntime().configured, true)
})

test('readiness requires authentication, the expected tenant, and a configured AI', () => {
  const api = runtime({ SITE_AGENT_URL: 'https://api.example/v1', HELLOADA_SITE_AGENT_TOKEN: 'secret-never-in-diagnostics' })
  const status = body => api.helloAdaConnection('demo', { status: 200, body })
  assert.equal(status({ tenant: 'demo', connected: true, ready: true }).status, 200)
  assert.equal(status({ tenant: 'other', connected: true, ready: true }).body.error, 'tenant_mismatch')
  assert.equal(status({ tenant: 'demo', connected: true, ready: false }).body.error, 'ai_unconfigured')
  assert.equal(api.helloAdaConnection('demo', { status: 401, body: {} }).status, 503)
  assert.equal(api.helloAdaConnection('demo').body.error, 'backend_unreachable')
  assert.doesNotMatch(JSON.stringify(status({ tenant: 'demo', connected: true, ready: true })), /secret-never|api\.example/)
})
