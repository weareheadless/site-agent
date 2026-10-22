import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'

test('Growth projections match the JSON wire shape without weakening exact values', async () => {
  const root = new URL('../src/lib/', import.meta.url)
  const hashSource = readFileSync(new URL('payload-hash.ts', root), 'utf8')
    .replace(/^export\s+/gm, '')
  const contractSource = readFileSync(new URL('growth-contract.ts', root), 'utf8')
    .replace(/^import\s+.*$/gm, '')
    .replace(/^export\s+\{[^\n]*\}\s+from\s+['"][^'"]+['"]\s*\n/gm, '')
    .replace(/^export\s+/gm, '')
  const adapters = "import assert from 'node:assert/strict'\nconst getPayloadCloudflareContext = async () => ({})\n"
  const checks = `
    const fields = ['featuredImage', 'sections', 'seo', 'missing']
    const document = {
      featuredImage: { id: 'media-1', alt: 'Image', url: undefined, metadata: { caption: null, rights: undefined } },
      sections: [{ blockType: 'hero', media: { id: 'media-2', alt: undefined }, explicitNull: null }, undefined, null],
      seo: { title: 'SEO', image: undefined, description: null, nested: { absent: undefined, explicitNull: null } },
    }
    const gatewayDocument = JSON.parse(JSON.stringify(document))
    const gatewayProjection = Object.fromEntries([...new Set(fields)].sort().map(field => [field, gatewayDocument[field] ?? null]))
    const projected = projectDocument(document, fields)
    assert.deepEqual(projected, gatewayProjection)
    assert.deepEqual(projected, {
      featuredImage: { id: 'media-1', alt: 'Image', metadata: { caption: null } },
      missing: null,
      sections: [{ blockType: 'hero', media: { id: 'media-2' }, explicitNull: null }, null, null],
      seo: { title: 'SEO', description: null, nested: { explicitNull: null } },
    })
    const absent = projectDocument(document, fields)
    const explicitNull = projectDocument({ ...document, seo: { ...document.seo, image: null } }, fields)
    assert.notEqual(stableJson(absent), stableJson(explicitNull), 'nested absent and explicit null must remain distinct')
    const changed = projectDocument({ ...document, featuredImage: { ...document.featuredImage, alt: 'Changed' } }, fields)
    assert.notEqual(stableJson(absent), stableJson(changed), 'meaningful nested changes must remain hash-visible')
    const changedRelation = projectDocument({ ...document, sections: [{ ...document.sections[0], media: { id: 'media-3' } }, ...document.sections.slice(1)] }, fields)
    assert.notEqual(stableJson(absent), stableJson(changedRelation), 'defined relation IDs must remain hash-visible')
  `
  const javascript = stripTypeScriptTypes(adapters + hashSource + contractSource + checks)
  await assert.doesNotReject(import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64')))
})
