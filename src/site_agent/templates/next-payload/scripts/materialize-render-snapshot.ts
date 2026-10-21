/** Host-owned CLI: materialize website data in the preview's local D1/R2 only. */
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { createHash } from 'node:crypto'
import { getPayload, type CollectionSlug, type GlobalSlug } from 'payload'
import { getPayloadCloudflareContext } from '../src/lib/cloudflare-context'
import { stableJson } from '../src/lib/payload-hash'

if (process.env.HELLOADA_PREVIEW_MODE !== '1' || process.env.PAYLOAD_CLI !== '1'
  || process.env.CLOUDFLARE_API_TOKEN || process.env.HELLOADA_CLOUDFLARE_CONFIG_PATH) {
  throw new Error('Render snapshot materialization requires isolated local bindings and no production credential')
}
const input = path.resolve(process.argv[2] || '')
const root = path.dirname(input)
const snapshot = JSON.parse(await fs.readFile(input, 'utf8'))
const config = (await import(pathToFileURL(path.resolve('payload.config.ts')).href)).default
const payload = await getPayload({ config })
await payload.db.migrate()
const context = await getPayloadCloudflareContext() as unknown as { env: { R2: { put(key: string, value: Uint8Array, options: unknown): Promise<unknown> } } }
const seed = snapshot.seed as { collections: Record<string, Record<string, unknown>[]>; globals: Record<string, Record<string, unknown>> }
const allowed = ['media', 'postCategories', 'productCategories', 'contactForms', 'appointmentTypes', 'pages', 'posts', 'products']
if (!seed || Object.keys(seed.collections).some((slug) => !allowed.includes(slug))
  || Object.keys(seed.globals).sort().join(',') !== 'navigation,siteSettings') throw new Error('Invalid render seed scope')
for (const slug of allowed.filter((slug) => seed.collections[slug])) {
  const current = await payload.find({ collection: slug as CollectionSlug, limit: 1, depth: 0, overrideAccess: true })
  if (current.totalDocs !== 0) throw new Error('Render materialization requires an empty local database')
  for (const row of seed.collections[slug]) {
    const { id, ...data } = row
    if (typeof id !== 'number' && typeof id !== 'string') throw new Error('Render row has no native identity')
    await payload.db.create({ collection: slug as CollectionSlug, customID: id, data, returning: false })
  }
}
for (const [slug, data] of Object.entries(seed.globals)) {
  await payload.db.createGlobal({ slug: slug as GlobalSlug, data, returning: false })
}
const files = JSON.parse(await fs.readFile(path.join(root, 'media-manifest.json'), 'utf8')) as Array<{ key: string; file: string; sha256: string; mimeType: string }>
for (const file of files) {
  if (path.basename(file.file) !== file.file || !file.key || file.key.includes('..')) throw new Error('Invalid render media path')
  const bytes = await fs.readFile(path.join(root, file.file))
  if (createHash('sha256').update(bytes).digest('hex') !== file.sha256) throw new Error('Render media digest mismatch')
  await context.env.R2.put(file.key, bytes, { httpMetadata: { contentType: file.mimeType } })
}
const project = (expected: unknown, actual: unknown): unknown => {
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length) throw new Error('Render read-back array changed')
    return expected.map((item, index) => project(item, actual[index]))
  }
  if (expected && typeof expected === 'object') {
    if (!actual || typeof actual !== 'object' || Array.isArray(actual)) throw new Error('Render read-back object changed')
    return Object.fromEntries(Object.entries(expected).map(([key, value]) => [key, project(value, (actual as Record<string, unknown>)[key])]))
  }
  return actual
}
const verify = (expected: unknown, actual: unknown) => {
  if (stableJson(expected) !== stableJson(project(expected, actual))) throw new Error('Canonical Payload read-back differs from the frozen render input')
}
for (const locale of snapshot.locales) {
  for (const [slug, rows] of Object.entries(snapshot.documents[locale]) as Array<[CollectionSlug, Array<{ id: string | number }> ]>) {
    for (const expected of rows) {
      verify(expected, await payload.findByID({ collection: slug, id: expected.id, locale, draft: false, depth: 2, overrideAccess: true }))
    }
  }
  for (const [slug, expected] of Object.entries(snapshot.globals[locale])) {
    verify(expected, await payload.findGlobal({ slug: slug as GlobalSlug, locale, draft: false, depth: 2, overrideAccess: true }))
  }
}
console.log(JSON.stringify({ ok: true, canonicalReadback: true, collections: Object.fromEntries(Object.entries(seed.collections).map(([slug, rows]) => [slug, rows.length])), mediaFiles: files.length }))
await payload.destroy()
process.exit(0)
