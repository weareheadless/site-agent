import assert from 'node:assert/strict'
import test from 'node:test'

import { helloAdaSectionEntries, readHelloAdaGlobal, readHelloAdaPage, readHelloAdaPost, readHelloAdaPosts, readHelloAdaProduct } from '../src/server.ts'

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
  await readHelloAdaProduct(payload, 'lamp', 'en')
  await readHelloAdaPosts(payload, 'en')
  await readHelloAdaGlobal(payload, 'navigation', 'es-MX')
  const page = payload.calls.find(([, args]) => args.collection === 'pages')?.[1]
  const post = payload.calls.find(([, args]) => args.collection === 'posts' && args.where.and)?.[1]
  const product = payload.calls.find(([, args]) => args.collection === 'products')?.[1]
  const listing = payload.calls.find(([, args]) => args.collection === 'posts' && args.where.published)?.[1]
  const global = payload.calls.find(([kind]) => kind === 'findGlobal')?.[1]
  assert.equal(page.locale, 'es-MX')
  assert.deepEqual(page.where.and[1], { published: { equals: true } })
  assert.equal(post.where.and[1].published.equals, true)
  assert.equal(product.where.and[1].published.equals, true)
  assert.equal(listing.where.published.equals, true)
  assert.equal(global.slug, 'navigation')
  assert.equal(global.locale, 'es-MX')
})

test('stable section keys, never array position, resolve an editable group', () => {
  const document = { sections: [{ key: 'contact', entries: [{ key: 'phone', type: 'helloAdaLink' }] }, { key: 'intro', entries: [{ key: 'heading' }] }] }
  assert.equal(helloAdaSectionEntries(document, 'contact')[0].key, 'phone')
  assert.equal(helloAdaSectionEntries(document, 'missing').length, 0)
})
