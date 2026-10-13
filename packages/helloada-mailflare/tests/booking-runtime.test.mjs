import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { assertCalendarMutationCapacity, createPublicBooking, getBookingCapacityWarnings, getPublicBookingDetails } from "../integration-src/src/lib/helloada-booking-runtime.ts";
import { createBookingType, deactivateBookingType, updateBookingType } from "../../../src/site_agent/templates/next-payload/mailflare-booking-service.ts";

function fixture({ capacity = 1, duration = 30, timeZone = "UTC", hours } = {}) {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(`
    CREATE TABLE helloada_tenant_owners (tenant_id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL);
    CREATE TABLE helloada_booking_settings (user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, time_zone TEXT NOT NULL, weekly_availability TEXT NOT NULL, max_concurrent_appointments INTEGER NOT NULL, minimum_notice_hours INTEGER NOT NULL, booking_window_days INTEGER NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL);
    CREATE TABLE booking_events (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL, enabled INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      color TEXT NOT NULL DEFAULT '#f28b55', host_ids TEXT NOT NULL DEFAULT '[]', location TEXT NOT NULL DEFAULT '',
      weekdays TEXT NOT NULL DEFAULT '[]', start_time TEXT NOT NULL DEFAULT '', end_time TEXT NOT NULL DEFAULT '',
      time_ranges TEXT NOT NULL DEFAULT '[]', time_zone TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL DEFAULT 0, helloada_weekly_availability TEXT NOT NULL DEFAULT '[]',
      helloada_calendar_enabled INTEGER NOT NULL DEFAULT 0, helloada_minimum_notice_hours INTEGER NOT NULL DEFAULT 24,
      helloada_booking_window_days INTEGER NOT NULL DEFAULT 60, helloada_payload_managed INTEGER NOT NULL DEFAULT 0,
      helloada_revision INTEGER NOT NULL DEFAULT 1,
      UNIQUE(user_id,slug)
    );
    CREATE TABLE domains (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, hostname TEXT NOT NULL, status TEXT NOT NULL);
    CREATE TABLE mailboxes (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, domain_id TEXT NOT NULL, local_part TEXT NOT NULL, disabled INTEGER NOT NULL);
    CREATE TABLE contacts (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL, display_name TEXT, source TEXT NOT NULL, last_seen_at INTEGER, created_at INTEGER NOT NULL, UNIQUE(user_id,email));
    CREATE TABLE messages (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, direction TEXT NOT NULL, provider_message_id TEXT, from_addr TEXT NOT NULL, to_addr TEXT NOT NULL, subject TEXT, snippet TEXT, text_body TEXT, status TEXT NOT NULL, thread_id TEXT, helloada_contact_id TEXT, helloada_delivery_state TEXT, helloada_source_page TEXT, created_at INTEGER NOT NULL);
    CREATE TABLE calendar_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, title TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL, attendees TEXT NOT NULL, color TEXT NOT NULL, repeat TEXT NOT NULL, repeat_days TEXT NOT NULL, repeat_anchor_day INTEGER, repeat_until INTEGER, excluded_occurrences TEXT NOT NULL, time_zone TEXT, starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, booking_request_id TEXT, booking_request_hash TEXT, booking_consent_at INTEGER, helloada_state TEXT, helloada_receipt_id TEXT, helloada_answers TEXT, helloada_consent_accepted_at INTEGER, helloada_notification_state TEXT, helloada_notification_lease_until INTEGER, helloada_buffer_minutes INTEGER NOT NULL DEFAULT 0, helloada_booking_type_id TEXT, helloada_booking_type_name TEXT, helloada_booking_duration_minutes INTEGER, helloada_contact_id TEXT, helloada_capacity_revision INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
    CREATE UNIQUE INDEX calendar_booking_idempotency ON calendar_events(user_id,booking_request_id);
    CREATE TRIGGER calendar_revision_insert AFTER INSERT ON calendar_events BEGIN UPDATE helloada_booking_settings SET revision=revision+1 WHERE user_id=NEW.user_id; END;
    CREATE TRIGGER calendar_revision_update AFTER UPDATE ON calendar_events BEGIN UPDATE helloada_booking_settings SET revision=revision+1 WHERE user_id=NEW.user_id; END;
    CREATE TRIGGER calendar_revision_delete AFTER DELETE ON calendar_events BEGIN UPDATE helloada_booking_settings SET revision=revision+1 WHERE user_id=OLD.user_id; END;
    CREATE TRIGGER calendar_capacity_insert BEFORE INSERT ON calendar_events WHEN NOT EXISTS (SELECT 1 FROM helloada_booking_settings WHERE user_id=NEW.user_id AND revision=NEW.helloada_capacity_revision) BEGIN SELECT RAISE(ABORT, 'helloada_capacity_revision_conflict'); END;
    CREATE TRIGGER calendar_capacity_update BEFORE UPDATE ON calendar_events WHEN (NEW.starts_at IS NOT OLD.starts_at OR NEW.ends_at IS NOT OLD.ends_at OR NEW.repeat IS NOT OLD.repeat OR NEW.time_zone IS NOT OLD.time_zone) AND NOT EXISTS (SELECT 1 FROM helloada_booking_settings WHERE user_id=NEW.user_id AND revision=NEW.helloada_capacity_revision) BEGIN SELECT RAISE(ABORT, 'helloada_capacity_revision_conflict'); END;
    INSERT INTO helloada_tenant_owners VALUES ('tenant-1','owner-1');
    INSERT INTO domains VALUES ('domain-1','owner-1','example.test','active');
    INSERT INTO mailboxes VALUES ('mailbox-1','owner-1','domain-1','hello',0);
  `);
  const schedule = hours ?? Array.from({ length: 7 }, (_, day) => ({ day, startTime: "00:00", endTime: "23:45" }));
  sqlite.prepare("INSERT INTO helloada_booking_settings VALUES (?,?,?,?,?,?,?,?,?)")
    .run("owner-1", 1, timeZone, JSON.stringify(schedule), capacity, 0, 365, 1, Date.now());
  sqlite.prepare("INSERT INTO booking_events (id,user_id,slug,name,description,duration_minutes,enabled,updated_at) VALUES (?,?,?,?,?,?,?,?)")
    .run("type-1", "owner-1", "consultation", "Consultation", "", duration, 1, 1000);

  const statement = (sql) => {
    let values = [];
    const item = {
      bind(...args) { values = args; return item; },
      async first() { return sqlite.prepare(sql).get(...values) ?? null; },
      async all() { return { results: sqlite.prepare(sql).all(...values) }; },
      async run() { const result = sqlite.prepare(sql).run(...values); return { meta: { changes: Number(result.changes) } }; },
      executeInBatch() {
        const query = sqlite.prepare(sql);
        if (/^\s*select/i.test(sql)) return { results: query.all(...values) };
        const result = query.run(...values);
        return { meta: { changes: Number(result.changes) } };
      },
    };
    return item;
  };
  const db = {
    prepare: statement,
    async batch(statements) {
      sqlite.exec("BEGIN IMMEDIATE");
      try {
        const results = statements.map((item) => item.executeInBatch());
        sqlite.exec("COMMIT");
        return results;
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
    },
  };
  return { sqlite, db };
}

const futureDate = (days = 2) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
const slotAt = (date, time = "12:00") => new Date(date + "T" + time + ":00.000Z").toISOString();
const input = (startsAt, requestId) => ({
  startsAt, name: "Ada Client", email: "visitor@example.test", notes: "", requestId,
  consent: true, sourcePage: "/appointments",
});
const details = (db, date, type = "type-1") => getPublicBookingDetails(db, "tenant-1", type, date, "turnstile-key");

test("native Calendar events use epoch milliseconds and half-open slot boundaries", async () => {
  const { sqlite, db } = fixture();
  const date = futureDate();
  const noon = Date.parse(slotAt(date));
  const firstRevision = await assertCalendarMutationCapacity(db, "owner-1", [{ startsAt: noon - 30 * 60_000, endsAt: noon, repeat: "none", timeZone: "UTC" }]);
  sqlite.prepare("INSERT INTO calendar_events (id,user_id,title,description,location,attendees,color,repeat,repeat_days,excluded_occurrences,time_zone,starts_at,ends_at,helloada_capacity_revision,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .run("busy-1", "owner-1", "Busy", "", "", "[]", "blue", "none", "[]", "[]", "UTC", noon - 30 * 60_000, noon, firstRevision, Date.now(), Date.now());
  const available = await details(db, date);
  assert.ok(available.slots.some((slot) => slot.startsAt === slotAt(date, "12:00")));

  const secondRevision = await assertCalendarMutationCapacity(db, "owner-1", [{ startsAt: noon, endsAt: noon + 30 * 60_000, repeat: "none", timeZone: "UTC" }], ["busy-1"]);
  sqlite.prepare("UPDATE calendar_events SET starts_at=?,ends_at=?,helloada_capacity_revision=? WHERE id='busy-1'")
    .run(noon, noon + 30 * 60_000, secondRevision);
  const blocked = await details(db, date);
  assert.ok(!blocked.slots.some((slot) => slot.startsAt === slotAt(date, "12:00")));
  assert.ok(blocked.slots.some((slot) => slot.startsAt === slotAt(date, "12:30")));
});

test("two concurrent submissions for the last unit admit one appointment; idempotent retry adds none", async () => {
  const { sqlite, db } = fixture();
  const startsAt = slotAt(futureDate());
  const outcomes = await Promise.all([
    createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", input(startsAt, "request-000000000001")),
    createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", input(startsAt, "request-000000000002")),
  ]);
  assert.equal(outcomes.filter((result) => result.state === "created").length, 1);
  assert.equal(outcomes.filter((result) => result.state === "unavailable").length, 1);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events WHERE booking_request_id IS NOT NULL").get().count, 1);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM messages").get().count, 1);
  const created = outcomes.find((result) => result.state === "created");
  const repeated = await createPublicBooking(db, "tenant-1", "hello@example.test", "type-1",
    input(startsAt, outcomes[0].state === "created" ? "request-000000000001" : "request-000000000002"));
  assert.equal(repeated.state, "duplicate");
  assert.equal(repeated.eventId, created.eventId);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events WHERE booking_request_id IS NOT NULL").get().count, 1);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM messages").get().count, 1);
});

