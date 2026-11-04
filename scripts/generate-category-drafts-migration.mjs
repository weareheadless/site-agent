/** Offline, review-time generator for the category draft lifecycle.
 *
 *  Never called by a deployment. Emits one reviewed snapshot + migration pair
 *  containing only the delta from the committed baseline:
 *
 *  - the Payload version tables for `productCategories` (drafts),
 *  - `_status` on the base table, backfilled to `published` so the twelve live
 *    categories do not disappear when the collection becomes draftable,
 *  - the retired, empty category section tables.
 *
 *  Dropping the section tables is a reviewed decision: a category renders its
 *  criteria-derived products and never used composed sections, and the block
 *  tables pushed the versioned identifiers past SQLite's 63-character limit.
 *  The migration refuses to run if any of those tables holds a row.
 */
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { isDeepStrictEqual } from 'node:util'

import { createHelloAdaSchema } from '../packages/helloada-payload-core/src/schema/index.ts'

const root = fileURLToPath(new URL('../', import.meta.url))
const require = createRequire(path.join(root, 'packages/helloada-payload-core/package.json'))
const { buildConfig } = await import(pathToFileURL(require.resolve('payload')).href)
const { sqliteD1Adapter } = await import(pathToFileURL(require.resolve('@payloadcms/db-d1-sqlite')).href)
const { lexicalEditor } = await import(pathToFileURL(require.resolve('@payloadcms/richtext-lexical')).href)

const directory = path.join(root, 'src/site_agent/templates/next-payload/src/migrations')
const baselineName = '20261104_170000_category_criteria'
const name = '20261104_190000_category_drafts'
const before = JSON.parse(readFileSync(path.join(directory, `${baselineName}.json`), 'utf8'))

const config = await buildConfig({
  ...createHelloAdaSchema(async () => undefined), secret: 'offline-schema-generation',
  editor: lexicalEditor(), db: sqliteD1Adapter({ binding: {} }),
  localization: { locales: ['en'], defaultLocale: 'en', fallback: false },
})
const payload = { config, logger: console, collections: Object.fromEntries(config.collections.map((item) => [item.slug, { config: item }])) }
const adapter = config.db.init({ payload })
await adapter.init()
const { generateDrizzleJson, generateMigration } = adapter.requireDrizzleKit()
const target = JSON.parse(JSON.stringify(await generateDrizzleJson(adapter.schema)))

const id = (value) => '`' + String(value).replaceAll('`', '``') + '`'

const newTables = Object.keys(target.tables).filter((table) => !before.tables[table]).sort()
const droppedTables = Object.keys(before.tables).filter((table) => !target.tables[table]).sort()
const expectedNew = ['_product_categories_v', '_product_categories_v_locales']
if (JSON.stringify(newTables) !== JSON.stringify(expectedNew)) {
  throw new Error(`Unexpected new tables: ${newTables.join(', ')}`)
}
for (const table of droppedTables) {
  if (!/^product_categories_(sections|blocks_)/.test(table)) {
    throw new Error(`Refusing to drop an unexpected table: ${table}`)
  }
}
for (const table of Object.keys(target.tables)) {
  if (!before.tables[table]) continue
  const added = Object.keys(target.tables[table].columns).filter((column) => !before.tables[table].columns[column])
  const removed = Object.keys(before.tables[table].columns).filter((column) => !target.tables[table].columns[column])
  const allowed = table === 'product_categories' ? ['_status'] : []
  if (JSON.stringify(added) !== JSON.stringify(allowed) || removed.length) {
    throw new Error(`Unexpected column delta on ${table}: +${added.join(',')} -${removed.join(',')}`)
  }
}

// A full-schema generation gives the exact CREATE TABLE text without asking
// drizzle to guess whether a table was created or renamed.
const fullSql = await generateMigration(adapter.defaultDrizzleSnapshot, target)
const creates = new Map(fullSql.flatMap((statement) => {
  const match = statement.match(/^CREATE TABLE `([^`]+)`/)
  return match ? [[match[1], statement]] : []
}))
for (const table of newTables) {
  if (!creates.get(table)) throw new Error(`No CREATE TABLE generated for ${table}`)
}

const indexStatements = []
for (const [table, definition] of Object.entries(target.tables)) {
  if (!newTables.includes(table) && table !== 'product_categories') continue
  for (const [indexName, index] of Object.entries(definition.indexes || {})) {
    const previous = before.tables[table]?.indexes?.[indexName]
    if (previous && isDeepStrictEqual(previous, index)) continue
    if (previous) throw new Error(`Unexpected changed index ${table}.${indexName}`)
    indexStatements.push(`CREATE ${index.isUnique ? 'UNIQUE ' : ''}INDEX ${id(indexName)} ON ${id(table)} (${index.columns.map(id).join(', ')});`)
  }
}

const statements = [
  ...newTables.map((table) => creates.get(table)),
  // Match the snapshot's declared default; the backfill below republishes the
  // rows that were already live.
  `ALTER TABLE ${id('product_categories')} ADD COLUMN ${id('_status')} text DEFAULT 'draft';`,
  // Every row that exists before the lifecycle was live by definition. The new
  // column defaults to draft, so this backfill is unconditional: it must not
  // depend on the column being null.
  `UPDATE ${id('product_categories')} SET ${id('_status')} = 'published';`,
  ...indexStatements,
  ...droppedTables.map((table) => `DROP TABLE ${id(table)};`),
]
if (statements.some((statement) => typeof statement !== 'string' || !statement.trim())) {
  throw new Error('A generated statement is missing')
}

const source = [
  "import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'",
  "import { sql } from '@payloadcms/db-d1-sqlite'", '',
  '// Generated offline by scripts/generate-category-drafts-migration.mjs.',
  '// Forward-only: stage the matching Worker before applying.',
  'export async function up({ db }: MigrateUpArgs): Promise<void> {',
  ...droppedTables.map((table) => `  if ((await db.all(sql.raw(${JSON.stringify(`SELECT 1 FROM ${id(table)} LIMIT 1`)}))).length) throw new Error(${JSON.stringify(`Category section content in ${table} must be moved before the draft lifecycle migration.`)})`),
  ...statements.map((statement) => `  await db.run(sql.raw(${JSON.stringify(statement)}))`),
  '}', '',
  'export async function down(_args: MigrateDownArgs): Promise<void> {',
  "  throw new Error('The category draft lifecycle is forward-only. Restore the reviewed D1 backup and matching Worker to roll back.')",
  '}', '',
].join('\n')

target.prevId = before.id
target.id = createHash('sha256').update(name).digest('hex').slice(0, 32).replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, '$1-$2-$3-$4-$5')
writeFileSync(path.join(directory, `${name}.ts`), source)
writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(target, null, 2) + '\n')
console.log(`${name}: ${statements.length} reviewed statements (${newTables.length} new tables, ${droppedTables.length} retired)`)
