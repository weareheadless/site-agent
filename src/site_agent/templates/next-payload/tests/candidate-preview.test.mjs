import assert from 'node:assert/strict'
import test from 'node:test'
import { exactCandidatePreviewReady } from '../src/admin/lib/candidate-preview.ts'

const candidate = { run_id: 'run-1', candidate_sha: 'a'.repeat(40), preview: {
  run_id: 'run-1', candidate_sha: 'a'.repeat(40), job_id: 'job-1', status: 'ready', preview_url: '/preview/job-1/',
} }

test('a compiled exact candidate is visible before publication eligibility', () => {
  assert.equal(exactCandidatePreviewReady(candidate), true)
})

test('preparing, failed and stale candidates never mount as ready previews', () => {
  for (const patch of [{ status: 'running' }, { status: 'failed' }, { run_id: 'old-run' },
    { candidate_sha: 'b'.repeat(40) }, { job_id: '' }, { preview_url: null }]) {
    assert.equal(exactCandidatePreviewReady({ ...candidate, preview: { ...candidate.preview, ...patch } }), false)
  }
})
