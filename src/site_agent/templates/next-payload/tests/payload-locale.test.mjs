import assert from 'node:assert/strict'
import test from 'node:test'

import { resolvePayloadLocale } from '../src/lib/payload-locale.ts'

const enabledLocales = ['fr', 'en']

test('uses Payload’s default when no locale is requested', () => {
  assert.equal(resolvePayloadLocale(null, enabledLocales), undefined)
  assert.equal(resolvePayloadLocale('', enabledLocales), undefined)
})

test('accepts only explicit enabled locales', () => {
  assert.equal(resolvePayloadLocale('fr', enabledLocales), 'fr')
  assert.equal(resolvePayloadLocale('en', enabledLocales), 'en')
  assert.throws(() => resolvePayloadLocale('all', enabledLocales), /not enabled/)
})

test('rejects an unconfigured locale instead of forwarding an invalid Payload value', () => {
  assert.throws(() => resolvePayloadLocale('es', enabledLocales), /not enabled/)
  assert.throws(() => resolvePayloadLocale('fr', []), /not enabled/)
})

test('rejects malformed explicit locale values rather than silently selecting the default', () => {
  assert.throws(() => resolvePayloadLocale(42, enabledLocales), /must be a string/)
  assert.throws(() => resolvePayloadLocale({ locale: 'fr' }, enabledLocales), /must be a string/)
})
