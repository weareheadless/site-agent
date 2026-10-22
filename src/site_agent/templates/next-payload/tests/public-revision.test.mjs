import assert from 'node:assert/strict'
import test from 'node:test'
import { publicRevisionAttributes } from '../src/lib/public-revision.ts'

test('public proof identifies the actual supplied Payload revision without altering the document', () => {
  const document = Object.freeze({ id: 6, updatedAt: '2026-10-21T01:02:03.000Z', title: 'Content' })
  assert.deepEqual(publicRevisionAttributes(document), {
    'data-helloada-document-id': '6',
    'data-helloada-updated-at': '2026-10-21T01:02:03.000Z',
  })
  assert.equal(document.title, 'Content')
})

test('missing canonical identity or revision never emits successful proof', () => {
  for (const document of [{}, { id: 6 }, { updatedAt: '2026-10-21' }, { id: '', updatedAt: '2026-10-21' }]) {
    assert.throws(() => publicRevisionAttributes(document), /canonical Payload document revision/)
  }
})
