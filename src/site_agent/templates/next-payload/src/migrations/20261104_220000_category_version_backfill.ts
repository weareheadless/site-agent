import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'
import { sql } from '@payloadcms/db-d1-sqlite'

// Generated offline by scripts/generate-category-version-backfill-migration.mjs.
// Forward-only and idempotent: it only fills version rows that are missing.
export async function up({ db }: MigrateUpArgs): Promise<void> {
  const missing = await db.all(sql.raw(
    'SELECT p.id FROM product_categories p WHERE NOT EXISTS (SELECT 1 FROM _product_categories_v v WHERE v.parent_id = p.id) ORDER BY p.id',
  )) as Array<{ id: number }>
  for (const row of missing) {
    const parent = Number(row.id)
    if (!Number.isSafeInteger(parent) || parent < 1) throw new Error('A category row has no safe integer identity.')
    await db.run(sql.raw(`INSERT INTO _product_categories_v (
  parent_id, version_source_id, version_source_url, version_featured_image_id, version_canonical_url, version_criteria_city, version_criteria_region, version_criteria_availability, version_criteria_price_min_minor, version_criteria_price_max_minor, version_published, version_updated_at, version_created_at, version__status, latest, created_at, updated_at
) SELECT id, source_id, source_url, featured_image_id, canonical_url, criteria_city, criteria_region, criteria_availability, criteria_price_min_minor, criteria_price_max_minor, published, updated_at, created_at, 'published', 1, created_at, updated_at
FROM product_categories WHERE id = ${parent}`))
    await db.run(sql.raw(`INSERT INTO _product_categories_v_locales (
  version_title, version_slug, version_description, version_seo_title, version_seo_description, version_seo_image_id, _locale, _parent_id
) SELECT title, slug, description, seo_title, seo_description, seo_image_id, _locale,
  (SELECT MAX(id) FROM _product_categories_v WHERE parent_id = ${parent})
FROM product_categories_locales WHERE _parent_id = ${parent}`))
  }
}

export async function down(_args: MigrateDownArgs): Promise<void> {
  throw new Error('The category version backfill is forward-only. Restore the reviewed D1 backup to roll back.')
}
