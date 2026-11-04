import { getPayloadCloudflareContext } from '@/lib/cloudflare-context'
import { hashJson, stableJson } from '@/lib/payload-hash'
import {
  expectedRevisionOf, isRevisionHash, readCollectionRevision, readGlobalRevision, revisionHash,
} from '@/lib/payload-revision'
import { fieldValueMatches } from '@/lib/payload-field-match'
import { runtimeValue } from '@/lib/runtime-env'

export { hashJson, stableJson } from '@/lib/payload-hash'

type JsonObject = Record<string, unknown>

type D1Statement = {
  bind(...values: unknown[]): D1Statement
  first<T = Record<string, unknown>>(): Promise<T | null>
  run(): Promise<{ meta?: { changes?: number } }>
}

type D1Database = { prepare(sql: string): D1Statement }

const database = async () => {
  const context = await getPayloadCloudflareContext() as unknown as { env?: { D1?: D1Database } }
  const binding = context.env?.D1
  if (!binding) throw new Error('The managed Growth contract requires the tenant D1 binding')
  return binding
}

const now = () => new Date().toISOString()

export const tenantId = () => runtimeValue('HELLOADA_TENANT_ID')

export const asObject = (value: unknown): JsonObject =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {}

export const projectDocument = (document: JsonObject, fields: string[]) => {
  const projection = Object.fromEntries([...new Set(fields)].sort().map((field) => [field, document[field] ?? null]))
  // Match the gateway's JSON response: nested undefined object properties are
  // omitted and undefined array entries become null. Keep declared top-level
  // missing fields explicit as null before the roundtrip.
  return JSON.parse(JSON.stringify(projection)) as JsonObject
}

export const candidateRow = async (packageHash: string) => {
  const db = await database()
  const result = await db.prepare(
    'SELECT * FROM helloada_growth_candidates WHERE package_hash = ?1',
  ).bind(packageHash).first()
  return result ? asObject(result) : undefined
}

export const operationByKey = async (operationKey: string) => {
  const db = await database()
  const row = await db.prepare('SELECT * FROM helloada_growth_operations WHERE operation_key = ?1')
    .bind(operationKey).first()
  return row ? asObject(row) : undefined
}

export const saveCandidate = async (packageData: JsonObject, packageHash: string, result: JsonObject) => {
  const timestamp = now()
  const db = await database()
  await db.prepare(`INSERT INTO helloada_growth_candidates
    (package_hash, tenant_id, initiative_id, collection_name, document_id, base_hash, candidate_hash, package_json, state, result_json, created_at, updated_at)
    VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'validated', ?9, ?10, ?10)
    ON CONFLICT(package_hash) DO UPDATE SET state = 'validated', result_json = excluded.result_json, updated_at = excluded.updated_at
  `).bind(
    packageHash,
    tenantId(),
    String(packageData.initiativeId || ''),
    String(packageData.collection || ''),
    String(packageData.documentId || ''),
    String(packageData.baseHash || ''),
    String(packageData.candidateHash || ''),
    stableJson(packageData),
    stableJson(result),
    timestamp,
  ).run()
}

export const claimOperation = async (operationKey: string, documentKey: string, packageHash: string) => {
  const timestamp = now()
  const db = await database()
  const inserted = await db.prepare(`INSERT OR IGNORE INTO helloada_growth_operations
    (operation_key, document_key, tenant_id, package_hash, state, created_at, updated_at)
    VALUES (?1, ?2, ?3, ?4, 'writing', ?5, ?5)`)
    .bind(operationKey, documentKey, tenantId(), packageHash, timestamp).run()
  const row = await db.prepare(
    'SELECT * FROM helloada_growth_operations WHERE operation_key = ?1',
  ).bind(operationKey).first()
  return { inserted: Number(inserted.meta?.changes || 0) > 0, row: row ? asObject(row) : undefined }
}

export const activeOperation = async (documentKey: string, operationKey: string) => {
  const db = await database()
  const row = await db.prepare(
    "SELECT * FROM helloada_growth_operations WHERE document_key = ?1 AND state IN ('writing', 'uncertain') AND operation_key != ?2 ORDER BY updated_at DESC LIMIT 1",
  ).bind(documentKey, operationKey).first()
  return row ? asObject(row) : undefined
}

export const completeOperation = async (operationKey: string, result: JsonObject) => {
  const db = await database()
  await db.prepare(`UPDATE helloada_growth_operations
    SET state = 'completed', result_json = ?1, updated_at = ?2 WHERE operation_key = ?3 AND state = 'writing'`)
    .bind(stableJson(result), now(), operationKey).run()
}

