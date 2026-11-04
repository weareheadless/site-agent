/** Offline, review-time generator for the category version backfill.
 *
 *  Never called by a deployment. Enabling drafts on a collection that already
 *  has documents leaves those documents without a version row, so Payload's
 *  draft list (admin and workspace) cannot see them until each is saved once.
 *  This data-only migration writes the missing version rows from the published
 *  base rows. It is idempotent and changes no schema, so the snapshot is the
 *  previous one with a new identity.
 */
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const directory = path.join(root, 'src/site_agent/templates/next-payload/src/migrations')
const baselineName = '20261104_190000_category_drafts'
const name = '20261104_220000_category_version_backfill'
const baseline = JSON.parse(readFileSync(path.join(directory, `${baselineName}.json`), 'utf8'))

const baseColumns = [
  ['source_id', 'version_source_id'],
  ['source_url', 'version_source_url'],
  ['featured_image_id', 'version_featured_image_id'],
  ['canonical_url', 'version_canonical_url'],
  ['criteria_city', 'version_criteria_city'],
  ['criteria_region', 'version_criteria_region'],
  ['criteria_availability', 'version_criteria_availability'],
  ['criteria_price_min_minor', 'version_criteria_price_min_minor'],
  ['criteria_price_max_minor', 'version_criteria_price_max_minor'],
  ['published', 'version_published'],
  ['updated_at', 'version_updated_at'],
  ['created_at', 'version_created_at'],
]
const localeColumns = [
  ['title', 'version_title'],
  ['slug', 'version_slug'],
  ['description', 'version_description'],
  ['seo_title', 'version_seo_title'],
  ['seo_description', 'version_seo_description'],
  ['seo_image_id', 'version_seo_image_id'],
]

const versionInsert = [
  `INSERT INTO _product_categories_v (`,
  `  parent_id, ${baseColumns.map(([, to]) => to).join(', ')}, version__status, latest, created_at, updated_at`,
  `) SELECT id, ${baseColumns.map(([from]) => from).join(', ')}, 'published', 1, created_at, updated_at`,
  `FROM product_categories WHERE id = \${parent}`,
].join('\n')
const localeInsert = [
  `INSERT INTO _product_categories_v_locales (`,
  `  ${localeColumns.map(([, to]) => to).join(', ')}, _locale, _parent_id`,
  `) SELECT ${localeColumns.map(([from]) => from).join(', ')}, _locale,`,
  `  (SELECT MAX(id) FROM _product_categories_v WHERE parent_id = \${parent})`,
  `FROM product_categories_locales WHERE _parent_id = \${parent}`,
].join('\n')

const source = [
  "import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'",
  "import { sql } from '@payloadcms/db-d1-sqlite'", '',
  '// Generated offline by scripts/generate-category-version-backfill-migration.mjs.',
  '// Forward-only and idempotent: it only fills version rows that are missing.',
  'export async function up({ db }: MigrateUpArgs): Promise<void> {',
  '  const missing = await db.all(sql.raw(',
  "    'SELECT p.id FROM product_categories p WHERE NOT EXISTS (SELECT 1 FROM _product_categories_v v WHERE v.parent_id = p.id) ORDER BY p.id',",
  '  )) as Array<{ id: number }>',
  '  for (const row of missing) {',
  '    const parent = Number(row.id)',
  "    if (!Number.isSafeInteger(parent) || parent < 1) throw new Error('A category row has no safe integer identity.')",
  `    await db.run(sql.raw(\`${versionInsert}\`))`,
  `    await db.run(sql.raw(\`${localeInsert}\`))`,
  '  }',
  '}', '',
  'export async function down(_args: MigrateDownArgs): Promise<void> {',
  "  throw new Error('The category version backfill is forward-only. Restore the reviewed D1 backup to roll back.')",
  '}', '',
].join('\n')

const snapshot = JSON.parse(JSON.stringify(baseline))
snapshot.prevId = baseline.id
snapshot.id = createHash('sha256').update(name).digest('hex').slice(0, 32).replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, '$1-$2-$3-$4-$5')
writeFileSync(path.join(directory, `${name}.ts`), source)
writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(snapshot, null, 2) + '\n')
console.log(`${name}: data-only backfill for categories without a version row`)
