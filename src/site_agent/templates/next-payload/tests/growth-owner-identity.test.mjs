import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'

test('the bridge uses server-authenticated actor, never browser headers or JSON', async () => {
  const source = readFileSync(new URL('../src/lib/helloada-upstream.ts', import.meta.url), 'utf8')
    .replace(/^import[^\n]+\n/gm, '')
  const harness = `
    import assert from 'node:assert/strict'
    const helloAdaRuntime = () => ({url:'https://api.example.test',token:'service-test-token'})
    const helloAdaWorkspacePath = () => '/api/workspace/drafts/1/approve'
    let observed
    const fetch = async (url, options) => { observed = options; return Response.json({ok:true}) }
  `
  const checks = `
    const request = () => new Request('https://owner.example.test/api/helloada/drafts/1/approve', {
      method:'POST', headers:{'content-type':'application/json','X-HelloAda-Owner-Id':'payload:foreign:9'},
      body:JSON.stringify({owner_actor_id:'payload:foreign:9',review_package_hash:'exact'})})
    await fetchHelloAdaUpstream('/api/helloada/drafts/1/approve', request(), 'payload:tenant:7')
    assert.equal(observed.headers.get('X-HelloAda-Owner-Id'), 'payload:tenant:7')
    assert.equal(observed.headers.get('Authorization'), 'Bearer service-test-token')
    await fetchHelloAdaUpstream('/api/helloada/drafts/1/approve', request())
    assert.equal(observed.headers.get('X-HelloAda-Owner-Id'), null)
  `
  const javascript = stripTypeScriptTypes(harness + source + checks)
  await assert.doesNotReject(import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64')))
})
