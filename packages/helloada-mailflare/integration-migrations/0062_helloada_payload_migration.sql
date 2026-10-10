ALTER TABLE contacts ADD COLUMN helloada_phone TEXT;
ALTER TABLE contacts ADD COLUMN helloada_company TEXT;
ALTER TABLE contacts ADD COLUMN helloada_notes TEXT;

ALTER TABLE messages ADD COLUMN helloada_delivery_state TEXT;
ALTER TABLE messages ADD COLUMN helloada_source_page TEXT;
ALTER TABLE messages ADD COLUMN helloada_form_snapshot TEXT;

ALTER TABLE calendar_events ADD COLUMN helloada_state TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_receipt_id TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_answers TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_consent_accepted_at INTEGER;
ALTER TABLE calendar_events ADD COLUMN helloada_notification_state TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_buffer_minutes INTEGER NOT NULL DEFAULT 0;

ALTER TABLE booking_events ADD COLUMN helloada_buffer_minutes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE booking_events ADD COLUMN helloada_weekly_availability TEXT NOT NULL DEFAULT '[]';
ALTER TABLE booking_events ADD COLUMN helloada_locales TEXT NOT NULL DEFAULT '{}';
ALTER TABLE booking_events ADD COLUMN helloada_calendar_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE booking_events ADD COLUMN helloada_minimum_notice_hours INTEGER NOT NULL DEFAULT 24;
ALTER TABLE booking_events ADD COLUMN helloada_booking_window_days INTEGER NOT NULL DEFAULT 60;
ALTER TABLE booking_events ADD COLUMN helloada_payload_managed INTEGER NOT NULL DEFAULT 0;

CREATE TABLE helloada_import_runs (
  tenant_id TEXT PRIMARY KEY NOT NULL,
  version TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('running', 'failed', 'complete')),
  lease_token TEXT,
  lease_until INTEGER,
  source_sha256 TEXT,
  counts_json TEXT,
  error_code TEXT,
  started_at INTEGER NOT NULL,
  completed_at INTEGER
);

CREATE TABLE helloada_import_records (
  source_collection TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  target_collection TEXT NOT NULL,
  target_id TEXT NOT NULL,
  migrated_at INTEGER NOT NULL,
  PRIMARY KEY (source_collection, source_id)
);

CREATE TABLE helloada_imported_operations (
  source_id TEXT PRIMARY KEY NOT NULL,
  operation_id TEXT NOT NULL,
  operation_type TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  next_attempt_at INTEGER,
  provider_reference TEXT,
  error_code TEXT,
  payload TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