test("availability omits daylight-saving gaps and emits one deterministic repeated wall time", async () => {
  const hours = Array.from({ length: 7 }, (_, day) => ({ day, startTime: "00:00", endTime: "04:00" }));
  const { db: springDb } = fixture({ timeZone: "America/New_York", hours });
  const spring = await details(springDb, "2027-03-14");
  assert.ok(!spring.slots.some((slot) => slot.time.startsWith("02:")));
  assert.ok(spring.slots.some((slot) => slot.time === "03:00"));

  const { db: fallDb } = fixture({ timeZone: "America/New_York", hours });
  const fall = await details(fallDb, "2026-11-01");
  const repeatedHour = fall.slots.filter((slot) => slot.time.startsWith("01:"));
  assert.ok(repeatedHour.length > 0);
  assert.equal(new Set(repeatedHour.map((slot) => slot.time)).size, repeatedHour.length);
});

test("capacity two admits two overlapping appointments across different type durations and rejects a third", async () => {
  const { sqlite, db } = fixture({ capacity: 2, duration: 30 });
  sqlite.prepare("INSERT INTO booking_events (id,user_id,slug,name,description,duration_minutes,enabled,updated_at) VALUES (?,?,?,?,?,?,?,?)")
    .run("type-2", "owner-1", "extended", "Long consultation", "", 60, 1, 1000);
  const startsAt = slotAt(futureDate());
  const attempts = await Promise.all([
    createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", input(startsAt, "capacity-two-request-0001")),
    createPublicBooking(db, "tenant-1", "hello@example.test", "type-2", input(startsAt, "capacity-two-request-0002")),
    createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", input(startsAt, "capacity-two-request-0003")),
  ]);
  assert.equal(attempts.filter((result) => result.state === "created").length, 2);
  assert.equal(attempts.filter((result) => result.state === "unavailable").length, 1);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events WHERE booking_request_id IS NOT NULL").get().count, 2);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM messages").get().count, 2);
});