/** Settle an interrupted receipt only after the destination state is verified. */
export const reconcileOperation = async (operationKey: string, result: JsonObject) => {
  const db = await database()
  await db.prepare(`UPDATE helloada_growth_operations
    SET state = 'completed', result_json = ?1, updated_at = ?2
    WHERE operation_key = ?3 AND state IN ('writing', 'uncertain')`)
    .bind(stableJson(result), now(), operationKey).run()
}

/** Retire an explicitly abandoned uncertain preparation only if its exact row is unchanged. */
export const retireObsoleteOperation = async (input: {
  operationKey: string
  documentKey: string
  packageHash: string
  expectedUpdatedAt: string
  expectedResultHash: string
  priorResultJson: string
  receipt: JsonObject
}) => {
  const db = await database()
  const result = await db.prepare(`UPDATE helloada_growth_operations
    SET state = 'completed', result_json = ?1, updated_at = ?2
    WHERE operation_key = ?3 AND document_key = ?4 AND tenant_id = ?5
      AND package_hash = ?6 AND state = 'uncertain' AND updated_at = ?7
      AND result_json = ?8`)
    .bind(stableJson(input.receipt), now(), input.operationKey, input.documentKey,
      tenantId(), input.packageHash, input.expectedUpdatedAt, input.priorResultJson).run()
  return Number(result.meta?.changes || 0) === 1
}

/** Persist the exact desired document hash before invoking a Payload write. */
export const prepareOperation = async (operationKey: string, intent: JsonObject) => {
  const db = await database()
  await db.prepare(`UPDATE helloada_growth_operations
    SET result_json = ?1, updated_at = ?2 WHERE operation_key = ?3 AND state = 'writing'`)
    .bind(stableJson(intent), now(), operationKey).run()
}

export const failOperation = async (operationKey: string, result: JsonObject) => {
  const db = await database()
  await db.prepare(`UPDATE helloada_growth_operations
    SET state = 'uncertain', result_json = ?1, updated_at = ?2 WHERE operation_key = ?3 AND state = 'writing'`)
    .bind(stableJson(result), now(), operationKey).run()
}

export const operationResult = (row: JsonObject | undefined) => {
  if (!row?.result_json) return undefined
  try {
    const result = JSON.parse(String(row.result_json))
    return result && typeof result === 'object' ? result as JsonObject : undefined
  } catch {
    return undefined
  }
}

export const operationContext = (req: { context?: Record<string, unknown> }, operationKey: string) => {
  req.context = { ...(req.context || {}), helloAdaGrowthOperation: operationKey }
}

type WriteRequest = { context?: Record<string, unknown>; locale?: unknown; payload?: any }
type WriteLease = { operationKey: string; depth: number; attempted: boolean; settled: boolean; intent?: JsonObject }
const writeLeaseKey = Symbol.for('helloada.payload.write-lease')
const contentWriteKey = 'payload:content'
const writeConflict = (message: string) => Object.assign(new Error(message), { status: 409, statusCode: 409 })
const writeContext = (req: WriteRequest | undefined) => {
  if (!req) throw writeConflict('Payload write request identity is required.')
  req.context ||= {}
  return req.context as Record<PropertyKey, unknown>
}

/** The revision a caller reviewed, in the shape a lease intent stores. */
const leaseIntent = (req: WriteRequest | undefined, collection?: string, id?: unknown): JsonObject | undefined => {
  const expected = expectedRevisionOf(req)
  if (expected) {
    return expected.kind === 'collection'
      ? { collection: expected.collection, id: expected.id, locale: expected.locale, expectedHash: expected.hash }
      : { global: expected.global, locale: expected.locale, expectedHash: expected.hash }
  }
  if (!collection) return undefined
  // Without a reviewed revision we can still record the target, but not a base
  // hash, so a failed write cannot be proven harmless from it. A create has no
  // document identity yet; the null id still attributes the lease to its write.
  return {
    collection,
    id: id === undefined || id === null || id === '' ? null : String(id),
    locale: typeof req?.locale === 'string' ? req.locale : undefined,
  }
}

