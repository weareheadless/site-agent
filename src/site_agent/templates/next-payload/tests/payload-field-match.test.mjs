import assert from 'node:assert/strict'
import { fieldMismatchDiagnostic, fieldMismatchKeys, fieldValueMatches } from '../src/lib/payload-field-match.ts'

const requested = {
  title: 'Draft title',
  slug: 'draft-title',
  hero: { id: 41 },
  content: [{
    blockType: 'image',
    image: { id: 52, url: '/media/hero.png', filename: 'hero.png' },
  }],
}

const persisted = {
  ...requested,
  id: 7,
  createdAt: '2026-10-21T12:00:00.000Z',
  updatedAt: '2026-10-21T12:00:01.000Z',
  _status: 'draft',
  hero: { id: 41, url: '/api/media/file/41/portrait.png', filename: 'portrait.png', createdAt: '2026-01-01' },
  content: [{
    id: 'block-1',
    blockType: 'image',
    image: { id: 52, url: '/api/media/file/52/hero.png', filename: 'hero.png', updatedAt: '2026-10-21' },
    createdAt: '2026-10-21',
    _status: 'draft',
  }],
}

assert.equal(fieldValueMatches(persisted, requested), true, 'Payload relation wrappers and metadata remain idempotent')
assert.deepEqual(fieldMismatchKeys(persisted, requested), [])

const changed = {
  ...persisted,
  title: 'Stored secret title',
  content: [{ blockType: 'image', image: { id: 999, url: '/private/stored.png' } }],
}
assert.equal(fieldValueMatches(changed, requested), false)
assert.deepEqual(fieldMismatchKeys(changed, requested), ['title', 'content'], 'only mismatched top-level input keys are reported')

const diagnostic = fieldMismatchDiagnostic(fieldMismatchKeys(changed, requested))
assert.equal(diagnostic, 'Payload did not persist the exact requested draft fields: title, content')
assert.ok(!diagnostic.includes('Stored secret title'))
assert.ok(!diagnostic.includes('/private/stored.png'))
assert.ok(!diagnostic.includes('Draft title'))

console.log('payload field comparison regression tests passed')

const seoPatch = { seo: { title: 'New search title', description: 'New description' } }
assert.equal(fieldValueMatches({ seo: { ...seoPatch.seo, image: null } }, seoPatch), true,
  'Optional group defaults must not make a schema-valid partial update look unsaved')
assert.equal(fieldValueMatches({ seo: { ...seoPatch.seo, image: 52 } }, seoPatch), true,
  'A partial group update must preserve unrequested existing values')
assert.equal(fieldValueMatches({ seo: { ...seoPatch.seo, title: 'Different' } }, seoPatch), false)
assert.equal(fieldValueMatches({ seo: { title: seoPatch.seo.title } }, seoPatch), false,
  'Every explicitly requested nested value must be persisted')
assert.equal(fieldValueMatches({ content: [{ text: 'First' }, { text: 'Unexpected' }] },
  { content: [{ text: 'First' }] }), false, 'Arrays remain exact in length and order')
assert.equal(fieldValueMatches({ content: [{ text: 'Second' }, { text: 'First' }] },
  { content: [{ text: 'First' }, { text: 'Second' }] }), false)
