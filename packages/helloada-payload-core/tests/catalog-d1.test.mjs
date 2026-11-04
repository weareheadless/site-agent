import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'

import { buildConfig } from 'payload'
import { sqliteD1Adapter } from '@payloadcms/db-d1-sqlite'
import { lexicalEditor } from '@payloadcms/richtext-lexical'
import { createHelloAdaSchema } from '../src/schema/index.ts'

test('the real D1 adapter builds per-locale slug uniqueness and indexed catalog constraints', async () => {
  const schema = createHelloAdaSchema(async () => undefined)
  const config = await buildConfig({
    ...schema, secret: 'offline-schema-test', editor: lexicalEditor(),
    db: sqliteD1Adapter({ binding: {} }),
    localization: { locales: ['en', 'es'], defaultLocale: 'en', fallback: false },
  })
  const payload = { config, logger: console, collections: Object.fromEntries(config.collections.map(config => [config.slug, { config }])) }
  const adapter = config.db.init({ payload })
  await adapter.init()
  const { generateDrizzleJson, generateMigration } = adapter.requireDrizzleKit()
  const snapshot = await generateDrizzleJson(adapter.schema)
  const statements = await generateMigration(adapter.defaultDrizzleSnapshot, snapshot)
  const db = new DatabaseSync(':memory:')
  try {
    for (const statement of statements) db.exec(statement)
    db.exec("INSERT INTO pages (id, created_at, updated_at) VALUES (1, '2026-11-03', '2026-11-03'), (2, '2026-11-03', '2026-11-03')")
    db.exec("INSERT INTO pages_locales (_parent_id, _locale, slug) VALUES (1, 'es', 'color-y-corte'), (1, 'en', 'color-and-cuts'), (2, 'es', 'color-and-cuts')")
    assert.throws(() => db.exec("INSERT INTO pages_locales (_parent_id, _locale, slug) VALUES (2, 'en', 'color-and-cuts')"), /UNIQUE/)
    db.exec("INSERT INTO products (id, created_at, updated_at) VALUES (1, '2026-11-03', '2026-11-03')")
    db.exec("INSERT INTO product_attributes (product_id, key, value_type, value_number, created_at, updated_at) VALUES (1, 'area', 'number', 80, '2026-11-03', '2026-11-03')")
    assert.throws(() => db.exec("INSERT INTO product_attributes (product_id, key, created_at, updated_at) VALUES (1, 'area', '2026-11-03', '2026-11-03')"), /UNIQUE/)
    assert.match(db.prepare("EXPLAIN QUERY PLAN SELECT * FROM product_attributes WHERE key='area' AND value_number > 70").all().map(row => row.detail).join(' '), /INDEX/)
    db.exec("INSERT INTO product_variants (product_id, sku, selection_key, created_at, updated_at) VALUES (1, 'SHIRT-M', 'size:m', '2026-11-03', '2026-11-03')")
    assert.throws(() => db.exec("INSERT INTO product_variants (product_id, sku, selection_key, created_at, updated_at) VALUES (1, 'SHIRT-M2', 'size:m', '2026-11-03', '2026-11-03')"), /UNIQUE/)
    assert.throws(() => db.exec("INSERT INTO product_variants (product_id, sku, selection_key, created_at, updated_at) VALUES (1, 'SHIRT-M', 'size:l', '2026-11-03', '2026-11-03')"), /UNIQUE/)
  } finally { db.close() }
})
