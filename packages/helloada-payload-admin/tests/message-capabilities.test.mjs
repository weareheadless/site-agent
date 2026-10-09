import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { isBusinessCorrespondenceReady } from '../src/lib/message-capabilities.ts'

const messagesUi = readFileSync(new URL('../src/components/HelloAdaMessages.tsx', import.meta.url), 'utf8')

test('business correspondence is enabled only for an active verified Resend mailbox', () => {
  assert.equal(isBusinessCorrespondenceReady({
    address: 'owner@example.com',
    state: 'active',
    outboundProvider: 'resend',
    outboundMode: 'business_correspondence',
  }), true)
})

test('mailbox readiness alone does not enable correspondence sending', () => {
  for (const mailbox of [
    undefined,
    { address: 'owner@example.com', state: 'pending', outboundProvider: 'resend', outboundMode: 'business_correspondence' },
    { address: 'owner@example.com', state: 'active', outboundProvider: 'cloudflare', outboundMode: 'business_correspondence' },
    { address: 'owner@example.com', state: 'active', outboundProvider: 'resend', outboundMode: 'transactional_only' },
    { address: '  ', state: 'active', outboundProvider: 'resend', outboundMode: 'business_correspondence' },
  ]) assert.equal(isBusinessCorrespondenceReady(mailbox), false)
})

test('the shared Messages UI uses the verified sender capability for every send action', () => {
  assert.match(messagesUi, /const canSendBusinessEmail = isBusinessCorrespondenceReady\(mailbox\)/)
  assert.match(messagesUi, /const canSendCurrentDraft = canSendBusinessEmail/)
  assert.doesNotMatch(messagesUi, /const canSendCurrentDraft = canSend && currentDraft\?\.direction !== 'owner_message'/)
})
