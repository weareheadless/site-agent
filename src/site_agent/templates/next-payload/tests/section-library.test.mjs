import assert from 'node:assert/strict'
import { test } from 'node:test'

import { sectionDirection, sectionEntriesToContent } from '../src/components/site/sections/adapt.ts'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { sectionComponents } from '../src/components/site/sections/registry.ts'

const media = (value) => (typeof value === 'number' ? { src: `/media/${value}.jpg`, alt: `Media ${value}` } : { src: '', alt: '' })

const paragraph = (key, text) => ({ key, blockType: 'helloAdaParagraph', text })
const heading = (key, text) => ({ key, blockType: 'helloAdaHeading', text, level: 'h2' })

test('a paragraph before the heading is the eyebrow, not the body', () => {
  const { content } = sectionEntriesToContent([
    paragraph('home.hero.eyebrow', 'Independent by design'),
    heading('home.hero.heading', 'Make your next move clearer.'),
    paragraph('home.hero.introduction', 'Brand strategy for independent businesses.'),
  ], media)

  assert.equal(content.eyebrow, 'Independent by design')
  assert.equal(content.headline, 'Make your next move clearer.')
  assert.equal(content.body, 'Brand strategy for independent businesses.')
  assert.deepEqual(content.supporting, [])
})

test('further approved paragraphs stay visible as supporting copy', () => {
  const { content } = sectionEntriesToContent([
    heading('home.hero.heading', 'A headline.'),
    paragraph('home.hero.introduction', 'The body.'),
    paragraph('home.supporting.paragraph-1', 'One more point.'),
    paragraph('home.supporting.paragraph-2', 'And another.'),
  ], media)

  assert.equal(content.body, 'The body.')
  assert.deepEqual(content.supporting, ['One more point.', 'And another.'])
})

test('without an eyebrow the first paragraph after the heading is still the body', () => {
  const { content } = sectionEntriesToContent([
    heading('home.hero.heading', 'A headline.'),
    paragraph('home.hero.introduction', 'The body.'),
  ], media)

  assert.equal(content.eyebrow, undefined)
  assert.equal(content.body, 'The body.')
})

test('a pipe splits the headline into plain and italic emphasis', () => {
  const { content } = sectionEntriesToContent([
    heading('home.hero.heading', 'Tu color, | en las mismas manos.'),
  ], media)

  assert.equal(content.headline, 'Tu color,')
  assert.equal(content.emphasis, 'en las mismas manos.')
})

test('the link becomes the action and the image keeps a usable alternative', () => {
  const { content } = sectionEntriesToContent([
    heading('home.hero.heading', 'A headline.'),
    { key: 'home.hero.image', blockType: 'helloAdaImage', image: 7 },
    { key: 'home.hero.primary-action', blockType: 'helloAdaLink', text: 'Start a conversation', href: 'https://wa.me/15551234567' },
  ], media)

  assert.deepEqual(content.image, { src: '/media/7.jpg', alt: 'Media 7' })
  assert.deepEqual(content.action, { label: 'Start a conversation', href: 'https://wa.me/15551234567' })
})

test('every rendered part reports the content entry the owner can edit', () => {
  const { bindings } = sectionEntriesToContent([
    paragraph('home.hero.eyebrow', 'An eyebrow'),
    heading('home.hero.heading', 'A headline.'),
    paragraph('home.hero.introduction', 'The body.'),
    paragraph('home.supporting.paragraph-1', 'Supporting one.'),
    { key: 'home.hero.image', blockType: 'helloAdaImage', image: 7 },
    { key: 'home.hero.primary-action', blockType: 'helloAdaLink', text: 'Act', href: '/contact' },
  ], media)

  assert.deepEqual(bindings, {
    eyebrow: { key: 'home.hero.eyebrow', property: 'text' },
    headline: { key: 'home.hero.heading', property: 'text' },
    body: { key: 'home.hero.introduction', property: 'text' },
    supporting: [{ key: 'home.supporting.paragraph-1', property: 'text' }],
    action: { key: 'home.hero.primary-action', property: 'text' },
    image: { key: 'home.hero.image', property: 'image' },
  })
})

test('a section only carries direction values the renderer understands', () => {
  assert.deepEqual(sectionDirection({
    direction: { align: 'overlap', rules: false, treatment: 'monochrome', scale: 'compact' },
  }), { align: 'overlap', rules: false, treatment: 'monochrome', scale: 'compact' })

  // Unknown values are dropped rather than rendered as an accidental look.
  assert.deepEqual(sectionDirection({
    direction: { align: 'diagonal', rules: 'yes', treatment: 'sepia', scale: 'huge' },
  }), { align: undefined, rules: undefined, treatment: undefined, scale: undefined })

  assert.deepEqual(sectionDirection({}), {})
})

test('the ordered section registry renders every section with one h1 and supporting h2s', () => {
  for (const align of ['split-left', 'split-right', 'centred', 'overlap', 'reversed']) {
    const html = Object.entries(sectionComponents).map(([layout, Component], index) => {
      const { content } = sectionEntriesToContent([
        heading(`${layout}.heading`, `Heading ${index}`), paragraph(`${layout}.body`, `Body ${index}`),
        { key: `${layout}.image`, blockType: 'helloAdaImage', image: index + 5 },
        { key: `${layout}.action`, blockType: 'helloAdaLink', text: `Action ${index}`, href: '#contact' },
      ], media)
      return renderToStaticMarkup(createElement(Component, { content, direction: { align }, bindings: { headline: `${layout}.heading` } }))
    }).join('')
    assert.equal((html.match(/<h1\b/g) || []).length, 1)
    assert.equal((html.match(/<h2\b/g) || []).length, 4)
    for (let index = 0; index < 5; index++) {
      assert.ok(html.includes(`Heading ${index}`))
      assert.ok(html.includes(`Body ${index}`))
      assert.ok(html.includes(`Action ${index}`))
      assert.ok(html.includes(`/media/${index + 5}.jpg`))
    }
  }
})

test('gallery keeps every assigned image and its editable binding', () => {
  const { content, bindings } = sectionEntriesToContent([
    heading('gallery.heading', 'The work'),
    ...[5, 6, 7].map((id) => ({ key: `gallery.image-${id}`, blockType: 'helloAdaImage', image: id })),
  ], media)
  assert.deepEqual(bindings.additionalImages, [
    { key: 'gallery.image-6', property: 'image' }, { key: 'gallery.image-7', property: 'image' },
  ])
  const html = renderToStaticMarkup(createElement(sectionComponents.gallery, { content, bindings: {
    image: bindings.image.key, additionalImages: bindings.additionalImages.map((item) => item.key),
  } }))
  for (const id of [5, 6, 7]) {
    assert.ok(html.includes(`/media/${id}.jpg`))
    assert.ok(html.includes(`data-helloada-field="gallery.image-${id}"`))
  }
})
