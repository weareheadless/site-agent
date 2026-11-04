import assert from 'node:assert/strict'
import test from 'node:test'

import {
  categoryCriteriaWhere,
  categoryRoute,
  readCategoryMembers,
} from '../src/catalog/reader.ts'

const product = (overrides = {}) => ({
  id: 1,
  slug: 'a-product',
  title: 'A product',
  published: true,
  _status: 'published',
  priceMinor: 15000000,
  availability: 'Under Construction',
  location: { city: 'Tulum', region: 'Aldea Zama' },
  ...overrides,
})

test('the category query narrows only the fields that are not localized', () => {
  assert.deepEqual(
    categoryCriteriaWhere({
      city: ' Tulum ', region: 'Aldea Zama', priceMinMinor: 0, priceMaxMinor: 20000000, availability: 'Ready',
    }),
    {
      and: [
        { published: { equals: true } },
        { _status: { equals: 'published' } },
        { 'location.city': { equals: 'Tulum' } },
        { 'location.region': { equals: 'Aldea Zama' } },
        { priceMinor: { greater_than_equal: 0 } },
        { priceMinor: { less_than: 20000000 } },
      ],
    },
  )
  assert.deepEqual(categoryCriteriaWhere({}), {
    and: [{ published: { equals: true } }, { _status: { equals: 'published' } }],
  })
})

test('membership is decided by the shared predicate, not by the query alone', async () => {
  const queries = []
  const docs = [
    product({ id: 1, slug: 'alpha', availability: 'Ready' }),
    product({ id: 2, slug: 'bravo', availability: 'ready' }),
    product({ id: 3, slug: 'charlie', availability: 'Under Construction' }),
    product({ id: 4, slug: 'delta', published: false }),
    product({ id: 5, slug: 'echo', priceMinor: 99999999 }),
  ]
  const payload = {
    find: async (query) => {
      queries.push(query)
      return { docs }
    },
  }
  const criteria = { city: 'Tulum', availability: 'Ready', priceMaxMinor: 20000000 }
  const result = await readCategoryMembers(payload, { criteria, locale: 'es', limit: 1 })
  assert.equal(queries.length, 1)
  assert.equal(queries[0].collection, 'products')
  assert.equal(queries[0].draft, false)
  assert.equal(queries[0].locale, 'es')
  assert.equal(queries[0].sort, 'slug', 'the source grids are alphabetical by localized slug')
  assert.equal(queries[0].depth, 1)
  assert.equal(queries[0].pagination, false)
  assert.equal(queries[0].where.and.some((row) => 'availability' in row), false,
    'localized availability is never a SQL filter')
  assert.equal(result.total, 2, 'case-insensitive availability and the shared predicate decide membership')
  assert.equal(result.pages, 2)
  assert.deepEqual(result.documents.map((doc) => doc.id), [1])
  const second = await readCategoryMembers(payload, { criteria, locale: 'es', page: 2, limit: 1 })
  assert.deepEqual(second.documents.map((doc) => doc.id), [2])
})

test('a page beyond the last page is empty but still reports the real total', async () => {
  const payload = { find: async () => ({ docs: [product({ id: 1 })] }) }
  const result = await readCategoryMembers(payload, { criteria: {}, locale: 'en', page: 9, limit: 12 })
  assert.equal(result.total, 1)
  assert.equal(result.pages, 1)
  assert.deepEqual(result.documents, [])
})

test('a category route never invents a slug or an unsafe base', () => {
  assert.equal(
    categoryRoute({ slug: 'playa-del-carmen-condos-under-200k' }, '/collections/'),
    '/collections/playa-del-carmen-condos-under-200k/',
  )
  assert.throws(() => categoryRoute({}, '/collections'), /slug/)
  assert.throws(() => categoryRoute({ slug: 'x' }, 'collections'), /absolute site path/)
})
