import { getPayloadCloudflareContext } from '@/lib/cloudflare-context'
import { hashJson, stableJson } from '@/lib/payload-hash'
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

type WriteRequest = { context?: Record<string, unknown> }
type WriteLease = { operationKey: string; depth: number; attempted: boolean; settled: boolean }
const writeLeaseKey = Symbol.for('helloada.payload.write-lease')
const contentWriteKey = 'payload:content'
const writeConflict = (message: string) => Object.assign(new Error(message), { status: 409, statusCode: 409 })
const writeContext = (req: WriteRequest | undefined) => {
  if (!req) throw writeConflict('Payload write request identity is required.')
  req.context ||= {}
  return req.context as Record<PropertyKey, unknown>
}

const acquireContentWrite = async (req: WriteRequest | undefined): Promise<WriteLease> => {
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
  if (!claimed.inserted) throw writeConflict('Another website write is in progress. No edit was applied; reload after it completes.')
  const unresolved = await activeOperation(contentWriteKey, operationKey)
  if (unresolved) {
    await completeOperation(operationKey, { state: 'blocked-before-write', blockedBy: String(unresolved.operation_key) })
    throw writeConflict('A prior website write has an unverified outcome. Reconcile that operation before writing again.')
  }
  const lease: WriteLease = { operationKey, depth: 1, attempted: false, settled: false }
  context[writeLeaseKey] = lease
  return lease
}

const settleContentWrite = async (req: WriteRequest | undefined, failed: boolean) => {
  if (!req?.context) return
  const context = req.context as Record<PropertyKey, unknown>
  const lease = context[writeLeaseKey] as WriteLease | undefined
  if (!lease || lease.settled) return
  if (!failed && lease.depth > 1) { lease.depth -= 1; return }
  if (failed && lease.attempted) await failOperation(lease.operationKey, { state: 'uncertain', scope: contentWriteKey })
  else await completeOperation(lease.operationKey, { state: 'completed', scope: contentWriteKey })
  lease.settled = true
  delete context[writeLeaseKey]
}

/** Hold the same native-writer boundary across an exact multi-document action. */
export const withPayloadWriteGuard = async <T>(req: WriteRequest, action: () => Promise<T>): Promise<T> => {
  await acquireContentWrite(req)
  try {
    const result = await action()
    await settleContentWrite(req, false)
    return result
  } catch (error) {
    await settleContentWrite(req, true)
    throw error
  }
}

export const assertNativeWriteAllowed = async (
  collection: string, id: unknown, req: WriteRequest | undefined, operation = 'update', _data?: unknown,
) => {
  if (operation === 'complete' || operation === 'failed') {
    await settleContentWrite(req, operation === 'failed')
    return
  }
  const lease = await acquireContentWrite(req)
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

export const contractCapabilities = [
  'conditionalDraft',
  'immutablePreview',
  'exactApproval',
  'allPublisherGuard',
  'effectReceipts',
  'obsoleteOperationRetirement',
] as const
