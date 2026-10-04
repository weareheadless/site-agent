import { MigrateUpArgs, MigrateDownArgs, sql } from '@payloadcms/db-d1-sqlite'

export async function up({ db }: MigrateUpArgs): Promise<void> {
  await db.run(sql`CREATE TABLE \`users_sessions\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`created_at\` text,
  	\`expires_at\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`users\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`users_sessions_order_idx\` ON \`users_sessions\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`users_sessions_parent_id_idx\` ON \`users_sessions\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`users\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`email\` text NOT NULL,
  	\`reset_password_token\` text,
  	\`reset_password_expiration\` text,
  	\`salt\` text,
  	\`hash\` text,
  	\`login_attempts\` numeric DEFAULT 0,
  	\`lock_until\` text
  );
  `)
  await db.run(sql`CREATE INDEX \`users_updated_at_idx\` ON \`users\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`users_created_at_idx\` ON \`users\` (\`created_at\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`users_email_idx\` ON \`users\` (\`email\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_heading_order_idx\` ON \`pages_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_heading_parent_id_idx\` ON \`pages_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_heading_path_idx\` ON \`pages_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_blocks_hello_ada_heading_locales_locale_parent_id_uniq\` ON \`pages_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_paragraph_order_idx\` ON \`pages_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_paragraph_parent_id_idx\` ON \`pages_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_paragraph_path_idx\` ON \`pages_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_blocks_hello_ada_paragraph_locales_locale_parent_id_un\` ON \`pages_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_rich_text_order_idx\` ON \`pages_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_rich_text_parent_id_idx\` ON \`pages_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_rich_text_path_idx\` ON \`pages_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_blocks_hello_ada_rich_text_locales_locale_parent_id_un\` ON \`pages_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_image_order_idx\` ON \`pages_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_image_parent_id_idx\` ON \`pages_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_image_path_idx\` ON \`pages_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_image_image_idx\` ON \`pages_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_blocks_hello_ada_image_locales_locale_parent_id_unique\` ON \`pages_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_link_order_idx\` ON \`pages_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_link_parent_id_idx\` ON \`pages_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_link_path_idx\` ON \`pages_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_blocks_hello_ada_link_locales_locale_parent_id_unique\` ON \`pages_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_content_list_items_order_idx\` ON \`pages_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`pages_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_content_list_items_image_idx\` ON \`pages_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_blocks_hello_ada_content_list_items_locales_locale_par\` ON \`pages_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_content_list_order_idx\` ON \`pages_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_content_list_parent_id_idx\` ON \`pages_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_content_list_path_idx\` ON \`pages_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`pages_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_sections_order_idx\` ON \`pages_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_sections_parent_id_idx\` ON \`pages_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_sections_locales_locale_parent_id_unique\` ON \`pages_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`pages\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`source_id\` text,
  	\`slug\` text,
  	\`canonical_url\` text,
  	\`published\` integer DEFAULT true,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`_status\` text DEFAULT 'draft'
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_slug_idx\` ON \`pages\` (\`slug\`);`)
  await db.run(sql`CREATE INDEX \`pages_updated_at_idx\` ON \`pages\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`pages_created_at_idx\` ON \`pages\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`pages__status_idx\` ON \`pages\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`pages_locales\` (
  	\`title\` text,
  	\`summary\` text,
  	\`body\` text,
  	\`featured_image_id\` integer,
  	\`seo_title\` text,
  	\`seo_description\` text,
  	\`seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_featured_image_idx\` ON \`pages_locales\` (\`featured_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE INDEX \`pages_seo_seo_image_idx\` ON \`pages_locales\` (\`seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`pages_locales_locale_parent_id_unique\` ON \`pages_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_heading_order_idx\` ON \`_pages_v_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_heading_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_heading_path_idx\` ON \`_pages_v_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_blocks_hello_ada_heading_locales_locale_parent_id_u\` ON \`_pages_v_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_paragraph_order_idx\` ON \`_pages_v_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_paragraph_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_paragraph_path_idx\` ON \`_pages_v_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_blocks_hello_ada_paragraph_locales_locale_parent_id\` ON \`_pages_v_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_rich_text_order_idx\` ON \`_pages_v_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_rich_text_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_rich_text_path_idx\` ON \`_pages_v_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_blocks_hello_ada_rich_text_locales_locale_parent_id\` ON \`_pages_v_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_image_order_idx\` ON \`_pages_v_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_image_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_image_path_idx\` ON \`_pages_v_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_image_image_idx\` ON \`_pages_v_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_blocks_hello_ada_image_locales_locale_parent_id_uni\` ON \`_pages_v_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_link_order_idx\` ON \`_pages_v_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_link_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_link_path_idx\` ON \`_pages_v_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_blocks_hello_ada_link_locales_locale_parent_id_uniq\` ON \`_pages_v_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_content_list_items_order_idx\` ON \`_pages_v_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_content_list_items_image_idx\` ON \`_pages_v_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_blocks_hello_ada_content_list_items_locales_locale_\` ON \`_pages_v_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_content_list_order_idx\` ON \`_pages_v_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_content_list_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_content_list_path_idx\` ON \`_pages_v_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_version_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_version_sections_order_idx\` ON \`_pages_v_version_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_version_sections_parent_id_idx\` ON \`_pages_v_version_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_version_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v_version_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_version_sections_locales_locale_parent_id_unique\` ON \`_pages_v_version_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`parent_id\` integer,
  	\`version_source_id\` text,
  	\`version_slug\` text,
  	\`version_canonical_url\` text,
  	\`version_published\` integer DEFAULT true,
  	\`version_updated_at\` text,
  	\`version_created_at\` text,
  	\`version__status\` text DEFAULT 'draft',
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`snapshot\` integer,
  	\`published_locale\` text,
  	\`latest\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_parent_idx\` ON \`_pages_v\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_version_version_slug_idx\` ON \`_pages_v\` (\`version_slug\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_version_version_updated_at_idx\` ON \`_pages_v\` (\`version_updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_version_version_created_at_idx\` ON \`_pages_v\` (\`version_created_at\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_version_version__status_idx\` ON \`_pages_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_created_at_idx\` ON \`_pages_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_updated_at_idx\` ON \`_pages_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_snapshot_idx\` ON \`_pages_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_published_locale_idx\` ON \`_pages_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_latest_idx\` ON \`_pages_v\` (\`latest\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_locales\` (
  	\`version_title\` text,
  	\`version_summary\` text,
  	\`version_body\` text,
  	\`version_featured_image_id\` integer,
  	\`version_seo_title\` text,
  	\`version_seo_description\` text,
  	\`version_seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`version_featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_version_version_featured_image_idx\` ON \`_pages_v_locales\` (\`version_featured_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_version_seo_version_seo_image_idx\` ON \`_pages_v_locales\` (\`version_seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_pages_v_locales_locale_parent_id_unique\` ON \`_pages_v_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_heading_order_idx\` ON \`posts_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_heading_parent_id_idx\` ON \`posts_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_heading_path_idx\` ON \`posts_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_blocks_hello_ada_heading_locales_locale_parent_id_uniq\` ON \`posts_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_paragraph_order_idx\` ON \`posts_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_paragraph_parent_id_idx\` ON \`posts_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_paragraph_path_idx\` ON \`posts_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_blocks_hello_ada_paragraph_locales_locale_parent_id_un\` ON \`posts_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_rich_text_order_idx\` ON \`posts_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_rich_text_parent_id_idx\` ON \`posts_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_rich_text_path_idx\` ON \`posts_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_blocks_hello_ada_rich_text_locales_locale_parent_id_un\` ON \`posts_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_image_order_idx\` ON \`posts_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_image_parent_id_idx\` ON \`posts_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_image_path_idx\` ON \`posts_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_image_image_idx\` ON \`posts_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_blocks_hello_ada_image_locales_locale_parent_id_unique\` ON \`posts_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_link_order_idx\` ON \`posts_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_link_parent_id_idx\` ON \`posts_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_link_path_idx\` ON \`posts_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_blocks_hello_ada_link_locales_locale_parent_id_unique\` ON \`posts_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_content_list_items_order_idx\` ON \`posts_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`posts_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_content_list_items_image_idx\` ON \`posts_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_blocks_hello_ada_content_list_items_locales_locale_par\` ON \`posts_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_content_list_order_idx\` ON \`posts_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_content_list_parent_id_idx\` ON \`posts_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_content_list_path_idx\` ON \`posts_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`posts_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_sections_order_idx\` ON \`posts_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_sections_parent_id_idx\` ON \`posts_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_sections_locales_locale_parent_id_unique\` ON \`posts_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`source_id\` text,
  	\`slug\` text,
  	\`published_at\` text,
  	\`modified_at\` text,
  	\`category_id\` integer,
  	\`canonical_url\` text,
  	\`published\` integer DEFAULT true,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`_status\` text DEFAULT 'draft',
  	FOREIGN KEY (\`category_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_slug_idx\` ON \`posts\` (\`slug\`);`)
  await db.run(sql`CREATE INDEX \`posts_category_idx\` ON \`posts\` (\`category_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_updated_at_idx\` ON \`posts\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`posts_created_at_idx\` ON \`posts\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`posts__status_idx\` ON \`posts\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`posts_locales\` (
  	\`title\` text,
  	\`summary\` text,
  	\`body\` text,
  	\`featured_image_id\` integer,
  	\`author\` text,
  	\`seo_title\` text,
  	\`seo_description\` text,
  	\`seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_featured_image_idx\` ON \`posts_locales\` (\`featured_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE INDEX \`posts_seo_seo_image_idx\` ON \`posts_locales\` (\`seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`posts_locales_locale_parent_id_unique\` ON \`posts_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_rels\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`order\` integer,
  	\`parent_id\` integer NOT NULL,
  	\`path\` text NOT NULL,
  	\`media_id\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`media_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_rels_order_idx\` ON \`posts_rels\` (\`order\`);`)
  await db.run(sql`CREATE INDEX \`posts_rels_parent_idx\` ON \`posts_rels\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_rels_path_idx\` ON \`posts_rels\` (\`path\`);`)
  await db.run(sql`CREATE INDEX \`posts_rels_media_id_idx\` ON \`posts_rels\` (\`media_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_heading_order_idx\` ON \`_posts_v_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_heading_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_heading_path_idx\` ON \`_posts_v_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_blocks_hello_ada_heading_locales_locale_parent_id_u\` ON \`_posts_v_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_paragraph_order_idx\` ON \`_posts_v_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_paragraph_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_paragraph_path_idx\` ON \`_posts_v_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_blocks_hello_ada_paragraph_locales_locale_parent_id\` ON \`_posts_v_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_rich_text_order_idx\` ON \`_posts_v_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_rich_text_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_rich_text_path_idx\` ON \`_posts_v_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_blocks_hello_ada_rich_text_locales_locale_parent_id\` ON \`_posts_v_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_image_order_idx\` ON \`_posts_v_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_image_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_image_path_idx\` ON \`_posts_v_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_image_image_idx\` ON \`_posts_v_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_blocks_hello_ada_image_locales_locale_parent_id_uni\` ON \`_posts_v_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_link_order_idx\` ON \`_posts_v_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_link_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_link_path_idx\` ON \`_posts_v_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_blocks_hello_ada_link_locales_locale_parent_id_uniq\` ON \`_posts_v_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_content_list_items_order_idx\` ON \`_posts_v_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_content_list_items_image_idx\` ON \`_posts_v_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_blocks_hello_ada_content_list_items_locales_locale_\` ON \`_posts_v_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_content_list_order_idx\` ON \`_posts_v_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_content_list_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_content_list_path_idx\` ON \`_posts_v_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_version_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_version_sections_order_idx\` ON \`_posts_v_version_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_sections_parent_id_idx\` ON \`_posts_v_version_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_version_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v_version_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_version_sections_locales_locale_parent_id_unique\` ON \`_posts_v_version_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`parent_id\` integer,
  	\`version_source_id\` text,
  	\`version_slug\` text,
  	\`version_published_at\` text,
  	\`version_modified_at\` text,
  	\`version_category_id\` integer,
  	\`version_canonical_url\` text,
  	\`version_published\` integer DEFAULT true,
  	\`version_updated_at\` text,
  	\`version_created_at\` text,
  	\`version__status\` text DEFAULT 'draft',
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`snapshot\` integer,
  	\`published_locale\` text,
  	\`latest\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_category_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_parent_idx\` ON \`_posts_v\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_version_slug_idx\` ON \`_posts_v\` (\`version_slug\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_version_category_idx\` ON \`_posts_v\` (\`version_category_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_version_updated_at_idx\` ON \`_posts_v\` (\`version_updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_version_created_at_idx\` ON \`_posts_v\` (\`version_created_at\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_version__status_idx\` ON \`_posts_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_created_at_idx\` ON \`_posts_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_updated_at_idx\` ON \`_posts_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_snapshot_idx\` ON \`_posts_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_published_locale_idx\` ON \`_posts_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_latest_idx\` ON \`_posts_v\` (\`latest\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_locales\` (
  	\`version_title\` text,
  	\`version_summary\` text,
  	\`version_body\` text,
  	\`version_featured_image_id\` integer,
  	\`version_author\` text,
  	\`version_seo_title\` text,
  	\`version_seo_description\` text,
  	\`version_seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`version_featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_version_version_featured_image_idx\` ON \`_posts_v_locales\` (\`version_featured_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_version_seo_version_seo_image_idx\` ON \`_posts_v_locales\` (\`version_seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_posts_v_locales_locale_parent_id_unique\` ON \`_posts_v_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_rels\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`order\` integer,
  	\`parent_id\` integer NOT NULL,
  	\`path\` text NOT NULL,
  	\`media_id\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`media_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_rels_order_idx\` ON \`_posts_v_rels\` (\`order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_rels_parent_idx\` ON \`_posts_v_rels\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_rels_path_idx\` ON \`_posts_v_rels\` (\`path\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_rels_media_id_idx\` ON \`_posts_v_rels\` (\`media_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_heading_order_idx\` ON \`post_categories_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_heading_parent_id_idx\` ON \`post_categories_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_heading_path_idx\` ON \`post_categories_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_blocks_hello_ada_heading_locales_locale_pare\` ON \`post_categories_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_paragraph_order_idx\` ON \`post_categories_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_paragraph_parent_id_idx\` ON \`post_categories_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_paragraph_path_idx\` ON \`post_categories_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_blocks_hello_ada_paragraph_locales_locale_pa\` ON \`post_categories_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_rich_text_order_idx\` ON \`post_categories_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_rich_text_parent_id_idx\` ON \`post_categories_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_rich_text_path_idx\` ON \`post_categories_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_blocks_hello_ada_rich_text_locales_locale_pa\` ON \`post_categories_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_image_order_idx\` ON \`post_categories_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_image_parent_id_idx\` ON \`post_categories_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_image_path_idx\` ON \`post_categories_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_image_image_idx\` ON \`post_categories_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_blocks_hello_ada_image_locales_locale_parent\` ON \`post_categories_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_link_order_idx\` ON \`post_categories_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_link_parent_id_idx\` ON \`post_categories_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_link_path_idx\` ON \`post_categories_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_blocks_hello_ada_link_locales_locale_parent_\` ON \`post_categories_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_content_list_items_order_idx\` ON \`post_categories_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`post_categories_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_content_list_items_imag_idx\` ON \`post_categories_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_blocks_hello_ada_content_list_items_locales_\` ON \`post_categories_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_content_list_order_idx\` ON \`post_categories_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_content_list_parent_id_idx\` ON \`post_categories_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_content_list_path_idx\` ON \`post_categories_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_sections_order_idx\` ON \`post_categories_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_sections_parent_id_idx\` ON \`post_categories_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_sections_locales_locale_parent_id_unique\` ON \`post_categories_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`source_id\` text,
  	\`slug\` text,
  	\`source_url\` text,
  	\`canonical_url\` text,
  	\`featured_image_id\` integer,
  	\`published\` integer DEFAULT true,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`_status\` text DEFAULT 'draft',
  	FOREIGN KEY (\`featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_source_id_idx\` ON \`post_categories\` (\`source_id\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_slug_idx\` ON \`post_categories\` (\`slug\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_featured_image_idx\` ON \`post_categories\` (\`featured_image_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_updated_at_idx\` ON \`post_categories\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_created_at_idx\` ON \`post_categories\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`post_categories__status_idx\` ON \`post_categories\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_locales\` (
  	\`title\` text,
  	\`summary\` text,
  	\`seo_title\` text,
  	\`seo_description\` text,
  	\`seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_seo_seo_image_idx\` ON \`post_categories_locales\` (\`seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`post_categories_locales_locale_parent_id_unique\` ON \`post_categories_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_heading_order_idx\` ON \`_post_categories_v_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_heading_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_heading_path_idx\` ON \`_post_categories_v_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_blocks_hello_ada_heading_locales_locale_p\` ON \`_post_categories_v_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_paragraph_order_idx\` ON \`_post_categories_v_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_paragraph_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_paragraph_path_idx\` ON \`_post_categories_v_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_blocks_hello_ada_paragraph_locales_locale\` ON \`_post_categories_v_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_rich_text_order_idx\` ON \`_post_categories_v_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_rich_text_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_rich_text_path_idx\` ON \`_post_categories_v_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_blocks_hello_ada_rich_text_locales_locale\` ON \`_post_categories_v_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_image_order_idx\` ON \`_post_categories_v_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_image_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_image_path_idx\` ON \`_post_categories_v_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_image_image_idx\` ON \`_post_categories_v_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_blocks_hello_ada_image_locales_locale_par\` ON \`_post_categories_v_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_link_order_idx\` ON \`_post_categories_v_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_link_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_link_path_idx\` ON \`_post_categories_v_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_blocks_hello_ada_link_locales_locale_pare\` ON \`_post_categories_v_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_content_list_items_order_idx\` ON \`_post_categories_v_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_content_list_items_i_idx\` ON \`_post_categories_v_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_blocks_hello_ada_content_list_items_local\` ON \`_post_categories_v_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_content_list_order_idx\` ON \`_post_categories_v_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_content_list_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_content_list_path_idx\` ON \`_post_categories_v_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_version_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_sections_order_idx\` ON \`_post_categories_v_version_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_sections_parent_id_idx\` ON \`_post_categories_v_version_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_version_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v_version_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_version_sections_locales_locale_parent_id\` ON \`_post_categories_v_version_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`parent_id\` integer,
  	\`version_source_id\` text,
  	\`version_slug\` text,
  	\`version_source_url\` text,
  	\`version_canonical_url\` text,
  	\`version_featured_image_id\` integer,
  	\`version_published\` integer DEFAULT true,
  	\`version_updated_at\` text,
  	\`version_created_at\` text,
  	\`version__status\` text DEFAULT 'draft',
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`snapshot\` integer,
  	\`published_locale\` text,
  	\`latest\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_parent_idx\` ON \`_post_categories_v\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_version_source_id_idx\` ON \`_post_categories_v\` (\`version_source_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_version_slug_idx\` ON \`_post_categories_v\` (\`version_slug\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_version_featured_image_idx\` ON \`_post_categories_v\` (\`version_featured_image_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_version_updated_at_idx\` ON \`_post_categories_v\` (\`version_updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_version_created_at_idx\` ON \`_post_categories_v\` (\`version_created_at\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_version__status_idx\` ON \`_post_categories_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_created_at_idx\` ON \`_post_categories_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_updated_at_idx\` ON \`_post_categories_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_snapshot_idx\` ON \`_post_categories_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_published_locale_idx\` ON \`_post_categories_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_latest_idx\` ON \`_post_categories_v\` (\`latest\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_locales\` (
  	\`version_title\` text,
  	\`version_summary\` text,
  	\`version_seo_title\` text,
  	\`version_seo_description\` text,
  	\`version_seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`version_seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_version_seo_version_seo_image_idx\` ON \`_post_categories_v_locales\` (\`version_seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_post_categories_v_locales_locale_parent_id_unique\` ON \`_post_categories_v_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_heading_order_idx\` ON \`products_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_heading_parent_id_idx\` ON \`products_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_heading_path_idx\` ON \`products_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_blocks_hello_ada_heading_locales_locale_parent_id_u\` ON \`products_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_paragraph_order_idx\` ON \`products_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_paragraph_parent_id_idx\` ON \`products_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_paragraph_path_idx\` ON \`products_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_blocks_hello_ada_paragraph_locales_locale_parent_id\` ON \`products_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_rich_text_order_idx\` ON \`products_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_rich_text_parent_id_idx\` ON \`products_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_rich_text_path_idx\` ON \`products_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_blocks_hello_ada_rich_text_locales_locale_parent_id\` ON \`products_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_image_order_idx\` ON \`products_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_image_parent_id_idx\` ON \`products_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_image_path_idx\` ON \`products_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_image_image_idx\` ON \`products_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_blocks_hello_ada_image_locales_locale_parent_id_uni\` ON \`products_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_link_order_idx\` ON \`products_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_link_parent_id_idx\` ON \`products_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_link_path_idx\` ON \`products_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_blocks_hello_ada_link_locales_locale_parent_id_uniq\` ON \`products_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_content_list_items_order_idx\` ON \`products_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`products_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_content_list_items_image_idx\` ON \`products_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`products_blocks_hello_ada_content_list_items_locales_locale_\` ON \`products_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_content_list_order_idx\` ON \`products_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_content_list_parent_id_idx\` ON \`products_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_content_list_path_idx\` ON \`products_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`products_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_sections_order_idx\` ON \`products_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_sections_parent_id_idx\` ON \`products_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_sections_locales_locale_parent_id_unique\` ON \`products_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`source_id\` text,
  	\`slug\` text,
  	\`price\` numeric,
  	\`currency\` text,
  	\`category_id\` integer,
  	\`canonical_url\` text,
  	\`published\` integer DEFAULT false,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`_status\` text DEFAULT 'draft',
  	FOREIGN KEY (\`category_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`products_slug_idx\` ON \`products\` (\`slug\`);`)
  await db.run(sql`CREATE INDEX \`products_category_idx\` ON \`products\` (\`category_id\`);`)
  await db.run(sql`CREATE INDEX \`products_updated_at_idx\` ON \`products\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`products_created_at_idx\` ON \`products\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`products__status_idx\` ON \`products\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`products_locales\` (
  	\`title\` text,
  	\`summary\` text,
  	\`body\` text,
  	\`featured_image_id\` integer,
  	\`availability\` text,
  	\`seo_title\` text,
  	\`seo_description\` text,
  	\`seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_featured_image_idx\` ON \`products_locales\` (\`featured_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE INDEX \`products_seo_seo_image_idx\` ON \`products_locales\` (\`seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`products_locales_locale_parent_id_unique\` ON \`products_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`products_rels\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`order\` integer,
  	\`parent_id\` integer NOT NULL,
  	\`path\` text NOT NULL,
  	\`locale\` text,
  	\`media_id\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`media_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_rels_order_idx\` ON \`products_rels\` (\`order\`);`)
  await db.run(sql`CREATE INDEX \`products_rels_parent_idx\` ON \`products_rels\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_rels_path_idx\` ON \`products_rels\` (\`path\`);`)
  await db.run(sql`CREATE INDEX \`products_rels_locale_idx\` ON \`products_rels\` (\`locale\`);`)
  await db.run(sql`CREATE INDEX \`products_rels_media_id_idx\` ON \`products_rels\` (\`media_id\`,\`locale\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`level\` text DEFAULT 'h2',
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_heading_order_idx\` ON \`_products_v_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_heading_parent_id_idx\` ON \`_products_v_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_heading_path_idx\` ON \`_products_v_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_heading_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_blocks_hello_ada_heading_locales_locale_parent_i\` ON \`_products_v_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_paragraph_order_idx\` ON \`_products_v_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_paragraph_parent_id_idx\` ON \`_products_v_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_paragraph_path_idx\` ON \`_products_v_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_blocks_hello_ada_paragraph_locales_locale_parent\` ON \`_products_v_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_rich_text_order_idx\` ON \`_products_v_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_rich_text_parent_id_idx\` ON \`_products_v_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_rich_text_path_idx\` ON \`_products_v_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_blocks_hello_ada_rich_text_locales_locale_parent\` ON \`_products_v_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`image_id\` integer,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_image_order_idx\` ON \`_products_v_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_image_parent_id_idx\` ON \`_products_v_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_image_path_idx\` ON \`_products_v_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_image_image_idx\` ON \`_products_v_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_blocks_hello_ada_image_locales_locale_parent_id_\` ON \`_products_v_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_link_order_idx\` ON \`_products_v_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_link_parent_id_idx\` ON \`_products_v_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_link_path_idx\` ON \`_products_v_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_link_locales\` (
  	\`text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_blocks_hello_ada_link_locales_locale_parent_id_u\` ON \`_products_v_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_content_list_items_order_idx\` ON \`_products_v_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`_products_v_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_content_list_items_image_idx\` ON \`_products_v_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_blocks_hello_ada_content_list_items_locales_loca\` ON \`_products_v_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`label\` text,
  	\`_uuid\` text,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_content_list_order_idx\` ON \`_products_v_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_content_list_parent_id_idx\` ON \`_products_v_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_content_list_path_idx\` ON \`_products_v_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_version_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_version_sections_order_idx\` ON \`_products_v_version_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_sections_parent_id_idx\` ON \`_products_v_version_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_version_sections_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v_version_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_version_sections_locales_locale_parent_id_unique\` ON \`_products_v_version_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`parent_id\` integer,
  	\`version_source_id\` text,
  	\`version_slug\` text,
  	\`version_price\` numeric,
  	\`version_currency\` text,
  	\`version_category_id\` integer,
  	\`version_canonical_url\` text,
  	\`version_published\` integer DEFAULT false,
  	\`version_updated_at\` text,
  	\`version_created_at\` text,
  	\`version__status\` text DEFAULT 'draft',
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`snapshot\` integer,
  	\`published_locale\` text,
  	\`latest\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_category_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_parent_idx\` ON \`_products_v\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_version_slug_idx\` ON \`_products_v\` (\`version_slug\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_version_category_idx\` ON \`_products_v\` (\`version_category_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_version_updated_at_idx\` ON \`_products_v\` (\`version_updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_version_created_at_idx\` ON \`_products_v\` (\`version_created_at\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_version__status_idx\` ON \`_products_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_created_at_idx\` ON \`_products_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_updated_at_idx\` ON \`_products_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_snapshot_idx\` ON \`_products_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_published_locale_idx\` ON \`_products_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_latest_idx\` ON \`_products_v\` (\`latest\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_locales\` (
  	\`version_title\` text,
  	\`version_summary\` text,
  	\`version_body\` text,
  	\`version_featured_image_id\` integer,
  	\`version_availability\` text,
  	\`version_seo_title\` text,
  	\`version_seo_description\` text,
  	\`version_seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`version_featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_version_version_featured_image_idx\` ON \`_products_v_locales\` (\`version_featured_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_version_seo_version_seo_image_idx\` ON \`_products_v_locales\` (\`version_seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`_products_v_locales_locale_parent_id_unique\` ON \`_products_v_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_rels\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`order\` integer,
  	\`parent_id\` integer NOT NULL,
  	\`path\` text NOT NULL,
  	\`locale\` text,
  	\`media_id\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`media_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_rels_order_idx\` ON \`_products_v_rels\` (\`order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_rels_parent_idx\` ON \`_products_v_rels\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_rels_path_idx\` ON \`_products_v_rels\` (\`path\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_rels_locale_idx\` ON \`_products_v_rels\` (\`locale\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_rels_media_id_idx\` ON \`_products_v_rels\` (\`media_id\`,\`locale\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_heading\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`label\` text NOT NULL,
  	\`level\` text DEFAULT 'h2',
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_heading_order_idx\` ON \`product_categories_blocks_hello_ada_heading\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_heading_parent_id_idx\` ON \`product_categories_blocks_hello_ada_heading\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_heading_path_idx\` ON \`product_categories_blocks_hello_ada_heading\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_heading_locales\` (
  	\`text\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_heading\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_blocks_hello_ada_heading_locales_locale_p\` ON \`product_categories_blocks_hello_ada_heading_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_paragraph\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`label\` text NOT NULL,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_paragraph_order_idx\` ON \`product_categories_blocks_hello_ada_paragraph\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_paragraph_parent_id_idx\` ON \`product_categories_blocks_hello_ada_paragraph\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_paragraph_path_idx\` ON \`product_categories_blocks_hello_ada_paragraph\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_paragraph_locales\` (
  	\`text\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_paragraph\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_blocks_hello_ada_paragraph_locales_locale\` ON \`product_categories_blocks_hello_ada_paragraph_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_rich_text\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`label\` text NOT NULL,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_rich_text_order_idx\` ON \`product_categories_blocks_hello_ada_rich_text\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_rich_text_parent_id_idx\` ON \`product_categories_blocks_hello_ada_rich_text\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_rich_text_path_idx\` ON \`product_categories_blocks_hello_ada_rich_text\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_rich_text_locales\` (
  	\`value\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_rich_text\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_blocks_hello_ada_rich_text_locales_locale\` ON \`product_categories_blocks_hello_ada_rich_text_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_image\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`label\` text NOT NULL,
  	\`image_id\` integer NOT NULL,
  	\`block_name\` text,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_image_order_idx\` ON \`product_categories_blocks_hello_ada_image\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_image_parent_id_idx\` ON \`product_categories_blocks_hello_ada_image\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_image_path_idx\` ON \`product_categories_blocks_hello_ada_image\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_image_image_idx\` ON \`product_categories_blocks_hello_ada_image\` (\`image_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_image_locales\` (
  	\`alt\` text,
  	\`caption\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_image\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_blocks_hello_ada_image_locales_locale_par\` ON \`product_categories_blocks_hello_ada_image_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_link\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`label\` text NOT NULL,
  	\`external\` integer DEFAULT false,
  	\`new_tab\` integer DEFAULT false,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_link_order_idx\` ON \`product_categories_blocks_hello_ada_link\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_link_parent_id_idx\` ON \`product_categories_blocks_hello_ada_link\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_link_path_idx\` ON \`product_categories_blocks_hello_ada_link\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_link_locales\` (
  	\`text\` text NOT NULL,
  	\`href\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_link\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_blocks_hello_ada_link_locales_locale_pare\` ON \`product_categories_blocks_hello_ada_link_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_content_list_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_content_list\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_content_list_items_order_idx\` ON \`product_categories_blocks_hello_ada_content_list_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_content_list_items_parent_id_idx\` ON \`product_categories_blocks_hello_ada_content_list_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_content_list_items_locales\` (
  	\`title\` text,
  	\`body\` text,
  	\`image_id\` integer,
  	\`alt\` text,
  	\`link_text\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_blocks_hello_ada_content_list_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_content_list_items_i_idx\` ON \`product_categories_blocks_hello_ada_content_list_items_locales\` (\`image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_blocks_hello_ada_content_list_items_local\` ON \`product_categories_blocks_hello_ada_content_list_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_content_list\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`_path\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`label\` text NOT NULL,
  	\`block_name\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_content_list_order_idx\` ON \`product_categories_blocks_hello_ada_content_list\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_content_list_parent_id_idx\` ON \`product_categories_blocks_hello_ada_content_list\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_content_list_path_idx\` ON \`product_categories_blocks_hello_ada_content_list\` (\`_path\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_sections\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_sections_order_idx\` ON \`product_categories_sections\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_sections_parent_id_idx\` ON \`product_categories_sections\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_sections_locales\` (
  	\`label\` text NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories_sections\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_sections_locales_locale_parent_id_unique\` ON \`product_categories_sections_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`source_id\` text,
  	\`source_url\` text,
  	\`slug\` text NOT NULL,
  	\`featured_image_id\` integer,
  	\`canonical_url\` text,
  	\`published\` integer DEFAULT true,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	FOREIGN KEY (\`featured_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_slug_idx\` ON \`product_categories\` (\`slug\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_featured_image_idx\` ON \`product_categories\` (\`featured_image_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_updated_at_idx\` ON \`product_categories\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_created_at_idx\` ON \`product_categories\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_locales\` (
  	\`title\` text NOT NULL,
  	\`description\` text,
  	\`seo_title\` text,
  	\`seo_description\` text,
  	\`seo_image_id\` integer,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`seo_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_seo_seo_image_idx\` ON \`product_categories_locales\` (\`seo_image_id\`,\`_locale\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`product_categories_locales_locale_parent_id_unique\` ON \`product_categories_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`media_tags\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`value\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`media_tags_order_idx\` ON \`media_tags\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`media_tags_parent_id_idx\` ON \`media_tags\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`media_dominant_colors\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`value\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`media_dominant_colors_order_idx\` ON \`media_dominant_colors\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`media_dominant_colors_parent_id_idx\` ON \`media_dominant_colors\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`media_suggested_uses\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`value\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`media_suggested_uses_order_idx\` ON \`media_suggested_uses\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`media_suggested_uses_parent_id_idx\` ON \`media_suggested_uses\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`media_quality_notes\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`value\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`media_quality_notes_order_idx\` ON \`media_quality_notes\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`media_quality_notes_parent_id_idx\` ON \`media_quality_notes\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`media\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`source_id\` text,
  	\`source_url\` text,
  	\`original_url\` text,
  	\`ocr_text\` text,
  	\`proposed_knowledge\` text,
  	\`source_kind\` text,
  	\`analysis_status\` text DEFAULT 'pending',
  	\`analysis_provider\` text,
  	\`analysis_model\` text,
  	\`analysis_version\` numeric DEFAULT 1,
  	\`analysis_error\` text,
  	\`analysis_updated_at\` text,
  	\`analysis\` text,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`url\` text,
  	\`thumbnail_u_r_l\` text,
  	\`filename\` text,
  	\`mime_type\` text,
  	\`filesize\` numeric,
  	\`width\` numeric,
  	\`height\` numeric,
  	\`focal_x\` numeric,
  	\`focal_y\` numeric
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`media_source_id_idx\` ON \`media\` (\`source_id\`);`)
  await db.run(sql`CREATE INDEX \`media_updated_at_idx\` ON \`media\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`media_created_at_idx\` ON \`media\` (\`created_at\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`media_filename_idx\` ON \`media\` (\`filename\`);`)
  await db.run(sql`CREATE TABLE \`media_locales\` (
  	\`alt\` text,
  	\`description\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`media_locales_locale_parent_id_unique\` ON \`media_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`payload_kv\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text NOT NULL,
  	\`data\` text NOT NULL
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`payload_kv_key_idx\` ON \`payload_kv\` (\`key\`);`)
  await db.run(sql`CREATE TABLE \`payload_locked_documents\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`global_slug\` text,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL
  );
  `)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_global_slug_idx\` ON \`payload_locked_documents\` (\`global_slug\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_updated_at_idx\` ON \`payload_locked_documents\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_created_at_idx\` ON \`payload_locked_documents\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`payload_locked_documents_rels\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`order\` integer,
  	\`parent_id\` integer NOT NULL,
  	\`path\` text NOT NULL,
  	\`users_id\` integer,
  	\`pages_id\` integer,
  	\`posts_id\` integer,
  	\`post_categories_id\` integer,
  	\`products_id\` integer,
  	\`product_categories_id\` integer,
  	\`media_id\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`payload_locked_documents\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`users_id\`) REFERENCES \`users\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`pages_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`posts_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`post_categories_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`products_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`product_categories_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`media_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_order_idx\` ON \`payload_locked_documents_rels\` (\`order\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_parent_idx\` ON \`payload_locked_documents_rels\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_path_idx\` ON \`payload_locked_documents_rels\` (\`path\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_users_id_idx\` ON \`payload_locked_documents_rels\` (\`users_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_pages_id_idx\` ON \`payload_locked_documents_rels\` (\`pages_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_posts_id_idx\` ON \`payload_locked_documents_rels\` (\`posts_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_post_categories_id_idx\` ON \`payload_locked_documents_rels\` (\`post_categories_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_products_id_idx\` ON \`payload_locked_documents_rels\` (\`products_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_product_categories_id_idx\` ON \`payload_locked_documents_rels\` (\`product_categories_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_media_id_idx\` ON \`payload_locked_documents_rels\` (\`media_id\`);`)
  await db.run(sql`CREATE TABLE \`payload_preferences\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`value\` text,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL
  );
  `)
  await db.run(sql`CREATE INDEX \`payload_preferences_key_idx\` ON \`payload_preferences\` (\`key\`);`)
  await db.run(sql`CREATE INDEX \`payload_preferences_updated_at_idx\` ON \`payload_preferences\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`payload_preferences_created_at_idx\` ON \`payload_preferences\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`payload_preferences_rels\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`order\` integer,
  	\`parent_id\` integer NOT NULL,
  	\`path\` text NOT NULL,
  	\`users_id\` integer,
  	FOREIGN KEY (\`parent_id\`) REFERENCES \`payload_preferences\`(\`id\`) ON UPDATE no action ON DELETE cascade,
  	FOREIGN KEY (\`users_id\`) REFERENCES \`users\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`payload_preferences_rels_order_idx\` ON \`payload_preferences_rels\` (\`order\`);`)
  await db.run(sql`CREATE INDEX \`payload_preferences_rels_parent_idx\` ON \`payload_preferences_rels\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_preferences_rels_path_idx\` ON \`payload_preferences_rels\` (\`path\`);`)
  await db.run(sql`CREATE INDEX \`payload_preferences_rels_users_id_idx\` ON \`payload_preferences_rels\` (\`users_id\`);`)
  await db.run(sql`CREATE TABLE \`payload_migrations\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`name\` text,
  	\`batch\` numeric,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL
  );
  `)
  await db.run(sql`CREATE INDEX \`payload_migrations_updated_at_idx\` ON \`payload_migrations\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`payload_migrations_created_at_idx\` ON \`payload_migrations\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`site_settings\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`logo_id\` integer,
  	\`email\` text,
  	\`telephone\` text,
  	\`facebook_url\` text,
  	\`instagram_url\` text,
  	\`tiktok_url\` text,
  	\`default_social_image_id\` integer,
  	\`address_postal_code\` text,
  	\`_status\` text DEFAULT 'draft',
  	\`updated_at\` text,
  	\`created_at\` text,
  	FOREIGN KEY (\`logo_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`default_social_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`site_settings_logo_idx\` ON \`site_settings\` (\`logo_id\`);`)
  await db.run(sql`CREATE INDEX \`site_settings_default_social_image_idx\` ON \`site_settings\` (\`default_social_image_id\`);`)
  await db.run(sql`CREATE INDEX \`site_settings__status_idx\` ON \`site_settings\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`site_settings_locales\` (
  	\`site_name\` text,
  	\`description\` text,
  	\`tagline\` text,
  	\`promo_text\` text,
  	\`promo_href\` text,
  	\`promo_cta\` text,
  	\`footer_kicker\` text,
  	\`footer_title\` text,
  	\`footer_note\` text,
  	\`default_seo_title\` text,
  	\`default_seo_description\` text,
  	\`journal_title\` text,
  	\`journal_description\` text,
  	\`address_street_address\` text,
  	\`address_address_locality\` text,
  	\`address_address_region\` text,
  	\`address_address_country\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`site_settings\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`site_settings_locales_locale_parent_id_unique\` ON \`site_settings_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_site_settings_v\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`version_logo_id\` integer,
  	\`version_email\` text,
  	\`version_telephone\` text,
  	\`version_facebook_url\` text,
  	\`version_instagram_url\` text,
  	\`version_tiktok_url\` text,
  	\`version_default_social_image_id\` integer,
  	\`version_address_postal_code\` text,
  	\`version__status\` text DEFAULT 'draft',
  	\`version_updated_at\` text,
  	\`version_created_at\` text,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`snapshot\` integer,
  	\`published_locale\` text,
  	\`latest\` integer,
  	FOREIGN KEY (\`version_logo_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null,
  	FOREIGN KEY (\`version_default_social_image_id\`) REFERENCES \`media\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`_site_settings_v_version_version_logo_idx\` ON \`_site_settings_v\` (\`version_logo_id\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_version_version_default_social_image_idx\` ON \`_site_settings_v\` (\`version_default_social_image_id\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_version_version__status_idx\` ON \`_site_settings_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_created_at_idx\` ON \`_site_settings_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_updated_at_idx\` ON \`_site_settings_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_snapshot_idx\` ON \`_site_settings_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_published_locale_idx\` ON \`_site_settings_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_site_settings_v_latest_idx\` ON \`_site_settings_v\` (\`latest\`);`)
  await db.run(sql`CREATE TABLE \`_site_settings_v_locales\` (
  	\`version_site_name\` text,
  	\`version_description\` text,
  	\`version_tagline\` text,
  	\`version_promo_text\` text,
  	\`version_promo_href\` text,
  	\`version_promo_cta\` text,
  	\`version_footer_kicker\` text,
  	\`version_footer_title\` text,
  	\`version_footer_note\` text,
  	\`version_default_seo_title\` text,
  	\`version_default_seo_description\` text,
  	\`version_journal_title\` text,
  	\`version_journal_description\` text,
  	\`version_address_street_address\` text,
  	\`version_address_address_locality\` text,
  	\`version_address_address_region\` text,
  	\`version_address_address_country\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_site_settings_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_site_settings_v_locales_locale_parent_id_unique\` ON \`_site_settings_v_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	\`visible\` integer DEFAULT true,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation_items_order_idx\` ON \`navigation_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`navigation_items_parent_id_idx\` ON \`navigation_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_items_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`navigation_items_locales_locale_parent_id_unique\` ON \`navigation_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_footer\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	\`visible\` integer DEFAULT true,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation_footer_order_idx\` ON \`navigation_footer\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`navigation_footer_parent_id_idx\` ON \`navigation_footer\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_footer_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_footer\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`navigation_footer_locales_locale_parent_id_unique\` ON \`navigation_footer_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_groups_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation_groups_items_order_idx\` ON \`navigation_groups_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`navigation_groups_items_parent_id_idx\` ON \`navigation_groups_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_groups_items_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_groups_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`navigation_groups_items_locales_locale_parent_id_unique\` ON \`navigation_groups_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_groups\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation_groups_order_idx\` ON \`navigation_groups\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`navigation_groups_parent_id_idx\` ON \`navigation_groups\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_groups_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`navigation_groups_locales_locale_parent_id_unique\` ON \`navigation_groups_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_footer_groups_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_footer_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation_footer_groups_items_order_idx\` ON \`navigation_footer_groups_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`navigation_footer_groups_items_parent_id_idx\` ON \`navigation_footer_groups_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_footer_groups_items_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_footer_groups_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`navigation_footer_groups_items_locales_locale_parent_id_uniq\` ON \`navigation_footer_groups_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_footer_groups\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` text PRIMARY KEY NOT NULL,
  	\`key\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation_footer_groups_order_idx\` ON \`navigation_footer_groups\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`navigation_footer_groups_parent_id_idx\` ON \`navigation_footer_groups\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation_footer_groups_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` text NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`navigation_footer_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`navigation_footer_groups_locales_locale_parent_id_unique\` ON \`navigation_footer_groups_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`navigation\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_status\` text DEFAULT 'draft',
  	\`updated_at\` text,
  	\`created_at\` text
  );
  `)
  await db.run(sql`CREATE INDEX \`navigation__status_idx\` ON \`navigation\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	\`visible\` integer DEFAULT true,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_items_order_idx\` ON \`_navigation_v_version_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_items_parent_id_idx\` ON \`_navigation_v_version_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_items_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_navigation_v_version_items_locales_locale_parent_id_unique\` ON \`_navigation_v_version_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_footer\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	\`visible\` integer DEFAULT true,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_footer_order_idx\` ON \`_navigation_v_version_footer\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_footer_parent_id_idx\` ON \`_navigation_v_version_footer\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_footer_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_footer\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_navigation_v_version_footer_locales_locale_parent_id_unique\` ON \`_navigation_v_version_footer_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_groups_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_groups_items_order_idx\` ON \`_navigation_v_version_groups_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_groups_items_parent_id_idx\` ON \`_navigation_v_version_groups_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_groups_items_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_groups_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_navigation_v_version_groups_items_locales_locale_parent_id_\` ON \`_navigation_v_version_groups_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_groups\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_groups_order_idx\` ON \`_navigation_v_version_groups\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_groups_parent_id_idx\` ON \`_navigation_v_version_groups\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_groups_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_navigation_v_version_groups_locales_locale_parent_id_unique\` ON \`_navigation_v_version_groups_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_footer_groups_items\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`external\` integer DEFAULT false,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_footer_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_footer_groups_items_order_idx\` ON \`_navigation_v_version_footer_groups_items\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_footer_groups_items_parent_id_idx\` ON \`_navigation_v_version_footer_groups_items\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_footer_groups_items_locales\` (
  	\`label\` text,
  	\`href\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_footer_groups_items\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_navigation_v_version_footer_groups_items_locales_locale_par\` ON \`_navigation_v_version_footer_groups_items_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_footer_groups\` (
  	\`_order\` integer NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`key\` text,
  	\`_uuid\` text,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_footer_groups_order_idx\` ON \`_navigation_v_version_footer_groups\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_footer_groups_parent_id_idx\` ON \`_navigation_v_version_footer_groups\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v_version_footer_groups_locales\` (
  	\`label\` text,
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`_locale\` text NOT NULL,
  	\`_parent_id\` integer NOT NULL,
  	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_navigation_v_version_footer_groups\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_navigation_v_version_footer_groups_locales_locale_parent_id\` ON \`_navigation_v_version_footer_groups_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_navigation_v\` (
  	\`id\` integer PRIMARY KEY NOT NULL,
  	\`version__status\` text DEFAULT 'draft',
  	\`version_updated_at\` text,
  	\`version_created_at\` text,
  	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
  	\`snapshot\` integer,
  	\`published_locale\` text,
  	\`latest\` integer
  );
  `)
  await db.run(sql`CREATE INDEX \`_navigation_v_version_version__status_idx\` ON \`_navigation_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_created_at_idx\` ON \`_navigation_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_updated_at_idx\` ON \`_navigation_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_snapshot_idx\` ON \`_navigation_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_published_locale_idx\` ON \`_navigation_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_navigation_v_latest_idx\` ON \`_navigation_v\` (\`latest\`);`)
}

