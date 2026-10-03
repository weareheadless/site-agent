import assert from 'node:assert/strict'
import test from 'node:test'

import { helloAdaSectionEntries, readHelloAdaGlobal, readHelloAdaPage, readHelloAdaPost, readHelloAdaPosts } from '../src/server.ts'

const makePayload = () => {
  const calls = []
  return {
    calls,
    async find(args) { calls.push(['find', args]); return { docs: [{ id: 1, slug: 'home', sections: [] }] } },
    async findGlobal(args) { calls.push(['findGlobal', args]); return { siteName: 'Tenant site' } },
  }
}

test('public readers use published, tenant-local Payload reads and the explicit locale', async () => {
  const payload = makePayload()
  await readHelloAdaPage(payload, '/home/', 'es-MX')
  await readHelloAdaPost(payload, 'story', 'fr')
  await readHelloAdaPosts(payload, 'en')
  await readHelloAdaGlobal(payload, 'navigation', 'es-MX')
  assert.equal(payload.calls[0][1].locale, 'es-MX')
  assert.deepEqual(payload.calls[0][1].where.and[1], { published: { equals: true } })
  assert.equal(payload.calls[1][1].where.and[1].published.equals, true)
  assert.equal(payload.calls[2][1].where.published.equals, true)
  assert.equal(payload.calls[3][1].slug, 'navigation')
  assert.equal(payload.calls[3][1].locale, 'es-MX')
})

test('stable section keys, never array position, resolve an editable group', () => {
  const document = { sections: [{ key: 'contact', entries: [{ key: 'phone', type: 'helloAdaLink' }] }, { key: 'intro', entries: [{ key: 'heading' }] }] }
  assert.equal(helloAdaSectionEntries(document, 'contact')[0].key, 'phone')
  assert.equal(helloAdaSectionEntries(document, 'missing').length, 0)
})
