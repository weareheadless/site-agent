import { MigrateUpArgs, MigrateDownArgs, sql } from '@payloadcms/db-d1-sqlite'

export async function up({ db, payload, req }: MigrateUpArgs): Promise<void> {
  await db.run(sql`CREATE TABLE \`pages_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`pages\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_contact_form_order_idx\` ON \`pages_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_contact_form_parent_id_idx\` ON \`pages_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_contact_form_path_idx\` ON \`pages_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`pages_blocks_hello_ada_contact_form_form_idx\` ON \`pages_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`_pages_v_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`_uuid\` text,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_pages_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_contact_form_order_idx\` ON \`_pages_v_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_contact_form_parent_id_idx\` ON \`_pages_v_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_contact_form_path_idx\` ON \`_pages_v_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_pages_v_blocks_hello_ada_contact_form_form_idx\` ON \`_pages_v_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`posts_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`posts\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_contact_form_order_idx\` ON \`posts_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_contact_form_parent_id_idx\` ON \`posts_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_contact_form_path_idx\` ON \`posts_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`posts_blocks_hello_ada_contact_form_form_idx\` ON \`posts_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`_posts_v_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`_uuid\` text,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_posts_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_contact_form_order_idx\` ON \`_posts_v_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_contact_form_parent_id_idx\` ON \`_posts_v_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_contact_form_path_idx\` ON \`_posts_v_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_posts_v_blocks_hello_ada_contact_form_form_idx\` ON \`_posts_v_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`post_categories_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`post_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_contact_form_order_idx\` ON \`post_categories_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_contact_form_parent_id_idx\` ON \`post_categories_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_contact_form_path_idx\` ON \`post_categories_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`post_categories_blocks_hello_ada_contact_form_form_idx\` ON \`post_categories_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`_post_categories_v_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`_uuid\` text,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_post_categories_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_contact_form_order_idx\` ON \`_post_categories_v_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_contact_form_parent_id_idx\` ON \`_post_categories_v_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_contact_form_path_idx\` ON \`_post_categories_v_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_post_categories_v_blocks_hello_ada_contact_form_form_idx\` ON \`_post_categories_v_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`products_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`products\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_contact_form_order_idx\` ON \`products_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_contact_form_parent_id_idx\` ON \`products_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_contact_form_path_idx\` ON \`products_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`products_blocks_hello_ada_contact_form_form_idx\` ON \`products_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`_products_v_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`key\` text,
	\`label\` text,
	\`form_id\` integer,
	\`_uuid\` text,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_products_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_contact_form_order_idx\` ON \`_products_v_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_contact_form_parent_id_idx\` ON \`_products_v_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_contact_form_path_idx\` ON \`_products_v_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`_products_v_blocks_hello_ada_contact_form_form_idx\` ON \`_products_v_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`product_categories_blocks_hello_ada_contact_form\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`_path\` text NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text NOT NULL,
	\`label\` text NOT NULL,
	\`form_id\` integer NOT NULL,
	\`block_name\` text,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`product_categories\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_contact_form_order_idx\` ON \`product_categories_blocks_hello_ada_contact_form\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_contact_form_parent_id_idx\` ON \`product_categories_blocks_hello_ada_contact_form\` (\`_parent_id\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_contact_form_path_idx\` ON \`product_categories_blocks_hello_ada_contact_form\` (\`_path\`);`)
  await db.run(sql`CREATE INDEX \`product_categories_blocks_hello_ada_contact_form_form_idx\` ON \`product_categories_blocks_hello_ada_contact_form\` (\`form_id\`);`)
  await db.run(sql`CREATE TABLE \`contact_forms_fields_choices\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` text NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`contact_forms_fields\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`contact_forms_fields_choices_order_idx\` ON \`contact_forms_fields_choices\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`contact_forms_fields_choices_parent_id_idx\` ON \`contact_forms_fields_choices\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`contact_forms_fields_choices_locales\` (
	\`label\` text,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`_locale\` text NOT NULL,
	\`_parent_id\` text NOT NULL,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`contact_forms_fields_choices\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`contact_forms_fields_choices_locales_locale_parent_id_unique\` ON \`contact_forms_fields_choices_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`contact_forms_fields\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`id\` text PRIMARY KEY NOT NULL,
	\`key\` text,
	\`type\` text,
	\`maps_to\` text DEFAULT 'none',
	\`required\` integer DEFAULT false,
	\`max_length\` numeric DEFAULT 500,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`contact_forms_fields_order_idx\` ON \`contact_forms_fields\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`contact_forms_fields_parent_id_idx\` ON \`contact_forms_fields\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`contact_forms_fields_locales\` (
	\`label\` text,
	\`placeholder\` text,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`_locale\` text NOT NULL,
	\`_parent_id\` text NOT NULL,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`contact_forms_fields\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`contact_forms_fields_locales_locale_parent_id_unique\` ON \`contact_forms_fields_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`contact_forms\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`slug\` text,
	\`enabled\` integer DEFAULT false,
	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`_status\` text DEFAULT 'draft'
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`contact_forms_slug_idx\` ON \`contact_forms\` (\`slug\`);`)
  await db.run(sql`CREATE INDEX \`contact_forms_updated_at_idx\` ON \`contact_forms\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`contact_forms_created_at_idx\` ON \`contact_forms\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`contact_forms__status_idx\` ON \`contact_forms\` (\`_status\`);`)
  await db.run(sql`CREATE TABLE \`contact_forms_locales\` (
	\`title\` text,
	\`intro\` text,
	\`submit_label\` text DEFAULT 'Send message',
	\`success_message\` text DEFAULT 'Thank you. Your message has been received.',
	\`id\` integer PRIMARY KEY NOT NULL,
	\`_locale\` text NOT NULL,
	\`_parent_id\` integer NOT NULL,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`contact_forms_locales_locale_parent_id_unique\` ON \`contact_forms_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_contact_forms_v_version_fields_choices\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`key\` text,
	\`_uuid\` text,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_contact_forms_v_version_fields\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_fields_choices_order_idx\` ON \`_contact_forms_v_version_fields_choices\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_fields_choices_parent_id_idx\` ON \`_contact_forms_v_version_fields_choices\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_contact_forms_v_version_fields_choices_locales\` (
	\`label\` text,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`_locale\` text NOT NULL,
	\`_parent_id\` integer NOT NULL,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_contact_forms_v_version_fields_choices\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_contact_forms_v_version_fields_choices_locales_locale_paren\` ON \`_contact_forms_v_version_fields_choices_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_contact_forms_v_version_fields\` (
	\`_order\` integer NOT NULL,
	\`_parent_id\` integer NOT NULL,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`key\` text,
	\`type\` text,
	\`maps_to\` text DEFAULT 'none',
	\`required\` integer DEFAULT false,
	\`max_length\` numeric DEFAULT 500,
	\`_uuid\` text,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_contact_forms_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_fields_order_idx\` ON \`_contact_forms_v_version_fields\` (\`_order\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_fields_parent_id_idx\` ON \`_contact_forms_v_version_fields\` (\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_contact_forms_v_version_fields_locales\` (
	\`label\` text,
	\`placeholder\` text,
	\`id\` integer PRIMARY KEY NOT NULL,
	\`_locale\` text NOT NULL,
	\`_parent_id\` integer NOT NULL,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_contact_forms_v_version_fields\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_contact_forms_v_version_fields_locales_locale_parent_id_uni\` ON \`_contact_forms_v_version_fields_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`_contact_forms_v\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`parent_id\` integer,
	\`version_slug\` text,
	\`version_enabled\` integer DEFAULT false,
	\`version_updated_at\` text,
	\`version_created_at\` text,
	\`version__status\` text DEFAULT 'draft',
	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`snapshot\` integer,
	\`published_locale\` text,
	\`latest\` integer,
	FOREIGN KEY (\`parent_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_parent_idx\` ON \`_contact_forms_v\` (\`parent_id\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_version_slug_idx\` ON \`_contact_forms_v\` (\`version_slug\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_version_updated_at_idx\` ON \`_contact_forms_v\` (\`version_updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_version_created_at_idx\` ON \`_contact_forms_v\` (\`version_created_at\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_version_version__status_idx\` ON \`_contact_forms_v\` (\`version__status\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_created_at_idx\` ON \`_contact_forms_v\` (\`created_at\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_updated_at_idx\` ON \`_contact_forms_v\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_snapshot_idx\` ON \`_contact_forms_v\` (\`snapshot\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_published_locale_idx\` ON \`_contact_forms_v\` (\`published_locale\`);`)
  await db.run(sql`CREATE INDEX \`_contact_forms_v_latest_idx\` ON \`_contact_forms_v\` (\`latest\`);`)
  await db.run(sql`CREATE TABLE \`_contact_forms_v_locales\` (
	\`version_title\` text,
	\`version_intro\` text,
	\`version_submit_label\` text DEFAULT 'Send message',
	\`version_success_message\` text DEFAULT 'Thank you. Your message has been received.',
	\`id\` integer PRIMARY KEY NOT NULL,
	\`_locale\` text NOT NULL,
	\`_parent_id\` integer NOT NULL,
	FOREIGN KEY (\`_parent_id\`) REFERENCES \`_contact_forms_v\`(\`id\`) ON UPDATE no action ON DELETE cascade
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`_contact_forms_v_locales_locale_parent_id_unique\` ON \`_contact_forms_v_locales\` (\`_locale\`,\`_parent_id\`);`)
  await db.run(sql`CREATE TABLE \`contacts\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`email_key\` text NOT NULL,
	\`email\` text NOT NULL,
	\`name\` text,
	\`phone\` text,
	\`company\` text,
	\`notes\` text,
	\`source\` text NOT NULL,
	\`last_seen_at\` text,
	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`contacts_email_key_idx\` ON \`contacts\` (\`email_key\`);`)
  await db.run(sql`CREATE INDEX \`contacts_updated_at_idx\` ON \`contacts\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`contacts_created_at_idx\` ON \`contacts\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`conversations\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`subject\` text NOT NULL,
	\`contact_id\` integer NOT NULL,
	\`participant_email\` text NOT NULL,
	\`mailbox_key\` text NOT NULL,
	\`thread_key\` text,
	\`state\` text DEFAULT 'needs_reply' NOT NULL,
	\`unread\` integer DEFAULT true,
	\`source\` text NOT NULL,
	\`source_page\` text,
	\`last_activity_at\` text NOT NULL,
	\`last_message_preview\` text,
	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	FOREIGN KEY (\`contact_id\`) REFERENCES \`contacts\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`conversations_contact_idx\` ON \`conversations\` (\`contact_id\`);`)
  await db.run(sql`CREATE INDEX \`conversations_mailbox_key_idx\` ON \`conversations\` (\`mailbox_key\`);`)
  await db.run(sql`CREATE INDEX \`conversations_thread_key_idx\` ON \`conversations\` (\`thread_key\`);`)
  await db.run(sql`CREATE INDEX \`conversations_updated_at_idx\` ON \`conversations\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`conversations_created_at_idx\` ON \`conversations\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`messages\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`conversation_id\` integer NOT NULL,
	\`direction\` text NOT NULL,
	\`from\` text NOT NULL,
	\`to\` text NOT NULL,
	\`subject\` text NOT NULL,
	\`text\` text NOT NULL,
	\`draft_text\` text,
	\`draft_revision\` numeric DEFAULT 0,
	\`delivery_state\` text DEFAULT 'received' NOT NULL,
	\`form_id\` integer,
	\`form_snapshot\` text,
	\`receipt_id\` text,
	\`external_message_id\` text,
	\`in_reply_to\` text,
	\`references\` text,
	\`raw_object_key\` text,
	\`attachment_manifest\` text,
	\`approval_hash\` text,
	\`approved_by\` text,
	\`approved_at\` text,
	\`operation_id\` text,
	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	FOREIGN KEY (\`conversation_id\`) REFERENCES \`conversations\`(\`id\`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (\`form_id\`) REFERENCES \`contact_forms\`(\`id\`) ON UPDATE no action ON DELETE set null
  );
  `)
  await db.run(sql`CREATE INDEX \`messages_conversation_idx\` ON \`messages\` (\`conversation_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_form_idx\` ON \`messages\` (\`form_id\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`messages_receipt_id_idx\` ON \`messages\` (\`receipt_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_external_message_id_idx\` ON \`messages\` (\`external_message_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_in_reply_to_idx\` ON \`messages\` (\`in_reply_to\`);`)
  await db.run(sql`CREATE INDEX \`messages_operation_id_idx\` ON \`messages\` (\`operation_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_updated_at_idx\` ON \`messages\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`messages_created_at_idx\` ON \`messages\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`message_operations\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`operation_id\` text NOT NULL,
	\`operation_type\` text NOT NULL,
	\`idempotency_key\` text NOT NULL,
	\`state\` text DEFAULT 'accepted' NOT NULL,
	\`attempts\` numeric DEFAULT 0,
	\`next_attempt_at\` text,
	\`lease_until\` text,
	\`payload\` text,
	\`private_object_key\` text,
	\`provider_reference\` text,
	\`error_code\` text,
	\`updated_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	\`created_at\` text DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`message_operations_operation_id_idx\` ON \`message_operations\` (\`operation_id\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`message_operations_idempotency_key_idx\` ON \`message_operations\` (\`idempotency_key\`);`)
  await db.run(sql`CREATE INDEX \`message_operations_updated_at_idx\` ON \`message_operations\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`message_operations_created_at_idx\` ON \`message_operations\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`message_mailbox\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`domain\` text,
	\`address\` text,
	\`state\` text DEFAULT 'domain_required' NOT NULL,
	\`status_detail\` text,
	\`activated_at\` text,
	\`updated_at\` text,
	\`created_at\` text
  );
  `)
  await db.run(sql`DROP TABLE \`helloada_growth_candidates\`;`)
  await db.run(sql`DROP TABLE \`helloada_growth_operations\`;`)
  await db.run(sql`PRAGMA foreign_keys=OFF;`)
  await db.run(sql`CREATE TABLE \`__new_media\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`source_id\` text NOT NULL,
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
  await db.run(sql`INSERT INTO \`__new_media\`("id", "source_id", "source_url", "original_url", "ocr_text", "proposed_knowledge", "source_kind", "analysis_status", "analysis_provider", "analysis_model", "analysis_version", "analysis_error", "analysis_updated_at", "analysis", "updated_at", "created_at", "url", "thumbnail_u_r_l", "filename", "mime_type", "filesize", "width", "height", "focal_x", "focal_y") SELECT "id", "source_id", "source_url", "original_url", "ocr_text", "proposed_knowledge", "source_kind", "analysis_status", "analysis_provider", "analysis_model", "analysis_version", "analysis_error", "analysis_updated_at", "analysis", "updated_at", "created_at", "url", "thumbnail_u_r_l", "filename", "mime_type", "filesize", "width", "height", "focal_x", "focal_y" FROM \`media\`;`)
  await db.run(sql`DROP TABLE \`media\`;`)
  await db.run(sql`ALTER TABLE \`__new_media\` RENAME TO \`media\`;`)
  await db.run(sql`PRAGMA foreign_keys=ON;`)
  await db.run(sql`CREATE UNIQUE INDEX \`media_source_id_idx\` ON \`media\` (\`source_id\`);`)
  await db.run(sql`CREATE INDEX \`media_updated_at_idx\` ON \`media\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`media_created_at_idx\` ON \`media\` (\`created_at\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`media_filename_idx\` ON \`media\` (\`filename\`);`)
  await db.run(sql`ALTER TABLE \`payload_locked_documents_rels\` ADD \`contact_forms_id\` integer REFERENCES contact_forms(id);`)
  await db.run(sql`ALTER TABLE \`payload_locked_documents_rels\` ADD \`contacts_id\` integer REFERENCES contacts(id);`)
  await db.run(sql`ALTER TABLE \`payload_locked_documents_rels\` ADD \`conversations_id\` integer REFERENCES conversations(id);`)
  await db.run(sql`ALTER TABLE \`payload_locked_documents_rels\` ADD \`messages_id\` integer REFERENCES messages(id);`)
  await db.run(sql`ALTER TABLE \`payload_locked_documents_rels\` ADD \`message_operations_id\` integer REFERENCES message_operations(id);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_contact_forms_id_idx\` ON \`payload_locked_documents_rels\` (\`contact_forms_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_contacts_id_idx\` ON \`payload_locked_documents_rels\` (\`contacts_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_conversations_id_idx\` ON \`payload_locked_documents_rels\` (\`conversations_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_messages_id_idx\` ON \`payload_locked_documents_rels\` (\`messages_id\`);`)
  await db.run(sql`CREATE INDEX \`payload_locked_documents_rels_message_operations_id_idx\` ON \`payload_locked_documents_rels\` (\`message_operations_id\`);`)
  await db.run(sql`ALTER TABLE \`site_settings_locales\` ADD \`contact_label\` text;`)
  await db.run(sql`ALTER TABLE \`_site_settings_v_locales\` ADD \`version_contact_label\` text;`)
}