const acquireContentWrite = async (
  req: WriteRequest | undefined,
  intent?: JsonObject,
): Promise<WriteLease> => {
  const context = writeContext(req)
  const nested = context[writeLeaseKey] as WriteLease | undefined
  if (nested && !nested.settled) {
    nested.depth += 1
    return nested
  }
  const tenant = tenantId()
  if (!tenant) throw writeConflict('The Payload tenant identity is not configured.')
  const operationKey = `payload-write:${tenant}:${crypto.randomUUID()}`
  const packageHash = await hashJson({ tenant, scope: contentWriteKey })
  // The existing D1 unique-writing-document index is the atomic acquisition.
  // All native operations, including bulk operations, use the same tenant-local
  // content key. A request-local depth only permits that operation's own hooks.
  const claimed = await claimOperation(operationKey, contentWriteKey, packageHash)
  if (!claimed.inserted) {
    // A lease left by a failed Local API write blocks every later edit. Release
    // it only when the current revision proves that write had no effect.
    const blocking = await activeOperation(contentWriteKey, operationKey)
    const released = blocking && req?.payload
      ? await recoverBlockingLease(req.payload, blocking).catch(() => false)
      : false
    const retried = released ? await claimOperation(operationKey, contentWriteKey, packageHash) : claimed
    if (!retried.inserted) {
      throw writeConflict('Another website write is in progress. No edit was applied; reload after it completes.')
    }
  }
  const unresolved = await activeOperation(contentWriteKey, operationKey)
  if (unresolved) {
    await completeOperation(operationKey, { state: 'blocked-before-write', blockedBy: String(unresolved.operation_key) })
    throw writeConflict('A prior website write has an unverified outcome. Reconcile that operation before writing again.')
  }
  const lease: WriteLease = { operationKey, depth: 1, attempted: false, settled: false, intent }
  context[writeLeaseKey] = lease
  // Persist the intent before any Payload mutation so a later attempt can prove
  // what this write was about to change.
  if (intent) await prepareOperation(operationKey, { state: 'write-intent', scope: contentWriteKey, ...intent })
  return lease
}

/**
 * Decide whether a failed write may release its lease.
 *
 * Payload's D1 adapter has no transactions, so a failure can leave partial
 * effects. Only two outcomes are provable: the revision is still the one the
 * write started from (no effect), or it already matches the data the write
 * intended to persist (applied). A pre-persistence rejection (Payload validation
 * or access error) is also provably harmless.
 */
const settleFailedWrite = async (req: WriteRequest, lease: WriteLease, error: unknown) => {
  if (!lease.attempted) {
    await completeOperation(lease.operationKey, { state: 'no-effect', scope: contentWriteKey, rejected: true })
    return
  }
  const outcome = await settleStrandedWrite(req.payload, lease.intent, error, {
    operation_key: lease.operationKey, state: 'writing',
  }).catch(() => 'blocked' as const)
  if (outcome === 'settled-no-effect' || outcome === 'settled-applied') return
  await failOperation(lease.operationKey, { state: 'uncertain', scope: contentWriteKey })
}

const settleContentWrite = async (req: WriteRequest | undefined, failed: boolean, error?: unknown) => {
  if (!req?.context) return
  const context = req.context as Record<PropertyKey, unknown>
  const lease = context[writeLeaseKey] as WriteLease | undefined
  if (!lease || lease.settled) return
  if (!failed && lease.depth > 1) { lease.depth -= 1; return }
  if (failed) await settleFailedWrite(req, lease, error)
  else await completeOperation(lease.operationKey, { state: 'completed', scope: contentWriteKey })
  lease.settled = true
  delete context[writeLeaseKey]
}

/** Hold the same native-writer boundary across an exact multi-document action. */
export const withPayloadWriteGuard = async <T>(req: WriteRequest, action: () => Promise<T>): Promise<T> => {
  await acquireContentWrite(req, leaseIntent(req))
  try {
    const result = await action()
    await settleContentWrite(req, false)
    return result
  } catch (error) {
    await settleContentWrite(req, true, error)
    throw error
  }
}

export const assertNativeWriteAllowed = async (
  collection: string, id: unknown, req: WriteRequest | undefined, operation = 'update', _data?: unknown,
) => {
  if (operation === 'complete') {
    await settleContentWrite(req, false)
    return
  }
  if (operation === 'failed') {
    // The HTTP error hook hands us the actual error; its status decides whether
    // the write was rejected before persistence.
    await settleContentWrite(req, true, _data)
    return
  }
  const lease = await acquireContentWrite(req, leaseIntent(req, collection, id))
  try {
    const currentOperation = String(req?.context?.helloAdaGrowthOperation || '')
    const row = id
      ? await activeOperation(`${collection}:${String(id)}`, currentOperation)
      : await (await database()).prepare(
        "SELECT * FROM helloada_growth_operations WHERE document_key LIKE ?1 AND state IN ('writing', 'uncertain') AND operation_key != ?2 LIMIT 1",
      ).bind(`${collection}:%`, currentOperation).first()
    if (row) throw writeConflict('This document is being prepared by Ada. The owner edit was not overwritten; review the current operation.')
    lease.attempted = true
  } catch (error) {
    // No Payload write has crossed this hook. Release only this nested entry;
    // an enclosing action still owns its lease and any earlier effects.
    await settleContentWrite(req, false)
    throw error
  }
}

