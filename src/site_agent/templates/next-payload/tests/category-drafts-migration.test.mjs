import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { Miniflare } = require('miniflare')

const MIGRATION = new URL('../src/migrations/20261104_190000_category_drafts.ts', import.meta.url)

/** Every `sql.raw("…")` argument the migration executes, decoded. */
const statementsOf = async (pattern) => {
  const source = await readFile(MIGRATION, 'utf8')
  return [...source.matchAll(pattern)].map((match) => JSON.parse(match[1]))
}

const RETIRED = [
  'product_categories_sections', 'product_categories_sections_locales',
  ...['heading', 'heading_locales', 'paragraph', 'paragraph_locales', 'rich_text', 'rich_text_locales',
    'image', 'image_locales', 'link', 'link_locales', 'content_list', 'content_list_items',
    'content_list_items_locales', 'contact_form', 'booking']
    .map((name) => `product_categories_blocks_hello_ada_${name}`),
]

const harness = async (t) => {
  const mf = new Miniflare({ workers: [{ config: {
    type: 'worker', name: 'category-drafts-migration', compatibilityDate: '2025-01-01',
    manifest: { mainModule: 'index.js', modules: {
      'index.js': { type: 'esm', contents: 'export default { fetch() { return new Response("ok") } }' },
    } },
    env: { D1: { type: 'd1', id: 'D1' } },
  } }] })
  const db = await mf.getD1Database('D1')
  await db.prepare('CREATE TABLE product_categories (id integer PRIMARY KEY NOT NULL, published integer DEFAULT true)').run()
  await db.prepare("INSERT INTO product_categories (id, published) VALUES (1, 1), (2, 1)").run()
  for (const table of RETIRED) await db.prepare(`CREATE TABLE \`${table}\` (id integer PRIMARY KEY NOT NULL)`).run()
  t.after(() => mf.dispose())
  return { db, apply: async () => {
    const guards = await statementsOf(/if \(\(await db\.all\(sql\.raw\(("(?:[^"\\]|\\.)*")\)\)\)\.length\)/g)
    for (const guard of guards) {
      const rows = (await db.prepare(guard).all()).results
      assert.deepEqual(rows, [], `guard must pass on an empty table: ${guard}`)
    }
    for (const statement of await statementsOf(/await db\.run\(sql\.raw\(("(?:[^"\\]|\\.)*")\)\)/g)) {
      await db.prepare(statement).run()
    }
  } }
}

test('every existing category stays published when the draft lifecycle is applied', async (t) => {
  const { db, apply } = await harness(t)
  await apply()
  const rows = (await db.prepare('SELECT id, _status FROM product_categories ORDER BY id').all()).results
  assert.deepEqual(rows, [{ id: 1, _status: 'published' }, { id: 2, _status: 'published' }],
    'the new column defaults to draft, so the backfill must not depend on null')
})

test('the migration retires only the empty category section tables and adds the version tables', async (t) => {
  const { db, apply } = await harness(t)
  await apply()
  const tables = (await db.prepare(
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%product_categories%'",
  ).all()).results.map((row) => row.name)
  assert.deepEqual(tables.sort(), ['_product_categories_v', '_product_categories_v_locales', 'product_categories'])
  const indexes = (await db.prepare(
    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%product_categories%'",
  ).all()).results.map((row) => row.name)
  assert.ok(indexes.includes('product_categories__status_idx'), 'the publication status is indexed')
})

test('category section content blocks the migration instead of being dropped', async (t) => {
  const { db } = await harness(t)
  await db.prepare('INSERT INTO `product_categories_sections` (id) VALUES (1)').run()
  const guards = await statementsOf(/if \(\(await db\.all\(sql\.raw\(("(?:[^"\\]|\\.)*")\)\)\)\.length\)/g)
  const blocked = []
  for (const guard of guards) {
    if ((await db.prepare(guard).all()).results.length) blocked.push(guard)
  }
  assert.equal(blocked.length, 1, 'exactly the table that holds content stops the migration')
  assert.match(blocked[0], /product_categories_sections/)
})
