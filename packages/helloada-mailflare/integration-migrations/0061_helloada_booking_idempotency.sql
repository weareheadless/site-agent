ALTER TABLE calendar_events ADD COLUMN booking_request_id TEXT;
ALTER TABLE calendar_events ADD COLUMN booking_request_hash TEXT;
ALTER TABLE calendar_events ADD COLUMN booking_consent_at INTEGER;
CREATE UNIQUE INDEX calendar_events_booking_request_idx ON calendar_events (user_id, booking_request_id);