export type RecoveryOutcome = 'none' | 'settled-no-effect' | 'settled-applied' | 'blocked'

type RevisionTarget =
  | { kind?: 'collection'; collection: string; id: string; locale?: string; expectedHash: string; data?: JsonObject }
  | { kind: 'global'; global: string; locale?: string; expectedHash: string; data?: JsonObject }

/**
 * Attribute a lease row to the write that is settling it. A row from another
 * document must never be settled by this write's evidence.
 */
const intentMatches = (intent: JsonObject | undefined, target: JsonObject): boolean => {
  if (!intent) return true
  if (typeof intent.global === 'string' || target.kind === 'global') {
    return String(intent.global || '') === String(target.global || '')
  }
  const intentId = intent.id === undefined || intent.id === null ? '' : String(intent.id)
  const targetId = target.id === undefined || target.id === null ? '' : String(target.id)
  return String(intent.collection || '') === String(target.collection || '') && intentId === targetId
}

const currentRevision = async (payload: any, target: RevisionTarget): Promise<JsonObject> =>
  target.kind === 'global'
    ? readGlobalRevision(payload, { global: target.global, locale: target.locale })
    : readCollectionRevision(payload, { collection: target.collection, id: target.id, locale: target.locale })

/**
 * Settle a stranded content lease only with proof of what happened.
 *
 * The tenant has exactly one content writer at a time, so a lease left in
 * `writing` blocks every later edit. Payload's Local API does not run the HTTP
 * `afterError` hook, so a failed write can strand it. We settle it only when the
 * current revision is still the one the interrupted write started from (no
 * effect) or already matches the data that write intended to persist (applied).
 * Anything else stays blocked for explicit reconciliation.
 */
export const recoverContentWrite = async (
  payload: any,
  target: RevisionTarget,
  row?: JsonObject,
): Promise<RecoveryOutcome> => {
  const blocking = row ?? await activeOperation(contentWriteKey, '')
  if (!blocking) return 'none'
  if (blocking.state !== 'writing') return 'blocked'
  if (!intentMatches(operationResult(blocking), target as unknown as JsonObject)) return 'blocked'
  if (!isRevisionHash(target.expectedHash)) return 'blocked'
  let current: JsonObject
  try {
    current = await currentRevision(payload, target)
  } catch {
    return 'blocked'
  }
  const hash = await revisionHash(current)
  const noEffect = hash === target.expectedHash
  const applied = !noEffect && target.data ? fieldValueMatches(current, target.data) : false
  if (!noEffect && !applied) return 'blocked'
  await completeOperation(String(blocking.operation_key), {
    state: noEffect ? 'no-effect' : 'applied',
    scope: contentWriteKey,
    recovered: true,
  })
  return noEffect ? 'settled-no-effect' : 'settled-applied'
}

/**
 * Settle the tenant content lease after a failed Local API write.
 *
 * Payload's Local API never runs the HTTP `afterError` hook, so every caller of
 * `payload.create/update/updateGlobal/restoreVersion` must settle on failure.
 * A known revision makes the outcome provable; otherwise a pre-persistence
 * (4xx) rejection is still provably harmless. Anything else stays blocked.
 */
