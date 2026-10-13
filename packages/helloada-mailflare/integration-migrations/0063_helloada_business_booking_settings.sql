CREATE TABLE helloada_tenant_owners (
  tenant_id TEXT PRIMARY KEY NOT NULL,
  owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL
);

CREATE TABLE helloada_booking_settings (
  user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
  time_zone TEXT NOT NULL DEFAULT '',
  weekly_availability TEXT NOT NULL DEFAULT '[]',
  max_concurrent_appointments INTEGER NOT NULL DEFAULT 1 CHECK (max_concurrent_appointments BETWEEN 1 AND 50),
  minimum_notice_hours INTEGER NOT NULL DEFAULT 24 CHECK (minimum_notice_hours BETWEEN 0 AND 8760),
  booking_window_days INTEGER NOT NULL DEFAULT 60 CHECK (booking_window_days BETWEEN 1 AND 365),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  updated_at INTEGER NOT NULL
);

ALTER TABLE calendar_events ADD COLUMN helloada_booking_type_id TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_contact_id TEXT;
ALTER TABLE messages ADD COLUMN helloada_contact_id TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_booking_type_name TEXT;
ALTER TABLE calendar_events ADD COLUMN helloada_booking_duration_minutes INTEGER;
ALTER TABLE calendar_events ADD COLUMN helloada_notification_lease_until INTEGER;
ALTER TABLE calendar_events ADD COLUMN helloada_capacity_revision INTEGER;
ALTER TABLE booking_events ADD COLUMN helloada_revision INTEGER NOT NULL DEFAULT 1 CHECK (helloada_revision > 0);

UPDATE calendar_events
SET starts_at = CASE WHEN starts_at < 100000000000 THEN starts_at * 1000 ELSE starts_at END,
    ends_at = CASE WHEN ends_at < 100000000000 THEN ends_at * 1000 ELSE ends_at END,
    repeat_until = CASE WHEN repeat_until IS NOT NULL AND repeat_until < 100000000000 THEN repeat_until * 1000 ELSE repeat_until END,
    booking_consent_at = CASE WHEN booking_consent_at > 100000000000 THEN CAST(booking_consent_at / 1000 AS INTEGER) ELSE booking_consent_at END,
    helloada_consent_accepted_at = CASE WHEN helloada_consent_accepted_at > 100000000000 THEN CAST(helloada_consent_accepted_at / 1000 AS INTEGER) ELSE helloada_consent_accepted_at END,
    created_at = CASE WHEN created_at > 100000000000 THEN CAST(created_at / 1000 AS INTEGER) ELSE created_at END,
    updated_at = CASE WHEN updated_at > 100000000000 THEN CAST(updated_at / 1000 AS INTEGER) ELSE updated_at END
WHERE starts_at < 100000000000
   OR ends_at < 100000000000
   OR (repeat_until IS NOT NULL AND repeat_until < 100000000000)
   OR booking_consent_at > 100000000000
   OR helloada_consent_accepted_at > 100000000000
   OR created_at > 100000000000
   OR updated_at > 100000000000;

UPDATE contacts SET
  last_seen_at = CASE WHEN last_seen_at > 100000000000 THEN CAST(last_seen_at / 1000 AS INTEGER) ELSE last_seen_at END,
  created_at = CASE WHEN created_at > 100000000000 THEN CAST(created_at / 1000 AS INTEGER) ELSE created_at END
WHERE last_seen_at > 100000000000 OR created_at > 100000000000;

UPDATE messages SET created_at = CAST(created_at / 1000 AS INTEGER)
WHERE created_at > 100000000000;

UPDATE booking_events SET
  created_at = CASE WHEN created_at > 100000000000 THEN CAST(created_at / 1000 AS INTEGER) ELSE created_at END,
  updated_at = CASE WHEN updated_at > 100000000000 THEN CAST(updated_at / 1000 AS INTEGER) ELSE updated_at END
WHERE created_at > 100000000000 OR updated_at > 100000000000;

CREATE INDEX calendar_events_helloada_type_idx ON calendar_events (user_id, helloada_booking_type_id, starts_at);
CREATE INDEX messages_helloada_contact_idx ON messages (mailbox_id, helloada_contact_id, created_at);

WITH imported AS (
  SELECT user_id,
         COUNT(*) AS total,
         COUNT(DISTINCT time_zone) AS zone_count,
         COUNT(DISTINCT helloada_weekly_availability) AS hours_count,
         COUNT(DISTINCT helloada_minimum_notice_hours) AS notice_count,
         COUNT(DISTINCT helloada_booking_window_days) AS horizon_count,
         MIN(time_zone) AS source_zone,
         MIN(helloada_weekly_availability) AS source_hours,
         MIN(helloada_calendar_enabled) AS source_enabled,
         MIN(helloada_minimum_notice_hours) AS source_notice,
         MIN(helloada_booking_window_days) AS source_horizon
  FROM booking_events
  WHERE helloada_payload_managed = 1
  GROUP BY user_id
)
INSERT INTO helloada_booking_settings
  (user_id, enabled, time_zone, weekly_availability, max_concurrent_appointments, minimum_notice_hours, booking_window_days, revision, updated_at)
