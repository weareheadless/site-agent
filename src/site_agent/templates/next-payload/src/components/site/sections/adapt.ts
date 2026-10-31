import { mediaUrl } from '@/lib/content'
import type { HeroAlignment, HeroContent, HeroDirection } from './hero'

/**
 * Translate a Payload section's content blocks into a section's props.
 *
 * The schema stores content, not layout: a heading, paragraphs, an image, a
 * link. This adapter is the single place that decides which block becomes the
 * headline, the body, the action and the image, so the same content can be
 * rendered by any section variant.
 *
 * A heading may carry an italic break with a pipe:
 *   "Tu color, | en las mismas manos."
 * The part after the pipe is set in italic. That keeps the authoring surface
 * plain text while still allowing the typographic break the design needs.
 */

type Entry = Record<string, unknown> & { key?: string; blockType?: string }

const ALIGNMENTS = new Set<HeroAlignment>(['split-left', 'split-right', 'centred', 'overlap', 'reversed'])
const TREATMENTS = new Set(['colour', 'monochrome'])
const SCALES = new Set(['editorial', 'compact'])

const text = (value: unknown) => (typeof value === 'string' ? value.trim() : '')

export function sectionEntriesToContent(entries: readonly unknown[]): HeroContent {
  let headline = ''
  let emphasis: string | undefined
  let body: string | undefined
  let action: HeroContent['action']
  let image: HeroContent['image']

  for (const raw of entries) {
    if (!raw || typeof raw !== 'object') continue
    const entry = raw as Entry
    switch (entry.blockType) {
      case 'helloAdaHeading': {
        const value = text(entry.text)
        if (!value || headline) break
        const [plain, ...rest] = value.split('|')
        headline = plain.trim()
        const tail = rest.join('|').trim()
        if (tail) emphasis = tail
        break
      }
      case 'helloAdaParagraph': {
        const value = text(entry.text)
        if (value && !body) body = value
        break
      }
      case 'helloAdaLink': {
        const href = text(entry.href)
        const label = text(entry.text)
        if (href && label && !action) action = { label, href }
        break
      }
      case 'helloAdaImage': {
        if (image) break
        const src = mediaUrl(entry.image)
        if (src) image = { src, alt: text(entry.alt) }
        break
      }
      default:
        break
    }
  }

  return { headline, emphasis, body, action, image }
}

export function sectionDirection(section: Record<string, unknown>): HeroDirection {
  const raw = section.direction
  if (!raw || typeof raw !== 'object') return {}
  const direction = raw as Record<string, unknown>
  const align = text(direction.align)
  const treatment = text(direction.treatment)
  const scale = text(direction.scale)
  return {
    align: ALIGNMENTS.has(align as HeroAlignment) ? (align as HeroAlignment) : undefined,
    rules: typeof direction.rules === 'boolean' ? direction.rules : undefined,
    treatment: TREATMENTS.has(treatment) ? (treatment as HeroDirection['treatment']) : undefined,
    scale: SCALES.has(scale) ? (scale as HeroDirection['scale']) : undefined,
  }
}
