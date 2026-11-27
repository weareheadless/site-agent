import type { MetadataRoute } from 'next'

import { originHost, siteOrigin } from '@/lib/site-origin'
import { runtimeValue } from '@/lib/runtime-env'

/**
 * The robots file every site has, without anyone writing one.
 *
 * A `robots.txt` that cannot name the site's own sitemap tells a crawler half of
 * what it needs. Cloudflare prepends its content-signals block to whatever this
 * route answers, so the file the crawler reads is this one plus that preamble —
 * which is why the origin must answer here rather than leave the whole file to
 * the edge.
 *
 * A preview is not a site: it is served on its own signed origin and must never
 * be indexed, so the same route refuses crawling when the request is not the
 * registered live host. One implementation for both, so they cannot disagree.
 *
 * This file is tenant-owned rather than shared runtime: a custom crawl policy
 * is a legitimate owner or Growth change, and a release must not overwrite it.
 */
export const dynamic = 'force-dynamic'

export default async function robots(): Promise<MetadataRoute.Robots> {
  const origin = await siteOrigin()
  const registered = originHost(runtimeValue('NEXT_PUBLIC_SITE_URL'))
  // With no registered address the request is all there is, and it is the live
  // site by definition. When one is registered, anything else is a preview.
  const isLive = registered ? originHost(origin) === registered : true
  if (!isLive) {
    return { rules: { userAgent: '*', disallow: '/' } }
  }
  return {
    rules: { userAgent: '*', allow: '/', disallow: ['/admin', '/api/', '/helloada-preview'] },
    sitemap: new URL('/sitemap.xml', origin).toString(),
    host: origin,
  }
}
