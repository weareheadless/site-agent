import assert from 'node:assert/strict'
import test from 'node:test'

import { createHelloAdaSchema, createHelloAdaAuthoringContract, validateHelloAdaAuthoringData } from '../src/schema/index.ts'
import { validateCatalogAttribute, validateCatalogOptions, validateVariantSelection, validateMinorAmount } from '../src/schema/catalog.ts'

const schema = createHelloAdaSchema(async () => undefined)
const collection = (slug) => schema.collections.find((item) => item.slug === slug)
const field = (slug, name) => collection(slug).fields.find((item) => item.name === name)

test('real estate facts and retail variants belong to the canonical schema', () => {
  for (const slug of ['productAttributes', 'productVariants']) {
    assert.ok(collection(slug))
    assert.ok(collection(slug).versions.drafts)
    assert.ok(collection(slug).hooks.beforeOperation.length)
    assert.ok(createHelloAdaAuthoringContract().collections[slug])
  }
  assert.equal(field('products', 'location').type, 'group')
  assert.equal(field('products', 'priceMinor').type, 'number')
  assert.equal(field('productVariants', 'sku').unique, true)
  assert.ok(collection('productVariants').indexes.some((index) => index.unique && index.fields.includes('selectionKey')))
  assert.ok(collection('productAttributes').indexes.some((index) => index.fields.includes('valueNumber')))
})

test('one attribute has exactly one typed value, including zero and false', () => {
  assert.equal(validateCatalogAttribute({ key: 'beds', valueType: 'number', valueNumber: 0 }), true)
  assert.equal(validateCatalogAttribute({ key: 'pool', valueType: 'boolean', valueBoolean: false }), true)
  assert.notEqual(validateCatalogAttribute({ key: 'beds', valueType: 'number', valueText: 'two' }), true)
  assert.notEqual(validateCatalogAttribute({ key: 'beds', valueType: 'number', valueNumber: 2, valueText: 'two' }), true)
  assert.notEqual(validateCatalogAttribute({ key: 'beds', valueType: 'number', valueNumber: Infinity }), true)
})

test('variant selections cover each declared option exactly once', () => {
  const options = [{ key: 'size', label: 'Size', values: [{ key: 's', label: 'Small' }, { key: 'm', label: 'Medium' }] }]
  assert.equal(validateCatalogOptions(options), true)
  assert.equal(validateCatalogOptions([...options, ...options]), 'Product option keys must be unique.')
  assert.equal(validateVariantSelection(options, [{ option: 'size', value: 'm' }]), true)
  for (const selection of [[], [{ option: 'size', value: 'xl' }], [{ option: 'colour', value: 'red' }], [{ option: 'size', value: 's' }, { option: 'size', value: 'm' }]]) {
    assert.notEqual(validateVariantSelection(options, selection), true)
  }
})

test('money and stock use safe integer units; no implicit cents conversion', () => {
  for (const value of [0, 1250, Number.MAX_SAFE_INTEGER, undefined, null]) assert.equal(validateMinorAmount(value), true)
  for (const value of [-1, 12.5, Infinity, NaN, '1200', Number.MAX_SAFE_INTEGER + 1]) assert.notEqual(validateMinorAmount(value), true)
})

test('native and Ada writes enforce catalog validation, including partial updates', async () => {
  assert.equal(validateHelloAdaAuthoringData('collection', 'productAttributes', { product: 1, key: 'area', label: 'Area', valueType: 'number', valueNumber: 80, unit: 'm²' }, { operation: 'create' }), true)
  assert.throws(() => validateHelloAdaAuthoringData('collection', 'products', { priceMinor: 1.5 }), /integer/)
  const hook = collection('productAttributes').hooks.beforeValidate[0]
  await assert.rejects(() => hook({ data: { valueText: 'two' }, originalDoc: { key: 'beds', valueType: 'number', valueNumber: 2 } }), /exactly one/)
  assert.equal((await hook({ data: { valueNumber: 3 }, originalDoc: { key: 'beds', valueType: 'number', valueNumber: 2 } })).valueNumber, 3)
})

test('variants validate options against the actual product and derive stable selection identity', async () => {
  const hook = collection('productVariants').hooks.beforeValidate[0]
  const req = { payload: { findByID: async () => ({ options: [{ key: 'size', label: 'Size', values: [{ key: 'm', label: 'Medium' }] }] }) } }
  const data = { product: 3, sku: 'SHIRT-M', options: [{ option: 'size', value: 'm' }], priceMinor: 1250 }
  const result = await hook({ data, req })
  assert.equal(typeof result.selectionKey, 'string')
  assert.ok(result.selectionKey.length)
  await assert.rejects(() => hook({ data: { ...data, options: [{ option: 'size', value: 'xl' }] }, req }), /declared/)
  await assert.rejects(() => hook({ data: { ...data, stock: 1.5 }, req }), /integer/)
})

test('Astrid pages support translated slugs and a gallery without a retail catalog', () => {
  for (const slug of ['pages', 'posts', 'postCategories', 'products', 'productCategories']) {
    assert.equal(field(slug, 'slug').localized, true)
  }
  assert.equal(field('pages', 'gallery').hasMany, true)
  assert.equal(validateHelloAdaAuthoringData('collection', 'pages', { title: 'Colour and cuts', slug: 'color-and-cuts', gallery: [1, 2] }), true)
})
