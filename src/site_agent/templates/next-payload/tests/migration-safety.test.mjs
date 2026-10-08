import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const migration = readFileSync(new URL('../src/migrations/20261006_061835_helloada_owner_handoff.ts', import.meta.url), 'utf8')
const snapshot = JSON.parse(readFileSync(new URL('../src/migrations/20261006_061835_helloada_owner_handoff.json', import.meta.url), 'utf8'))

test('owner handoff preserves Growth operation tables created by the preceding migration', () => {
  const up = migration.slice(migration.indexOf('export async function up'), migration.indexOf('export async function down'))
  const down = migration.slice(migration.indexOf('export async function down'))
  for (const table of ['helloada_growth_candidates', 'helloada_growth_operations']) {
    assert.equal(up.includes('DROP TABLE `' + table + '`'), false)
    assert.equal(down.includes('CREATE TABLE `' + table + '`'), false)
  }
})

test('owner handoff adds the external subject without invalidating existing Payload users', () => {
  assert.ok(migration.replaceAll('\\`', '`').includes('ALTER TABLE `users` ADD `helloada_subject` text;'))
  assert.equal(snapshot.tables.users.columns.helloada_subject.notNull, false)
  assert.equal(snapshot.tables.users.indexes.users_helloada_subject_idx.isUnique, true)
  assert.ok(snapshot.tables.helloada_growth_candidates)
  assert.ok(snapshot.tables.helloada_growth_operations)
})
