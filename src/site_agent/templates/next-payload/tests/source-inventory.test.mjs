import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import ts from 'typescript'

import { scanPresentation } from '../../../application/source_inventory_ast.mjs'

test('host presentation inventory rejects visible copy outside Payload and counts shared bindings', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'helloada-source-inventory-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const presentation = path.join(root, 'src/components/site/presentation')
  fs.mkdirSync(presentation, { recursive: true })
  fs.writeFileSync(path.join(root, 'helloada-content-contract.json'), JSON.stringify({
    collections: { pages: ['title', 'featuredImage', 'sections'] },
    globals: {},
  }))
  const component = path.join(presentation, 'Hero.tsx')

  fs.writeFileSync(component, `export default function Hero() {
    const heading = 'A hardcoded business promise'
    return <main><h1>{heading}</h1><p>Another hardcoded paragraph</p></main>
  }
`)
  const invalid = scanPresentation(root, ts)
  assert.equal(invalid.violations.length, 2)
  assert.ok(invalid.violations.every((item) => item.reason === 'visible_copy_must_come_from_payload'))

  fs.writeFileSync(component, `import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'
  export default function Hero({ page }) {
    return <main><h1 data-helloada-field={helloAdaBindingId('pages', String(page.id), { collection: 'pages', documentId: String(page.id), field: 'title' })}>{page.title}</h1>
      <img src={page.featuredImage.url} alt={page.featuredImage.alt} data-helloada-field={helloAdaBindingId('pages', String(page.id), { collection: 'pages', documentId: String(page.id), field: 'featuredImage' })} />
      <button aria-label="Open menu">⌘</button></main>
  }
`)
  const valid = scanPresentation(root, ts)
  assert.deepEqual(valid.violations, [])
  assert.equal(valid.bindingCount, 2)
  assert.equal(valid.editableImages, 1)
  assert.equal(valid.imageElements, 1)

  fs.writeFileSync(path.join(root, 'src/components/site/TenantSections.tsx'), `
    import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'
    export default function TenantSections({ collection, documentId, item, target }) {
      const itemTarget = { ...target, field: 'item' }
      return <section data-helloada-field={helloAdaBindingId(collection, documentId, { field: 'sectionLabel' })}>
        <img src={item.image} alt={item.alt} data-helloada-field={helloAdaBindingId(collection, documentId, { field: 'entry', property: 'image' })} />
        <h2 data-helloada-field={helloAdaBindingId(collection, documentId, { ...itemTarget, property: 'title' })}>{item.title}</h2>
      </section>
    }
  `)
  const nested = scanPresentation(root, ts)
  assert.deepEqual(nested.violations, [])
  assert.equal(nested.bindingCount, 5)
  assert.equal(nested.editableImages, 2)
  assert.equal(nested.imageElements, 2)
})
