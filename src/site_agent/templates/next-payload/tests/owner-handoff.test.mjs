import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import test from 'node:test'

import { verifyOwnerHandoffToken } from '../src/lib/helloada-handoff.ts'

const encoder = new TextEncoder()
const encode = (value) => Buffer.from(value).toString('base64url')

async function tokenFor(overrides = {}) {
  const pair = await webcrypto.subtle.generateKey({
    name: 'RSASSA-PKCS1-v1_5',
    modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]),
    hash: 'SHA-256',
  }, true, ['sign', 'verify'])
  const publicKey = new Uint8Array(await webcrypto.subtle.exportKey('spki', pair.publicKey))
  const now = 1_800_000_000
  const header = encode(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
  const claims = {
    iss: 'https://helloada.app',
    aud: 'tenant-demo',
    sub: 'owner-42',
    jti: 'a9V4sR3eQ2wX7cL8',
    purpose: 'payload-admin-session',
    target_origin: 'https://tenant-demo.workers.dev',
    iat: now,
    exp: now + 60,
    ...overrides,
  }
  const body = encode(JSON.stringify(claims))
  const message = `${header}.${body}`
  const signature = await webcrypto.subtle.sign('RSASSA-PKCS1-v1_5', pair.privateKey, encoder.encode(message))
  return { token: `${message}.${encode(signature)}`, publicKey, now, claims }
}

const verifyOptions = (token) => ({
  issuer: 'https://helloada.app',
  tenantId: 'tenant-demo',
  targetOrigin: 'https://tenant-demo.workers.dev',
  publicKey: token.publicKey,
  nowSeconds: token.now,
})

test('owner handoff accepts an issuer-signed, short-lived grant for the exact tenant and origin', async () => {
  const issued = await tokenFor()
  assert.deepEqual(await verifyOwnerHandoffToken(issued.token, verifyOptions(issued)), issued.claims)
})

test('owner handoff rejects cross-tenant, cross-origin, wrong-purpose and expired grants', async () => {
  for (const overrides of [
    { aud: 'another-tenant' },
    { target_origin: 'https://attacker.example' },
    { purpose: 'publish-website' },
    { exp: 1_799_999_999 },
    { exp: 1_800_000_121 },
    { iat: 1_799_999_879 },
  ]) {
    const issued = await tokenFor(overrides)
    await assert.rejects(verifyOwnerHandoffToken(issued.token, verifyOptions(issued)))
  }
})

test('owner handoff rejects tampering and unsupported algorithms', async () => {
  const issued = await tokenFor()
  const parts = issued.token.split('.')
  const changedBody = encode(JSON.stringify({ ...issued.claims, sub: 'other-owner' }))
  await assert.rejects(verifyOwnerHandoffToken(`${parts[0]}.${changedBody}.${parts[2]}`, verifyOptions(issued)))
  const badHeader = encode(JSON.stringify({ alg: 'none', typ: 'JWT' }))
  await assert.rejects(verifyOwnerHandoffToken(`${badHeader}.${parts[1]}.${parts[2]}`, verifyOptions(issued)))
})
