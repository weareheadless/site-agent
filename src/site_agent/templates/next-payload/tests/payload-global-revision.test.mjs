import assert from 'node:assert/strict'
import test from 'node:test'

import { hashJson, withoutPayloadMetadata } from '../src/lib/payload-hash.ts'

test('global draft write and subsequent read have the same content revision', async () => {
  const fields = { siteName: 'Owner identity', description: 'Confirmed copy', logo: null }
  // Payload updateGlobal attaches globalType after saving a draft version;
  // findGlobal projects the persisted fields without that operation metadata.
  for (const globalType of [undefined, 'siteSettings']) {
    const written = { ...fields, id: 1, globalType, _status: 'draft' }
    const read = { ...fields, _status: 'draft' }
    assert.equal(await hashJson(withoutPayloadMetadata(written)), await hashJson(withoutPayloadMetadata(read)))
  }
})

test('global revision still changes when any authored field changes', async () => {
  const before = { siteName: 'Owner identity', description: 'Confirmed copy' }
  const after = { ...before, description: 'Another writer changed the copy' }
  assert.notEqual(await hashJson(withoutPayloadMetadata(before)), await hashJson(withoutPayloadMetadata(after)))
})
