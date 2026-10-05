import assert from 'node:assert/strict'
import test from 'node:test'

import {
  helloAdaIdempotencyKey,
  normalizeHelloAdaEmail,
  validateHelloAdaFormSubmission,
  validateHelloAdaReplyText,
} from '../src/messages/index.ts'

const form = {
  _status: 'published', enabled: true,
  fields: [
    { key: 'name', label: 'Name', type: 'text', mapsTo: 'name' },
    { key: 'email', label: 'Email', type: 'email', mapsTo: 'email', required: true },
    { key: 'message', label: 'Message', type: 'textarea', mapsTo: 'message', required: true, maxLength: 2000 },
    { key: 'terms', label: 'I agree', type: 'consent', mapsTo: 'none', required: true },
    { key: 'interest', label: 'Interested in', type: 'select', mapsTo: 'none', choices: [{ key: 'repair', label: 'Repair' }] },
  ],
}

test('email normalization preserves local-part semantics and only normalizes domain case', () => {
  assert.equal(normalizeHelloAdaEmail('  Jane+site@EXAMPLE.COM  '), 'Jane+site@example.com')
  assert.throws(() => normalizeHelloAdaEmail('not-an-email'))
  assert.throws(() => normalizeHelloAdaEmail('x@example.com\r\nBcc:evil@example.com'))
})

test('form submissions are bounded and validated against published form fields', () => {
  const result = validateHelloAdaFormSubmission(form, {
    answers: { name: ' Jane ', email: 'Jane@EXAMPLE.com', message: ' Hello ', terms: true, interest: 'repair' },
  })
  assert.deepEqual(result.contact, { name: 'Jane', email: 'Jane@example.com' })
  assert.equal(result.message, 'Hello')
  assert.throws(() => validateHelloAdaFormSubmission({ ...form, enabled: false }, { answers: {} }), /not accepting/)
  assert.throws(() => validateHelloAdaFormSubmission(form, { answers: { email: 'visitor@example.com', message: 'Hi' } }), /confirm/)
  assert.throws(() => validateHelloAdaFormSubmission(form, { answers: { email: 'visitor@example.com', message: 'Hi', terms: true, interest: 'admin' } }), /available answers/)
  assert.throws(() => validateHelloAdaFormSubmission(form, { answers: { email: 'visitor@example.com', message: 'Hi', terms: true, unexpected: 'value' } }), /unknown field/)
})

test('reply drafts and client idempotency keys have strict bounds', () => {
  assert.equal(validateHelloAdaReplyText('  Thanks for reaching out.  '), 'Thanks for reaching out.')
  assert.throws(() => validateHelloAdaReplyText('  '), /plain text/)
  assert.throws(() => validateHelloAdaReplyText(`x${'a'.repeat(10_000)}`), /10,000/)
  assert.equal(helloAdaIdempotencyKey('request_id_123456'), 'request_id_123456')
  assert.throws(() => helloAdaIdempotencyKey('short'), /request ID/)
})
