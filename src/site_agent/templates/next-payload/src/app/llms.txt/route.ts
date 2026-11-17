import { getCloudflareContext } from '@opennextjs/cloudflare'

import { siteCorpus, type SiteCorpusEnv } from '@/lib/assistant-site-context'

export const dynamic = 'force-dynamic'

/**
 * The site's published content as markdown: the visitor assistant's reference
 * material and an AEO artifact for other assistants. Published by construction —
 * committed pages plus published Payload documents, never a draft.
 */
export async function GET(request: Request) {
  const env = getCloudflareContext().env as unknown as SiteCorpusEnv
  const origin = new URL(request.url).origin
  try {
    const corpus = await siteCorpus(env, origin)
    return new Response(corpus.markdown, {
      headers: {
        'content-type': 'text/markdown; charset=utf-8',
        'cache-control': 'public, max-age=0, s-maxage=3600',
        'x-page-count': String(corpus.pageCount),
        'x-truncated-pages': String(corpus.truncatedPages),
      },
    })
  } catch {
    // Never serve an empty or partial site description as if it were the site.
    return new Response('# Unavailable\n\nThe site description could not be built.\n', {
      status: 503,
      headers: { 'content-type': 'text/markdown; charset=utf-8', 'cache-control': 'no-store' },
    })
  }
}
