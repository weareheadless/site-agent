import type { Payload } from 'payload'

type ContentRecord = Record<string, unknown>

const objectValue = (value: unknown): ContentRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as ContentRecord : {}

const normalizedSlug = (value: string) => value.trim().replace(/^\/+|\/+$/g, '') || 'home'

export type HelloAdaContentReader = Pick<Payload, 'find' | 'findGlobal'>

export const readHelloAdaPage = async (payload: HelloAdaContentReader, slug: string, locale?: string) => {
  const result = await payload.find({
    collection: 'pages', draft: false, depth: 2, limit: 1, pagination: false,
    overrideAccess: true, locale: locale as never,
    where: { and: [{ slug: { equals: normalizedSlug(slug) } }, { published: { equals: true } }] },
  })
  return result.docs[0] as ContentRecord | undefined
}

export const readHelloAdaPost = async (payload: HelloAdaContentReader, slug: string, locale?: string) => {
  const result = await payload.find({
    collection: 'posts', draft: false, depth: 2, limit: 1, pagination: false,
    overrideAccess: true, locale: locale as never,
    where: { and: [{ slug: { equals: normalizedSlug(slug) } }, { published: { equals: true } }] },
  })
  return result.docs[0] as ContentRecord | undefined
}

export const readHelloAdaPosts = async (payload: HelloAdaContentReader, locale?: string) => {
  const result = await payload.find({
    collection: 'posts', draft: false, depth: 2, limit: 100, pagination: false,
    overrideAccess: true, locale: locale as never, sort: '-publishedAt',
    where: { published: { equals: true } },
  })
  return result.docs as ContentRecord[]
}

export const readHelloAdaGlobal = async (payload: HelloAdaContentReader, slug: 'navigation' | 'siteSettings', locale?: string) =>
  await payload.findGlobal({ slug, draft: false, depth: 2, overrideAccess: true, locale: locale as never }) as ContentRecord

export const helloAdaSeo = (document: ContentRecord | undefined, settings: ContentRecord) => {
  const seo = objectValue(document?.seo)
  const image = objectValue(seo.image || document?.featuredImage || settings.defaultSocialImage)
  return {
    title: String(seo.title || document?.title || settings.defaultSeoTitle || settings.siteName || '').trim(),
    description: String(seo.description || document?.summary || settings.defaultSeoDescription || settings.description || '').trim(),
    image: String(image.url || image.originalUrl || image.thumbnailURL || '').trim(),
    canonical: String(document?.canonicalUrl || '').trim(),
  }
}

export const helloAdaSectionEntries = (document: ContentRecord | undefined, sectionKey: string) => {
  const sections = Array.isArray(document?.sections) ? document.sections : []
  const section = sections.map(objectValue).find((item) => item.key === sectionKey)
  return Array.isArray(section?.entries) ? section.entries.map(objectValue) : []
}

export const helloAdaEntry = (entries: ContentRecord[], key: string) => entries.find((entry) => entry.key === key)
