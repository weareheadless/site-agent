import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { ensureTenantBookingOwner } from "../../../src/site_agent/templates/next-payload/mailflare-owner-gate.ts";

function fixture() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(`
    CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL, password_hash TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, is_primary_admin INTEGER NOT NULL, can_manage_mailboxes INTEGER NOT NULL, can_manage_domains INTEGER NOT NULL, can_manage_users INTEGER NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
    CREATE TABLE helloada_tenant_owners (tenant_id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE TABLE helloada_booking_settings (user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, time_zone TEXT NOT NULL, weekly_availability TEXT NOT NULL, max_concurrent_appointments INTEGER NOT NULL, minimum_notice_hours INTEGER NOT NULL, booking_window_days INTEGER NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL);
  `);
  const statement = (sql) => {
    let values = [];
    const item = {
      bind(...args) { values = args; return item; },
      async first() { return sqlite.prepare(sql).get(...values) ?? null; },
      async all() { return { results: sqlite.prepare(sql).all(...values) }; },
      async run() {
        const result = sqlite.prepare(sql).run(...values);
        return { meta: { changes: Number(result.changes) } };
      },
    };
    return item;
  };
  return { sqlite, db: { prepare: statement } };
}

test("booking configuration provisions the workspace owner the mailbox gate would", async () => {
  const { sqlite, db } = fixture();

  const ownerId = await ensureTenantBookingOwner(db, "site-test");
  assert.match(ownerId, /^ha_[0-9a-f]{64}$/);

  const owner = sqlite.prepare("SELECT id, email, password_hash, disabled FROM users WHERE id = ?").get(ownerId);
  assert.equal(owner.password_hash, "!helloada-payload-sso-only");
  assert.equal(owner.disabled, 0);
  assert.equal(owner.email, `${ownerId}@identity.helloada.invalid`);

  const mapping = sqlite.prepare("SELECT owner_user_id FROM helloada_tenant_owners WHERE tenant_id = ?").get("site-test");
  assert.equal(mapping.owner_user_id, ownerId);

  const settings = sqlite.prepare("SELECT enabled, revision FROM helloada_booking_settings WHERE user_id = ?").get(ownerId);
  assert.deepEqual({ ...settings }, { enabled: 0, revision: 1 });

  // A second call resolves the same owner and changes nothing.
  assert.equal(await ensureTenantBookingOwner(db, "site-test"), ownerId);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM users").get().n, 1);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM helloada_booking_settings").get().n, 1);
});

test("a registration built on a shared identity is repaired to the tenant's own", async () => {
  const { sqlite, db } = fixture();
  // The legacy shape: a registration naming an account derived from a platform
  // user rather than the tenant, with that account holding real mailbox access.
  sqlite.prepare("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    .run("owner-1", "owner@example.test", "a-real-hash", "Owner", "user", 0, 0, 0, 0, 0, 1);
  sqlite.prepare("INSERT INTO helloada_tenant_owners VALUES (?,?,?)").run("site-test", "owner-1", 1);
  sqlite.prepare("INSERT INTO helloada_booking_settings VALUES (?,?,?,?,?,?,?,?,?)")
    .run("owner-1", 1, "UTC", "[]", 1, 0, 365, 7, 1);

  const ownerId = await ensureTenantBookingOwner(db, "site-test");
  assert.match(ownerId, /^ha_[0-9a-f]{64}$/);
  assert.notEqual(ownerId, "owner-1", "the shared identity is not this tenant's owner");

  // The seat's own rows moved with it, so nothing it had is lost.
  const settings = sqlite.prepare("SELECT user_id, revision FROM helloada_booking_settings").all();
  assert.deepEqual(settings.map((row) => ({ ...row })), [{ user_id: ownerId, revision: 7 }]);

  // The superseded account is disabled, never deleted: its audit trail stays.
  assert.equal(sqlite.prepare("SELECT disabled FROM users WHERE id = ?").get("owner-1").disabled, 1);
  // And its credential is untouched -- a platform call never rewrites a person's.
  assert.equal(sqlite.prepare("SELECT password_hash FROM users WHERE id = ?").get("owner-1").password_hash, "a-real-hash");

  // A second call is a no-op: the repair is idempotent.
  assert.equal(await ensureTenantBookingOwner(db, "site-test"), ownerId);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM helloada_booking_settings").get().n, 1);
});

test("a disabled canonical owner fails closed instead of being replaced", async () => {
  const { sqlite, db } = fixture();
  // Canonical registration, but the account behind it cannot be used. Repair
  // must not paper over that by minting a different identity.
  const ownerId = await ensureTenantBookingOwner(db, "site-test");
  sqlite.prepare("UPDATE users SET disabled = 1 WHERE id = ?").run(ownerId);

  await assert.rejects(ensureTenantBookingOwner(db, "site-test"), /mailbox_owner_identity_invalid/);
  // No second account was created to route around the disabled one.
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM users").get().n, 1);
  assert.equal(sqlite.prepare("SELECT owner_user_id FROM helloada_tenant_owners WHERE tenant_id = ?").get("site-test").owner_user_id, ownerId);
});
