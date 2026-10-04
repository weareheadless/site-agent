import { getPayload } from 'payload'
import {
  helloAdaSeo,
  readHelloAdaGlobal,
  readHelloAdaPage,
  readHelloAdaPost,
  readHelloAdaPosts,
  readHelloAdaProduct,
} from '@weareheadless/helloada-payload-core/server'

import config from '@payload-config'

export type ContentRecord = Record<string, unknown>

const objectValue = (value: unknown): ContentRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as ContentRecord : {}

const text = (value: unknown) => String(value ?? '').trim()

export const mediaUrl = (value: unknown) => {
  const media = objectValue(value)
  return text(media.url || media.originalUrl || media.thumbnailURL)
}

export const mediaAlt = (value: unknown) => {
  const media = objectValue(value)
  return text(media.alt || media.filename || '')
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

// Routes are request-rendered on the Worker. A build-time Payload read would
// silently bind to an empty local D1, so it is an architecture error.
const payload = async (): Promise<PayloadClient> => {
  if (process.env.PAYLOAD_LOCAL_BUILD === '1' || process.env.NEXT_PHASE === 'phase-production-build') {
    throw new Error('Public Payload content was read during a build; managed routes must remain request-rendered.')
  }
  return getPayload({ config })
}

export async function getPageBySlug(slug = 'home', locale?: string): Promise<ContentRecord | undefined> {
  return await readHelloAdaPage(await payload(), slug, locale) as ContentRecord | undefined
}

export async function getProductBySlug(slug: string, locale?: string): Promise<ContentRecord | undefined> {
  return await readHelloAdaProduct(await payload(), slug, locale) as ContentRecord | undefined
}

export async function getPublishedPosts(locale?: string): Promise<ContentRecord[]> {
  return await readHelloAdaPosts(await payload(), locale) as ContentRecord[]
}

export async function getPostBySlug(slug: string, locale?: string): Promise<ContentRecord | undefined> {
  return await readHelloAdaPost(await payload(), slug, locale) as ContentRecord | undefined
}

export async function getSiteSettings(locale?: string): Promise<ContentRecord> {
  return await readHelloAdaGlobal(await payload(), 'siteSettings', locale) as ContentRecord
}

export async function getNavigation(locale?: string): Promise<ContentRecord> {
  return await readHelloAdaGlobal(await payload(), 'navigation', locale) as ContentRecord
}

export const seoFor = (document: ContentRecord | undefined, settings: ContentRecord) => {
  const seo = objectValue(document?.seo)
  return {
    ...helloAdaSeo(document, settings),
    title: text(seo.title || document?.title || settings.defaultSeoTitle || settings.siteName),
  }
}
