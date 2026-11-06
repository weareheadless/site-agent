import assert from 'node:assert/strict'
import test from 'node:test'

import { helloAdaWorkspacePath } from '../src/admin/server/runtime-env.ts'

test('publication and checkpoint routes reach the workspace bridge', () => {
  assert.equal(helloAdaWorkspacePath('/api/helloada/publication', 'GET'), '/workspace/publication')
  assert.equal(helloAdaWorkspacePath('/api/helloada/checkpoints', 'GET', '?limit=40'), '/workspace/checkpoints?limit=40')
  assert.equal(helloAdaWorkspacePath('/api/helloada/checkpoints/restore', 'POST'), '/workspace/checkpoints/restore')
})

test('publication and checkpoint routes reject the wrong method', () => {
  assert.equal(helloAdaWorkspacePath('/api/helloada/publication', 'POST'), undefined)
  assert.equal(helloAdaWorkspacePath('/api/helloada/checkpoints', 'POST'), undefined)
  assert.equal(helloAdaWorkspacePath('/api/helloada/checkpoints/restore', 'GET'), undefined)
})
