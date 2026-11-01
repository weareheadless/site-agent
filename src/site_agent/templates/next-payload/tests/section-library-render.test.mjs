import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { sectionDirection, sectionEntriesToContent } from '../src/components/site/sections/adapt.ts'
import { sectionComponents } from '../src/components/site/sections/registry.ts'

const media = (value) => ({ src: `/media/${value}.jpg`, alt: `Media ${value}` })
const heading = (key, text) => ({ key, blockType: 'helloAdaHeading', text })
const paragraph = (key, text) => ({ key, blockType: 'helloAdaParagraph', text })

test('the ordered section registry renders every section with one h1 and supporting h2s', () => {
  for (const align of ['split-left', 'split-right', 'centred', 'overlap', 'reversed']) {
    const html = Object.entries(sectionComponents).map(([layout, Component], index) => {
      const { content } = sectionEntriesToContent([
        heading(`${layout}.heading`, `Heading ${index}`), paragraph(`${layout}.body`, `Body ${index}`),
        { key: `${layout}.image`, blockType: 'helloAdaImage', image: index + 5 },
        { key: `${layout}.action`, blockType: 'helloAdaLink', text: `Action ${index}`, href: '#contact' },
      ], media)
      return renderToStaticMarkup(createElement(Component, { content, direction: sectionDirection({ direction: { align } }), bindings: { headline: `${layout}.heading` } }))
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