test("an idempotent retry returns its original event after settings or type are disabled", async () => {
  const { sqlite, db } = fixture();
  const startsAt = slotAt(futureDate());
  const request = input(startsAt, "stable-request-identity-0001");
  const first = await createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", request);
  assert.equal(first.state, "created");
  sqlite.prepare("UPDATE helloada_booking_settings SET enabled=0 WHERE user_id='owner-1'").run();
  sqlite.prepare("UPDATE booking_events SET enabled=0 WHERE id='type-1'").run();
  const retry = await createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", request);
  assert.equal(retry.state, "duplicate");
  assert.equal(retry.eventId, first.eventId);
  await assert.rejects(
    createPublicBooking(db, "tenant-1", "hello@example.test", "type-1", { ...request, email: "different@example.test" }),
    /booking_request_id_conflict/,
  );
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events WHERE booking_request_id IS NOT NULL").get().count, 1);
});

test("public lookup is tenant-scoped, omits private records, and rejects inactive types", async () => {
  const { sqlite, db } = fixture();
  const date = futureDate();
  const details = await getPublicBookingDetails(db, "tenant-1", "type-1", date, "public-key");
  assert.equal(details.name, "Consultation");
  assert.ok(!JSON.stringify(details).includes("owner-1"));
  assert.ok(!JSON.stringify(details).includes("hello@example.test"));
  await assert.rejects(getPublicBookingDetails(db, "tenant-2", "type-1", date, "public-key"), /booking_owner_not_provisioned/);
  sqlite.prepare("UPDATE booking_events SET enabled=0 WHERE user_id='owner-1' AND id='type-1'").run();
  await assert.rejects(getPublicBookingDetails(db, "tenant-1", "type-1", date, "public-key"), /booking_type_not_found/);
});

