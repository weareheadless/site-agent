import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import {
  claimBookingConfirmation,
  finishBookingConfirmation,
  listBookingNotificationIssues,
} from "../integration-src/src/lib/helloada-booking-notifications.ts";

function binding(sqlite) {
  return {
    prepare(sql) {
      let values = [];
      return {
        bind(...args) { values = args; return this; },
        async first() { return sqlite.prepare(sql).get(...values) ?? null; },
        async all() { return { results: sqlite.prepare(sql).all(...values) }; },
        async run() {
          const result = sqlite.prepare(sql).run(...values);
          return { meta: { changes: Number(result.changes) } };
        },
      };
    },
  };
}

test("notification retry claims only delivery and never creates a duplicate appointment", async () => {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec([
    "CREATE TABLE domains (id TEXT PRIMARY KEY, hostname TEXT NOT NULL, status TEXT NOT NULL);",
    "CREATE TABLE mailboxes (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, domain_id TEXT NOT NULL, local_part TEXT NOT NULL, disabled INTEGER NOT NULL);",
    "CREATE TABLE calendar_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, title TEXT NOT NULL, starts_at INTEGER NOT NULL, time_zone TEXT, booking_request_id TEXT, helloada_answers TEXT, helloada_booking_type_name TEXT, helloada_booking_duration_minutes INTEGER, helloada_notification_state TEXT, helloada_notification_lease_until INTEGER, updated_at INTEGER);",
    "INSERT INTO domains VALUES ('domain-1','example.test','active');",
    "INSERT INTO mailboxes VALUES ('mailbox-1','owner-1','domain-1','hello',0);",
  ].join("\n"));
  sqlite.prepare("INSERT INTO calendar_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)").run("event-1", "owner-1", "mailbox-1", "Massage - Ada Client", 1791741600000, "America/Cancun", "request-1", JSON.stringify({ name: "Ada Client", email: "visitor@example.test" }), "Massage", 120, "pending", null, 1000);
  const db = binding(sqlite);
  const before = await listBookingNotificationIssues(db, "owner-1");
  assert.equal(before.length, 1);
  assert.doesNotMatch(JSON.stringify(before), /visitor@example\.test/);

  const claims = await Promise.all([
    claimBookingConfirmation(db, "owner-1", "event-1", 2_000),
    claimBookingConfirmation(db, "owner-1", "event-1", 2_000),
  ]);
  assert.equal(claims.filter(Boolean).length, 1);
  const message = claims.find(Boolean);
  assert.equal(message.to, "visitor@example.test");
  assert.equal(message.from, "hello@example.test");
  assert.match(message.text, /120 minutes/);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events").get().count, 1);
  assert.equal((await listBookingNotificationIssues(db, "owner-1", 2_001)).length, 0);

  await finishBookingConfirmation(db, "owner-1", "event-1", false);
  assert.equal((await listBookingNotificationIssues(db, "owner-1", 2_002)).length, 1);
  const retry = await claimBookingConfirmation(db, "owner-1", "event-1", 2_003);
  assert.ok(retry);
  await finishBookingConfirmation(db, "owner-1", "event-1", true);
  assert.equal((await listBookingNotificationIssues(db, "owner-1", 2_004)).length, 0);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS count FROM calendar_events").get().count, 1);
  assert.equal(sqlite.prepare("SELECT helloada_notification_state FROM calendar_events WHERE id='event-1'").get().helloada_notification_state, "sent");
});
