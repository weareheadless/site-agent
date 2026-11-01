import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

// Exercise the real workspace callback without a second implementation of its
// selection/queue policy or a browser login in unit tests.
const source = readFileSync(new URL('../src/components/WebsiteWorkspace.tsx', import.meta.url), 'utf8')
const body = source.split('const loadPreviewPlan = useCallback(async () => {')[1].split('}, [t])')[0]
const compiled = ts.transpileModule(`export default async function(dependencies) {
  const { fetchHelloAda, setPreviewPlan, setSourceReview, setPreviewStatus, setPreviewRevision,
    setError, sourceReviewIdentityRef, t } = dependencies
  ${body}
}`, { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext } }).outputText
const loadPreviewPlan = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default

async function load(draft, latest, previousReview) {
  const calls = []
  const state = { review: previousReview }
  const setter = (key) => (value) => { state[key] = typeof value === 'function' ? value(state[key]) : value }
  await loadPreviewPlan({
    fetchHelloAda: async (url, options) => {
      calls.push({ url, options })
      return { ok: true, json: async () => url.includes('drafts?') ? { drafts: [draft] } : latest }
    },
    setPreviewPlan: setter('plan'), setSourceReview: setter('review'), setPreviewStatus: setter('status'),
    setPreviewRevision: setter('revision'), setError: setter('error'),
    sourceReviewIdentityRef: { current: '' }, t: (key) => key,
  })
  return { calls, state }
}

const sha = 'a'.repeat(40)
const merge = { id: 3, kind: 'merge', meta: { head_sha: sha, preview: { requires_build: true, mode: 'compile' } } }

test('merge preview queue carries the exact draft and never displays baseline content as review', async () => {
  const { calls, state } = await load(merge, { status: 'failed', commit: 'b'.repeat(40) })
  const start = calls.find((call) => call.options?.method === 'POST')
  assert.ok(start)
  assert.deepEqual(JSON.parse(start.options.body), { branch: 'preview', commit: sha, draft_id: 3, mode: 'compiled_preview' })
  assert.deepEqual(state.review, { draftId: 3, sha, url: '' })
})

test('a ready preview for the same commit but a different or absent draft cannot be substituted', async () => {
  for (const draft_id of [undefined, 2]) {
    const { calls, state } = await load(merge, { id: 'wrong-preview', status: 'ready', commit: sha, draft_id })
    assert.ok(calls.some((call) => call.options?.method === 'POST'))
    assert.equal(state.review.url, '')
  }
})

test('a ready exact merge draft uses its compiled runtime instead of the baseline page', async () => {
  const { calls, state } = await load(merge, { id: 'exact-preview', status: 'ready', commit: sha, draft_id: 3 })
  assert.equal(calls.filter((call) => call.options?.method === 'POST').length, 0)
  assert.equal(state.review.url, '/api/helloada/source/preview/exact-preview/runtime/')
  assert.equal(state.plan.status, 'ready')
})

test('design previews remain worker-owned and never queue a browser build', async () => {
  const draft = { ...merge, kind: 'design', meta: { ...merge.meta, candidate_sha: sha } }
  const { calls, state } = await load(draft, { status: 'running', commit: sha, design_run_id: 'retained-run' })
  assert.equal(calls.filter((call) => call.options?.method === 'POST').length, 0)
  assert.equal(state.review.url, '')
  assert.equal(state.status, 'build-required')
})

test('a persisted ready compile plan still resolves its exact runtime after reload', async () => {
  const ready = { ...merge, meta: { ...merge.meta, preview: { mode: 'compile', requires_build: false, status: 'ready' } } }
  const { state } = await load(ready, { id: 'exact-preview', status: 'ready', commit: sha, draft_id: 3 })
  assert.equal(state.review.url, '/api/helloada/source/preview/exact-preview/runtime/')
})

test('a compiled draft without an exact commit stays empty and cannot queue branch head', async () => {
  const incomplete = { ...merge, meta: { preview: { mode: 'compile', requires_build: true } } }
  const { calls, state } = await load(incomplete, {})
  assert.equal(calls.filter((call) => call.options?.method === 'POST').length, 0)
  assert.equal(state.review.url, '')
  assert.equal(state.status, 'error')
})

test('existing non-compiled overlay review retains its existing path', async () => {
  const overlay = { ...merge, meta: { ...merge.meta, preview: { mode: 'overlay', requires_build: false } } }
  const { calls, state } = await load(overlay, {})
  assert.equal(calls.length, 1)
  assert.equal(state.review, undefined)
  assert.equal(state.plan.mode, 'overlay')
})

test('publication stays disabled until the exact compiled review is visible', () => {
  assert.match(source, /disabled=\{publishing \|\| Boolean\(sourceReview && !sourceReview\.url\)\}/)
})

test('a failed or pending recheck clears a previously visible compiled review', async () => {
  for (const status of ['failed', 'running']) {
    const { state } = await load(merge, { id: 'rechecked', status, commit: sha, draft_id: 3 },
      { draftId: 3, sha, url: '/api/helloada/source/preview/old-ready/runtime/' })
    assert.equal(state.review.url, '')
  }
})
