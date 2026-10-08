import { NextResponse } from 'next/server'

import {
  createHelloAdaAuthoringContract,
  HELLOADA_CAPABILITIES,
  HELLOADA_CORE_VERSION,
  HELLOADA_CONTENT_CONTRACT_VERSION,
  HELLOADA_SCHEMA_REVISION,
} from '@weareheadless/helloada-payload-core/schema'
import { createHelloAdaContractIdentity } from '@weareheadless/helloada-payload-core/contract'
import { helloAdaSite } from '@/helloada.config'
import { hashJson } from '@/lib/payload-hash'
import { serviceAuthorized } from '@/lib/service-auth'

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) {
    return NextResponse.json({ error: 'service authentication required' }, { status: 401 })
  }
  const loadedSchemaIdentity = createHelloAdaContractIdentity({
    locales: helloAdaSite.locales,
    defaultLocale: helloAdaSite.defaultLocale,
    collections: HELLOADA_CAPABILITIES.collections,
    globals: HELLOADA_CAPABILITIES.globals,
  }).schemaIdentity
  const configuredSchemaIdentity = process.env.HELLOADA_SCHEMA_IDENTITY || ''
  const enabledCollections = [
    'pages',
    ...(helloAdaSite.features?.posts ? ['posts'] : []),
    ...(helloAdaSite.features?.commerce ? ['products'] : []),
  ]
  const enabledGlobals = ['siteSettings', 'navigation']
  const completeAuthoring = createHelloAdaAuthoringContract()
  const authoring = {
    ...completeAuthoring,
    collections: Object.fromEntries(Object.entries(completeAuthoring.collections).filter(([slug]) => enabledCollections.includes(slug))),
    globals: Object.fromEntries(Object.entries(completeAuthoring.globals).filter(([slug]) => enabledGlobals.includes(slug))),
  }
  if (loadedSchemaIdentity !== configuredSchemaIdentity) {
    return NextResponse.json({ error: 'authoring_schema_identity_mismatch' }, { status: 503, headers: { 'Cache-Control': 'no-store' } })
  }
  const authoringContractHash = await hashJson(authoring)
  const contract = {
    version: 1,
    coreVersion: HELLOADA_CORE_VERSION,
    contract: HELLOADA_CONTENT_CONTRACT_VERSION,
    schemaRevision: HELLOADA_SCHEMA_REVISION,
    schemaIdentity: loadedSchemaIdentity,
    authoringContractHash,
    authoring,
    enabled: { collections: enabledCollections, globals: enabledGlobals },
    locales: [...helloAdaSite.locales],
    defaultLocale: helloAdaSite.defaultLocale,
    modules: {
      posts: Boolean(helloAdaSite.features?.posts),
      commerce: Boolean(helloAdaSite.features?.commerce),
    },
  }
  return NextResponse.json(contract, { headers: { 'Cache-Control': 'private, no-store' } })
}
