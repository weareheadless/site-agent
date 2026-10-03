import { validateHelloAdaLink } from '../schema/index.ts'

type Row = Record<string, unknown>

export type HelloAdaBindingTarget = {
  collection: string
  documentId: string
  field: string
  sectionKey?: string
  entryKey?: string
  itemKey?: string
  property?: string
}

export type HelloAdaBindingEdit = HelloAdaBindingTarget & {
  expectedValue: unknown
  newValue: unknown
}

const objectValue = (value: unknown): Row =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {}

export const helloAdaPlainText = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  const node = objectValue(value)
  if (node.root && typeof node.root === 'object') return helloAdaPlainText(node.root)
  if (typeof node.text === 'string') return node.text
  if (!Array.isArray(node.children)) return ''
  return node.children.map(helloAdaPlainText).filter(Boolean).join('\n').trim()
}

export const helloAdaBindingId = (collection: string, documentId: string, target: HelloAdaBindingTarget) =>
  `payload:${[collection, documentId, target.sectionKey, target.entryKey, target.itemKey, target.field, target.property]
    .filter((value) => value !== undefined && value !== '')
    .map((value) => encodeURIComponent(String(value)))
    .join(':')}`

const binding = (
  document: Row,
  route: string,
  target: HelloAdaBindingTarget,
  label: string,
  section: string,
  type: 'text' | 'richText' | 'image' | 'link',
  value: unknown,
  extra: Row = {},
) => {
  const text = type === 'richText' ? helloAdaPlainText(value) : value == null ? '' : String(value)
  const id = helloAdaBindingId(target.collection, target.documentId, target)
  return {
    id, key: id, label, section, sectionOrder: 0, type, sourceType: type,
    editorRole: type === 'image' ? 'image' : 'paragraph', editorVisible: true,
    editable: true, status: 'editable', kind: 'content', value: text, text,
    route, routes: [route], ...extra,
    contentEdit: { ...target, expectedValue: text },
  }
}

const labelValue = (value: unknown, fallback: string) => String(value || fallback).trim()
const mediaValue = (value: unknown) => objectValue(value)
const mediaId = (value: unknown) => {
  const media = mediaValue(value)
  // Payload relations must use the tenant-local collection ID. `sourceId` is
  // provenance only and can refer to an asset in another system.
  return media.id || media.sourceId || ''
}

