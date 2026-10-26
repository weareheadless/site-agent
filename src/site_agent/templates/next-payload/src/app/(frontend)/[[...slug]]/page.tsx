import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import BlogListingPresentation from '@/components/site/presentation/BlogListingPresentation'
import PublicDocument from '@/components/PublicDocument'
import { PublicRevisionList } from '@/components/platform/PublicRevision'
import { articleDetailPath, articleIndexPath, pathForDocument, postSlugForPath } from '@/lib/content-routes'
import { getPageBySlug, getPostBySlug, getProductBySlug, getPublishedPosts, getSiteSettings, seoFor } from '@/lib/content'

export const dynamic = 'force-dynamic'

type Props = { params: Promise<{ slug?: string[] }> }

const routePath = async (params: Props['params']) => {
  const { slug } = await params
  return slug?.length ? '/' + slug.map(encodeURIComponent).join('/') : '/'
}

const documentSlug = (path: string) => path === '/' ? 'home' : path.replace(/^\/+|\/+$/g, '').split('/').map(decodeURIComponent).join('/')

const routeMetadata = (title: string, description: string, image?: string, canonical?: string): Metadata => ({
  title,
  description: description || undefined,
  alternates: canonical ? { canonical } : undefined,
  openGraph: { title, description: description || undefined, images: image ? [image] : undefined },
})

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const path = await routePath(params)
  const postRoute = postSlugForPath(path)
  if (!postRoute && path === '/') {
    try {
      const home = await getPageBySlug('home')
      if (!home) {
        const fallback = await getSiteSettings().catch(() => ({}))
        return routeMetadata(
          String(fallback.defaultSeoTitle || fallback.siteName || 'HelloAda site').trim(),
          String(fallback.defaultSeoDescription || fallback.description || '').trim(),
        )
      }
    } catch {
      return routeMetadata('HelloAda site', '')
    }
  }
  const settings = await getSiteSettings()
  if (postRoute?.kind === 'index') {
    const title = String(settings.journalTitle || settings.defaultSeoTitle || settings.siteName || '').trim()
    const description = String(settings.journalDescription || settings.defaultSeoDescription || settings.description || '').trim()
    if (!title) throw new Error('Payload site settings need a title for the articles page.')
    return routeMetadata(title, description)
  }
  const post = postRoute?.kind === 'detail' ? await getPostBySlug(postRoute.slug) : undefined
  const slug = documentSlug(path)
  const [page, product] = postRoute ? [undefined, undefined] : await Promise.all([
    getPageBySlug(slug),
    getProductBySlug(slug),
  ])
  if (page && product) throw new Error('Payload assigns the same public route to both a page and a product.')
  const document = post || page || product
  // The page render below owns the canonical 404 decision. Calling
  // notFound() from generateMetadata as well makes the Cloudflare OpenNext
  // adapter serialize a missing Payload document as HTTP 500, even though the
  // rendered body is its 404 page. Keep metadata total for an unpublished or
  // not-yet-created home document and let PublicRoute return the real 404.
  if (!document) return routeMetadata(String(settings.defaultSeoTitle || settings.siteName || 'HelloAda site').trim(), String(settings.defaultSeoDescription || settings.description || '').trim())
  const seo = seoFor(document, settings)
  return routeMetadata(seo.title, seo.description, seo.image, seo.canonical)
}

export default async function PublicRoute({ params }: Props) {
  const path = await routePath(params)
  const postRoute = postSlugForPath(path)
  if (!postRoute && path === '/') {
    let home
    try {
      home = await getPageBySlug('home')
    } catch {
      home = undefined
    }
    if (!home) {
      return (
        <main style={{ minHeight: '70vh', display: 'grid', placeItems: 'center', padding: '4rem 1.5rem', textAlign: 'center' }}>
          <div>
            <h1 style={{ fontFamily: 'Georgia, serif', fontSize: 'clamp(2rem, 6vw, 4rem)', margin: 0 }}>HelloAda site</h1>
            <p style={{ marginTop: '1rem', opacity: 0.7 }}>This site is being prepared.</p>
          </div>
        </main>
      )
    }
  }
  if (postRoute?.kind === 'index') {
    const [posts, settings] = await Promise.all([getPublishedPosts(), getSiteSettings()])
    if (path !== articleIndexPath()) throw new Error('Articles listing route configuration is inconsistent.')
    return <>
      <PublicRevisionList documents={posts} />
      <BlogListingPresentation posts={posts} settings={settings} detailBasePath={articleDetailPath()} />
    </>
  }

  const post = postRoute?.kind === 'detail' ? await getPostBySlug(postRoute.slug) : undefined
  const slug = documentSlug(path)
  let page
  let product
  let settings
  if (postRoute) {
    settings = await getSiteSettings()
  } else {
    ;[page, product, settings] = await Promise.all([
      getPageBySlug(slug),
      getProductBySlug(slug),
      getSiteSettings(),
    ])
  }
  if (page && product) throw new Error('Payload assigns the same public route to both a page and a product.')
  const document = post || page || product
  if (!document) notFound()
  const collection = post ? 'posts' : product ? 'products' : 'pages'
  const kind = post ? 'post' : product ? 'product' : 'page'
  const expectedRoute = pathForDocument(collection, String(document.slug || ''))
  if (expectedRoute !== path) notFound()
  return <PublicDocument document={document} settings={settings} kind={kind} collection={collection} />
}
