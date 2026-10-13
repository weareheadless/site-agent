import assert from 'node:assert/strict'
import test from 'node:test'
import { selectOwnerCollections, selectOwnerGlobals } from '../src/lib/owner-navigation.ts'

test('owner navigation exposes authored content, not operational collections', () => {
  const items = ['pages', 'posts', 'media', 'contactForms', 'appointmentTypes', 'calendarEvents', 'contacts', 'messages', 'users']
    .map((slug) => ({ slug }))
  assert.deepEqual(selectOwnerCollections(items).map(({ slug }) => slug), ['pages', 'posts', 'media', 'contactForms'])
})

test('owner settings never link to hidden mailbox or calendar globals', () => {
  const items = ['siteSettings', 'navigation', 'messageMailbox', 'calendarSettings'].map((slug) => ({ slug }))
  assert.deepEqual(selectOwnerGlobals(items, ['siteSettings', 'navigation', 'messageMailbox', 'calendarSettings']).map(({ slug }) => slug), ['siteSettings', 'navigation'])
})
