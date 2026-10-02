import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import { getPageBySlug, getSiteSettings, lexicalParagraphs, mediaAlt, mediaUrl, seoFor } from '@/lib/content'

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
  const image = mediaUrl(page?.featuredImage)
  const paragraphs = lexicalParagraphs(page?.body)
  return (
    <main className="content-page">
      <p className="eyebrow">{settings.siteName || 'HelloAda site'}</p>
      <h1>{page?.title || settings.siteName || 'Your new website'}</h1>
      {image ? <img className="article-image" src={image} alt={mediaAlt(page?.featuredImage)} /> : null}
      {page?.summary ? <p className="article-intro">{page.summary}</p> : null}
      <div className="article-body">
        {paragraphs.map((paragraph: string, index: number) => <p key={`${index}-${paragraph.slice(0, 12)}`}>{paragraph}</p>)}
      </div>
      {!page ? <p className="empty-state">This homepage is ready for its first owner-approved content update in Payload.</p> : null}
    </main>
  )
}
