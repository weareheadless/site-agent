import { headers } from 'next/headers'

import { runtimeValue } from './runtime-env'

/**
 * The absolute origin this build answers on.
 *
 * Document metadata and the sitemap need a full URL, and the request itself is
 * the only value that is always true: the registered domain, a workers.dev
 * address and a preview origin are the same site, and a hardcoded domain would
 * make the wrong one canonical on the others. The configured site URL wins when
 * it is set, because a Worker behind Cloudflare sees an internal host; the
 * request host is the fallback for a tenant that has not registered one yet.
 */
export const siteOrigin = async (): Promise<string> => {
  const configured = runtimeValue('NEXT_PUBLIC_SITE_URL')
  if (configured) {
    try {
      const url = new URL(configured)
      if (url.protocol === 'https:' || url.protocol === 'http:') return url.origin
    } catch {
      // A malformed optional setting must not break metadata; fall through to
      // the request, which is the origin the page was actually served from.
    }
  }
  const incoming = await headers()
  const host = String(incoming.get('x-forwarded-host') || incoming.get('host') || '').trim()
  const proto = String(incoming.get('x-forwarded-proto') || 'https').trim()
  if (!host) throw new Error('The site origin could not be resolved for this request.')
  return `${proto}://${host}`
}

/** The host of an absolute origin, for comparing this build against the live site. */
export const originHost = (value: string): string => {
  try {
    return new URL(value).host.toLowerCase()
  } catch {
    return ''
  }
}
