import assert from 'node:assert/strict'
import test from 'node:test'

import { resolvePayloadLocale } from '../src/lib/payload-locale.ts'

const enabledLocales = ['fr', 'en']

test('uses Payload’s default when no locale is requested', () => {
  assert.equal(resolvePayloadLocale(null, enabledLocales), undefined)
  assert.equal(resolvePayloadLocale('', enabledLocales), undefined)
})

test('accepts only enabled locales and Payload’s all-locale selector', () => {
  assert.equal(resolvePayloadLocale('fr', enabledLocales), 'fr')
  assert.equal(resolvePayloadLocale('en', enabledLocales), 'en')
  assert.equal(resolvePayloadLocale('all', enabledLocales), 'all')
})

test('rejects an unconfigured locale instead of forwarding an invalid Payload value', () => {
  assert.throws(() => resolvePayloadLocale('es', enabledLocales), /not enabled/)
  assert.throws(() => resolvePayloadLocale('all', []), /unavailable/)
})

test('rejects malformed explicit locale values rather than silently selecting the default', () => {
  assert.throws(() => resolvePayloadLocale(42, enabledLocales), /must be a string/)
  assert.throws(() => resolvePayloadLocale({ locale: 'fr' }, enabledLocales), /must be a string/)
})
