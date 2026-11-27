import type { MetadataRoute } from 'next'

import {
  articleDetailPath,
  articleIndexPath,
  pathForDocument,
  presentationRoutes,
} from '@/lib/content-routes'
import { getPageBySlug, getPublishedPosts } from '@/lib/content'
import { siteOrigin } from '@/lib/site-origin'

/**
 * The sitemap every site has, without anyone writing one.
 *
 * A sitemap is not a design decision: it is the list of public routes a build
 * can serve. It is derived from the same resolvers the routes themselves use —
 * the committed presentation pages from the generated inventory, the home
 * document, and each published article by its canonical path — so a site that
 * never writes a sitemap still gets a complete one, and a site whose pages
 * change gets the new list with no second file to keep in step.
 *
 * Only published documents are listed. Sitemap entries naming an unpublished
 * document ask a crawler to fetch a 404, so a missing home document omits the
 * root rather than inventing it. A tenant that wants a different discovery
 * declaration owns this file, which is why it is not shared runtime: the
 * default must be replaceable without fighting a release.
 */
export const dynamic = 'force-dynamic'

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = await siteOrigin()
  const [home, posts] = await Promise.all([
    getPageBySlug('home').catch(() => undefined),
    getPublishedPosts().catch(() => [] as Record<string, unknown>[]),
  ])

  const routes = new Set<string>(presentationRoutes())
  if (home) routes.add(pathForDocument('pages', String(home.slug || 'home')))
  const detailBase = articleDetailPath().replace(/\/$/, '')
  const postsBySlug = new Map<string, Record<string, unknown>>()
  for (const post of posts as Record<string, unknown>[]) {
    const slug = String(post.slug || '').trim()
    if (!slug) continue
    postsBySlug.set(slug, post)
    routes.add(`${detailBase}/${slug}`)
  }
  if (posts.length) routes.add(articleIndexPath())

  const modified = (value: unknown) => {
    const parsed = value ? new Date(String(value)) : undefined
    return parsed && !Number.isNaN(parsed.valueOf()) ? parsed : undefined
  }

  return [...routes]
    .filter((route) => route.startsWith('/') && !route.startsWith('//'))
    .sort((left, right) => left.localeCompare(right))
    .map((route) => {
      const slug = route.split('/').filter(Boolean).pop() || ''
      const post = route === articleIndexPath() ? undefined : postsBySlug.get(slug)
      return {
        url: new URL(route, origin).toString(),
        lastModified: modified(post?.updatedAt),
        changeFrequency: route === '/' ? 'weekly' : 'monthly',
        priority: route === '/' ? 1 : 0.7,
      }
    })
}
