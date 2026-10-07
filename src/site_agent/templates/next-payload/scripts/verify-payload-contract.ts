import type { CollectionSlug } from 'payload'

process.env.PAYLOAD_CLI = '1'

const { getPayload } = await import('payload')
const { default: config } = await import('@payload-config')

const collections = ['pages', 'posts', 'postCategories', 'products', 'productCategories'] as const
const versionedCollections = ['pages', 'posts', 'postCategories', 'products'] as const
const failures: string[] = []
const websitePresentValue = process.env.HELLOADA_WEBSITE_PRESENT
if (websitePresentValue !== 'true' && websitePresentValue !== 'false') {
  throw new Error('HELLOADA_WEBSITE_PRESENT must be explicitly set to true or false.')
}
const websitePresent = websitePresentValue === 'true'

const check = async (label: string, operation: () => Promise<unknown>) => {
  try {
    await operation()
    console.log(`[payload-contract] ok: ${label}`)
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    failures.push(`${label}: ${message}`)
    console.error(`[payload-contract] failed: ${label}: ${message}`)
  }
}

const objectValue = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

const hasAuthoredText = (value: unknown): boolean => {
  if (typeof value === 'string') return Boolean(value.trim())
  if (Array.isArray(value)) return value.some(hasAuthoredText)
  if (!value || typeof value !== 'object') return false
  const ignored = new Set(['id', 'key', 'type', 'blockType', 'version', 'indent', 'format', 'direction', 'mode', 'detail', 'style', '_status', 'createdAt', 'updatedAt'])
  return Object.entries(value as Record<string, unknown>)
    .some(([key, child]) => !ignored.has(key) && hasAuthoredText(child))
}

const payload = await getPayload({ config })

try {
  for (const collection of collections) {
    await check(`${collection} published read`, () => payload.find({ collection: collection as CollectionSlug, draft: false, depth: 0, limit: 1, pagination: false, overrideAccess: true }))
    await check(`${collection} draft read`, () => payload.find({ collection: collection as CollectionSlug, draft: true, depth: 0, limit: 1, pagination: false, overrideAccess: true }))
  }

  for (const collection of versionedCollections) {
    await check(`${collection} version read`, () => payload.findVersions({ collection: collection as CollectionSlug, depth: 0, limit: 1, overrideAccess: true }))
  }

  const globals: Record<string, Record<string, unknown>> = {}
  for (const slug of ['siteSettings', 'navigation'] as const) {
    await check(`${slug} published read`, async () => {
      const value = await payload.findGlobal({ slug, draft: false, depth: 0, overrideAccess: true })
      globals[slug] = value as unknown as Record<string, unknown>
    })
    await check(`${slug} draft read`, () => payload.findGlobal({ slug, draft: true, depth: 0, overrideAccess: true }))
  }

  if (websitePresent) {
    await check('siteSettings publishable name', async () => {
      if (!String(globals.siteSettings?.siteName ?? '').trim()) {
        throw new Error('Published siteSettings.siteName is empty; publish the business identity in Payload before release.')
      }
    })

    await check('navigation has shared header and footer links', async () => {
      const navigation = globals.navigation ?? {}
      const items = navigation.items
      const footer = navigation.footer
      if (!Array.isArray(items) || items.length === 0) throw new Error('Published navigation.items is empty.')
      if (!Array.isArray(footer) || footer.length === 0) throw new Error('Published navigation.footer is empty.')
    })

    await check('published home page is complete enough to render', async () => {
      const result = await payload.find({
        collection: 'pages',
        where: { slug: { equals: 'home' } },
        draft: false,
        depth: 1,
        limit: 1,
        pagination: false,
        overrideAccess: true,
      })
      const home = result.docs[0] as unknown as Record<string, unknown> | undefined
      if (!home) throw new Error('No published pages document with slug "home" exists.')
      if (!String(home.title ?? '').trim()) throw new Error('Published home page title is empty.')
      if (!String(home.summary ?? '').trim()) throw new Error('Published home page summary is empty.')
      const seo = objectValue(home.seo)
      if (!String(seo.title ?? '').trim() || !String(seo.description ?? '').trim()) {
        throw new Error('Published home page needs both seo.title and seo.description.')
      }
      if (!hasAuthoredText(home.body) && !hasAuthoredText(home.sections)) {
        throw new Error('Published home page has no authored body or sections.')
      }
    })
  } else {
    console.log('[payload-contract] published business content checks skipped: intake site is explicitly empty')
  }

  await check('media read', () => payload.find({ collection: 'media', depth: 0, limit: 1, pagination: false, overrideAccess: true }))

  if (failures.length) throw new Error(`Payload contract verification failed (${failures.length} checks). Fix the content contract before deploying.`)

  console.log(websitePresent
    ? '[payload-contract] schema, shared chrome, published homepage, drafts, versions, and media reads passed'
    : '[payload-contract] schema, empty-intake state, drafts, versions, and media reads passed')
} finally {
  await payload.destroy()
}

process.exit(0)
