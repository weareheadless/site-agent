import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { isBusinessCorrespondenceReady } from '../src/lib/message-capabilities.ts'
import { isHelloAdaMessageDraftHash } from '../src/lib/message-draft-contract.ts'

const messagesUi = readFileSync(new URL('../src/components/HelloAdaMessages.tsx', import.meta.url), 'utf8')
const templateApi = readFileSync(new URL('../../../src/site_agent/templates/next-payload/src/lib/messages-api.ts', import.meta.url), 'utf8')

test('business correspondence is enabled only for an active verified Resend mailbox', () => {
  assert.equal(isBusinessCorrespondenceReady({
    address: 'owner@example.com',
    state: 'active',
    outboundProvider: 'resend',
    outboundMode: 'business_correspondence',
  }), true)
})

test('reviewed draft hashes match the exact shared SHA-256 representation', () => {
  assert.equal(isHelloAdaMessageDraftHash(`sha256:${'a'.repeat(64)}`), true)
  for (const value of [
    'a'.repeat(64),
    `sha256:${'A'.repeat(64)}`,
    `sha256:${'a'.repeat(63)}`,
    `sha256:${'a'.repeat(65)}`,
    undefined,
  ]) assert.equal(isHelloAdaMessageDraftHash(value), false)
})

test('both server send paths use the shared reviewed-draft hash contract', () => {
  assert.match(templateApi, /import \{ isHelloAdaMessageDraftHash \} from '@weareheadless\/helloada-payload-admin\/message-draft-contract'/)
  assert.equal((templateApi.match(/if \(!isHelloAdaMessageDraftHash\(draftHash\)\)/g) || []).length, 2)
  assert.doesNotMatch(templateApi, /if \(!\/\^\[a-f0-9\]\{64\}\$\/\.test\(draftHash\)\)/)
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

test('saved draft detail restores only the currently approved send-review hash', () => {
  assert.equal(templateApi.split('item.approvalHash === currentHash').length - 1, 2)
  assert.equal(messagesUi.split('setDraftHash(isHelloAdaMessageDraftHash(').length - 1, 2)
})

test('new-message composition stays in the mailbox and separates saved review from sending', () => {
  assert.match(messagesUi, /helloada-inline-composer/)
  assert.doesNotMatch(messagesUi, /helloada-compose-dialog/)
  assert.match(messagesUi, /name="intent" value="save"/)
  assert.match(messagesUi, /name="intent" value="review"/)
  assert.match(messagesUi, /setConfirmSend\(true\)/)
  assert.match(messagesUi, /helloada-send-preview/)
  assert.match(messagesUi, /owner\.messagesSendNow/)
})

test('selected mailbox folder survives a page reconnect', () => {
  assert.match(messagesUi, /initialMessageFilter/)
  assert.match(messagesUi, /searchParams\.get\('folder'\)/)
  assert.match(messagesUi, /searchParams\.set\('folder', filter\)/)
})
