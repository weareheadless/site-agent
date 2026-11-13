import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'

/**
 * The tenant bridge is a contract, not a passthrough: only the paths named
 * here reach the site-agent. A Growth route the UI calls but the bridge does
 * not map is a 503 in the owner's browser, which is how the decision queue
 * first failed. These cases pin the whole opportunity/task surface.
 */
const load = async () => {
  const source = readFileSync(new URL('../src/lib/helloada-runtime.ts', import.meta.url), 'utf8')
    .replace(/^import[^\n]+\n/gm, '')
  const javascript = stripTypeScriptTypes(source)
  return import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64'))
}

test('the bridge maps the opportunity queue with its filters', async () => {
  const { helloAdaWorkspacePath } = await load()
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth/opportunities', 'GET', '?status=detected&limit=100'),
    '/workspace/growth/opportunities?status=detected&limit=100',
  )
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth/opportunities', 'POST'),
    undefined,
  )
})

test('the bridge maps one decision and one task, and refuses a wrong method', async () => {
  const { helloAdaWorkspacePath } = await load()
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth/opportunities/cmu123abc_-x/decision', 'POST'),
    '/workspace/growth/opportunities/cmu123abc_-x/decision',
  )
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth/opportunities/cmu123abc/decision', 'GET'),
    undefined,
  )
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth/tasks/cmu123abc', 'GET'),
    '/workspace/growth/tasks/cmu123abc',
  )
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/growth/tasks/cmu123abc', 'POST'),
    '/workspace/growth/tasks/cmu123abc',
  )
  assert.equal(helloAdaWorkspacePath('/api/helloada/growth/tasks/cmu123abc', 'DELETE'), undefined)
})

test('the bridge does not extend an id into another path segment', async () => {
  const { helloAdaWorkspacePath } = await load()
  // A caller cannot smuggle a second segment or an encoded separator through
  // the id, because the shape is anchored and the id charset excludes `/`.
  assert.equal(helloAdaWorkspacePath('/api/helloada/growth/tasks/one/two', 'GET'), undefined)
  assert.equal(helloAdaWorkspacePath('/api/helloada/growth/opportunities/a%2Fb/decision', 'POST'), undefined)
  assert.equal(helloAdaWorkspacePath('/api/helloada/growth/opportunities/../decision', 'POST'), undefined)
})

test('the bridge keeps mapping the saved analytics observations', async () => {
  const { helloAdaWorkspacePath } = await load()
  assert.equal(
    helloAdaWorkspacePath('/api/helloada/seo/analytics', 'GET', '?days=28'),
    '/workspace/seo/analytics?days=28',
  )
})
