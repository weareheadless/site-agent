import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'
import { sql } from '@payloadcms/db-d1-sqlite'

// Generated offline by scripts/generate-category-criteria-migration.mjs.
// Additive and forward-only: collection criteria columns on product_categories.
export async function up({ db }: MigrateUpArgs): Promise<void> {
  await db.run(sql.raw("ALTER TABLE `product_categories` ADD COLUMN `criteria_city` text;"))
  await db.run(sql.raw("ALTER TABLE `product_categories` ADD COLUMN `criteria_region` text;"))
  await db.run(sql.raw("ALTER TABLE `product_categories` ADD COLUMN `criteria_availability` text;"))
  await db.run(sql.raw("ALTER TABLE `product_categories` ADD COLUMN `criteria_price_min_minor` numeric;"))
  await db.run(sql.raw("ALTER TABLE `product_categories` ADD COLUMN `criteria_price_max_minor` numeric;"))
}

export async function down(_args: MigrateDownArgs): Promise<void> {
  // Payload tenant releases are forward-only; preserve records.
}
