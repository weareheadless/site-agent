import assert from 'node:assert/strict'
import test from 'node:test'

import { createHelloAdaContractIdentity } from '../src/contract.ts'

test('shared schema identity is locale-independent while tenant configuration remains explicit', () => {
  const atelier = createHelloAdaContractIdentity({ locales: ['fr', 'en'], defaultLocale: 'fr' })
  const oceanic = createHelloAdaContractIdentity({ locales: ['en'], defaultLocale: 'en' })
  const reordered = createHelloAdaContractIdentity({ locales: ['en', 'fr'], defaultLocale: 'fr' })
  assert.equal(atelier.schemaIdentity, oceanic.schemaIdentity)
  assert.equal(atelier.configurationIdentity, reordered.configurationIdentity)
  assert.notEqual(atelier.configurationIdentity, oceanic.configurationIdentity)
  assert.notEqual(
    atelier.schemaIdentity,
    createHelloAdaContractIdentity({ collections: ['pages'], locales: ['en'], defaultLocale: 'en' }).schemaIdentity,
  )
  assert.throws(() => createHelloAdaContractIdentity({ collections: ['pages', 'customData'], locales: ['en'], defaultLocale: 'en' }), /Unsupported HelloAda collections/)
  assert.throws(() => createHelloAdaContractIdentity({ locales: ['fr'], defaultLocale: 'en' }), /default locale must be included/)
})
