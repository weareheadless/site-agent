import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { hashOwnerMessageDraft } from '../src/lib/owner-message-draft-hash.ts'

test('Payload numeric IDs and Worker string IDs share one owner-message approval hash', async () => {
  const fields = {
    conversationId: '23',
    revision: 2,
    from: 'northstar-coffee@helloada.app',
    to: 'northstar-coffee@helloada.app',
    cc: [],
    bcc: [],
    subject: 'Resend live delivery check',
    text: 'Self-addressed delivery test.',
  }

  const payloadHash = await hashOwnerMessageDraft({ ...fields, messageId: 41 })
  const workerHash = await hashOwnerMessageDraft({ ...fields, messageId: '41' })

  assert.equal(payloadHash, workerHash)
})

test('the API and queue processor both use the canonical owner-message hash', async () => {
  const api = await readFile(new URL('../src/lib/messages-api.ts', import.meta.url), 'utf8')
  const processor = await readFile(new URL('../src/lib/message-processing.ts', import.meta.url), 'utf8')

  assert.match(api, /hashOwnerMessageDraft\(/)
  assert.match(processor, /hashOwnerMessageDraft\(/)
  assert.match(processor, /message_integrity_mismatch/)
})