export const settleStrandedWrite = async (
  payload: any,
  target: JsonObject | undefined,
  error: unknown,
  row?: JsonObject,
): Promise<RecoveryOutcome> => {
  const blocking = row ?? await activeOperation(contentWriteKey, '')
  if (!blocking) return 'none'
  if (blocking.state !== 'writing') return 'blocked'
  if (target && !intentMatches(operationResult(blocking), target)) return 'blocked'
  const expectedHash = typeof target?.expectedHash === 'string' ? target.expectedHash : ''
  const isGlobal = target?.kind === 'global' && typeof target.global === 'string'
  const isCollection = typeof target?.collection === 'string' && target.id !== undefined && target.id !== null && String(target.id) !== ''
  if (payload && isRevisionHash(expectedHash) && (isGlobal || isCollection)) {
    const proof = await recoverContentWrite(payload, {
      ...(isGlobal
        ? { kind: 'global' as const, global: String(target!.global) }
        : { collection: String(target!.collection), id: String(target!.id) }),
      locale: typeof target!.locale === 'string' && target!.locale ? target!.locale : undefined,
      expectedHash,
      data: (target!.data && typeof target!.data === 'object' ? target!.data : undefined) as JsonObject | undefined,
    }, blocking)
    // A revision read proves the write landed even when the caller saw an error.
    if (proof !== 'blocked') return proof
  }
  const status = Number((error as { status?: number; statusCode?: number } | undefined)?.status
    ?? (error as { statusCode?: number } | undefined)?.statusCode)
  if (Number.isFinite(status) && status >= 400 && status < 500) {
    // Payload validates before it persists, so a client error is no effect.
    await completeOperation(String(blocking.operation_key), { state: 'no-effect', scope: contentWriteKey, status })
    return 'settled-no-effect'
  }
  return 'blocked'
}

/**
 * Run one Local API write and leave the shared lease settled.
 *
 * Success is settled by the schema hook after Payload persists. On failure the
 * recovery proof decides whether the write had no effect (safe to release) or
 * actually landed; an unprovable outcome stays blocked and is reported.
 */
export const withRecoveredWrite = async <T>(
  payload: any,
  target: JsonObject | undefined,
  action: () => Promise<T>,
): Promise<T> => {
  try {
    return await action()
  } catch (error) {
    const outcome = await settleStrandedWrite(payload, target, error).catch(() => 'blocked' as const)
    if (outcome === 'blocked') {
      // The outcome is genuinely unknown. Record that, so the lease blocks the
      // next writer as uncertain rather than looking like a live write.
      const blocking = await activeOperation(contentWriteKey, '').catch(() => undefined)
      if (blocking?.state === 'writing' && target
        && intentMatches(operationResult(blocking), target)) {
        await failOperation(String(blocking.operation_key), { state: 'uncertain', scope: contentWriteKey, reason: 'unverified-write' })
          .catch(() => undefined)
      }
      console.error('helloada_payload_write_unverified', {
        scope: typeof target?.global === 'string' ? target.global : target?.collection,
        documentId: target?.id === undefined ? undefined : String(target.id),
        errorName: error instanceof Error ? error.name : 'UnknownError',
      })
    }
    throw error
  }
}

/** Release a blocking lease whose recorded intent proves the interrupted write had no effect. */
export const recoverBlockingLease = async (payload: any, blocking: JsonObject): Promise<boolean> => {
  const intent = operationResult(blocking)
  if (!intent || intent.state !== 'write-intent' || !isRevisionHash(intent.expectedHash)) return false
  const collection = typeof intent.collection === 'string' ? intent.collection : ''
  const id = intent.id === undefined || intent.id === null ? '' : String(intent.id)
  if (!collection || !id) return false
  const outcome = await recoverContentWrite(payload, {
    collection,
    id,
    locale: typeof intent.locale === 'string' && intent.locale ? intent.locale : undefined,
    expectedHash: String(intent.expectedHash),
  }, blocking).catch(() => 'blocked' as const)
  return outcome === 'settled-no-effect' || outcome === 'settled-applied'
}

/**
 * Settle the shared lease from Payload's HTTP `afterError` hook.
 *
 * Prepend this to a collection/global so it runs before the schema's own
 * `afterError`: the lease is removed from the request context once settled, so
 * the later hook becomes a no-op instead of marking a harmless validation
 * failure as uncertain.
 */
export const writeFailureHook = (scope: string) => async ({
  req, error,
}: { req?: WriteRequest; error?: unknown }) => {
  await assertNativeWriteAllowed(scope, undefined, req, 'failed', error)
}

/** Put the settling error hook first while preserving every existing hook. */
export const withWriteFailureSettlement = <T extends { slug: string; hooks?: Record<string, unknown[]> }>(
  items: T[],
): T[] => items.map((item) => ({
  ...item,
  hooks: {
    ...(item.hooks || {}),
    afterError: [writeFailureHook(item.slug), ...((item.hooks?.afterError as unknown[]) || [])],
  },
}))

export const contractCapabilities = [
  'conditionalDraft',
  'immutablePreview',
  'exactApproval',
  'allPublisherGuard',
  'effectReceipts',
  'obsoleteOperationRetirement',
] as const
