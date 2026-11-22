/** Verify the committed migration and the generated schema agree.
 *
 *  A durable fix needs two properties, and this asserts both:
 *   1. the schema generated from the config carries every locale parent index;
 *   2. a later `migrate:create` diff against the committed snapshot is empty,
 *      so nothing silently drops those indexes.
 */
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
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

const config = await buildConfig({
  ...createHelloAdaSchema(async () => undefined),
  secret: 'offline-schema-verification',
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
const { generateDrizzleJson, generateMigration } = adapter.requireDrizzleKit()
const generated = JSON.parse(JSON.stringify(await generateDrizzleJson(adapter.schema)))

let generatedIndexes = 0
for (const [tableName, table] of Object.entries(generated.tables ?? {})) {
  if (!tableName.endsWith('_locales')) continue
  for (const index of Object.values(table.indexes ?? {})) {
    if ((index.columns ?? [])[0] === '_parent_id') generatedIndexes += 1
  }
}

const snapshot = JSON.parse(readFileSync(path.join(directory, '20261123_090000_locale_parent_indexes.json'), 'utf8'))
const up = (await generateMigration(snapshot, generated) ?? []).join('\n')
const drops = (up.match(/DROP\s+INDEX/gi) ?? []).length
const creates = (up.match(/CREATE\s+(?:UNIQUE\s+)?INDEX/gi) ?? []).length

const migration = readFileSync(path.join(directory, '20261123_090000_locale_parent_indexes.ts'), 'utf8')
const ddl = (migration.match(/CREATE INDEX IF NOT EXISTS/g) ?? []).length

console.log(`generated locale parent indexes : ${generatedIndexes}`)
console.log(`committed migration statements  : ${ddl}`)
console.log(`future migrate:create diff      : DROP=${drops} CREATE=${creates}`)
const ok = generatedIndexes === 95 && ddl === 95 && drops === 0 && creates === 0
console.log(ok ? 'VERIFIED: indexes are in the schema and survive migrate:create' : 'FAILED')
process.exit(ok ? 0 : 1)
