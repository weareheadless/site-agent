import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import { getPageBySlug, getSiteSettings, seoFor } from '@/lib/content'
import PublicDocument from '@/components/PublicDocument'

export const dynamic = 'force-dynamic'

type Props = { params: Promise<{ slug?: string[] }> }

const routeSlug = (segments: string[] | undefined) => segments?.join('/') || 'home'

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const [page, settings] = await Promise.all([getPageBySlug(routeSlug(slug)), getSiteSettings()])
  if (!page && routeSlug(slug) !== 'home') return {}
  const seo = seoFor(page, settings)
  return {
    title: seo.title,
    description: seo.description || undefined,
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    openGraph: { title: seo.title, description: seo.description || undefined, images: seo.image ? [seo.image] : undefined },
  }
}

export default async function PageRoute({ params }: Props) {
  const { slug } = await params
  const route = routeSlug(slug)
  const [page, settings] = await Promise.all([getPageBySlug(route), getSiteSettings()])
  if (!page && route !== 'home') notFound()
  return <PublicDocument document={page} settings={settings} kind="page" />
}
