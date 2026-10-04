import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import BlogListingPresentation from '@/components/site/presentation/BlogListingPresentation'
import PublicDocument from '@/components/PublicDocument'
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
  if (!document) notFound()
  const seo = seoFor(document, settings)
  return routeMetadata(seo.title, seo.description, seo.image, seo.canonical)
}

export default async function PublicRoute({ params }: Props) {
  const path = await routePath(params)
  const postRoute = postSlugForPath(path)
  if (postRoute?.kind === 'index') {
    const [posts, settings] = await Promise.all([getPublishedPosts(), getSiteSettings()])
    if (path !== articleIndexPath()) throw new Error('Articles listing route configuration is inconsistent.')
    return <BlogListingPresentation posts={posts} settings={settings} detailBasePath={articleDetailPath()} />
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