SELECT user_id,
       CASE WHEN zone_count = 1 AND hours_count = 1 AND source_hours <> '[]' AND source_enabled = 1 THEN 1 ELSE 0 END,
       CASE WHEN zone_count = 1 AND hours_count = 1 AND source_hours <> '[]' THEN source_zone ELSE '' END,
       CASE WHEN hours_count = 1 AND zone_count = 1 AND source_hours <> '[]' THEN source_hours ELSE '[]' END,
       1,
       CASE WHEN notice_count = 1 THEN source_notice ELSE 24 END,
       CASE WHEN horizon_count = 1 THEN source_horizon ELSE 60 END,
       1,
       CAST(unixepoch() AS INTEGER) * 1000
FROM imported;

INSERT INTO helloada_booking_settings
  (user_id, enabled, time_zone, weekly_availability, max_concurrent_appointments, minimum_notice_hours, booking_window_days, revision, updated_at)
SELECT users.id, 0, '', '[]', 1, 24, 60, 1, CAST(unixepoch() AS INTEGER) * 1000
FROM users
WHERE NOT EXISTS (
  SELECT 1 FROM helloada_booking_settings
  WHERE helloada_booking_settings.user_id = users.id
);

CREATE TRIGGER helloada_booking_settings_user_insert
AFTER INSERT ON users
BEGIN
  INSERT INTO helloada_booking_settings
    (user_id, enabled, time_zone, weekly_availability, max_concurrent_appointments, minimum_notice_hours, booking_window_days, revision, updated_at)
  VALUES (NEW.id, 0, '', '[]', 1, 24, 60, 1, CAST(unixepoch() AS INTEGER) * 1000);
END;

CREATE TRIGGER helloada_calendar_capacity_insert
BEFORE INSERT ON calendar_events
WHEN NOT EXISTS (
  SELECT 1 FROM helloada_booking_settings
  WHERE user_id = NEW.user_id AND revision = NEW.helloada_capacity_revision
)
BEGIN
  SELECT RAISE(ABORT, 'helloada_capacity_revision_conflict');
END;

CREATE TRIGGER helloada_calendar_capacity_update
BEFORE UPDATE ON calendar_events
WHEN (
  NEW.starts_at IS NOT OLD.starts_at
  OR NEW.ends_at IS NOT OLD.ends_at
  OR NEW.repeat IS NOT OLD.repeat
  OR NEW.repeat_days IS NOT OLD.repeat_days
  OR NEW.repeat_anchor_day IS NOT OLD.repeat_anchor_day
  OR NEW.repeat_until IS NOT OLD.repeat_until
  OR NEW.excluded_occurrences IS NOT OLD.excluded_occurrences
  OR NEW.time_zone IS NOT OLD.time_zone
  OR NEW.helloada_buffer_minutes IS NOT OLD.helloada_buffer_minutes
  OR NEW.helloada_state IS NOT OLD.helloada_state
) AND NOT EXISTS (
  SELECT 1 FROM helloada_booking_settings
  WHERE user_id = NEW.user_id AND revision = NEW.helloada_capacity_revision
)
BEGIN
  SELECT RAISE(ABORT, 'helloada_capacity_revision_conflict');
END;

CREATE TRIGGER helloada_calendar_revision_insert
AFTER INSERT ON calendar_events
BEGIN
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = NEW.user_id;
END;

CREATE TRIGGER helloada_calendar_revision_update
AFTER UPDATE ON calendar_events
BEGIN
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = OLD.user_id;
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = NEW.user_id AND NEW.user_id <> OLD.user_id;
END;

CREATE TRIGGER helloada_calendar_revision_delete
AFTER DELETE ON calendar_events
BEGIN
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = OLD.user_id;
END;

CREATE TRIGGER helloada_booking_type_revision_insert
AFTER INSERT ON booking_events
BEGIN
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = NEW.user_id;
END;

CREATE TRIGGER helloada_booking_type_revision_update
AFTER UPDATE ON booking_events
BEGIN
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = OLD.user_id;
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = NEW.user_id AND NEW.user_id <> OLD.user_id;
END;

CREATE TRIGGER helloada_booking_type_revision_delete
AFTER DELETE ON booking_events
BEGIN
  UPDATE helloada_booking_settings
  SET revision = revision + 1, updated_at = CAST(unixepoch() AS INTEGER) * 1000
  WHERE user_id = OLD.user_id;
END;
