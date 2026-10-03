import { getPayload } from 'payload'
import {
  helloAdaSeo,
  readHelloAdaGlobal,
  readHelloAdaPage,
  readHelloAdaPost,
  readHelloAdaPosts,
} from '@weareheadless/helloada-payload-core/server'

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

// Builds must not open D1/R2. At runtime, binding errors are deliberately
// allowed to surface: a missing Payload document is never replaced by JSX copy.
const payload = async (): Promise<PayloadClient | undefined> => {
  if (process.env.PAYLOAD_LOCAL_BUILD === '1' || process.env.NEXT_PHASE === 'phase-production-build') return undefined
  return await getPayload({ config })
}

export async function getPageBySlug(slug = 'home', locale?: string): Promise<ContentRecord | undefined> {
  const instance = await payload()
  if (!instance) return undefined
  return await readHelloAdaPage(instance, slug, locale) as ContentRecord | undefined
}

export async function getPublishedPosts(locale?: string): Promise<ContentRecord[]> {
  const instance = await payload()
  if (!instance) return []
  return await readHelloAdaPosts(instance, locale) as ContentRecord[]
}

export async function getPostBySlug(slug: string, locale?: string): Promise<ContentRecord | undefined> {
  const instance = await payload()
  if (!instance) return undefined
  return await readHelloAdaPost(instance, slug, locale) as ContentRecord | undefined
}

export async function getSiteSettings(locale?: string): Promise<ContentRecord> {
  const instance = await payload()
  if (!instance) return {}
  return await readHelloAdaGlobal(instance, 'siteSettings', locale) as ContentRecord
}

export async function getNavigation(locale?: string): Promise<ContentRecord> {
  const instance = await payload()
  if (!instance) return {}
  return await readHelloAdaGlobal(instance, 'navigation', locale) as ContentRecord
}

export const seoFor = (document: ContentRecord | undefined, settings: ContentRecord) => {
  const seo = objectValue(document?.seo)
  return {
    ...helloAdaSeo(document, settings),
    title: text(seo.title || document?.title || settings.defaultSeoTitle || settings.siteName),
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
