import { MigrateUpArgs, MigrateDownArgs, sql } from '@payloadcms/db-d1-sqlite'

export async function up({ db, payload, req }: MigrateUpArgs): Promise<void> {
  // Earlier development databases allowed missing or duplicate conversation
  // keys. Preserve those records while bringing the shared unique-key
  // invariant online; runtime code continues to create only canonical keys.
  await db.run(sql`UPDATE conversations SET thread_key = 'migration:' || id WHERE thread_key IS NULL OR thread_key = '';`)
  await db.run(sql`UPDATE conversations SET thread_key = 'migration:' || id WHERE id IN (
    SELECT id FROM (
      SELECT id, ROW_NUMBER() OVER (PARTITION BY thread_key ORDER BY id) AS duplicate_rank
      FROM conversations WHERE thread_key IS NOT NULL AND thread_key <> ''
    ) WHERE duplicate_rank > 1
  );`)
  await db.run(sql`PRAGMA foreign_keys=OFF;`)
  await db.run(sql`CREATE TABLE \`__new_conversations\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`subject\` text NOT NULL,
	\`contact_id\` integer NOT NULL,
	\`participant_email\` text NOT NULL,
	\`mailbox_key\` text NOT NULL,
	\`thread_key\` text NOT NULL,
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
  await db.run(sql`INSERT INTO \`__new_conversations\`("id", "subject", "contact_id", "participant_email", "mailbox_key", "thread_key", "state", "unread", "source", "source_page", "last_activity_at", "last_message_preview", "updated_at", "created_at") SELECT "id", "subject", "contact_id", "participant_email", "mailbox_key", "thread_key", "state", "unread", "source", "source_page", "last_activity_at", "last_message_preview", "updated_at", "created_at" FROM \`conversations\`;`)
  await db.run(sql`DROP TABLE \`conversations\`;`)
  await db.run(sql`ALTER TABLE \`__new_conversations\` RENAME TO \`conversations\`;`)
  await db.run(sql`PRAGMA foreign_keys=ON;`)
  await db.run(sql`CREATE INDEX \`conversations_contact_idx\` ON \`conversations\` (\`contact_id\`);`)
  await db.run(sql`CREATE INDEX \`conversations_mailbox_key_idx\` ON \`conversations\` (\`mailbox_key\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`conversations_thread_key_idx\` ON \`conversations\` (\`thread_key\`);`)
  await db.run(sql`CREATE INDEX \`conversations_updated_at_idx\` ON \`conversations\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`conversations_created_at_idx\` ON \`conversations\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`__new_messages\` (
	\`id\` integer PRIMARY KEY NOT NULL,
	\`conversation_id\` integer NOT NULL,
	\`direction\` text NOT NULL,
	\`from\` text,
	\`to\` text,
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
  await db.run(sql`INSERT INTO \`__new_messages\`("id", "conversation_id", "direction", "from", "to", "subject", "text", "draft_text", "draft_revision", "delivery_state", "form_id", "form_snapshot", "receipt_id", "external_message_id", "in_reply_to", "references", "raw_object_key", "attachment_manifest", "approval_hash", "approved_by", "approved_at", "operation_id", "updated_at", "created_at") SELECT "id", "conversation_id", "direction", "from", "to", "subject", "text", "draft_text", "draft_revision", "delivery_state", "form_id", "form_snapshot", "receipt_id", "external_message_id", "in_reply_to", "references", "raw_object_key", "attachment_manifest", "approval_hash", "approved_by", "approved_at", "operation_id", "updated_at", "created_at" FROM \`messages\`;`)
  await db.run(sql`DROP TABLE \`messages\`;`)
  await db.run(sql`ALTER TABLE \`__new_messages\` RENAME TO \`messages\`;`)
  await db.run(sql`CREATE INDEX \`messages_conversation_idx\` ON \`messages\` (\`conversation_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_form_idx\` ON \`messages\` (\`form_id\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`messages_receipt_id_idx\` ON \`messages\` (\`receipt_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_external_message_id_idx\` ON \`messages\` (\`external_message_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_in_reply_to_idx\` ON \`messages\` (\`in_reply_to\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`messages_operation_id_idx\` ON \`messages\` (\`operation_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_updated_at_idx\` ON \`messages\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`messages_created_at_idx\` ON \`messages\` (\`created_at\`);`)
  await db.run(sql`ALTER TABLE \`message_operations\` ADD \`request_hash\` text DEFAULT '' NOT NULL;`)
  await db.run(sql`CREATE INDEX \`message_operations_request_hash_idx\` ON \`message_operations\` (\`request_hash\`);`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_address\` text;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_verified_at\` text;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_pending_address\` text;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_code_hash\` text;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_code_expires_at\` text;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_code_sent_at\` text;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` ADD \`notification_code_attempts\` numeric DEFAULT 0;`)
}

