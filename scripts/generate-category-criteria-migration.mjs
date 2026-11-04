/** Offline, review-time generator for the category-criteria additive columns.
 *  Never called by a deployment. Emits one reviewed snapshot + migration pair
 *  containing only the delta from the committed baseline. */
import { createRequire } from 'node:module'
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
const baselineName = '20261104_010000_business_catalog'
const name = '20261104_170000_category_criteria'
const baseline = JSON.parse(readFileSync(path.join(directory, `${baselineName}.json`), 'utf8'))

const config = await buildConfig({
  ...createHelloAdaSchema(async () => undefined), secret: 'offline-schema-generation',
  editor: lexicalEditor(), db: sqliteD1Adapter({ binding: {} }),
  localization: { locales: ['en'], defaultLocale: 'en', fallback: false },
})
const payload = { config, logger: console, collections: Object.fromEntries(config.collections.map((item) => [item.slug, { config: item }])) }
const adapter = config.db.init({ payload })
await adapter.init()
const { generateDrizzleJson } = adapter.requireDrizzleKit()
const generated = JSON.parse(JSON.stringify(await generateDrizzleJson(adapter.schema)))

const identifier = (value) => `\`${String(value).replaceAll('`', '``')}\``
const snapshot = JSON.parse(JSON.stringify(baseline))
const statements = []
const added = []

for (const [table, definition] of Object.entries(generated.tables)) {
  if (!snapshot.tables[table]) throw new Error(`Unexpected new table ${table}; this generator is additive-columns only.`)
  for (const [column, value] of Object.entries(definition.columns)) {
    if (snapshot.tables[table].columns[column]) continue
    if (value.primaryKey || value.autoincrement) throw new Error(`Unexpected primary key ${table}.${column}`)
    const reference = Object.values(definition.foreignKeys || {}).find((fk) => fk.columnsFrom.includes(column))
    if (reference) throw new Error(`Unexpected reference ${table}.${column}`)
    // SQLite additive policy: new columns stay nullable; Payload validates writes.
    snapshot.tables[table].columns[column] = { ...value, notNull: false }
    let clause = `${identifier(column)} ${value.type}`
    if (value.default !== undefined) clause += ` DEFAULT ${typeof value.default === 'boolean' ? Number(value.default) : value.default}`
    statements.push(`ALTER TABLE ${identifier(table)} ADD COLUMN ${clause};`)
    added.push(`${table}.${column}`)
  }
  for (const [indexName, index] of Object.entries(definition.indexes || {})) {
    const previous = snapshot.tables[table].indexes?.[indexName]
    if (previous && isDeepStrictEqual(previous, index)) continue
    if (previous) throw new Error(`Unexpected changed index ${table}.${indexName}`)
    snapshot.tables[table].indexes = { ...(snapshot.tables[table].indexes || {}), [indexName]: index }
    statements.push(`CREATE ${index.isUnique ? 'UNIQUE ' : ''}INDEX ${identifier(indexName)} ON ${identifier(table)} (${index.columns.map(identifier).join(', ')});`)
  }
}
if (!statements.length) throw new Error('The schema produced no additive statements.')

const migration = [
  "import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'",
  "import { sql } from '@payloadcms/db-d1-sqlite'",
  '',
  '// Generated offline by scripts/generate-category-criteria-migration.mjs.',
  '// Additive and forward-only: collection criteria columns on product_categories.',
  'export async function up({ db }: MigrateUpArgs): Promise<void> {',
  ...statements.map((statement) => `  await db.run(sql.raw(${JSON.stringify(statement)}))`),
  '}',
  '',
  'export async function down(_args: MigrateDownArgs): Promise<void> {',
  '  // Payload tenant releases are forward-only; preserve records.',
  '}',
  '',
].join('\n')

writeFileSync(path.join(directory, `${name}.json`), `${JSON.stringify(snapshot, null, 2)}\n`, { flag: 'wx' })
writeFileSync(path.join(directory, `${name}.ts`), migration, { flag: 'wx' })
console.log(`[category-criteria] ${statements.length} statements: ${added.join(', ')}`)