export async function down({ db }: MigrateDownArgs): Promise<void> {
  await db.run(sql`DROP TABLE \`users_sessions\`;`)
  await db.run(sql`DROP TABLE \`users\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`pages_sections\`;`)
  await db.run(sql`DROP TABLE \`pages_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`pages\`;`)
  await db.run(sql`DROP TABLE \`pages_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_version_sections\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_version_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`_pages_v\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`posts_sections\`;`)
  await db.run(sql`DROP TABLE \`posts_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`posts\`;`)
  await db.run(sql`DROP TABLE \`posts_locales\`;`)
  await db.run(sql`DROP TABLE \`posts_rels\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_version_sections\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_version_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_locales\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_rels\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`post_categories_sections\`;`)
  await db.run(sql`DROP TABLE \`post_categories_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`post_categories\`;`)
  await db.run(sql`DROP TABLE \`post_categories_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_version_sections\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_version_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`products_sections\`;`)
  await db.run(sql`DROP TABLE \`products_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`products\`;`)
  await db.run(sql`DROP TABLE \`products_locales\`;`)
  await db.run(sql`DROP TABLE \`products_rels\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`_products_v_version_sections\`;`)
  await db.run(sql`DROP TABLE \`_products_v_version_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v\`;`)
  await db.run(sql`DROP TABLE \`_products_v_locales\`;`)
  await db.run(sql`DROP TABLE \`_products_v_rels\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_heading\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_heading_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_paragraph\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_paragraph_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_rich_text\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_rich_text_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_image\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_image_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_link\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_link_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_content_list_items\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_content_list_items_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_content_list\`;`)
  await db.run(sql`DROP TABLE \`product_categories_sections\`;`)
  await db.run(sql`DROP TABLE \`product_categories_sections_locales\`;`)
  await db.run(sql`DROP TABLE \`product_categories\`;`)
  await db.run(sql`DROP TABLE \`product_categories_locales\`;`)
  await db.run(sql`DROP TABLE \`media_tags\`;`)
  await db.run(sql`DROP TABLE \`media_dominant_colors\`;`)
  await db.run(sql`DROP TABLE \`media_suggested_uses\`;`)
  await db.run(sql`DROP TABLE \`media_quality_notes\`;`)
  await db.run(sql`DROP TABLE \`media\`;`)
  await db.run(sql`DROP TABLE \`media_locales\`;`)
  await db.run(sql`DROP TABLE \`payload_kv\`;`)
  await db.run(sql`DROP TABLE \`payload_locked_documents\`;`)
  await db.run(sql`DROP TABLE \`payload_locked_documents_rels\`;`)
  await db.run(sql`DROP TABLE \`payload_preferences\`;`)
  await db.run(sql`DROP TABLE \`payload_preferences_rels\`;`)
  await db.run(sql`DROP TABLE \`payload_migrations\`;`)
  await db.run(sql`DROP TABLE \`site_settings\`;`)
  await db.run(sql`DROP TABLE \`site_settings_locales\`;`)
  await db.run(sql`DROP TABLE \`_site_settings_v\`;`)
  await db.run(sql`DROP TABLE \`_site_settings_v_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation_items\`;`)
  await db.run(sql`DROP TABLE \`navigation_items_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation_footer\`;`)
  await db.run(sql`DROP TABLE \`navigation_footer_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation_groups_items\`;`)
  await db.run(sql`DROP TABLE \`navigation_groups_items_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation_groups\`;`)
  await db.run(sql`DROP TABLE \`navigation_groups_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation_footer_groups_items\`;`)
  await db.run(sql`DROP TABLE \`navigation_footer_groups_items_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation_footer_groups\`;`)
  await db.run(sql`DROP TABLE \`navigation_footer_groups_locales\`;`)
  await db.run(sql`DROP TABLE \`navigation\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_items\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_footer\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_footer_locales\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_groups_items\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_groups_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_groups\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_groups_locales\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_footer_groups_items\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_footer_groups_items_locales\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_footer_groups\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v_version_footer_groups_locales\`;`)
  await db.run(sql`DROP TABLE \`_navigation_v\`;`)
}
