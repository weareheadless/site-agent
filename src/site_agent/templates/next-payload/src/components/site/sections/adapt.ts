import type { HeroAlignment, HeroContent, HeroDirection } from './hero'

/**
 * Translate a Payload section's content blocks into a section's props.
 *
 * The schema stores content, not layout: a heading, paragraphs, an image, a
 * link. This adapter is the single place that decides which block becomes the
 * headline, the eyebrow, the body, the supporting copy, the action and the
 * image, so the same content can be rendered by any section variant.
 *
 * The mapping is structural rather than key-based: a paragraph that precedes
 * the heading is the eyebrow, the first paragraph after it is the body, and
 * any further paragraphs are supporting copy. That keeps the authoring surface
 * plain and ordered while letting the section own where each part sits.
 *
 * The adapter also reports which content entry each part came from, so the
 * section can carry the owner's editable binding for it. A composed page stays
 * editable in the workspace; it does not become a picture of Payload data.
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

/**
 * Resolve a Payload media relation to a public source and its alternative text.
 *
 * Injected so this adapter stays a pure translation with no runtime imports:
 * the mapping is the thing worth testing, and it should not need a Payload
 * runtime to prove it maps an eyebrow to an eyebrow.
 */
export type MediaResolver = (value: unknown) => { src: string; alt: string }

/** Which content entry a rendered part came from, and which field it edits. */
export type SectionBinding = { key: string; property: 'text' | 'image' }

export type SectionBindings = {
  eyebrow?: SectionBinding
  headline?: SectionBinding
  body?: SectionBinding
  supporting?: SectionBinding[]
  action?: SectionBinding
  image?: SectionBinding
  additionalImages?: SectionBinding[]
}

export type SectionContent = {
  content: HeroContent
  bindings: SectionBindings
}

export function sectionEntriesToContent(entries: readonly unknown[], media: MediaResolver): SectionContent {
  let eyebrow = ''
  let eyebrowKey = ''
  let headline = ''
  let headlineKey = ''
  let emphasis: string | undefined
  let body = ''
  let bodyKey = ''
  const supporting: string[] = []
  const supportingBindings: SectionBinding[] = []
  let action: HeroContent['action']
  let actionKey = ''
  let image: HeroContent['image']
  let imageKey = ''
  const additionalImages: NonNullable<HeroContent['additionalImages']> = []
  const additionalImageBindings: SectionBinding[] = []
  let headingSeen = false
  const keys = new Set<string>()
  const invalid = (detail: string): never => { throw new Error(`Section content cannot be rendered: ${detail}.`) }

  for (const raw of entries) {
    if (!raw || typeof raw !== 'object') invalid('invalid content entry')
    const entry = raw as Entry
    const key = text(entry.key)
    if (!key || keys.has(key)) invalid('missing or duplicate stable content key')
    keys.add(key)
    switch (entry.blockType) {
      case 'helloAdaHeading': {
        const value = text(entry.text)
        if (!value || headingSeen) invalid('missing text or duplicate heading')
        const [plain, ...rest] = value.split('|')
        headline = plain.trim()
        headlineKey = key
        const tail = rest.join('|').trim()
        if (tail) emphasis = tail
        headingSeen = true
        break
      }
      case 'helloAdaParagraph': {
        const value = text(entry.text)
        if (!value) invalid('missing paragraph text')
        if (!headingSeen) {
          if (!eyebrow) {
            eyebrow = value
            eyebrowKey = key
          } else invalid('multiple eyebrows')
          break
        }
        if (!body) {
          body = value
          bodyKey = key
        } else {
          supporting.push(value)
          supportingBindings.push({ key, property: 'text' })
        }
        break
      }
      case 'helloAdaLink': {
        const href = text(entry.href)
        const label = text(entry.text)
        if (!href || !label || action) invalid('missing action content or duplicate action')
        action = { label, href }
        actionKey = key
        break
      }
      case 'helloAdaImage': {
        const resolved = media(entry.image)
        if (!resolved.src) invalid(`missing media for ${key}`)
        if (resolved.src) {
          const next = { src: resolved.src, alt: text(entry.alt) || resolved.alt }
          if (image) {
            additionalImages.push(next)
            additionalImageBindings.push({ key, property: 'image' })
          } else {
            image = next
            imageKey = key
          }
        }
        break
      }
      default:
        invalid(`unsupported block type ${String(entry.blockType)}`)
    }
  }
  if (!headingSeen) invalid('missing section heading')

  const bindings: SectionBindings = {}
  if (eyebrowKey) bindings.eyebrow = { key: eyebrowKey, property: 'text' }
  if (headlineKey) bindings.headline = { key: headlineKey, property: 'text' }
  if (bodyKey) bindings.body = { key: bodyKey, property: 'text' }
  if (supportingBindings.length) bindings.supporting = supportingBindings
  if (actionKey) bindings.action = { key: actionKey, property: 'text' }
  if (imageKey) bindings.image = { key: imageKey, property: 'image' }
  if (additionalImageBindings.length) bindings.additionalImages = additionalImageBindings

  return {
    content: {
      eyebrow: eyebrow || undefined,
      headline,
      emphasis,
      body: body || undefined,
      supporting,
      action,
      image,
      ...(additionalImages.length ? { additionalImages } : {}),
    },
    bindings,
  }
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
