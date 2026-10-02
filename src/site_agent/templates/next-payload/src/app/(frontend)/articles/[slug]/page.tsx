import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import { getPostBySlug, getSiteSettings, lexicalParagraphs, mediaAlt, mediaUrl, seoFor } from '@/lib/content'

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
  const image = mediaUrl(post.featuredImage)
  const paragraphs = lexicalParagraphs(post.body)
  return (
    <main className="content-page article-page">
      <a href="/articles">← All articles</a>
      <p className="eyebrow">{post.category || 'Journal'}</p>
      <h1>{post.title}</h1>
      {image ? <img className="article-image" src={image} alt={mediaAlt(post.featuredImage)} /> : null}
      {post.summary ? <p className="article-intro">{post.summary}</p> : null}
      <div className="article-body">
        {paragraphs.map((paragraph: string, index: number) => <p key={`${index}-${paragraph.slice(0, 12)}`}>{paragraph}</p>)}
      </div>
      <small>{settings.siteName || 'Website'} · {post.publishedAt ? new Date(String(post.publishedAt)).toLocaleDateString() : 'Draft article'}</small>
    </main>
  )
}
