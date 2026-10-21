import { getPayload } from 'payload'
import config from '@payload-config'
import { createHelloAdaContentContract, HELLOADA_CAPABILITIES } from '@weareheadless/helloada-payload-core/schema'
import { createHelloAdaContractIdentity } from '@weareheadless/helloada-payload-core/contract'
import { helloAdaSite } from '@/helloada.config'
import { stableJson } from '@/lib/payload-hash'
import { captureRenderSnapshot } from '@/lib/render-snapshot'
import { serviceAuthorized } from '@/lib/service-auth'

export const dynamic = 'force-dynamic'

/** Private render input export, never an owner or public database export. */
export async function GET(request: Request) {
  const headers = { 'Cache-Control': 'private, no-store' }
  if (!serviceAuthorized(request)) return Response.json({ error: 'service authentication required' }, { status: 401, headers })
  const schemaIdentity = createHelloAdaContractIdentity({
    locales: helloAdaSite.locales,
    defaultLocale: helloAdaSite.defaultLocale,
    collections: HELLOADA_CAPABILITIES.collections,
    globals: HELLOADA_CAPABILITIES.globals,
  }).schemaIdentity
  const tenant = process.env.HELLOADA_TENANT_ID || ''
  const sourceSha = process.env.HELLOADA_RELEASE_SHA || ''
  if (tenant !== helloAdaSite.tenantId || schemaIdentity !== process.env.HELLOADA_SCHEMA_IDENTITY) {
    return Response.json({ error: 'render_snapshot_identity_mismatch' }, { status: 503, headers })
  }
  try {
    const payload = await getPayload({ config })
    const contract = createHelloAdaContentContract()
    const collections = ['pages',
      ...(helloAdaSite.features?.posts ? ['posts', 'postCategories'] : []),
      ...(helloAdaSite.features?.commerce ? ['products', 'productCategories'] : []),
    ]
    const result = await captureRenderSnapshot({
      find: async (args) => {
        const result = await payload.find(args as Parameters<typeof payload.find>[0])
        return { docs: result.docs as unknown as Record<string, unknown>[], totalDocs: result.totalDocs, totalPages: result.totalPages, hasNextPage: result.hasNextPage }
      },
      findGlobal: async (args) => await payload.findGlobal(args as Parameters<typeof payload.findGlobal>[0]) as unknown as Record<string, unknown>,
    }, {
      tenant, sourceSha, schemaIdentity,
      locales: [...helloAdaSite.locales], defaultLocale: helloAdaSite.defaultLocale,
      collections: Object.fromEntries(collections.map((slug) => [slug, contract.collections[slug as keyof typeof contract.collections]])),
      globals: { siteSettings: contract.globals.siteSettings, navigation: contract.globals.navigation },
    })
    // Preserve the exact hashed JSON across JavaScript/Python serialization.
    // This is content metadata only: media bytes and runtime identity are
    // separately required before a candidate is eligible for owner review.
    return Response.json({ version: 1, snapshotJson: stableJson(result.snapshot), hash: result.hash }, { headers })
  } catch (error) {
    console.error('helloada_render_snapshot_failed', { name: error instanceof Error ? error.name : 'UnknownError' })
    return Response.json({ error: 'render_snapshot_unavailable' }, { status: 503, headers })
  }
}
