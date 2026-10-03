import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import { getPostBySlug, getSiteSettings, seoFor } from '@/lib/content'
import PublicDocument from '@/components/PublicDocument'

export const dynamic = 'force-dynamic'

type Props = { params: Promise<{ slug: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const [post, settings] = await Promise.all([getPostBySlug(slug), getSiteSettings()])
  if (!post) return {}
  const seo = seoFor(post, settings)
  return {
    title: seo.title,
    description: seo.description || undefined,
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    openGraph: { title: seo.title, description: seo.description || undefined, images: seo.image ? [seo.image] : undefined },
  }
}

export default async function ArticlePage({ params }: Props) {
  const { slug } = await params
  const [post, settings] = await Promise.all([getPostBySlug(slug), getSiteSettings()])
  if (!post) notFound()
  return <PublicDocument document={post} settings={settings} kind="post" />
}
