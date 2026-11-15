import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'

/**
 * Growth is not a tenant-runtime surface.
 *
 * The site-agent owns the CrawlSEO connector, the task queue and the ledger,
 * and the HelloAda control plane reaches all of it for every tenant through
 * its own authenticated gateway. When this bridge carried a second copy of
 * that contract, a tenant built before a route shipped answered 503 for it,
 * which is how the one-click handoff first failed. These cases keep the
 * contract in exactly one place.
 */
const load = async () => {
  const source = readFileSync(new URL('../src/lib/helloada-runtime.ts', import.meta.url), 'utf8')
    .replace(/^import[^\n]+\n/gm, '')
  const javascript = stripTypeScriptTypes(source)
  return import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64'))
}

test('the bridge does not carry the Growth contract', async () => {
  const { helloAdaWorkspacePath } = await load()
  const paths = [
    ['/api/helloada/growth', 'GET'],
    ['/api/helloada/growth/opportunities', 'GET'],
    ['/api/helloada/growth/opportunities/cmu123abc/open', 'POST'],
    ['/api/helloada/growth/opportunities/cmu123abc/decision', 'POST'],
    ['/api/helloada/growth/groups', 'POST'],
    ['/api/helloada/growth/bindings', 'GET'],
    ['/api/helloada/growth/tasks/cmu123abc', 'GET'],
    ['/api/helloada/growth/articles/45', 'GET'],
    ['/api/helloada/growth/actions/42/decision', 'POST'],
    ['/api/helloada/growth/check', 'POST'],
    ['/api/helloada/growth/budget', 'GET'],
    ['/api/helloada/growth/research-policy', 'GET'],
  ]
  for (const [path, method] of paths) {
    assert.equal(helloAdaWorkspacePath(path, method), undefined, `${method} ${path}`)
  }
})

test('the bridge still maps the surfaces a tenant really owns', async () => {
  const { helloAdaWorkspacePath } = await load()
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/seo/analytics', 'GET', '?days=28'),
    '/workspace/seo/analytics?days=28',
  )
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth', 'GET'),
    undefined,
  )
})

test('the bridge does not extend an id into another path segment', async () => {
  const { helloAdaWorkspacePath } = await load()
  // The remaining mapped ids keep the same anchored shape, so a caller cannot
  // smuggle a second segment or an encoded separator through one.
  assert.equal(helloAdaWorkspacePath('/api/helloada/conversations/1/two', 'GET'), undefined)
  assert.equal(helloAdaWorkspacePath('/api/helloada/conversations/a%2Fb', 'GET'), undefined)
})
