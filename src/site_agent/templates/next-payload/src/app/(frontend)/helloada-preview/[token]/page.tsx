import { cache } from 'react'
import type { Metadata } from 'next'
import { headers } from 'next/headers'
import { notFound } from 'next/navigation'
import { getPayload } from 'payload'
import type { CollectionSlug, GlobalSlug, TypedLocale } from 'payload'

import config from '@payload-config'
import PublicDocument from '@/components/PublicDocument'
import SiteChrome from '@/components/SiteChrome'
import { authenticateHelloAdaRequest } from '@/lib/helloada-auth'
import { serviceAuthorized } from '@/lib/service-auth'
import { seoFor } from '@/lib/content'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import { verifyHelloAdaPreviewToken } from '@/lib/helloada-preview'
import { helloAdaSite } from '@/helloada.config'
import { pathForDocument } from '@/lib/content-routes'

export const dynamic = 'force-dynamic'
export const revalidate = 0

type Props = { params: Promise<{ token: string }> }
type PreviewData = {
  collection: 'pages' | 'posts' | 'products'
  document: Record<string, unknown>
  settings: Record<string, unknown>
  navigation: Record<string, unknown>
  route: string
}

const expectedPublicRoute = (collection: PreviewData['collection'], document: Record<string, unknown>) => {
  const slug = String(document.slug || '').trim().replace(/^\/+|\/+$/g, '')
  if (!slug) return undefined
  return pathForDocument(collection, slug)
}

const loadPreview = cache(async (token: string): Promise<PreviewData> => {
  const claims = await verifyHelloAdaPreviewToken(token, helloAdaSite.tenantId)
  if (!claims) notFound()

  const incomingHeaders = new Headers(await headers())
  const request = new Request('https://helloada-preview.invalid/', { headers: incomingHeaders })
  const owner = claims.principal.type === 'owner'
  const auth = owner ? await authenticateHelloAdaRequest(request) : undefined
  if (owner && (!auth || String(auth.user.id) !== claims.principal.ownerId)) notFound()
  if (!owner && !serviceAuthorized(request)) notFound()
  const payload = auth?.payload || await getPayload({ config })
  const access = auth
    ? { overrideAccess: false as const, req: auth.req, user: auth.user }
    : { overrideAccess: true as const }

  let document: Record<string, unknown>
  try {
    document = await payload.findByID({
      collection: claims.collection as CollectionSlug,
      depth: 2,
      draft: claims.state === 'draft',
      id: claims.documentId,
      locale: claims.locale as TypedLocale,
      ...access,
    }) as unknown as Record<string, unknown>
  } catch {
    notFound()
  }
  if (await hashJson(withoutPayloadMetadata(document)) !== claims.documentHash) notFound()
  if (expectedPublicRoute(claims.collection, document) !== claims.route) notFound()

  const globals = await Promise.all(claims.globals.map(async (claim) => {
    const global = await payload.findGlobal({
      slug: claim.slug as GlobalSlug,
      depth: 2,
      draft: claims.state === 'draft',
      locale: claims.locale as TypedLocale,
      ...access,
    }) as unknown as Record<string, unknown>
    if (await hashJson(withoutPayloadMetadata(global)) !== claim.hash) notFound()
    return [claim.slug, global] as const
  }))
  const exactGlobals = Object.fromEntries(globals)
  const settings = exactGlobals.siteSettings
  const navigation = exactGlobals.navigation
  if (!settings || !navigation) notFound()
  return { collection: claims.collection, document, settings, navigation, route: claims.route }
})

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { token } = await params
  const { document, settings } = await loadPreview(token)
  const seo = seoFor(document, settings)
  return {
    title: seo.title,
    description: seo.description || undefined,
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    openGraph: { title: seo.title, description: seo.description || undefined, images: seo.image ? [seo.image] : undefined },
    robots: { index: false, follow: false, nocache: true },
  }
}

export default async function HelloAdaExactPreview({ params }: Props) {
  const { token } = await params
  const { collection, document, settings, navigation, route } = await loadPreview(token)
  const kind = collection === 'posts' ? 'post' : collection === 'products' ? 'product' : 'page'
  return <div data-helloada-preview-hash={await hashJson(withoutPayloadMetadata(document))} data-helloada-preview-route={route}>
    <SiteChrome navigation={navigation} settings={settings}><PublicDocument document={document} settings={settings} kind={kind} collection={collection} /></SiteChrome>
  </div>
}
