import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyHelloAdaBindingEdits,
  helloAdaBindingId,
  helloAdaContentBindings,
} from '../src/bindings/index.ts'
import { assignHelloAdaNavigationKeys, assignHelloAdaPageKeys } from '../src/schema/index.ts'

const lexical = (text) => ({ root: { type: 'root', children: [{ type: 'paragraph', children: [{ type: 'text', text }] }] } })

test('new sections and repeated items receive stable semantic IDs exactly once', () => {
  let serial = 0
  const createId = () => `id-${++serial}`
  const first = assignHelloAdaPageKeys([{
    label: 'Introduction',
    entries: [{ blockType: 'helloAdaContentList', label: 'Services', items: [{ title: 'Design' }] }],
  }], createId)
  assert.deepEqual([first[0].key, first[0].entries[0].key, first[0].entries[0].items[0].key], ['id-1', 'id-2', 'id-3'])
  assert.deepEqual(assignHelloAdaPageKeys(first, () => assert.fail('stable IDs must not be regenerated')), first)
  const navigation = assignHelloAdaNavigationKeys({ items: [{ label: 'Home' }], groups: [{ label: 'More', items: [{ label: 'Contact' }] }] }, createId)
  assert.deepEqual([navigation.items[0].key, navigation.groups[0].key, navigation.groups[0].items[0].key], ['id-4', 'id-5', 'id-6'])
})

test('editable bindings use stable section, block and item keys rather than array positions', () => {
  const document = {
    id: 'page-1', title: 'Home', summary: 'Intro', body: lexical('Body'),
    seo: { title: 'Search title', description: 'Search description' },
    sections: [{ key: 'home.hero', label: 'Hero', entries: [
      { key: 'home.hero.title', blockType: 'helloAdaHeading', label: 'Main headline', text: 'Welcome' },
      { key: 'home.hero.cta', blockType: 'helloAdaLink', label: 'Book now', text: 'Book', href: '/contact' },
      { key: 'home.hero.services', blockType: 'helloAdaContentList', label: 'Services', items: [{ key: 'service.one', title: 'Design', body: 'A site', href: '/work', linkText: 'See work' }] },
    ] }],
  }
  const fields = helloAdaContentBindings(document, 'pages', '/')
  assert.ok(fields.some((field) => field.label === 'Main headline' && field.contentEdit.entryKey === 'home.hero.title'))
  assert.ok(fields.some((field) => field.label === 'Book now destination' && field.value === '/contact'))
  assert.ok(fields.some((field) => field.label === 'Design destination' && field.value === '/work'))
  assert.equal(fields.find((field) => field.label === 'Main headline').id,
    helloAdaBindingId('pages', 'page-1', { collection: 'pages', documentId: 'page-1', sectionKey: 'home.hero', entryKey: 'home.hero.title', field: 'entry', property: 'text' }))
})

test('content edits patch by stable identity and preserve Lexical structure', () => {
  const document = {
    id: 'page-1', sections: [{ key: 'hero', label: 'Hero', entries: [
      { key: 'cta', blockType: 'helloAdaLink', text: 'Book', href: '/contact' },
      { key: 'copy', blockType: 'helloAdaRichText', value: lexical('Before') },
      { key: 'services', blockType: 'helloAdaContentList', items: [
        { key: 'one', title: 'First' }, { key: 'two', title: 'Second' },
      ] },
    ] }],
  }
  const updated = applyHelloAdaBindingEdits(document, [
    { collection: 'pages', documentId: 'page-1', sectionKey: 'hero', entryKey: 'cta', field: 'entry', property: 'href', expectedValue: '/contact', newValue: '/appointments' },
    { collection: 'pages', documentId: 'page-1', sectionKey: 'hero', entryKey: 'copy', field: 'entry', property: 'value', expectedValue: 'Before', newValue: lexical('After') },
    { collection: 'pages', documentId: 'page-1', sectionKey: 'hero', entryKey: 'services', itemKey: 'two', field: 'item', property: 'title', expectedValue: 'Second', newValue: 'Updated second' },
  ])
  assert.equal(updated.sections[0].entries[0].href, '/appointments')
  assert.equal(updated.sections[0].entries[1].value.root.children[0].children[0].text, 'After')
  assert.equal(updated.sections[0].entries[2].items[0].title, 'First')
  assert.equal(updated.sections[0].entries[2].items[1].title, 'Updated second')
  assert.equal(document.sections[0].entries[0].href, '/contact')
})

