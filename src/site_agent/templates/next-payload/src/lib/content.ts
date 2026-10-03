import { getPayload } from 'payload'

import config from '@payload-config'

export type ContentRecord = Record<string, any>

const objectValue = (value: unknown): ContentRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as ContentRecord : {}

const text = (value: unknown) => String(value ?? '').trim()

export const mediaUrl = (value: unknown) => {
  const media = objectValue(value)
  return text(media.url || media.originalUrl || media.thumbnailURL)
}

export const mediaAlt = (value: unknown) => {
  const media = objectValue(value)
  return text(media.alt || media.filename || 'Website image')
}

export const lexicalText = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  const node = objectValue(value)
  if (node.root && typeof node.root === 'object') return lexicalText(node.root)
  if (typeof node.text === 'string') return node.text.trim()
  if (!Array.isArray(node.children)) return ''
  return node.children.map(lexicalText).filter(Boolean).join('\n').trim()
}

export const lexicalParagraphs = (value: unknown) => lexicalText(value).split(/\n+/).map((line) => line.trim()).filter(Boolean)

type PayloadClient = Awaited<ReturnType<typeof getPayload>>

// A Cloudflare build must not initialize the D1/R2 Payload adapter. The
// frontend remains buildable; at runtime Payload is the source of truth.
// A runtime binding/database failure must surface instead of serving a
// different static website and hiding the failed canonical source.
const payload = async (): Promise<PayloadClient | undefined> => {
  if (process.env.PAYLOAD_LOCAL_BUILD === '1' || process.env.NEXT_PHASE === 'phase-production-build') return undefined
  return await getPayload({ config })
}

export async function getPageBySlug(slug = 'home'): Promise<ContentRecord | undefined> {
  const normalized = text(slug).replace(/^\/+|\/+$/g, '') || 'home'
  const instance = await payload()
  if (!instance) return undefined
  const result = await instance.find({
    collection: 'pages',
    draft: false,
    depth: 2,
    limit: 1,
    pagination: false,
    overrideAccess: true,
    where: { slug: { equals: normalized } },
  })
  return result.docs[0] as ContentRecord | undefined
}

export async function getPublishedPosts(): Promise<ContentRecord[]> {
  const instance = await payload()
  if (!instance) return []
  const result = await instance.find({
    collection: 'posts',
    draft: false,
    depth: 2,
    limit: 100,
    pagination: false,
    overrideAccess: true,
    sort: '-publishedAt',
  })
  return result.docs as ContentRecord[]
}

export async function getPostBySlug(slug: string): Promise<ContentRecord | undefined> {
  const instance = await payload()
  if (!instance) return undefined
  const result = await instance.find({
    collection: 'posts',
    draft: false,
    depth: 2,
    limit: 1,
    pagination: false,
    overrideAccess: true,
    where: { slug: { equals: text(slug) } },
  })
  return result.docs[0] as ContentRecord | undefined
}

export async function getSiteSettings(): Promise<ContentRecord> {
  const instance = await payload()
  if (!instance) return {}
  return await instance.findGlobal({
    slug: 'siteSettings',
    draft: false,
    depth: 2,
    overrideAccess: true,
  }) as ContentRecord
}

export async function getNavigation(): Promise<ContentRecord> {
  const instance = await payload()
  if (!instance) return {}
  return await instance.findGlobal({
    slug: 'navigation',
    draft: false,
    depth: 2,
    overrideAccess: true,
  }) as ContentRecord
}

export const seoFor = (document: ContentRecord | undefined, settings: ContentRecord) => {
  const seo = objectValue(document?.seo)
  return {
    title: text(seo.title || document?.title || settings.defaultSeoTitle || settings.siteName || 'Website'),
    description: text(seo.description || document?.summary || settings.defaultSeoDescription || settings.description),
    image: mediaUrl(seo.image || document?.featuredImage || settings.defaultSocialImage),
    canonical: text(document?.canonicalUrl),
  }
}

export const navigationItems = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item) => objectValue(item).visible !== false).map((item) => ({
        label: text(objectValue(item).label),
        href: text(objectValue(item).href) || '/',
        external: objectValue(item).external === true,
      })).filter((item) => item.label)
    : []
