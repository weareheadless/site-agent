import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'
import { sql } from '@payloadcms/db-d1-sqlite'

/**
 * Page sections gain a layout and art-direction parameters.
 *
 * The columns are nullable on purpose. An existing page section has no layout
 * until it opts in, and the renderer keeps its generic content treatment in
 * that case, so no existing site changes appearance.
 */
export async function up({ db }: MigrateUpArgs): Promise<void> {
  await db.run(sql.raw('ALTER TABLE `pages_sections` ADD COLUMN `layout` text;'))
  await db.run(sql.raw('ALTER TABLE `pages_sections` ADD COLUMN `direction_align` text;'))
  await db.run(sql.raw('ALTER TABLE `pages_sections` ADD COLUMN `direction_rules` integer;'))
  await db.run(sql.raw('ALTER TABLE `pages_sections` ADD COLUMN `direction_treatment` text;'))
  await db.run(sql.raw('ALTER TABLE `pages_sections` ADD COLUMN `direction_scale` text;'))
  await db.run(sql.raw('ALTER TABLE `_pages_v_version_sections` ADD COLUMN `layout` text;'))
  await db.run(sql.raw('ALTER TABLE `_pages_v_version_sections` ADD COLUMN `direction_align` text;'))
  await db.run(sql.raw('ALTER TABLE `_pages_v_version_sections` ADD COLUMN `direction_rules` integer;'))
  await db.run(sql.raw('ALTER TABLE `_pages_v_version_sections` ADD COLUMN `direction_treatment` text;'))
  await db.run(sql.raw('ALTER TABLE `_pages_v_version_sections` ADD COLUMN `direction_scale` text;'))
}

export async function down({ db }: MigrateDownArgs): Promise<void> {
  const tables = ['pages_sections', '_pages_v_version_sections']
  const columns = ['layout', 'direction_align', 'direction_rules', 'direction_treatment', 'direction_scale']
  for (const table of tables) {
    for (const column of columns) {
      await db.run(sql.raw(`ALTER TABLE \`${table}\` DROP COLUMN \`${column}\`;`))
    }
  }
}
