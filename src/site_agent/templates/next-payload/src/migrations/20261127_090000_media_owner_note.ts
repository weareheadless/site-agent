import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'
import { sql } from '@payloadcms/db-d1-sqlite'

// Adds the owner's own note to a media document.
//
// Additive and non-destructive: one nullable column, no data moved. `media` is
// not a versioned collection, so there is no companion `_media_v` table to
// extend. The note is unlocalized on purpose — it is internal context about the
// file, not published copy, so it is one value for every enabled language.
export async function up({ db }: MigrateUpArgs): Promise<void> {
  await db.run(sql.raw("ALTER TABLE `media` ADD COLUMN `owner_note` text;"))
}

export async function down({ db }: MigrateDownArgs): Promise<void> {
  await db.run(sql.raw("ALTER TABLE `media` DROP COLUMN `owner_note`;"))
}
