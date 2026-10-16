import type { Metadata } from 'next'

import PublicDocument from '@/components/PublicDocument'
import SiteChrome from '@/components/SiteChrome'
import { seoFor } from '@/lib/content'

export type HelloAdaPreviewRendererInput = {
  collection: 'pages' | 'posts' | 'products'
  document: Record<string, unknown>
  settings: Record<string, unknown>
  navigation: Record<string, unknown>
  route: string
}

export const helloAdaPreviewMetadata = ({ document, settings }: Pick<HelloAdaPreviewRendererInput, 'document' | 'settings'>): Metadata => {
  const seo = seoFor(document, settings)
  return {
    title: seo.title,
    description: seo.description || undefined,
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    openGraph: { title: seo.title, description: seo.description || undefined, images: seo.image ? [seo.image] : undefined },
    robots: { index: false, follow: false, nocache: true },
  }
}

export default function HelloAdaPreviewRenderer({ collection, document, settings, navigation }: HelloAdaPreviewRendererInput) {
  const kind = collection === 'posts' ? 'post' : collection === 'products' ? 'product' : 'page'
  return <SiteChrome navigation={navigation} settings={settings}>
    <PublicDocument document={document} settings={settings} kind={kind} collection={collection} />
  </SiteChrome>
}
