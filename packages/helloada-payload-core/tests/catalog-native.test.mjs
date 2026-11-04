import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { buildConfig, getPayload } from 'payload'
import { sqliteD1Adapter } from '@payloadcms/db-d1-sqlite'
import { lexicalEditor } from '@payloadcms/richtext-lexical'
import { createHelloAdaSchema } from '../src/schema/index.ts'
import { readHelloAdaProductCatalog } from '../src/server.ts'

// Execute the committed SQL locally, then exercise real Payload draft/locale/
// validation behavior through the actual D1 adapter, not an ORM-shaped mock.
const initialize = async database => {
  const directory = new URL('../../../src/site_agent/templates/next-payload/src/migrations/', import.meta.url)
  const index = readFileSync(new URL('index.ts', directory), 'utf8')
  for (const [, name] of index.matchAll(/import \* as migration_\w+ from '\.\/([^']+)'/g)) {
    const source = readFileSync(new URL(`${name}.ts`, directory), 'utf8')
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
    const sql = (parts, ...values) => parts.reduce((result, part, i) => result + part + (values[i] ?? ''), '')
    sql.raw = value => value
    const exports = {}
    new Function('require', 'exports', compiled)(name => { assert.equal(name, '@payloadcms/db-d1-sqlite'); return { sql } }, exports)
    await exports.up({ db: { run: async sql => database.exec(sql), all: async sql => database.prepare(sql).all() } })
  }
}
const bindingFor = database => {
  const prepare = (query, values = []) => ({
    bind: (...parameters) => prepare(query, parameters),
    all: async () => ({ results: database.prepare(query).all(...values), success: true, meta: {} }),
    raw: async () => { const statement = database.prepare(query); statement.setReturnArrays(true); return statement.all(...values) },
    run: async () => { const result = database.prepare(query).run(...values); return { success: true, results: [], meta: { changes: result.changes, last_row_id: result.lastInsertRowid } } },
    first: async column => { const row = database.prepare(query).get(...values); return column ? row?.[column] ?? null : row ?? null },
  })
  const binding = { prepare, batch: async statements => { const results = []; for (const statement of statements) results.push(await statement.all()); return results }, exec: async sql => database.exec(sql), withSession: () => binding }
  return binding
}

test('real Payload on the migrated D1 schema creates, drafts, publishes and validates catalog records', async () => {
  const database = new DatabaseSync(':memory:')
  database.exec('PRAGMA foreign_keys=ON')
  await initialize(database)
  const config = await buildConfig({
    ...createHelloAdaSchema(async () => undefined), secret: 'catalog-native-integration', telemetry: false,
    db: sqliteD1Adapter({ binding: bindingFor(database), push: false }), editor: lexicalEditor(),
    localization: { locales: ['en', 'es'], defaultLocale: 'en', fallback: false },
  })
  const payload = await getPayload({ config, key: 'catalog-native-test' })
  try {
    const product = await payload.create({ collection: 'products', locale: 'en', draft: false, overrideAccess: true, data: {
      title: 'Shirt', slug: 'shirt', currency: 'EUR', priceMinor: 1250, published: true, _status: 'published',
      options: [{ key: 'size', label: 'Size', values: [{ key: 'm', label: 'Medium' }, { key: 'l', label: 'Large' }] }],
    } })
    const attribute = await payload.create({ collection: 'productAttributes', locale: 'en', draft: false, overrideAccess: true, data: {
      product: product.id, key: 'weight', label: 'Weight', valueType: 'number', valueNumber: 80, unit: 'g', published: true, _status: 'published',
    } })
    assert.equal(attribute.valueNumber, 80)
    const attributeDraft = await payload.update({ collection: 'productAttributes', id: attribute.id, locale: 'en', draft: true, data: { valueNumber: 81 } })
    assert.equal(attributeDraft.valueNumber, 81)
    assert.equal((await payload.findByID({ collection: 'productAttributes', id: attribute.id, locale: 'en', draft: false })).valueNumber, 80)
    const variant = await payload.create({ collection: 'productVariants', locale: 'en', draft: false, overrideAccess: true, data: {
      product: product.id, sku: 'SHIRT-M', options: [{ option: 'size', value: 'm' }], priceMinor: 1250, stock: 0, published: true, _status: 'published',
    } })
    assert.ok(variant.selectionKey)
    await assert.rejects(() => payload.update({ collection: 'productVariants', id: variant.id, locale: 'en', draft: true, data: { stock: 1.5 } }), /integer/)
    const changed = await payload.update({ collection: 'productVariants', id: variant.id, locale: 'en', draft: true, data: { stock: 4 } })
    assert.equal(changed.stock, 4)
    assert.equal((await payload.findByID({ collection: 'productVariants', id: variant.id, locale: 'en', draft: false })).stock, 0)
    const publicCatalog = await readHelloAdaProductCatalog(payload, 'shirt', 'en')
    assert.equal(publicCatalog.variants[0].stock, 0)
    assert.equal(publicCatalog.attributes[0].valueNumber, 80)
    const draftAttribute = await payload.create({ collection: 'productAttributes', locale: 'en', draft: true, data: {
      product: product.id, key: 'material', label: 'Material', valueType: 'text', valueText: 'Cotton',
    } })
    assert.equal(draftAttribute.published, true, 'new records are visible when explicitly published, not while drafted')
    assert.equal((await readHelloAdaProductCatalog(payload, 'shirt', 'en')).attributes.length, 1)
    await payload.update({ collection: 'productAttributes', id: draftAttribute.id, locale: 'en', draft: false, data: { _status: 'published' } })
    assert.equal((await readHelloAdaProductCatalog(payload, 'shirt', 'en')).attributes.length, 2)
    await assert.rejects(() => payload.update({ collection: 'products', id: product.id, locale: 'en', draft: false, data: { options: [] } }), /published variant/)
    const page = await payload.create({ collection: 'pages', locale: 'es', draft: false, data: { title: 'Novias', slug: 'novias', published: true, _status: 'published' } })
    await payload.update({ collection: 'pages', id: page.id, locale: 'en', draft: false, data: { title: 'Bridal', slug: 'bridal' } })
    assert.equal((await payload.findByID({ collection: 'pages', id: page.id, locale: 'es', draft: false })).slug, 'novias')
    assert.equal((await payload.findByID({ collection: 'pages', id: page.id, locale: 'en', draft: false })).slug, 'bridal')
    assert.equal(database.prepare('PRAGMA foreign_key_check').all().length, 0)
  } finally {
    await payload.destroy()
    database.close()
  }
})