test('media relations use Payload IDs and owners cannot edit schema identity', () => {
  const document = {
    id: 'page-1',
    featuredImage: { id: 17, sourceId: 'legacy-asset-17' },
    seo: { image: { id: 23, sourceId: 'external-seo-image' } },
    sections: [{ key: 'hero', label: 'Hero', entries: [{ key: 'headline', blockType: 'helloAdaHeading', label: 'Headline', text: 'Welcome' }] }],
  }
  const fields = helloAdaContentBindings(document, 'pages', '/')
  assert.equal(fields.find((field) => field.label === 'Main image').value, '17')
  assert.equal(fields.find((field) => field.label === 'Social preview image').value, '23')
  const updated = applyHelloAdaBindingEdits(document, [
    { collection: 'pages', documentId: 'page-1', field: 'seoImage', expectedValue: '23', newValue: 31 },
    { collection: 'pages', documentId: 'page-1', field: 'canonicalUrl', expectedValue: '', newValue: 'https://example.com/home' },
  ])
  assert.equal(updated.seo.image, 31)
  assert.equal(updated.canonicalUrl, 'https://example.com/home')
  assert.throws(() => applyHelloAdaBindingEdits({ id: 'page-1', canonicalUrl: '' }, [
    { collection: 'pages', documentId: 'page-1', field: 'canonicalUrl', expectedValue: '', newValue: 'javascript:alert(1)' },
  ]), /HTTP or HTTPS/)
  assert.throws(() => applyHelloAdaBindingEdits(document, [
    { collection: 'pages', documentId: 'page-1', sectionKey: 'hero', entryKey: 'headline', field: 'entry', property: 'key', expectedValue: 'headline', newValue: 'other' },
  ]), /not owner-editable/)
  assert.throws(() => applyHelloAdaBindingEdits(document, [
    { collection: 'pages', documentId: 'page-1', sectionKey: 'hero', entryKey: 'headline', field: 'entry', property: 'blockType', expectedValue: 'helloAdaHeading', newValue: 'helloAdaLink' },
  ]), /not owner-editable/)
})

test('stale, duplicate, unsafe-link and malformed-rich-text edits fail before changing the document', () => {
  const document = { id: 'page-1', title: 'Current' }
  const base = { collection: 'pages', documentId: 'page-1', field: 'title' }
  assert.throws(() => applyHelloAdaBindingEdits(document, [{ ...base, expectedValue: 'Old', newValue: 'New' }]), /changed before/)
  assert.throws(() => applyHelloAdaBindingEdits(document, [
    { ...base, expectedValue: 'Current', newValue: 'New' },
    { ...base, expectedValue: 'Current', newValue: 'Other' },
  ]), /submitted more than once/)
  assert.throws(() => applyHelloAdaBindingEdits({ id: 'page-1', sections: [{ key: 'hero', entries: [{ key: 'cta', blockType: 'helloAdaLink', href: '/contact' }] }] }, [
    { collection: 'pages', documentId: 'page-1', sectionKey: 'hero', entryKey: 'cta', field: 'entry', property: 'href', expectedValue: '/contact', newValue: 'javascript:alert(1)' },
  ]), /safe|secure|destination/)
  assert.throws(() => applyHelloAdaBindingEdits({ id: 'page-1', body: lexical('Body') }, [
    { collection: 'pages', documentId: 'page-1', field: 'body', expectedValue: 'Body', newValue: { root: [] } },
  ]), /Lexical document format/)
})