/** Build the owner editor inventory from the same canonical document the public renderer consumes. */
export const helloAdaContentBindings = (
  document: Row,
  collection: string,
  route: string,
) => {
  const documentId = String(document.id || '')
  if (!documentId) throw new Error('Editable Payload document has no stable ID.')
  const targets = { collection, documentId }
  const seo = objectValue(document.seo)
  const seoImage = mediaValue(seo.image)
  const fields = [
    binding(document, route, { ...targets, field: 'title' }, 'Page title', 'Page details', 'text', document.title),
    binding(document, route, { ...targets, field: 'summary' }, 'Introduction', 'Page details', 'text', document.summary),
    binding(document, route, { ...targets, field: 'body' }, 'Main text', 'Page details', 'richText', document.body, { richText: document.body }),
    binding(document, route, { ...targets, field: 'seoTitle' }, 'Search title', 'Search and social preview', 'text', seo.title),
    binding(document, route, { ...targets, field: 'seoDescription' }, 'Search description', 'Search and social preview', 'text', seo.description),
    binding(document, route, { ...targets, field: 'seoImage' }, 'Social preview image', 'Search and social preview', 'image', mediaId(seo.image), { image: {
      id: String(seoImage.id || ''), sourceId: String(seoImage.sourceId || ''), url: String(seoImage.url || seoImage.originalUrl || ''),
      filename: String(seoImage.filename || ''), alt: String(seoImage.alt || ''),
    } }),
    binding(document, route, { ...targets, field: 'canonicalUrl' }, 'Canonical URL override', 'Search and social preview', 'text', document.canonicalUrl),
    binding(document, route, { ...targets, field: 'featuredImage' }, collection === 'posts' ? 'Article cover image' : 'Main image', 'Images', 'image', mediaId(document.featuredImage), {
      image: {
        id: String(mediaValue(document.featuredImage).id || ''),
        sourceId: String(mediaValue(document.featuredImage).sourceId || ''),
        url: String(mediaValue(document.featuredImage).url || mediaValue(document.featuredImage).originalUrl || ''),
        filename: String(mediaValue(document.featuredImage).filename || ''),
        alt: String(mediaValue(document.featuredImage).alt || ''),
      },
    }),
  ]

  const sections = Array.isArray(document.sections) ? document.sections : []
  for (const section of sections) {
    const sectionRow = objectValue(section)
    const sectionKey = String(sectionRow.key || '')
    if (!sectionKey) throw new Error('Editable Payload section has no stable ID.')
    const sectionLabel = labelValue(sectionRow.label, 'Page section')
    const sectionTarget = { ...targets, sectionKey }
    fields.push(binding(document, route, { ...sectionTarget, field: 'sectionLabel' }, `${sectionLabel} heading`, sectionLabel, 'text', sectionRow.label))
    const entries = Array.isArray(sectionRow.entries) ? sectionRow.entries : []
    for (const rawEntry of entries) {
      const entry = objectValue(rawEntry)
      const entryKey = String(entry.key || '')
      const block = String(entry.blockType || '')
      if (!entryKey || !block) throw new Error('Editable Payload content is missing a stable ID or supported type.')
      const entryTarget = { ...sectionTarget, entryKey }
      const label = labelValue(entry.label, 'Page content')
      if (block === 'helloAdaHeading' || block === 'helloAdaParagraph') {
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'text' }, label, sectionLabel, 'text', entry.text))
      } else if (block === 'helloAdaRichText') {
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'value' }, label, sectionLabel, 'richText', entry.value, { richText: entry.value }))
      } else if (block === 'helloAdaImage') {
        const image = mediaValue(entry.image)
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'image' }, label, 'Images', 'image', mediaId(entry.image), { image: {
          id: String(image.id || ''), sourceId: String(image.sourceId || ''), url: String(image.url || image.originalUrl || ''),
          filename: String(image.filename || ''), alt: String(entry.alt || image.alt || ''),
        } }))
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'alt' }, `${label} alternative text`, 'Images', 'text', entry.alt))
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'caption' }, `${label} caption`, 'Images', 'text', entry.caption))
      } else if (block === 'helloAdaLink') {
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'text' }, `${label} text`, sectionLabel, 'text', entry.text))
        fields.push(binding(document, route, { ...entryTarget, field: 'entry', property: 'href' }, `${label} destination`, sectionLabel, 'link', entry.href))
      } else if (block === 'helloAdaContentList') {
        if (!Array.isArray(entry.items)) throw new Error(`Payload list “${label}” has invalid items.`)
        for (const rawItem of entry.items) {
          const item = objectValue(rawItem)
          const itemKey = String(item.key || '')
          if (!itemKey) throw new Error(`Payload list “${label}” contains an item with no stable ID.`)
          const itemTarget = { ...entryTarget, itemKey, field: 'item' }
          const itemLabel = labelValue(item.title, label)
          fields.push(binding(document, route, { ...itemTarget, property: 'title' }, `${itemLabel} title`, label, 'text', item.title))
          fields.push(binding(document, route, { ...itemTarget, property: 'body' }, `${itemLabel} description`, label, 'text', item.body))
          const image = mediaValue(item.image)
          fields.push(binding(document, route, { ...itemTarget, property: 'image' }, `${itemLabel} image`, 'Images', 'image', mediaId(item.image), { image: {
            id: String(image.id || ''), sourceId: String(image.sourceId || ''), url: String(image.url || image.originalUrl || ''),
            filename: String(image.filename || ''), alt: String(item.alt || image.alt || ''),
          } }))
          fields.push(binding(document, route, { ...itemTarget, property: 'alt' }, `${itemLabel} alternative text`, 'Images', 'text', item.alt))
          fields.push(binding(document, route, { ...itemTarget, property: 'linkText' }, `${itemLabel} link text`, label, 'text', item.linkText))
          fields.push(binding(document, route, { ...itemTarget, property: 'href' }, `${itemLabel} destination`, label, 'link', item.href))
        }
      }
    }
  }
  return fields
}

const findByKey = (items: unknown[], key: string, label: string) => {
  const matches = items.map(objectValue).filter((item) => item.key === key)
  if (matches.length !== 1) throw new Error(`${label} identity is missing or ambiguous; reload the page before editing.`)
  return matches[0]
}

export const readHelloAdaBindingValue = (document: Row, target: HelloAdaBindingTarget): unknown => {
  if (target.field === 'seoTitle') return objectValue(document.seo).title ?? ''
  if (target.field === 'seoDescription') return objectValue(document.seo).description ?? ''
  if (target.field === 'seoImage') return mediaId(objectValue(document.seo).image)
  if (target.field === 'canonicalUrl') return document.canonicalUrl ?? ''
  if (target.field === 'body') return helloAdaPlainText(document.body)
  if (target.field === 'featuredImage') return mediaId(document.featuredImage)
  if (target.field === 'title' || target.field === 'summary') return document[target.field] ?? ''
  const sections = Array.isArray(document.sections) ? document.sections : []
  const section = findByKey(sections, String(target.sectionKey || ''), 'Section')
  if (target.field === 'sectionLabel') return section.label ?? ''
  const entries = Array.isArray(section.entries) ? section.entries : []
  const entry = findByKey(entries, String(target.entryKey || ''), 'Content item')
  if (target.field === 'entry') {
    const editableProperties: Record<string, readonly string[]> = {
      helloAdaHeading: ['text'],
      helloAdaParagraph: ['text'],
      helloAdaRichText: ['value'],
      helloAdaImage: ['image', 'alt', 'caption'],
      helloAdaLink: ['text', 'href'],
    }
    if (!editableProperties[String(entry.blockType || '')]?.includes(String(target.property || ''))) {
      throw new Error('This Payload content property is not owner-editable.')
    }
    if (target.property === 'image') return mediaId(entry.image)
    if (target.property === 'value') return helloAdaPlainText(entry.value)
    return entry[String(target.property || '')] ?? ''
  }
  if (target.field === 'item') {
    if (entry.blockType !== 'helloAdaContentList') throw new Error('This Payload content item is not an editable list.')
    if (!['title', 'body', 'image', 'alt', 'linkText', 'href'].includes(String(target.property || ''))) {
      throw new Error('This Payload list property is not owner-editable.')
    }
    const items = Array.isArray(entry.items) ? entry.items : []
    const item = findByKey(items, String(target.itemKey || ''), 'List item')
    if (target.property === 'image') return mediaId(item.image)
    return item[String(target.property || '')] ?? ''
  }
  throw new Error('This Payload value is not owner-editable.')
}

