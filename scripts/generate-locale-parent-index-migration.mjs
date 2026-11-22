/** Offline, review-time generator for the locale parent-index migration.
 *
 *  Emits both artifacts from one source of truth: the schema Payload builds from
 *  the real config (including the `localeParentIndexHook`). Generating the
 *  snapshot this way is what makes the index durable — the snapshot then matches
 *  the generated schema exactly, so a later `payload migrate:create` produces an
 *  empty diff instead of `DROP INDEX` for every locale table.
 */
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

import { createHelloAdaSchema } from '../packages/helloada-payload-core/src/schema/index.ts'
import { localeParentIndexHook } from '../src/site_agent/templates/next-payload/src/lib/locale-parent-index.ts'

const root = fileURLToPath(new URL('../', import.meta.url))
const require = createRequire(path.join(root, 'packages/helloada-payload-core/package.json'))
const { buildConfig } = await import(pathToFileURL(require.resolve('payload')).href)
const { sqliteD1Adapter } = await import(pathToFileURL(require.resolve('@payloadcms/db-d1-sqlite')).href)
const { lexicalEditor } = await import(pathToFileURL(require.resolve('@payloadcms/richtext-lexical')).href)

const directory = path.join(root, 'src/site_agent/templates/next-payload/src/migrations')
const baselineName = '20261105_020000_localized_catalog_facts'
const name = '20261123_090000_locale_parent_indexes'

const config = await buildConfig({
  ...createHelloAdaSchema(async () => undefined),
  secret: 'offline-schema-generation',
  editor: lexicalEditor(),
  db: sqliteD1Adapter({ binding: {}, beforeSchemaInit: [localeParentIndexHook] }),
  localization: { locales: ['en'], defaultLocale: 'en', fallback: false },
})
const payload = {
  config,
  logger: { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} },
  collections: Object.fromEntries(config.collections.map((item) => [item.slug, { config: item }])),
}
const adapter = config.db.init({ payload })
await adapter.init()
const { generateDrizzleJson } = adapter.requireDrizzleKit()
const generated = JSON.parse(JSON.stringify(await generateDrizzleJson(adapter.schema)))

/** The locale tables and the index name each one carries. */
const localeIndexes = []
const known = new Set()
for (const [tableName, table] of Object.entries(generated.tables ?? {})) {
  if (!tableName.endsWith('_locales')) continue
  for (const index of Object.values(table.indexes ?? {})) {
    if ((index.columns ?? [])[0] === '_parent_id' && index.name.endsWith('_parent_id_idx')) {
      localeIndexes.push({ table: tableName, index: index.name })
    }
  }
  known.add(tableName)
}
localeIndexes.sort((a, b) => a.table.localeCompare(b.table))

if (!localeIndexes.length) throw new Error('The generated schema carries no locale parent indexes.')

const baseline = JSON.parse(readFileSync(path.join(directory, `${baselineName}.json`), 'utf8'))
const target = generated
target.id = baseline.id
target.prevId = baseline.prevId

const identifier = (value) => '`' + String(value).replaceAll('`', '``') + '`'
const statements = [
  'import type { MigrateDownArgs, MigrateUpArgs } from \'@payloadcms/db-d1-sqlite\'',
  'import { sql } from \'@payloadcms/db-d1-sqlite\'',
  '',
  '// Generated offline by scripts/generate-locale-parent-index-migration.mjs.',
  '// Additive: an index per locale table so Payload\'s correlated `_parent_id`',
  '// locale lookup stops scanning the whole locale table. No data is moved.',
  'export async function up({ db }: MigrateUpArgs): Promise<void> {',
  ...localeIndexes.map(({ table, index }) =>
    `  await db.run(sql.raw("CREATE INDEX IF NOT EXISTS ${identifier(index)} ON ${identifier(table)} (${identifier('_parent_id')});"))`),
  '}',
  '',
  'export async function down({ db }: MigrateDownArgs): Promise<void> {',
  ...localeIndexes.map(({ index }) =>
    `  await db.run(sql.raw("DROP INDEX IF EXISTS ${identifier(index)};"))`),
  '}',
  '',
].join('\n')

writeFileSync(path.join(directory, `${name}.ts`), statements)
writeFileSync(path.join(directory, `${name}.json`), `${JSON.stringify(target, null, 2)}\n`)

console.log(`locale tables in the generated schema : ${known.size}`)
console.log(`parent indexes written                : ${localeIndexes.length}`)
console.log(`wrote                                 : ${name}.ts, ${name}.json`)
process.exit(0)
