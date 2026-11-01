/** Import canonical Payload content into this preview's isolated local D1.
 * Host-owned. Uses only the public Local API, the committed schema and a
 * private local binding; it never contacts production or writes a second store.
 */
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const [root, snapshotPath] = process.argv.slice(2)
if (!root || !snapshotPath || process.env.NODE_ENV !== 'development' || process.env.PAYLOAD_CLI !== '1'
    || process.env.CLOUDFLARE_API_TOKEN || process.env.PAYLOAD_GATEWAY_TOKEN) {
  throw new Error('Preview import requires an isolated local Payload CLI environment.')
}
const require = createRequire(path.join(root, 'package.json'))
const { getPayload } = await import(pathToFileURL(require.resolve('payload')).href)
const { default: config, cloudflare } = await import(pathToFileURL(path.join(root, 'payload.config.ts')).href)
const snapshot = JSON.parse(await readFile(snapshotPath, 'utf8'))
if (snapshot.schema !== 1 || !Array.isArray(snapshot.documents) || !Array.isArray(snapshot.globals)) {
  throw new Error('Canonical preview snapshot is invalid.')
}
const payload = await getPayload({ config, disableDBConnect: true })
// The exact committed migrations were already applied. Never let the
// development adapter generate or push a competing schema.
payload.db.push = false
await payload.db.connect()

// Local surrogate IDs differ from production; only relationships inside this
// private copy are remapped. The content bytes and revision identity are exact.
const mediaIds = new Map()
const documentIds = new Map()

const relationId = (value, collection) => {
  if (value && typeof value === 'object') {
    const original = value.id
    const mapped = documentIds.get(`${collection}:${original}`) ?? mediaIds.get(String(original)) ?? original
    return mapped
  }
  return value
}

const rewrite = (data, fields, collection) => {
  const result = { ...data }
  const walk = (fieldsToWalk) => {
    for (const field of fieldsToWalk || []) {
      if (field.type === 'tabs') { walk(field.tabs.flatMap((tab) => tab.fields)); continue }
      if (!field.name) { if (field.fields) walk(field.fields); continue }
      const value = result[field.name]
      if (value == null) continue
      if (field.type === 'upload' || field.type === 'relationship') {
        const target = typeof field.relationTo === 'string' ? field.relationTo : collection
        result[field.name] = field.hasMany
          ? value.map((entry) => relationId(entry, target))
          : relationId(value, target)
      } else if (field.type === 'array') {
        result[field.name] = value.map((entry) => rewrite(entry, field.fields, collection))
      } else if (field.type === 'group') {
        result[field.name] = rewrite(value, field.fields, collection)
      } else if (field.type === 'blocks') {
        result[field.name] = value.map((entry) => {
          const block = field.blocks.find((definition) => definition.slug === entry.blockType)
          if (!block) throw new Error('Preview content uses an unknown canonical block.')
          return { ...rewrite(entry, block.fields, collection), blockType: entry.blockType }
        })
      }
    }
  }
  walk(fields)
  return result
}

const clean = (document) => Object.fromEntries(Object.entries(document)
  .filter(([key]) => !['_helloadaRevision', 'createdAt', 'updatedAt', 'url', 'thumbnailURL', 'sizes'].includes(key)))

const collection = (slug) => {
  const definition = payload.config.collections.find((item) => item.slug === slug)
  if (!definition) throw new Error(`Preview content uses an unknown canonical collection: ${slug}`)
  return definition
}

for (const item of snapshot.media || []) {
  const data = rewrite(clean(item.document), collection('media').fields, 'media')
  const bytes = Buffer.from(item.bytes, 'base64')
  delete data.id
  const saved = await payload.create({
    collection: 'media', overrideAccess: true, locale: snapshot.defaultLocale, data,
    file: { data: bytes, mimetype: item.contentType, name: data.filename, size: bytes.length },
  })
  mediaIds.set(String(item.document.id), saved.id)
  if (item.document.filename) mediaIds.set(`filename:${item.document.filename}`, saved.id)
}

for (const item of snapshot.documents) {
  const definition = collection(item.collection)
  let created
  for (const [locale, document] of Object.entries(item.locales)) {
    const data = rewrite(clean(document), definition.fields, item.collection)
    delete data.id
    if (!created) {
      created = await payload.create({
        collection: item.collection, overrideAccess: true, locale, draft: false,
        data: { ...data, _status: 'published' },
      })
      documentIds.set(`${item.collection}:${item.locales[snapshot.defaultLocale]?.id ?? document.id}`,
        created.id)
      documentIds.set(`${item.collection}:${document.id}`, created.id)
    } else {
      await payload.update({ collection: item.collection, id: created.id, overrideAccess: true,
        locale, draft: false, data: { ...data, _status: 'published' } })
    }
  }
}

for (const item of snapshot.globals) {
  const definition = payload.config.globals.find((global) => global.slug === item.slug)
  if (!definition) throw new Error(`Preview content uses an unknown canonical global: ${item.slug}`)
  for (const [locale, document] of Object.entries(item.locales)) {
    const data = rewrite(clean(document), definition.fields, item.slug)
    delete data.id
    if (!Object.keys(data).length) continue
    await payload.updateGlobal({ slug: item.slug, overrideAccess: true, locale, data })
  }
}

await payload.destroy()
await cloudflare.dispose?.()
console.log(JSON.stringify({ ok: true, documents: snapshot.documents.length,
  media: (snapshot.media || []).length, globals: snapshot.globals.length }))
