import assert from 'node:assert/strict'
import test from 'node:test'

import { createHelloAdaSchema, createHelloAdaAuthoringContract } from '../src/schema/index.ts'
import { matchesCategoryCriteria, validateCategoryCriteria } from '../src/schema/catalog.ts'

const schema = createHelloAdaSchema(async () => undefined)
const categories = schema.collections.find((item) => item.slug === 'productCategories')
const criteria = categories.fields.find((item) => item.name === 'criteria')

const product = (overrides = {}) => ({
  published: true,
  _status: 'published',
  priceMinor: 14080300,
  availability: 'Ready',
  location: { city: 'Tulum', region: 'Region 15' },
  ...overrides,
})

test('collections store criteria instead of a curated membership list', () => {
  assert.equal(criteria.type, 'group')
  assert.deepEqual(criteria.fields.map((field) => field.name),
    ['city', 'region', 'availability', 'priceMinMinor', 'priceMaxMinor'])
  assert.equal(criteria.validate, validateCategoryCriteria)
  assert.ok(createHelloAdaAuthoringContract().collections.productCategories)
  assert.equal(categories.fields.some((field) => field.name === 'categories'), false,
    'Membership is derived from criteria, so no curated many-to-many field is invented')
})

test('city, region and availability must match exactly', () => {
  assert.equal(matchesCategoryCriteria(product(), { city: 'Tulum' }), true)
  assert.equal(matchesCategoryCriteria(product(), { city: 'Playa del Carmen' }), false)
  assert.equal(matchesCategoryCriteria(product(), { region: 'Region 15' }), true)
  assert.equal(matchesCategoryCriteria(product(), { region: 'Aldea Zama' }), false)
  assert.equal(matchesCategoryCriteria(product({ availability: 'immediate' }), { availability: 'Immediate' }), true)
  assert.equal(matchesCategoryCriteria(product(), { availability: 'Immediate' }), false)
})

test('the price floor is inclusive and the ceiling is exclusive', () => {
  assert.equal(matchesCategoryCriteria(product(), { priceMinMinor: 14080300 }), true)
  assert.equal(matchesCategoryCriteria(product(), { priceMinMinor: 14080301 }), false)
  assert.equal(matchesCategoryCriteria(product(), { priceMaxMinor: 14080301 }), true)
  assert.equal(matchesCategoryCriteria(product(), { priceMaxMinor: 14080300 }), false,
    'a product priced exactly at the ceiling is excluded, as the rendered grids show')
  assert.equal(matchesCategoryCriteria(product({ priceMinor: undefined }), { priceMinMinor: 1 }), false)
})

test('unpublished products never match', () => {
  assert.equal(matchesCategoryCriteria(product({ published: false }), {}), false)
  assert.equal(matchesCategoryCriteria(product({ _status: 'draft' }), {}), false)
  assert.equal(matchesCategoryCriteria(product({ _status: undefined }), {}), true)
})

test('property type is not a filter, matching the rendered pages', () => {
  assert.equal(matchesCategoryCriteria(product({ availablePropertyTypes: ['villa'] }), { city: 'Tulum' }), true)
})

test('criteria validation rejects an inverted or empty range', () => {
  assert.equal(validateCategoryCriteria({}), true)
  assert.equal(validateCategoryCriteria({ priceMinMinor: 100, priceMaxMinor: 200 }), true)
  assert.equal(validateCategoryCriteria({ priceMinMinor: 200, priceMaxMinor: 200 }), 'The category price ceiling must be above its floor (the ceiling is exclusive).')
  assert.equal(validateCategoryCriteria({ priceMinMinor: -1 }), 'Category priceMinMinor: Enter a non-negative safe integer in minor units.')
  assert.equal(validateCategoryCriteria({ city: 5 }), 'Category city must be text.')
})
