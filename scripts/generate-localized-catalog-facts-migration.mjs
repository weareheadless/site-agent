/** Offline, review-time generator for localized catalogue facts.
 *
 *  Never called by a deployment. The source stores price and location per
 *  locale, so one saved search returns a different set in each language. This
 *  migration moves those columns from the base tables into the locale tables
 *  additively: new nullable columns, the English values copied across, and the
 *  old columns left in place as dead data (no rebuild, no destructive drop).
 *
 *  Spanish values are imported separately through the workspace API, so the
 *  migration never invents a translation.
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
const baselineName = '20261104_220000_category_version_backfill'
const name = '20261105_020000_localized_catalog_facts'
const before = JSON.parse(readFileSync(path.join(directory, `${baselineName}.json`), 'utf8'))

const config = await buildConfig({
  ...createHelloAdaSchema(async () => undefined), secret: 'offline-schema-generation',
  editor: lexicalEditor(), db: sqliteD1Adapter({ binding: {} }),
  localization: { locales: ['en'], defaultLocale: 'en', fallback: false },
})
const payload = { config, logger: console, collections: Object.fromEntries(config.collections.map((item) => [item.slug, { config: item }])) }
const adapter = config.db.init({ payload })
await adapter.init()
const { generateDrizzleJson } = adapter.requireDrizzleKit()
const target = JSON.parse(JSON.stringify(await generateDrizzleJson(adapter.schema)))

const id = (value) => '`' + String(value).replaceAll('`', '``') + '`'

/** Every localized move this migration is allowed to perform. */
const moves = [
  { base: 'products', locales: 'products_locales', versionBase: '_products_v', versionLocales: '_products_v_locales', columns: [
    ['price_minor', 'price_minor'],
    ['location_city', 'location_city'],
    ['location_region', 'location_region'],
    ['location_neighbourhood', 'location_neighbourhood'],
  ] },
  { base: 'product_categories', locales: 'product_categories_locales', versionBase: '_product_categories_v', versionLocales: '_product_categories_v_locales', columns: [
    ['criteria_city', 'criteria_city'],
    ['criteria_region', 'criteria_region'],
    ['criteria_availability', 'criteria_availability'],
    ['criteria_price_min_minor', 'criteria_price_min_minor'],
    ['criteria_price_max_minor', 'criteria_price_max_minor'],
  ] },
]

if (Object.keys(target.tables).length !== Object.keys(before.tables).length) {
  throw new Error('This migration must not create or drop tables')
}
for (const table of Object.keys(target.tables)) {
  const added = Object.keys(target.tables[table].columns).filter((column) => !before.tables[table].columns[column])
  const removed = Object.keys(before.tables[table].columns).filter((column) => !target.tables[table].columns[column])
  const expected = moves.find((move) => table === move.locales || table === move.versionLocales)
  if (expected) {
    const wanted = expected.columns.map(([from, to]) => table === expected.locales ? to : `version_${to}`)
    if (JSON.stringify(added) !== JSON.stringify(wanted) || removed.length) {
      throw new Error(`Unexpected localized delta on ${table}: +${added.join(',')} -${removed.join(',')}`)
    }
    continue
  }
  const source = moves.find((move) => table === move.base || table === move.versionBase)
  if (source) {
    const wanted = source.columns.map(([from]) => table === source.base ? from : `version_${from}`)
    if (JSON.stringify(removed) !== JSON.stringify(wanted) || added.length) {
      throw new Error(`Unexpected base delta on ${table}: +${added.join(',')} -${removed.join(',')}`)
    }
    continue
  }
  if (added.length || removed.length) throw new Error(`Unexpected column delta on ${table}`)
}

const statements = []
for (const move of moves) {
  for (const [baseColumn, localeColumn] of move.columns) {
    const definition = target.tables[move.locales].columns[localeColumn]
    if (!definition || definition.primaryKey || definition.notNull) {
      throw new Error(`Localized column ${move.locales}.${localeColumn} is not a nullable addition`)
    }
    statements.push(`ALTER TABLE ${id(move.locales)} ADD COLUMN ${id(localeColumn)} ${definition.type};`)
    statements.push(`ALTER TABLE ${id(move.versionLocales)} ADD COLUMN ${id(`version_${localeColumn}`)} ${target.tables[move.versionLocales].columns[`version_${localeColumn}`].type};`)
    // English is the published source of truth for the existing rows. The other
    // locales are imported from the export, never copied from English.
    statements.push(`UPDATE ${id(move.locales)} SET ${id(localeColumn)} = (SELECT ${id(baseColumn)} FROM ${id(move.base)} WHERE ${id(move.base)}.id = ${id(move.locales)}._parent_id) WHERE _locale = 'en';`)
    statements.push(`UPDATE ${id(move.versionLocales)} SET ${id(`version_${localeColumn}`)} = (SELECT ${id(`version_${baseColumn}`)} FROM ${id(move.versionBase)} WHERE ${id(move.versionBase)}.id = ${id(move.versionLocales)}._parent_id) WHERE _locale = 'en';`)
  }
}
for (const [table, definition] of Object.entries(target.tables)) {
  for (const [indexName, index] of Object.entries(definition.indexes || {})) {
    const previous = before.tables[table]?.indexes?.[indexName]
    if (previous && isDeepStrictEqual(previous, index)) continue
    if (previous) throw new Error(`Unexpected changed index ${table}.${indexName}`)
    // SQLite index names are database-wide. A localized field keeps the index
    // name it had on the base table, so retire the old index first; its column
    // is now dead data.
    const retired = Object.entries(before.tables).find(([, definition]) => definition.indexes?.[indexName])
    if (retired && retired[0] !== table) {
      statements.push(`DROP INDEX IF EXISTS ${id(indexName)};`)
    }
    statements.push(`CREATE ${index.isUnique ? 'UNIQUE ' : ''}INDEX ${id(indexName)} ON ${id(table)} (${index.columns.map(id).join(', ')});`)
  }
}

const source = [
  "import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'",
  "import { sql } from '@payloadcms/db-d1-sqlite'", '',
  '// Generated offline by scripts/generate-localized-catalog-facts-migration.mjs.',
  '// Additive: new locale columns, English copied across, old columns retained.',
  'export async function up({ db }: MigrateUpArgs): Promise<void> {',
  ...statements.map((statement) => `  await db.run(sql.raw(${JSON.stringify(statement)}))`),
  '}', '',
  'export async function down(_args: MigrateDownArgs): Promise<void> {',
  "  throw new Error('Localized catalogue facts are forward-only. Restore the reviewed D1 backup to roll back.')",
  '}', '',
].join('\n')

target.prevId = before.id
target.id = createHash('sha256').update(name).digest('hex').slice(0, 32).replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, '$1-$2-$3-$4-$5')
writeFileSync(path.join(directory, `${name}.ts`), source)
writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(target, null, 2) + '\n')
console.log(`${name}: ${statements.length} reviewed statements`)
