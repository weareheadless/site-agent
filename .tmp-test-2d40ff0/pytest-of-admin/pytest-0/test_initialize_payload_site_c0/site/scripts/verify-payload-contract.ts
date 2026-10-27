import type { CollectionSlug } from 'payload'

process.env.PAYLOAD_CLI = '1'

const { getPayload } = await import('payload')
const { default: config } = await import('../payload.config.ts')

const collections = ['pages', 'posts', 'products', 'productCategories'] as const
const failures: string[] = []

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

const payload = await getPayload({ config })

try {
  for (const collection of collections) {
    await check(`${collection} published read`, () => payload.find({ collection: collection as CollectionSlug, draft: false, depth: 0, limit: 1, pagination: false, overrideAccess: true }))
    await check(`${collection} draft read`, () => payload.find({ collection: collection as CollectionSlug, draft: true, depth: 0, limit: 1, pagination: false, overrideAccess: true }))
    await check(`${collection} version read`, () => payload.findVersions({ collection: collection as CollectionSlug, depth: 0, limit: 1, overrideAccess: true }))
  }

  for (const global of ['siteSettings', 'navigation'] as const) {
    await check(`${global} published read`, () => payload.findGlobal({ slug: global, draft: false, depth: 0, overrideAccess: true }))
    await check(`${global} draft read`, () => payload.findGlobal({ slug: global, draft: true, depth: 0, overrideAccess: true }))
  }

  await check('media read', () => payload.find({ collection: 'media', depth: 0, limit: 1, pagination: false, overrideAccess: true }))

  if (failures.length) throw new Error(`Payload contract verification failed (${failures.length} checks). Fix the schema before deploying.`)

  console.log('[payload-contract] all Payload published, draft, version, global, and media reads passed')
} finally {
  await payload.destroy()
}

process.exit(0)