export async function down({ db, payload, req }: MigrateDownArgs): Promise<void> {
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
  );
  `)
  await db.run(sql`CREATE TABLE \`helloada_growth_operations\` (
	\`operation_key\` text PRIMARY KEY NOT NULL,
	\`document_key\` text NOT NULL,
	\`tenant_id\` text NOT NULL,
	\`package_hash\` text NOT NULL,
	\`state\` text NOT NULL,
	\`result_json\` text,
	\`created_at\` text NOT NULL,
	\`updated_at\` text NOT NULL
  );
  `)
  await db.run(sql`CREATE UNIQUE INDEX \`helloada_growth_writing_document\` ON \`helloada_growth_operations\` (\`document_key\`) WHERE state = writing;`)
  await db.run(sql`DROP TABLE \`pages_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`_pages_v_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`posts_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`_posts_v_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`post_categories_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`_post_categories_v_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`products_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`_products_v_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`product_categories_blocks_hello_ada_contact_form\`;`)
  await db.run(sql`DROP TABLE \`contact_forms_fields_choices\`;`)
  await db.run(sql`DROP TABLE \`contact_forms_fields_choices_locales\`;`)
  await db.run(sql`DROP TABLE \`contact_forms_fields\`;`)
  await db.run(sql`DROP TABLE \`contact_forms_fields_locales\`;`)
  await db.run(sql`DROP TABLE \`contact_forms\`;`)
  await db.run(sql`DROP TABLE \`contact_forms_locales\`;`)
  await db.run(sql`DROP TABLE \`_contact_forms_v_version_fields_choices\`;`)
  await db.run(sql`DROP TABLE \`_contact_forms_v_version_fields_choices_locales\`;`)
  await db.run(sql`DROP TABLE \`_contact_forms_v_version_fields\`;`)
  await db.run(sql`DROP TABLE \`_contact_forms_v_version_fields_locales\`;`)
  await db.run(sql`DROP TABLE \`_contact_forms_v\`;`)
  await db.run(sql`DROP TABLE \`_contact_forms_v_locales\`;`)
  await db.run(sql`DROP TABLE \`contacts\`;`)
  await db.run(sql`DROP TABLE \`conversations\`;`)
  await db.run(sql`DROP TABLE \`messages\`;`)
  await db.run(sql`DROP TABLE \`message_operations\`;`)
  await db.run(sql`DROP TABLE \`message_mailbox\`;`)
  await db.run(sql`PRAGMA foreign_keys=OFF;`)
  await db.run(sql`CREATE TABLE \`__new_payload_locked_documents_rels\` (
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
  await db.run(sql`INSERT INTO \`__new_payload_locked_documents_rels\`("id", "order", "parent_id", "path", "users_id", "pages_id", "posts_id", "post_categories_id", "products_id", "product_categories_id", "media_id") SELECT "id", "order", "parent_id", "path", "users_id", "pages_id", "posts_id", "post_categories_id", "products_id", "product_categories_id", "media_id" FROM \`payload_locked_documents_rels\`;`)
  await db.run(sql`DROP TABLE \`payload_locked_documents_rels\`;`)
  await db.run(sql`ALTER TABLE \`__new_payload_locked_documents_rels\` RENAME TO \`payload_locked_documents_rels\`;`)
  await db.run(sql`PRAGMA foreign_keys=ON;`)
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
  await db.run(sql`CREATE TABLE \`__new_media\` (
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
  await db.run(sql`INSERT INTO \`__new_media\`("id", "source_id", "source_url", "original_url", "ocr_text", "proposed_knowledge", "source_kind", "analysis_status", "analysis_provider", "analysis_model", "analysis_version", "analysis_error", "analysis_updated_at", "analysis", "updated_at", "created_at", "url", "thumbnail_u_r_l", "filename", "mime_type", "filesize", "width", "height", "focal_x", "focal_y") SELECT "id", "source_id", "source_url", "original_url", "ocr_text", "proposed_knowledge", "source_kind", "analysis_status", "analysis_provider", "analysis_model", "analysis_version", "analysis_error", "analysis_updated_at", "analysis", "updated_at", "created_at", "url", "thumbnail_u_r_l", "filename", "mime_type", "filesize", "width", "height", "focal_x", "focal_y" FROM \`media\`;`)
  await db.run(sql`DROP TABLE \`media\`;`)
  await db.run(sql`ALTER TABLE \`__new_media\` RENAME TO \`media\`;`)
  await db.run(sql`CREATE UNIQUE INDEX \`media_source_id_idx\` ON \`media\` (\`source_id\`);`)
  await db.run(sql`CREATE INDEX \`media_updated_at_idx\` ON \`media\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`media_created_at_idx\` ON \`media\` (\`created_at\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`media_filename_idx\` ON \`media\` (\`filename\`);`)
  await db.run(sql`ALTER TABLE \`site_settings_locales\` DROP COLUMN \`contact_label\`;`)
  await db.run(sql`ALTER TABLE \`_site_settings_v_locales\` DROP COLUMN \`version_contact_label\`;`)
}
