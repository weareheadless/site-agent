import { MigrateDownArgs, MigrateUpArgs, sql } from '@payloadcms/db-d1-sqlite'

export async function up({ db }: MigrateUpArgs): Promise<void> {
  await db.run(sql`CREATE TABLE \`helloada_growth_candidates\` (
    \`package_hash\` text PRIMARY KEY NOT NULL,
    \`tenant_id\` text NOT NULL,
    \`initiative_id\` text NOT NULL,
    \`collection_name\` text NOT NULL,
    \`document_id\` text NOT NULL,
    \`base_hash\` text NOT NULL,
    \`candidate_hash\` text NOT NULL,
    \`package_json\` text NOT NULL,
    \`state\` text NOT NULL,
    \`result_json\` text,
    \`created_at\` text NOT NULL,
    \`updated_at\` text NOT NULL
  );`)
  await db.run(sql`CREATE TABLE \`helloada_growth_operations\` (
    \`operation_key\` text PRIMARY KEY NOT NULL,
    \`document_key\` text NOT NULL,
    \`tenant_id\` text NOT NULL,
    \`package_hash\` text NOT NULL,
    \`state\` text NOT NULL,
    \`result_json\` text,
    \`created_at\` text NOT NULL,
    \`updated_at\` text NOT NULL
  );`)
  await db.run(sql`CREATE UNIQUE INDEX \`helloada_growth_writing_document\`
    ON \`helloada_growth_operations\` (\`document_key\`)
    WHERE \`state\` = 'writing';`)
}

export async function down({ db }: MigrateDownArgs): Promise<void> {
  await db.run(sql`DROP INDEX \`helloada_growth_writing_document\`;`)
  await db.run(sql`DROP TABLE \`helloada_growth_operations\`;`)
  await db.run(sql`DROP TABLE \`helloada_growth_candidates\`;`)
}
