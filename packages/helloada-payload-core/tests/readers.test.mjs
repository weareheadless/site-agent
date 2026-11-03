import assert from 'node:assert/strict'
import test from 'node:test'

import { helloAdaSectionEntries, readHelloAdaGlobal, readHelloAdaPage, readHelloAdaPost, readHelloAdaPosts, readHelloAdaProduct, readHelloAdaProductCatalog } from '../src/server.ts'

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

test('catalog readers paginate child rows and never query a draft or unrelated product', async () => {
  const calls = []
  const payload = { async find(args) {
    calls.push(args)
    if (args.collection === 'products') return { docs: [{ id: 7, options: [{ key: 'size', values: [{ key: 'm' }] }] }] }
    if (args.collection === 'productAttributes') return { docs: [{ id: args.page }], hasNextPage: args.page === 1 }
    return { docs: [{ id: 3, options: [{ option: 'size', value: 'm' }] }], hasNextPage: false }
  } }
  const result = await readHelloAdaProductCatalog(payload, 'shirt', 'fr')
  assert.equal(result.attributes.length, 2)
  assert.equal(result.variants.length, 1)
  for (const args of calls.slice(1)) {
    assert.equal(args.draft, false)
    assert.equal(args.locale, 'fr')
    assert.deepEqual(args.where.and, [{ product: { equals: 7 } }, { published: { equals: true } }])
  }
  assert.equal(await readHelloAdaProductCatalog({ find: async () => ({ docs: [] }) }, 'absent', 'en'), undefined)
})

test('a published variant cannot silently use options that only exist in a parent draft', async () => {
  const payload = { async find({ collection }) {
    if (collection === 'products') return { docs: [{ id: 7, options: [] }] }
    return { docs: collection === 'productVariants' ? [{ id: 8, options: [{ option: 'size', value: 'm' }] }] : [] }
  } }
  await assert.rejects(() => readHelloAdaProductCatalog(payload, 'shirt', 'fr'), /Published variant 8/)
})
