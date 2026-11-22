/** Locale-table parent indexes for the D1 adapter.
 *
 *  Payload builds each localized collection's locale table with one unique
 *  index on `(_locale, _parent_id)`. That order serves a lookup by locale, but
 *  Payload resolves a document's locales with a correlated subquery filtered on
 *  `_parent_id` alone:
 *
 *    (select ... from "<table>_locales" l where l._parent_id = "<table>".id)
 *
 *  SQLite cannot use a `(_locale, _parent_id)` index for a `_parent_id`-only
 *  predicate, so it scans every locale row once per row of the outer query. The
 *  cost is therefore (outer rows) x (all locale rows). On a catalogue-sized
 *  tenant that is 7,096 latest versions x 42,039 locale rows = 298 million rows
 *  read for one `limit 1` draft read: about 12 seconds, which exceeds the
 *  remote-binding request window, leaves the release verifier's D1 proxy
 *  session unusable, and makes every later check report a transport failure
 *  instead of its own result. A filtered listing read costs about 125,000 rows
 *  to render a single page.
 *
 *  The index is declared here rather than only in a migration so it is part of
 *  the schema generated from this config. A migration snapshot alone is not
 *  durable: Payload's `migrate:create` diffs the committed snapshot against the
 *  schema generated from the config, so an index present only in a snapshot is
 *  emitted as `DROP INDEX` by the next schema change. This uses the documented
 *  `beforeSchemaInit` hook, which runs once Payload has registered the raw
 *  table definitions and before it builds Drizzle tables from them.
 *
 *  Additive only: no column is altered, reordered or dropped and no data moves.
 *  Measured on a production-shaped local copy, the correlated locale read goes
 *  from 176 ms to 1.5 ms and stops scanning the locale table.
 */

import type { SQLiteSchemaHook } from '@payloadcms/drizzle/sqlite'

/** The raw table shape Payload's schema builder registers per collection. */
type RawTable = {
  name?: string
  indexes?: Record<string, { name: string; on: string[]; unique?: boolean }>
}

/** Add a `_parent_id` index to every locale table in the raw schema. */
export const localeParentIndexes = (rawTables: Record<string, RawTable>): void => {
  for (const [tableName, table] of Object.entries(rawTables)) {
    if (!tableName.endsWith('_locales') || !table) continue
    const indexes = (table.indexes ??= {})
    // An index that already leads with `_parent_id` makes this redundant.
    const alreadyServed = Object.values(indexes).some(
      (index) => Array.isArray(index.on) && index.on[0] === '_parentID',
    )
    if (alreadyServed) continue
    indexes.localeParent = {
      name: `${tableName}_parent_id_idx`,
      on: ['_parentID'],
      unique: false,
    }
  }
}

/** The adapter hook Payload calls before it builds tables from the raw schema.
 *
 *  Payload's published `SQLiteSchemaHookArgs` omits `adapter`, although every
 *  hook is invoked with it, so the runtime field is reached through a narrow
 *  cast. Payload replaces `adapter.tables` with whatever this returns, so the
 *  incoming schema is handed back unchanged.
 */
export const localeParentIndexHook: SQLiteSchemaHook = (args) => {
  const adapter = (args as unknown as { adapter?: { rawTables?: Record<string, RawTable> } }).adapter
  const rawTables = adapter?.rawTables
  if (rawTables) localeParentIndexes(rawTables)
  return args.schema
}
