import { getPayloadCloudflareContext } from '@/lib/cloudflare-context'
import { stableJson } from '@/lib/payload-hash'

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

export const tenantId = () => String(process.env.HELLOADA_TENANT_ID || '').trim()

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

export const assertNativeWriteAllowed = async (collection: string, id: unknown, req: { context?: Record<string, unknown> } | undefined) => {
  if (!id) return
  const currentOperation = String(req?.context?.helloAdaGrowthOperation || '')
  const key = `${collection}:${String(id)}`
  const row = await activeOperation(key, currentOperation)
  if (row) throw new Error('This document is being prepared by Ada. The owner edit was not overwritten; review or wait for the current operation.')
}

export const contractCapabilities = [
  'conditionalDraft',
  'immutablePreview',
  'exactApproval',
  'allPublisherGuard',
  'effectReceipts',
  'obsoleteOperationRetirement',
] as const
