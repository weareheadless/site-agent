import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createHelloAdaSchema,
  validateHelloAdaLink,
  validateHelloAdaNavigation,
  validateHelloAdaPageSections,
} from '../src/schema/index.ts'

test('all standard tenant schemas come from one contract and share the native mutation guard', () => {
  const guarded = []
  const schema = createHelloAdaSchema(async (...args) => guarded.push(args))
  const collections = Object.fromEntries(schema.collections.map((item) => [item.slug, item]))
  const globals = Object.fromEntries(schema.globals.map((item) => [item.slug, item]))
  assert.deepEqual(Object.keys(collections), ['users', 'pages', 'posts', 'products', 'productCategories', 'media'])
  assert.deepEqual(Object.keys(globals), ['siteSettings', 'navigation'])
  assert.ok(collections.pages.fields.some((field) => field.name === 'sections' && field.type === 'array'))
  assert.ok(collections.posts.fields.some((field) => field.name === 'featuredImage' && field.type === 'upload'))
  assert.ok(collections.products.fields.some((field) => field.name === 'category' && field.type === 'relationship'))
  assert.ok(globals.navigation.fields.some((field) => field.name === 'footerGroups'))
  assert.ok(globals.siteSettings.fields.some((field) => field.name === 'defaultSeoDescription'))
  assert.equal(typeof collections.pages.hooks.beforeOperation[0], 'function')
  assert.equal(typeof collections.pages.hooks.beforeValidate[0], 'function')
  assert.equal(typeof globals.navigation.hooks.beforeOperation[0], 'function')
  assert.equal(typeof globals.navigation.hooks.beforeValidate[0], 'function')
})

test('link validation accepts explicit web destinations and rejects executable or ambiguous URLs', () => {
  assert.equal(validateHelloAdaLink('/contact'), true)
  assert.equal(validateHelloAdaLink('#hours'), true)
  assert.equal(validateHelloAdaLink('https://example.com/contact'), true)
  assert.notEqual(validateHelloAdaLink('javascript:alert(1)'), true)
  assert.notEqual(validateHelloAdaLink('//example.com'), true)
  assert.notEqual(validateHelloAdaLink('example.com'), true)
})

test('page block identities are stable, globally unique and use Payload blockType slugs', () => {
  const valid = [{
    key: 'home.hero', label: 'Hero', entries: [
      { key: 'home.hero.heading', label: 'Main heading', blockType: 'helloAdaHeading', text: 'Welcome', level: 'h2' },
      { key: 'home.hero.cta', label: 'Primary action', blockType: 'helloAdaLink', text: 'Book now', href: '/contact' },
    ],
  }]
  assert.equal(validateHelloAdaPageSections(valid), true)
  assert.match(validateHelloAdaPageSections([{ ...valid[0], entries: [valid[0].entries[0], { ...valid[0].entries[1], key: 'home.hero' }] }]), /used more than once/)
  assert.match(validateHelloAdaPageSections([{ ...valid[0], entries: [{ key: 'heading', label: 'Heading', type: 'helloAdaHeading', text: 'Welcome' }] }]), /unsupported content type/)
  assert.match(validateHelloAdaPageSections([{ ...valid[0], entries: [{ key: '', label: 'Heading', blockType: 'helloAdaHeading' }] }]), /stable content ID/)
})

test('shared navigation IDs remain stable and cannot be reused across regions', () => {
  assert.equal(validateHelloAdaNavigation({ items: [{ key: 'primary.home' }], footer: [{ key: 'footer.contact' }] }), true)
  assert.match(validateHelloAdaNavigation({ items: [{ key: 'home' }], footer: [{ key: 'home' }] }), /used more than once/)
  assert.match(validateHelloAdaNavigation({ groups: [{ key: 'group', items: [{ label: 'Contact' }] }] }), /stable content ID/)
})
