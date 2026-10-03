import { getCloudflareContext } from '@opennextjs/cloudflare'

type JsonObject = Record<string, unknown>

const database = async () => {
  const context = await getCloudflareContext({ async: true }) as unknown as { env?: { D1?: any } }
  const binding = context.env?.D1
  if (!binding) throw new Error('The managed Growth contract requires the tenant D1 binding')
  return binding
}

const now = () => new Date().toISOString()

export const tenantId = () => String(process.env.HELLOADA_TENANT_ID || '').trim()

export const asObject = (value: unknown): JsonObject =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {}

const normalizeJson = (value: unknown): unknown => {
  if (value === undefined) return null
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(normalizeJson)
  const object = value as Record<string, unknown>
  return Object.fromEntries(Object.keys(object).sort().map((key) => [key, normalizeJson(object[key])]))
}

export const stableJson = (value: unknown) => JSON.stringify(normalizeJson(value))

export const hashJson = async (value: unknown) => {
  const encoded = new TextEncoder().encode(stableJson(value))
  const digest = await crypto.subtle.digest('SHA-256', encoded)
  return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

export const projectDocument = (document: JsonObject, fields: string[]) =>
  Object.fromEntries([...new Set(fields)].sort().map((field) => [field, document[field] ?? null]))

export const ensureGrowthTables = async () => {
  const db = await database()
  await db.prepare(`CREATE TABLE IF NOT EXISTS helloada_growth_candidates (
    package_hash TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    initiative_id TEXT NOT NULL,
    collection_name TEXT NOT NULL,
    document_id TEXT NOT NULL,
    base_hash TEXT NOT NULL,
    candidate_hash TEXT NOT NULL,
    package_json TEXT NOT NULL,
    state TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )`).run()
  await db.prepare(`CREATE TABLE IF NOT EXISTS helloada_growth_operations (
    operation_key TEXT PRIMARY KEY,
    document_key TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    package_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )`).run()
  await db.prepare("CREATE UNIQUE INDEX IF NOT EXISTS helloada_growth_writing_document ON helloada_growth_operations(document_key) WHERE state = 'writing'").run()
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

export const activeOperation = async (documentKey: string, packageHash: string) => {
  const db = await database()
  const row = await db.prepare(
    "SELECT * FROM helloada_growth_operations WHERE document_key = ?1 AND state = 'writing' AND package_hash != ?2 ORDER BY updated_at DESC LIMIT 1",
  ).bind(documentKey, packageHash).first()
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
  await ensureGrowthTables()
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
] as const
