/** Offline, review-time generator. Never called by a deployment. */
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
const name = '20261104_010000_business_catalog'
const before = JSON.parse(readFileSync(path.join(directory, '20261031_090000_helloada_section_layout.json'), 'utf8'))
const config = await buildConfig({
  ...createHelloAdaSchema(async () => undefined), secret: 'offline-schema-generation',
  editor: lexicalEditor(), db: sqliteD1Adapter({ binding: {} }),
  localization: { locales: ['en'], defaultLocale: 'en', fallback: false },
})
const payload = { config, logger: console, collections: Object.fromEntries(config.collections.map(config => [config.slug, { config }])) }
const adapter = config.db.init({ payload })
await adapter.init()
const { generateDrizzleJson, generateMigration } = adapter.requireDrizzleKit()
const target = JSON.parse(JSON.stringify(await generateDrizzleJson(adapter.schema)))
// Existing Payload writes already supply the configured default. Preserve the
// historical SQL default and existing mailbox values; catalog work does not
// change a provider or rebuild a mailbox table with cascading locale relations.
target.tables.message_mailbox.columns.outbound_provider.default = before.tables.message_mailbox.columns.outbound_provider.default
// Visibility defaults for new Payload writes do not republish existing rows or
// rewrite historical SQL defaults. _status remains the publication authority.
for (const [table, definition] of Object.entries(before.tables)) {
  for (const [column, value] of Object.entries(definition.columns)) {
    if (target.tables[table]?.columns[column] && value.default !== undefined) target.tables[table].columns[column].default = value.default
  }
}
const sql = await generateMigration(adapter.defaultDrizzleSnapshot, target)
const creates = new Map(sql.flatMap(statement => {
  const match = statement.match(/^CREATE TABLE `([^`]+)`/)
  return match ? [[match[1], statement]] : []
}))
const id = name => '`' + name.replaceAll('`', '``') + '`'
const columns = name => target.tables[name].columns
const statements = []
const bookingTables = Object.keys(before.tables).filter(name => name.endsWith('_blocks_hello_ada_booking'))
const slugTables = ['pages', 'posts', 'post_categories', 'products', 'product_categories', '_pages_v', '_posts_v', '_post_categories_v', '_products_v']

// This is an explicitly reviewed reconciliation, not a guessed foreign-key to
// Mailflare-ID conversion. Any retained legacy booking content blocks it.
for (const table of bookingTables) {
  const incoming = Object.values(before.tables).flatMap(t => Object.values(t.foreignKeys || {})).filter(fk => fk.tableTo === table)
  if (incoming.length) throw new Error(`Unexpected incoming relationship to ${table}`)
  statements.push(`DROP TABLE ${id(table)};`, creates.get(table))
}
for (const [table, definition] of Object.entries(target.tables)) {
  if (!before.tables[table]) { statements.push(creates.get(table)); continue }
  if (bookingTables.includes(table)) continue
  for (const [column, value] of Object.entries(definition.columns)) {
    if (before.tables[table].columns[column]) continue
    if (value.primaryKey || value.autoincrement) throw new Error(`Unexpected added primary key: ${table}.${column}`)
    // Nullable ADD COLUMN is the established SQLite additive policy. Payload
    // enforces required fields; existing localized slugs are backfilled below.
    target.tables[table].columns[column].notNull = false
    let clause = `${id(column)} ${value.type}`
    if (value.default !== undefined) clause += ` DEFAULT ${typeof value.default === 'boolean' ? Number(value.default) : value.default}`
    const refs = Object.values(definition.foreignKeys || {}).filter(fk => fk.columnsFrom.includes(column))
    if (refs.length > 1 || refs.some(fk => fk.columnsFrom.length !== 1 || fk.columnsTo.length !== 1)) throw new Error(`Unexpected composite reference: ${table}.${column}`)
    if (refs.length) {
      const fk = refs[0]
      clause += ` REFERENCES ${id(fk.tableTo)} (${id(fk.columnsTo[0])}) ON DELETE ${fk.onDelete.toUpperCase()} ON UPDATE ${fk.onUpdate.toUpperCase()}`
    }
    statements.push(`ALTER TABLE ${id(table)} ADD COLUMN ${clause};`)
  }
}
// Move every existing locale and every historical revision before retiring the
// old column. Slugs are never translated, inferred, or manufactured here.
for (const table of slugTables) {
  const column = table.startsWith('_') ? 'version_slug' : 'slug'
  const locales = `${table}_locales`
  statements.push(`UPDATE ${id(locales)} SET ${id(column)} = (SELECT ${id(column)} FROM ${id(table)} WHERE ${id(table)}.id = ${id(locales)}._parent_id);`)
  for (const [indexName, index] of Object.entries(before.tables[table].indexes)) {
    if (index.columns.includes(column)) statements.push(`DROP INDEX ${id(indexName)};`)
  }
  statements.push(`ALTER TABLE ${id(table)} DROP COLUMN ${id(column)};`)
}
for (const [table, definition] of Object.entries(target.tables)) {
  for (const [name, index] of Object.entries(definition.indexes || {})) {
    const previous = bookingTables.includes(table) ? undefined : before.tables[table]?.indexes?.[name]
    const retired = slugTables.includes(table) && previous?.columns.some(column => column === 'slug' || column === 'version_slug')
    if (previous && isDeepStrictEqual(previous, index) && !retired) continue
    if (previous && !retired) throw new Error(`Unexpected changed index ${table}.${name}`)
    statements.push(`CREATE ${index.isUnique ? 'UNIQUE ' : ''}INDEX ${id(name)} ON ${id(table)} (${index.columns.map(id).join(', ')});`)
  }
}
if (statements.some(statement => typeof statement !== 'string')) throw new Error('A generated table definition is missing')

const source = [
  "import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'",
  "import { sql } from '@payloadcms/db-d1-sqlite'", '',
  '// Generated offline by scripts/generate-business-catalog-migration.mjs.',
  '// Forward-only schema cutover: stage the matching Worker before applying.',
  'export async function up({ db }: MigrateUpArgs): Promise<void> {',
  ...bookingTables.map(table => `  if ((await db.all(sql.raw(${JSON.stringify(`SELECT 1 FROM ${id(table)} LIMIT 1`)}))).length) throw new Error(${JSON.stringify(`Legacy booking content in ${table} requires an explicit Mailflare mapping before this migration.`)})`),
  ...slugTables.map(table => {
    const column = table.startsWith('_') ? 'version_slug' : 'slug'
    return `  if ((await db.all(sql.raw(${JSON.stringify(`SELECT 1 FROM ${id(table)} t WHERE t.${id(column)} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ${id(`${table}_locales`)} l WHERE l._parent_id = t.id) LIMIT 1`)}))).length) throw new Error(${JSON.stringify(`A slug in ${table} has no locale row. Repair the source locale before migrating.`)})`
  }),
  ...statements.map(statement => `  await db.run(sql.raw(${JSON.stringify(statement)}))`),
  '}', '',
  'export async function down(_args: MigrateDownArgs): Promise<void> {',
  "  throw new Error('Catalog migration is forward-only. Restore the reviewed D1 backup and matching Worker to roll back.')", '}', '',
].join('\n')
target.prevId = before.id
target.id = createHash('sha256').update(name).digest('hex').slice(0, 32).replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, '$1-$2-$3-$4-$5')
writeFileSync(path.join(directory, `${name}.ts`), source)
writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(target, null, 2) + '\n')
console.log(`${name}: ${statements.length} reviewed DDL/backfill statements`)
