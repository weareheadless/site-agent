import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildOwnerMessageNotification,
  createMessageNotificationCode,
  equalMessageNotificationCodeHash,
  hashMessageNotificationCode,
  messageNotificationInboxUrl,
} from '../src/lib/message-notifications.ts'

test('verification codes are fixed-width and HMAC-bound to tenant and address', async () => {
  const code = createMessageNotificationCode()
  assert.match(code, /^\d{8}$/)
  const secret = 'tenant-service-secret'
  const digest = await hashMessageNotificationCode(secret, 'oceanicvibes', 'owner@example.com', code)
  assert.equal(equalMessageNotificationCodeHash(digest, digest), true)
  const changed = `${digest.slice(0, -1)}${digest.endsWith('0') ? '1' : '0'}`
  assert.equal(equalMessageNotificationCodeHash(digest, changed), false)
  assert.equal(equalMessageNotificationCodeHash(digest, await hashMessageNotificationCode(secret, 'atelier', 'owner@example.com', code)), false)
  assert.equal(equalMessageNotificationCodeHash(digest, await hashMessageNotificationCode(secret, 'oceanicvibes', 'other@example.com', code)), false)
  assert.equal(equalMessageNotificationCodeHash(digest, 'invalid'), false)
})

test('owner alerts are plain-text previews linked to the correct authenticated conversation', () => {
  const url = messageNotificationInboxUrl('oceanicvibes.com', '42')
  const parsed = new URL(url)
  assert.equal(parsed.origin, 'https://oceanicvibes.com')
  assert.equal(parsed.pathname, '/admin')
  assert.equal(parsed.searchParams.get('view'), 'messages')
  assert.equal(parsed.searchParams.get('state'), 'all')
  assert.equal(parsed.searchParams.get('conversation'), '42')
  assert.throws(() => messageNotificationInboxUrl('javascript:alert(1)', '42'))

  const alert = buildOwnerMessageNotification({
    mailboxAddress: 'hello@oceanicvibes.com',
    domain: 'oceanicvibes.com',
    conversationId: '42',
    sender: 'Visitor <visitor@example.com>\r\nBcc: attacker@example.com',
    subject: 'Need a booking\r\nBcc: attacker@example.com',
    preview: 'A'.repeat(2_000),
    locale: 'es-MX',
  })
  assert.equal(alert.subject.startsWith('Mensaje nuevo:'), true)
  assert.doesNotMatch(alert.subject, /[\r\n]/)
  assert.equal(alert.text.includes('Bcc: attacker@example.com'), false)
  assert.equal(alert.text.includes('A'.repeat(1_201)), false)
  assert.match(alert.text, /Abrir la conversación y responder: https:\/\/oceanicvibes\.com\/admin\?/)
  assert.match(alert.text, /Responde desde HelloAda/)
})
