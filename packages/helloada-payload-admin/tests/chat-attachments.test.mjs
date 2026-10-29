import test from 'node:test'
import assert from 'node:assert/strict'
import { canSendChatAttachments, remainingChatAttachmentSlots, splitChatImageFiles } from '../src/lib/chat-attachments.ts'

test('mixed selections retain supported images and report unsupported files separately', () => {
  const files = [{ name: 'a.png', type: 'image/png' }, { name: 'notes.pdf', type: 'application/pdf' }]
  const result = splitChatImageFiles(files)
  assert.deepEqual(result.supported.map((file) => file.name), ['a.png'])
  assert.deepEqual(result.unsupported.map((file) => file.name), ['notes.pdf'])
})

test('successful attachment remains independently ready when later upload fails', () => {
  const readyIds = []
  for (const result of [{ ok: true, id: 'asset-1' }, { ok: false }]) {
    if (result.ok && !readyIds.includes(result.id)) readyIds.push(result.id)
  }
  assert.deepEqual(readyIds, ['asset-1'])
  assert.equal(canSendChatAttachments(false, readyIds.length, ['failed']), false)
  assert.equal(canSendChatAttachments(false, readyIds.length, []), true)
})

test('limit accounts for ready and in-flight items; removal restores one slot', () => {
  assert.equal(remainingChatAttachmentSlots(11, 1), 0)
  assert.equal(remainingChatAttachmentSlots(10, 1), 1)
  assert.equal(remainingChatAttachmentSlots(10, 0), 2)
})

test('uploading, failed, and unsupported items cannot enable send; payload-ready list uses asset IDs', () => {
  for (const state of ['uploading', 'failed', 'unsupported']) {
    assert.equal(canSendChatAttachments(false, 0, [state]), false)
  }
  const requestAttachments = [{ asset_id: 'asset-1' }, { asset_id: 42 }].map(({ asset_id }) => ({ asset_id }))
  assert.deepEqual(requestAttachments, [{ asset_id: 'asset-1' }, { asset_id: 42 }])
})