test("capacity two permits a long appointment across separate busy events but counts true partial overlaps", async () => {
  const { sqlite, db } = fixture({ capacity: 2 });
  const date = futureDate();
  const start = Date.parse(slotAt(date, "12:00"));
  const insert = sqlite.prepare("INSERT INTO calendar_events (id,user_id,title,description,location,attendees,color,repeat,repeat_days,excluded_occurrences,time_zone,starts_at,ends_at,helloada_capacity_revision,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
  let revision = await assertCalendarMutationCapacity(db, "owner-1", [{ startsAt: start, endsAt: start + 15 * 60_000 }]);
  insert.run("busy-a", "owner-1", "Busy A", "", "", "[]", "blue", "none", "[]", "[]", "UTC", start, start + 15 * 60_000, revision, Date.now(), Date.now());
  revision = await assertCalendarMutationCapacity(db, "owner-1", [{ startsAt: start + 30 * 60_000, endsAt: start + 45 * 60_000 }]);
  insert.run("busy-b", "owner-1", "Busy B", "", "", "[]", "blue", "none", "[]", "[]", "UTC", start + 30 * 60_000, start + 45 * 60_000, revision, Date.now(), Date.now());
  await assert.doesNotReject(assertCalendarMutationCapacity(db, "owner-1", [{ startsAt: start, endsAt: start + 60 * 60_000 }]));
  await assert.rejects(assertCalendarMutationCapacity(db, "owner-1", [{ startsAt: start + 10 * 60_000, endsAt: start + 40 * 60_000 }, { startsAt: start + 10 * 60_000, endsAt: start + 40 * 60_000 }]), /calendar_capacity_exceeded/);
});


test("capacity reductions report existing over-capacity periods without changing appointments", async () => {
  const { sqlite, db } = fixture({ capacity: 3 });
  const start = Date.parse(slotAt(futureDate(), "12:00"));
  const insert = sqlite.prepare("INSERT INTO calendar_events (id,user_id,title,description,location,attendees,color,repeat,repeat_days,excluded_occurrences,time_zone,starts_at,ends_at,helloada_capacity_revision,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
  for (let index = 0; index < 3; index++) {
    const revision = sqlite.prepare("SELECT revision FROM helloada_booking_settings WHERE user_id='owner-1'").get().revision;
    insert.run("existing-" + index, "owner-1", "Existing " + index, "", "", "[]", "blue", "none", "[]", "[]", "UTC", start, start + 30 * 60_000, revision, Date.now(), Date.now());
  }
  assert.deepEqual(await getBookingCapacityWarnings(db, "owner-1", 3), {
    overlappingPeriods: 0, maxConcurrentAppointments: 3, horizonDays: 365,
  });
  assert.deepEqual(await getBookingCapacityWarnings(db, "owner-1", 2), {
    overlappingPeriods: 1, maxConcurrentAppointments: 2, horizonDays: 365,
  });
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events").get().count, 3);
});


test("booking types use immutable IDs and compare-and-swap integer revisions", async () => {
  const { sqlite, db } = fixture();
  const created = await createBookingType(db, "owner-1", {
    name: "Massage", slug: "massage", description: "One-to-one massage", durationMinutes: 120,
  });
  assert.match(created.id, /^ha_booking_[a-f0-9]{32}$/);
  assert.equal(created.revision, 1);
  const updated = await updateBookingType(db, "owner-1", created.id, 1, {
    slug: "massage", name: "Extended massage", description: "Updated service", durationMinutes: 150,
  });
  assert.equal(updated.id, created.id);
  assert.equal(updated.revision, 2);
  await assert.rejects(updateBookingType(db, "owner-1", created.id, 1, {
    name: "Stale edit", description: "", durationMinutes: 120,
  }), /booking_type_revision_conflict/);
  const inactive = await deactivateBookingType(db, "owner-1", created.id, 2);
  assert.equal(inactive.id, created.id);
  assert.equal(inactive.enabled, false);
  assert.equal(inactive.revision, 3);
  assert.equal(sqlite.prepare("SELECT name FROM booking_events WHERE id=?").get(created.id).name, "Extended massage");
});