export async function down({ db, payload, req }: MigrateDownArgs): Promise<void> {
  await db.run(sql`DROP INDEX \`message_operations_request_hash_idx\`;`)
  await db.run(sql`ALTER TABLE \`message_operations\` DROP COLUMN \`request_hash\`;`)
  await db.run(sql`PRAGMA foreign_keys=OFF;`)
  await db.run(sql`CREATE TABLE \`__new_conversations\` (
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
  await db.run(sql`INSERT INTO \`__new_conversations\`("id", "subject", "contact_id", "participant_email", "mailbox_key", "thread_key", "state", "unread", "source", "source_page", "last_activity_at", "last_message_preview", "updated_at", "created_at") SELECT "id", "subject", "contact_id", "participant_email", "mailbox_key", "thread_key", "state", "unread", "source", "source_page", "last_activity_at", "last_message_preview", "updated_at", "created_at" FROM \`conversations\`;`)
  await db.run(sql`DROP TABLE \`conversations\`;`)
  await db.run(sql`ALTER TABLE \`__new_conversations\` RENAME TO \`conversations\`;`)
  await db.run(sql`PRAGMA foreign_keys=ON;`)
  await db.run(sql`CREATE INDEX \`conversations_contact_idx\` ON \`conversations\` (\`contact_id\`);`)
  await db.run(sql`CREATE INDEX \`conversations_mailbox_key_idx\` ON \`conversations\` (\`mailbox_key\`);`)
  await db.run(sql`CREATE INDEX \`conversations_thread_key_idx\` ON \`conversations\` (\`thread_key\`);`)
  await db.run(sql`CREATE INDEX \`conversations_updated_at_idx\` ON \`conversations\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`conversations_created_at_idx\` ON \`conversations\` (\`created_at\`);`)
  await db.run(sql`CREATE TABLE \`__new_messages\` (
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
  await db.run(sql`INSERT INTO \`__new_messages\`("id", "conversation_id", "direction", "from", "to", "subject", "text", "draft_text", "draft_revision", "delivery_state", "form_id", "form_snapshot", "receipt_id", "external_message_id", "in_reply_to", "references", "raw_object_key", "attachment_manifest", "approval_hash", "approved_by", "approved_at", "operation_id", "updated_at", "created_at") SELECT "id", "conversation_id", "direction", "from", "to", "subject", "text", "draft_text", "draft_revision", "delivery_state", "form_id", "form_snapshot", "receipt_id", "external_message_id", "in_reply_to", "references", "raw_object_key", "attachment_manifest", "approval_hash", "approved_by", "approved_at", "operation_id", "updated_at", "created_at" FROM \`messages\`;`)
  await db.run(sql`DROP TABLE \`messages\`;`)
  await db.run(sql`ALTER TABLE \`__new_messages\` RENAME TO \`messages\`;`)
  await db.run(sql`CREATE INDEX \`messages_conversation_idx\` ON \`messages\` (\`conversation_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_form_idx\` ON \`messages\` (\`form_id\`);`)
  await db.run(sql`CREATE UNIQUE INDEX \`messages_receipt_id_idx\` ON \`messages\` (\`receipt_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_external_message_id_idx\` ON \`messages\` (\`external_message_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_in_reply_to_idx\` ON \`messages\` (\`in_reply_to\`);`)
  await db.run(sql`CREATE INDEX \`messages_operation_id_idx\` ON \`messages\` (\`operation_id\`);`)
  await db.run(sql`CREATE INDEX \`messages_updated_at_idx\` ON \`messages\` (\`updated_at\`);`)
  await db.run(sql`CREATE INDEX \`messages_created_at_idx\` ON \`messages\` (\`created_at\`);`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_address\`;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_verified_at\`;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_pending_address\`;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_code_hash\`;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_code_expires_at\`;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_code_sent_at\`;`)
  await db.run(sql`ALTER TABLE \`message_mailbox\` DROP COLUMN \`notification_code_attempts\`;`)
}
