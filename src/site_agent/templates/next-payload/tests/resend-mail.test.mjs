import assert from 'node:assert/strict'
import test from 'node:test'

import { sendResendMessage } from '../src/lib/resend-mail.ts'

test('Resend delivery identifies the site-agent client', async (t) => {
  const originalFetch = globalThis.fetch
  let request
  t.after(() => {
    globalThis.fetch = originalFetch
  })
  globalThis.fetch = async (url, options) => {
    request = { url, options }
    return Response.json({ id: 're_test_receipt' })
  }

  const receipt = await sendResendMessage('test-key', 'tenant', 'operation', {
    from: 'owner@example.com',
    to: 'visitor@example.net',
    subject: 'Test',
    text: 'Test message',
  })

  assert.equal(receipt, 're_test_receipt')
  assert.equal(request.url, 'https://api.resend.com/emails')
  const headers = new Headers(request.options.headers)
  assert.equal(headers.get('User-Agent'), 'site-agent/0.1 (+https://helloada.app)')
  assert.equal(headers.get('Idempotency-Key'), 'helloada:tenant:operation')
})
