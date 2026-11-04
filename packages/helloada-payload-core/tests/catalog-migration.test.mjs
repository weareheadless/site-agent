import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import ts from 'typescript'

const directory = new URL('../../../src/site_agent/templates/next-payload/src/migrations/', import.meta.url)
const previous = ['20261004_021536_helloada_initial', '20261004_090000_growth_operations', '20261006_061835_helloada_owner_handoff', '20261009_123644_helloada_mailbox_calendar', '20261031_090000_helloada_section_layout']
const target = '20261104_170000_category_criteria'
const catalog = '20261104_010000_business_catalog'
const load = (name) => {
  const source = readFileSync(new URL(`${name}.ts`, directory), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const sql = (parts, ...values) => parts.reduce((result, part, index) => result + part + (values[index] ?? ''), '')
  sql.raw = value => value
  const exports = {}
  const require = name => { assert.equal(name, '@payloadcms/db-d1-sqlite'); return { sql } }
  new Function('require', 'exports', compiled)(require, exports)
  return exports
}
const fixture = async () => {
  const database = new DatabaseSync(':memory:')
  database.exec('PRAGMA foreign_keys=ON')
  const db = { run: async sql => database.exec(sql), all: async sql => database.prepare(sql).all() }
  for (const name of previous) await load(name).up({ db })
  return { database, db }
}

test('the complete committed migration chain bootstraps a new D1-compatible database', async () => {
  const { database, db } = await fixture()
  try {
    await load(catalog).up({ db })
    await load(target).up({ db })
    assert.equal(database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='product_variants'").get().name, 'product_variants')
    assert.equal(database.prepare('PRAGMA foreign_key_check').all().length, 0)
    const snapshot = JSON.parse(readFileSync(new URL(`${target}.json`, directory)))
    for (const [table, definition] of Object.entries(snapshot.tables)) {
      const columns = database.prepare(`PRAGMA table_info(\`${table}\`)`).all().map(row => row.name).sort()
      assert.deepEqual(columns, Object.keys(definition.columns).sort(), `${table} matches the committed target columns`)
      for (const index of Object.values(definition.indexes)) {
        assert.ok(database.prepare("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?").get(index.name), `index ${index.name} exists`)
      }
    }
  } finally { database.close() }
})

test('catalog migration preserves localized content, historical slugs, money and relationships', async () => {
  const { database: sql, db } = await fixture()
  try {
    sql.exec("INSERT INTO pages (id,slug) VALUES (1,'novias'); INSERT INTO pages_locales (_parent_id,_locale,title) VALUES (1,'es','Novias'),(1,'en','Bridal')")
    sql.exec("INSERT INTO _pages_v (id,parent_id,version_slug) VALUES (1,1,'old-bridal'); INSERT INTO _pages_v_locales (_parent_id,_locale,version_title) VALUES (1,'es','Novias anteriores'),(1,'en','Old bridal')")
    sql.exec("INSERT INTO product_categories (id,slug) VALUES (1,'shirts'); INSERT INTO product_categories_locales (_parent_id,_locale,title) VALUES (1,'en','Shirts')")
    sql.exec("INSERT INTO products (id,slug,price,currency,category_id) VALUES (1,'shirt',12.5,'EUR',1); INSERT INTO products_locales (_parent_id,_locale,title) VALUES (1,'en','Shirt')")
    await load(catalog).up({ db })
    await load(target).up({ db })
    assert.deepEqual(sql.prepare('SELECT _locale,slug,title FROM pages_locales ORDER BY _locale').all().map(row => ({ ...row })), [{ _locale: 'en', slug: 'novias', title: 'Bridal' }, { _locale: 'es', slug: 'novias', title: 'Novias' }])
    assert.equal(sql.prepare('SELECT version_slug FROM _pages_v_locales LIMIT 1').get().version_slug, 'old-bridal')
    assert.deepEqual({ ...sql.prepare('SELECT price,currency,category_id,price_minor FROM products WHERE id=1').get() }, { price: 12.5, currency: 'EUR', category_id: 1, price_minor: null })
    sql.exec("UPDATE pages_locales SET slug='bridal' WHERE _locale='en'")
    // No obsolete NOT NULL global slug blocks a new category after cutover.
    sql.exec("INSERT INTO product_categories (id) VALUES (2); INSERT INTO product_categories_locales (_parent_id,_locale,title,slug) VALUES (2,'en','Trousers','trousers')")
    assert.equal(sql.prepare('PRAGMA foreign_key_check').all().length, 0)
  } finally { sql.close() }
})

test('unmapped source data stops the migration before the first DDL write', async () => {
  const { database: sql, db } = await fixture()
  try {
    sql.exec("INSERT INTO pages (id,slug) VALUES (1,'orphaned-locale')")
    const before = sql.prepare("SELECT sql FROM sqlite_master WHERE name='pages'").get().sql
    await assert.rejects(() => load(catalog).up({ db }), /no locale row/)
    assert.equal(sql.prepare("SELECT sql FROM sqlite_master WHERE name='pages'").get().sql, before)
    assert.equal(sql.prepare("SELECT 1 FROM sqlite_master WHERE name='product_variants'").get(), undefined)
  } finally { sql.close() }
})

test('retained legacy booking content is never erased or assigned an invented Mailflare ID', async () => {
  const { database: sql, db } = await fixture()
  try {
    sql.exec("INSERT INTO pages (id,slug) VALUES (1,'appointments'); INSERT INTO pages_locales (_parent_id,_locale,title) VALUES (1,'en','Appointments')")
    sql.exec("INSERT INTO pages_blocks_hello_ada_booking (_order,_parent_id,_path,id,label) VALUES (1,1,'sections.0.entries','legacy-booking','Appointment')")
    await assert.rejects(() => load(catalog).up({ db }), /explicit Mailflare mapping/)
    assert.equal(sql.prepare('SELECT label FROM pages_blocks_hello_ada_booking').get().label, 'Appointment')
    assert.equal(sql.prepare("SELECT 1 FROM sqlite_master WHERE name='product_variants'").get(), undefined)
  } finally { sql.close() }
})
