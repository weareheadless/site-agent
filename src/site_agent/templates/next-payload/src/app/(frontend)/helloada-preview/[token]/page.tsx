import { cache } from 'react'
import type { Metadata } from 'next'
import { headers } from 'next/headers'
import { notFound } from 'next/navigation'
import type { CollectionSlug } from 'payload'

import PublicDocument from '@/components/PublicDocument'
import SiteChrome from '@/components/SiteChrome'
import { authenticateHelloAdaRequest } from '@/lib/helloada-auth'
import { getSiteSettings, seoFor } from '@/lib/content'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import { verifyHelloAdaPreviewToken } from '@/lib/helloada-preview'
import { helloAdaSite } from '@/helloada.config'

export const dynamic = 'force-dynamic'
export const revalidate = 0

type Props = { params: Promise<{ token: string }> }
type PreviewData = {
  collection: 'pages' | 'posts' | 'products'
  document: Record<string, unknown>
  settings: Record<string, unknown>
  route: string
}

const expectedPublicRoute = (collection: PreviewData['collection'], document: Record<string, unknown>) => {
  const slug = String(document.slug || '').trim().replace(/^\/+|\/+$/g, '')
  if (!slug) return undefined
  if (collection === 'posts') return `/articles/${slug.split('/').map(encodeURIComponent).join('/')}`
  if (slug === 'home' || slug === 'index') return '/'
  return `/${slug.split('/').map(encodeURIComponent).join('/')}`
}

const loadPreview = cache(async (token: string): Promise<PreviewData> => {
  const claims = await verifyHelloAdaPreviewToken(token, helloAdaSite.tenantId)
  if (!claims) notFound()

  const incomingHeaders = new Headers(await headers())
  const request = new Request('https://helloada-preview.invalid/', { headers: incomingHeaders })
  const auth = await authenticateHelloAdaRequest(request)
  if (!auth || String(auth.user.id) !== claims.ownerId) notFound()

  let document: Record<string, unknown>
  try {
    document = await auth.payload.findByID({
      collection: claims.collection as CollectionSlug,
      depth: 2,
      draft: claims.state === 'draft',
      id: claims.documentId,
      overrideAccess: false,
      req: auth.req,
      user: auth.user,
    }) as unknown as Record<string, unknown>
  } catch {
    notFound()
  }
  if (await hashJson(withoutPayloadMetadata(document)) !== claims.documentHash) notFound()
  if (expectedPublicRoute(claims.collection, document) !== claims.route) notFound()

  const settings = await getSiteSettings()
  return { collection: claims.collection, document, settings, route: claims.route }
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
  const { collection, document, settings, route } = await loadPreview(token)
  const kind = collection === 'posts' ? 'post' : collection === 'products' ? 'product' : 'page'
  return <div data-helloada-preview-hash={await hashJson(withoutPayloadMetadata(document))} data-helloada-preview-route={route}>
    <SiteChrome><PublicDocument document={document} settings={settings} kind={kind} collection={collection} /></SiteChrome>
  </div>
}
