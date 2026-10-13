import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migration = await readFile(path.join(root, "integration-migrations/0063_helloada_business_booking_settings.sql"), "utf8");

function databaseWithLegacyCalendar() {
  const db = new DatabaseSync(":memory:");
  db.exec(`
    CREATE TABLE users (id TEXT PRIMARY KEY);
    CREATE TABLE booking_events (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, helloada_payload_managed INTEGER NOT NULL DEFAULT 0,
      time_zone TEXT, helloada_weekly_availability TEXT, helloada_calendar_enabled INTEGER,
      helloada_minimum_notice_hours INTEGER, helloada_booking_window_days INTEGER,
      created_at INTEGER, updated_at INTEGER
    );
    CREATE TABLE calendar_events (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, title TEXT, description TEXT,
      location TEXT, attendees TEXT, color TEXT, repeat TEXT, repeat_days TEXT, repeat_anchor_day INTEGER,
      repeat_until INTEGER, excluded_occurrences TEXT, time_zone TEXT, starts_at INTEGER, ends_at INTEGER,
      booking_consent_at INTEGER, created_at INTEGER, updated_at INTEGER, helloada_state TEXT, helloada_receipt_id TEXT,
      helloada_answers TEXT, helloada_consent_accepted_at INTEGER, helloada_notification_state TEXT,
      helloada_buffer_minutes INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE contacts (id TEXT PRIMARY KEY, last_seen_at INTEGER, created_at INTEGER);
    CREATE TABLE messages (id TEXT PRIMARY KEY, mailbox_id TEXT, created_at INTEGER);
    INSERT INTO users (id) VALUES ('existing-owner');
    INSERT INTO booking_events (id,user_id,helloada_payload_managed,time_zone,helloada_weekly_availability,helloada_calendar_enabled,helloada_minimum_notice_hours,helloada_booking_window_days,created_at,updated_at)
      VALUES ('legacy-type','existing-owner',0,'','[]',0,24,60,1800000000000,1800000000000);
    INSERT INTO contacts (id,last_seen_at,created_at) VALUES ('legacy-contact',1800000000000,1800000000000);
    INSERT INTO messages (id,mailbox_id,created_at) VALUES ('legacy-message',NULL,1800000000000);
    INSERT INTO calendar_events (id,user_id,title,repeat,starts_at,ends_at,booking_consent_at,created_at,updated_at,helloada_consent_accepted_at)
      VALUES ('legacy-event','existing-owner','Legacy','none',1800000000,1800001800,1800000000000,1800000000000,1800000000000,1800000000000);
  `);
  db.exec(migration);
  return db;
}

test("migration provisions current and future users, normalizes Calendar milliseconds, and CAS-gates writes", () => {
  const db = databaseWithLegacyCalendar();
  try {
    const existing = db.prepare("SELECT enabled,revision,time_zone,weekly_availability FROM helloada_booking_settings WHERE user_id='existing-owner'").get();
    assert.deepEqual({ ...existing }, { enabled: 0, revision: 1, time_zone: "", weekly_availability: "[]" });
    const legacy = db.prepare("SELECT starts_at,ends_at,booking_consent_at,helloada_consent_accepted_at,created_at,updated_at FROM calendar_events WHERE id='legacy-event'").get();
    assert.equal(legacy.starts_at, 1_800_000_000_000);
    assert.equal(legacy.ends_at, 1_800_001_800_000);
    assert.equal(legacy.booking_consent_at, 1_800_000_000);
    assert.equal(legacy.helloada_consent_accepted_at, 1_800_000_000);
    assert.equal(legacy.created_at, 1_800_000_000);
    assert.equal(legacy.updated_at, 1_800_000_000);
    assert.equal(db.prepare("SELECT created_at,updated_at,helloada_revision FROM booking_events WHERE id='legacy-type'").get().created_at, 1_800_000_000);
    assert.equal(db.prepare("SELECT last_seen_at,created_at FROM contacts WHERE id='legacy-contact'").get().created_at, 1_800_000_000);
    assert.equal(db.prepare("SELECT created_at FROM messages WHERE id='legacy-message'").get().created_at, 1_800_000_000);

    db.prepare("INSERT INTO users (id) VALUES (?)").run("future-owner");
    const future = db.prepare("SELECT enabled,revision,time_zone,weekly_availability FROM helloada_booking_settings WHERE user_id='future-owner'").get();
    assert.deepEqual({ ...future }, { enabled: 0, revision: 1, time_zone: "", weekly_availability: "[]" });

    const insert = db.prepare(`INSERT INTO calendar_events
      (id,user_id,title,repeat,repeat_days,excluded_occurrences,time_zone,starts_at,ends_at,helloada_capacity_revision,created_at,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`);
    insert.run("new-event","existing-owner","Busy","none","[]","[]","UTC",1_900_000_000_000,1_900_000_600_000,1,Date.now(),Date.now());
    assert.equal(db.prepare("SELECT revision FROM helloada_booking_settings WHERE user_id='existing-owner'").get().revision, 2);

    assert.throws(() => insert.run("stale-event","existing-owner","Busy","none","[]","[]","UTC",1_900_001_000_000,1_900_001_600_000,1,Date.now(),Date.now()), /helloada_capacity_revision_conflict/);
    assert.throws(() => db.prepare("UPDATE calendar_events SET starts_at=?,helloada_capacity_revision=? WHERE id='new-event'").run(1_900_002_000_000,1), /helloada_capacity_revision_conflict/);
    db.prepare("UPDATE calendar_events SET starts_at=?,helloada_capacity_revision=? WHERE id='new-event'").run(1_900_002_000_000,2);
    assert.equal(db.prepare("SELECT revision FROM helloada_booking_settings WHERE user_id='existing-owner'").get().revision, 3);
  } finally {
    db.close();
  }
});