const checkedValue = (target: HelloAdaBindingTarget, value: unknown) => {
  if (target.property === 'href') {
    const validation = value === '' || value === null ? true : validateHelloAdaLink(value)
    if (validation !== true) throw new Error(validation)
  }
  if (target.field === 'canonicalUrl' && value !== '' && value !== null) {
    try {
      const url = new URL(String(value))
      if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new Error('Canonical URL must use HTTP or HTTPS.')
    } catch (cause) {
      throw new Error(cause instanceof Error && cause.message.includes('Canonical URL') ? cause.message : 'Enter a complete canonical URL using HTTP or HTTPS.')
    }
  }
  if (target.property === 'value' || target.field === 'body') {
    const root = objectValue(value).root
    if (!root || typeof root !== 'object' || Array.isArray(root) || !Array.isArray(objectValue(root).children)) {
      throw new Error('Rich text must use the Payload Lexical document format.')
    }
    if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 200_000) throw new Error('Rich text exceeds the supported content size.')
  } else if (target.property === 'image' || target.field === 'featuredImage' || target.field === 'seoImage') {
    if (value !== '' && value !== null && !(typeof value === 'string' || typeof value === 'number')) throw new Error('Choose one image from the media library.')
  } else if (typeof value !== 'string') {
    throw new Error('This content field must be text.')
  }
  return value
}

const setTargetValue = (document: Row, target: HelloAdaBindingTarget, value: unknown) => {
  if (target.field === 'seoTitle' || target.field === 'seoDescription' || target.field === 'seoImage') {
    const property = target.field === 'seoTitle' ? 'title' : target.field === 'seoDescription' ? 'description' : 'image'
    const seo = { ...objectValue(document.seo), [property]: property === 'image' && value === '' ? null : value }
    return { ...document, seo }
  }
  if (target.field === 'canonicalUrl') return { ...document, canonicalUrl: value }
  if (target.field === 'title' || target.field === 'summary' || target.field === 'body' || target.field === 'featuredImage') {
    return { ...document, [target.field === 'featuredImage' && value === '' ? target.field : target.field]: value === '' && target.field === 'featuredImage' ? null : value }
  }
  const sections = Array.isArray(document.sections) ? structuredClone(document.sections) as unknown[] : []
  const section = findByKey(sections, String(target.sectionKey || ''), 'Section')
  if (target.field === 'sectionLabel') {
    section.label = value
  } else {
    const entries = Array.isArray(section.entries) ? section.entries : []
    const entry = findByKey(entries, String(target.entryKey || ''), 'Content item')
    if (target.field === 'entry') {
      const property = String(target.property || '')
      entry[property] = property === 'image' && value === '' ? null : value
    } else if (target.field === 'item') {
      const items = Array.isArray(entry.items) ? entry.items : []
      const item = findByKey(items, String(target.itemKey || ''), 'List item')
      const property = String(target.property || '')
      item[property] = property === 'image' && value === '' ? null : value
    } else {
      throw new Error('This Payload value is not owner-editable.')
    }
  }
  return { ...document, sections }
}

/** Apply a group of stable-key edits atomically against one exact draft. */
export const applyHelloAdaBindingEdits = (document: Row, edits: HelloAdaBindingEdit[]) => {
  if (!edits.length) throw new Error('Choose at least one content change.')
  const actualDocumentId = String(document.id || '')
  const seen = new Set<string>()
  for (const edit of edits) {
    if (edit.documentId !== actualDocumentId) throw new Error('Content edit belongs to a different Payload document.')
    const id = helloAdaBindingId(edit.collection, edit.documentId, edit)
    if (seen.has(id)) throw new Error('The same content value was submitted more than once.')
    seen.add(id)
    const current = readHelloAdaBindingValue(document, edit)
    const currentComparable = edit.field === 'body' || edit.property === 'value'
      ? helloAdaPlainText(current)
      : current == null ? '' : String(current)
    if (currentComparable !== String(edit.expectedValue ?? '')) throw new Error('Content changed before this edit was saved. Reload the page and try again.')
    checkedValue(edit, edit.newValue)
  }
  return edits.reduce((next, edit) => setTargetValue(next, edit, checkedValue(edit, edit.newValue)), document)
}
