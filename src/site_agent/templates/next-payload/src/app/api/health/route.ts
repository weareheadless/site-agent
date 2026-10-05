import { getPayload, type CollectionSlug } from 'payload'
import { getCloudflareContext } from '@opennextjs/cloudflare'
import { HELLOADA_CAPABILITIES, HELLOADA_CORE_VERSION, HELLOADA_CONTENT_CONTRACT_VERSION, HELLOADA_SCHEMA_REVISION } from '@weareheadless/helloada-payload-core/schema'
import { createHelloAdaContractIdentity } from '@weareheadless/helloada-payload-core/contract'
import { HELLOADA_PAYLOAD_ADMIN_VERSION } from '@weareheadless/helloada-payload-admin/version'
import { helloAdaSite } from '@/helloada.config'
import config from '@payload-config'
import templateManifest from '../../../../template-manifest.json'

export const dynamic = 'force-dynamic'

const verifyDatabaseContract = async () => {
  const context = await getCloudflareContext({ async: true }) as unknown as {
    env?: { D1?: { prepare: (query: string) => { all: () => Promise<{ results?: Array<{ name: string }> }> } } }
  }
  const database = context.env?.D1
  if (!database) throw new Error('Tenant D1 binding is unavailable')
  const tables = await database.prepare(
    "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
  ).all()
  const tableNames = (tables.results || []).map(({ name }) => name)
  if (!tableNames.includes('payload_migrations')) throw new Error('Payload migration ledger is missing')
  const applied = await database.prepare('SELECT name FROM payload_migrations ORDER BY batch ASC, id ASC').all()
  const appliedNames = (applied.results || []).map(({ name }) => name)
  const expectedNames = templateManifest.migrations.map(({ name }) => name)
  if (JSON.stringify(appliedNames) !== JSON.stringify(expectedNames)) {
    throw new Error('Applied Payload migrations differ from the committed template migration chain')
  }

  const payload = await getPayload({ config })
  const collections = [...HELLOADA_CAPABILITIES.collections, 'users'] as CollectionSlug[]
  await Promise.all(collections.map((collection) => payload.find({
    collection, depth: 0, draft: false, limit: 1, pagination: false, overrideAccess: true,
  })))
  await Promise.all(HELLOADA_CAPABILITIES.globals.map((slug) => payload.findGlobal({
    slug, depth: 0, draft: false, overrideAccess: true,
  })))
}

export async function GET() {
  const tenant = process.env.HELLOADA_TENANT_ID || ''
  const templateSchema = Number(templateManifest.templateSchema)
  const loaded = {
    payloadCore: HELLOADA_CORE_VERSION,
    contentContract: HELLOADA_CONTENT_CONTRACT_VERSION,
    schemaRevision: HELLOADA_SCHEMA_REVISION,
    payloadAdmin: HELLOADA_PAYLOAD_ADMIN_VERSION,
    schemaIdentity: createHelloAdaContractIdentity({
      locales: helloAdaSite.locales,
      defaultLocale: helloAdaSite.defaultLocale,
      collections: HELLOADA_CAPABILITIES.collections,
      globals: HELLOADA_CAPABILITIES.globals,
    }).schemaIdentity,
    migrationHead: templateManifest.migrationHead,
  }
  const configured = {
    payloadCore: process.env.HELLOADA_PAYLOAD_CORE_VERSION || '',
    contentContract: process.env.HELLOADA_CONTENT_CONTRACT_VERSION || '',
    schemaRevision: Number(process.env.HELLOADA_PAYLOAD_SCHEMA_REVISION || 0),
    payloadAdmin: process.env.HELLOADA_PAYLOAD_ADMIN_VERSION || '',
    schemaIdentity: process.env.HELLOADA_SCHEMA_IDENTITY || '',
    migrationHead: process.env.HELLOADA_PAYLOAD_MIGRATION_HEAD || '',
  }
  const compatible = Boolean(tenant)
    && templateSchema === 4
    && Object.entries(loaded).every(([key, value]) => configured[key as keyof typeof configured] === value)
  if (!compatible) {
    return Response.json({ ok: false, error: 'payload_contract_mismatch', tenant: tenant || null, loaded, configured, templateSchema },
      { status: 503, headers: { 'Cache-Control': 'no-store' } })
  }
  try {
    await verifyDatabaseContract()
  } catch (error) {
    console.error('[helloada-health] canonical Payload schema verification failed', error)
    return Response.json({ ok: false, error: 'payload_schema_unavailable', tenant, loaded, configured, templateSchema },
      { status: 503, headers: { 'Cache-Control': 'no-store' } })
  }
  return Response.json({
    ok: true,
    service: 'helloada-site',
    tenant: tenant || null,
    templateSchema,
    payloadSchema: 'ready',
    ...loaded,
    configured,
    workspaceApi: process.env.HELLOADA_WORKSPACE_API_VERSION || null,
    siteAgent: process.env.HELLOADA_SITE_AGENT_VERSION || null,
    releaseSha: process.env.HELLOADA_RELEASE_SHA || null,
  }, { status: compatible ? 200 : 503, headers: { 'Cache-Control': 'no-store' } })
}
