import { JWTAuthentication } from 'payload'
import type { Block, CollectionConfig, GlobalConfig } from 'payload'

export const HELLOADA_CONTENT_CONTRACT_VERSION = 'helloada-content-v4'
export const HELLOADA_CORE_VERSION = '0.5.9'
export const HELLOADA_SCHEMA_REVISION = 8

export const validateHelloAdaLink = (value: unknown): true | string => {
  if (typeof value !== 'string' || !value.trim()) return 'Enter a destination for this link.'
  const destination = value.trim()
  if (destination.includes('\\') || destination.startsWith('//') || [...destination].some((char) => char.charCodeAt(0) < 32)) {
    return 'This destination is not safe.'
  }
  if (destination.startsWith('/') || destination.startsWith('#') || destination.startsWith('mailto:') || destination.startsWith('tel:')) return true
  try {
    const parsed = new URL(destination)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? true : 'Use a site path, anchor, email, phone, or secure website URL.'
  } catch {
    return 'Use a site path, anchor, email, phone, or secure website URL.'
  }
}

const stableKey = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0 && value.trim().length <= 120

const newStableKey = () => `ha-${globalThis.crypto.randomUUID()}`

const ownerCanRead = ({ req }: { req: { user?: unknown } }) => Boolean(req.user)
const ownerCanWrite = ({ req }: { req: { user?: unknown } }) => Boolean(req.user)
const serviceOnly = () => false

const assignFormFieldKeys = (value: unknown, createId: () => string = newStableKey): unknown => {
  if (!Array.isArray(value)) return value
  return value.map((rawField) => {
    if (!rawField || typeof rawField !== 'object' || Array.isArray(rawField)) return rawField
    const field = rawField as Record<string, unknown>
    const choices = Array.isArray(field.choices) ? field.choices.map((rawChoice) => {
      if (!rawChoice || typeof rawChoice !== 'object' || Array.isArray(rawChoice)) return rawChoice
      const choice = rawChoice as Record<string, unknown>
      return { ...choice, key: stableKey(choice.key) ? choice.key : createId() }
    }) : field.choices
    return {
      ...field,
      key: stableKey(field.key) ? field.key : createId(),
      ...(Array.isArray(choices) ? { choices } : {}),
    }
  })
}

export const validateHelloAdaFormFields = (value: unknown): true | string => {
  if (!Array.isArray(value) || value.length < 1 || value.length > 12) return 'A form needs between 1 and 12 fields.'
  const keys = new Set<string>()
  const mappings = new Set<string>()
  const supportedTypes = new Set(['text', 'email', 'phone', 'textarea', 'select', 'consent'])
  const supportedMappings = new Set(['none', 'name', 'email', 'phone', 'company', 'message'])
  for (const [index, rawField] of value.entries()) {
    const field = rawField && typeof rawField === 'object' && !Array.isArray(rawField)
      ? rawField as Record<string, unknown>
      : {}
    if (!stableKey(field.key)) return `Form field ${index + 1} needs a stable ID.`
    if (keys.has(field.key)) return `Form field ID “${field.key}” is used more than once.`
    keys.add(field.key)
    if (!supportedTypes.has(String(field.type || ''))) return `Form field ${index + 1} has an unsupported type.`
    if (!String(field.label || '').trim()) return `Form field ${index + 1} needs a label.`
    if (String(field.label).length > 160) return `Form field ${index + 1} label is too long.`
    const mapping = String(field.mapsTo || 'none')
    if (!supportedMappings.has(mapping)) return `Form field ${index + 1} has an unsupported contact mapping.`
    if (mapping !== 'none') {
      if (mappings.has(mapping)) return `Only one form field can provide the ${mapping} value.`
      mappings.add(mapping)
    }
    if (mapping === 'email' && field.type !== 'email') return `Form field ${index + 1} must use the email input type.`
    if (mapping === 'email' && field.required !== true) return `Form field ${index + 1} must require an email address.`
    if (mapping === 'message' && !['text', 'textarea'].includes(String(field.type))) {
      return `Form field ${index + 1} must use a text input for the enquiry message.`
    }
    if (mapping === 'message' && field.required !== true) return `Form field ${index + 1} must require an enquiry message.`
    if (['name', 'company'].includes(mapping) && field.type !== 'text') return `Form field ${index + 1} must use a short text input.`
    if (mapping === 'phone' && field.type !== 'phone') return `Form field ${index + 1} must use the phone input type.`
    if (field.type === 'consent' && field.required !== true) return `Acknowledgement field ${index + 1} must be required.`
    if (field.maxLength !== undefined && field.maxLength !== null) {
      const maxLength = Number(field.maxLength)
      if (!Number.isInteger(maxLength) || maxLength < 1 || maxLength > 4000) return `Form field ${index + 1} has an invalid length limit.`
    }
    if (field.type === 'select') {
      if (!Array.isArray(field.choices) || field.choices.length < 1 || field.choices.length > 20) {
        return `Select field ${index + 1} needs between 1 and 20 choices.`
      }
      const choiceKeys = new Set<string>()
      for (const choice of field.choices) {
        const row = choice && typeof choice === 'object' && !Array.isArray(choice)
          ? choice as Record<string, unknown>
          : {}
        if (!stableKey(row.key) || choiceKeys.has(row.key) || !String(row.label || '').trim()) {
          return `Select field ${index + 1} has an invalid or duplicate choice.`
        }
        choiceKeys.add(row.key)
      }
    }
  }
  if (!mappings.has('email') || !mappings.has('message')) return 'A contact form must map one email field and one enquiry message.'
  return true
}

/**
 * Payload's read-only semantic IDs are generated once when a new record is
 * created. Existing IDs are never derived from array positions or regenerated
 * during edits/reordering.
 */
export const assignHelloAdaPageKeys = (
  value: unknown,
  createId: () => string = newStableKey,
): unknown => {
  if (!Array.isArray(value)) return value
  return value.map((rawSection) => {
    if (!rawSection || typeof rawSection !== 'object' || Array.isArray(rawSection)) return rawSection
    const section = rawSection as Record<string, unknown>
    const sectionKey = stableKey(section.key) ? section.key : createId()
    const entries = Array.isArray(section.entries) ? section.entries.map((rawEntry) => {
      if (!rawEntry || typeof rawEntry !== 'object' || Array.isArray(rawEntry)) return rawEntry
      const entry = rawEntry as Record<string, unknown>
      const entryKey = stableKey(entry.key) ? entry.key : createId()
      const items = Array.isArray(entry.items) ? entry.items.map((rawItem) => {
        if (!rawItem || typeof rawItem !== 'object' || Array.isArray(rawItem)) return rawItem
        const item = rawItem as Record<string, unknown>
        return { ...item, key: stableKey(item.key) ? item.key : createId() }
      }) : entry.items
      return {
        ...entry,
        key: entryKey,
        ...(Array.isArray(items) ? { items } : {}),
      }
    }) : section.entries
    return {
      ...section,
      key: sectionKey,
      ...(Array.isArray(entries) ? { entries } : {}),
    }
  })
}

export const assignHelloAdaNavigationKeys = (
  value: unknown,
  createId: () => string = newStableKey,
): unknown => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value
  const assignItems = (raw: unknown): unknown => {
    if (!Array.isArray(raw)) return raw
    return raw.map((rawItem) => {
      if (!rawItem || typeof rawItem !== 'object' || Array.isArray(rawItem)) return rawItem
      const item = rawItem as Record<string, unknown>
      return {
        ...item,
        key: stableKey(item.key) ? item.key : createId(),
        ...(Array.isArray(item.items) ? { items: assignItems(item.items) } : {}),
      }
    })
  }
  const root = value as Record<string, unknown>
  return Object.fromEntries(Object.entries(root).map(([key, entries]) => [
    key,
    ['items', 'footer', 'groups', 'footerGroups'].includes(key) ? assignItems(entries) : entries,
  ]))
}

/** Enforce the IDs that connect editable Payload values to rendered content. */
export const validateHelloAdaPageSections = (value: unknown): true | string => {
  if (value === undefined || value === null) return true
  if (!Array.isArray(value)) return 'Page content must be a list of named sections.'
  const keys = new Set<string>()
  const addKey = (candidate: unknown, label: string): string | null => {
    if (!stableKey(candidate)) return `${label} needs a stable content ID.`
    const normalized = candidate.trim()
    if (keys.has(normalized)) return `The content ID “${normalized}” is used more than once on this page.`
    keys.add(normalized)
    return null
  }
  for (const [sectionIndex, rawSection] of value.entries()) {
    const section = rawSection && typeof rawSection === 'object' && !Array.isArray(rawSection)
      ? rawSection as Record<string, unknown>
      : {}
    const sectionKeyError = addKey(section.key, `Section ${sectionIndex + 1}`)
    if (sectionKeyError) return sectionKeyError
    if (!String(section.label || '').trim()) return `Section ${sectionIndex + 1} needs a name.`
    const entries = section.entries
    if (entries === undefined || entries === null) continue
    if (!Array.isArray(entries)) return `Section ${sectionIndex + 1} content must be a list.`
    for (const [entryIndex, rawEntry] of entries.entries()) {
      const entry = rawEntry && typeof rawEntry === 'object' && !Array.isArray(rawEntry)
        ? rawEntry as Record<string, unknown>
        : {}
      const entryKeyError = addKey(entry.key, `Section ${sectionIndex + 1}, item ${entryIndex + 1}`)
      if (entryKeyError) return entryKeyError
      if (!supportedContentBlocks.has(String(entry.blockType || ''))) {
        return `Section ${sectionIndex + 1}, item ${entryIndex + 1} uses an unsupported content type.`
      }
      if (!String(entry.label || '').trim()) return `Section ${sectionIndex + 1}, item ${entryIndex + 1} needs an editor label.`
      if (entry.blockType === 'helloAdaContactForm' && !entry.form) {
        return `The contact form in section ${sectionIndex + 1} needs a published form selection.`
      }
      if (entry.blockType === 'helloAdaBooking' && !/^ha_booking_[a-f0-9]{32}$/.test(String(entry.bookingTypeId || ''))) {
        return 'The booking form in section ' + (sectionIndex + 1) + ' needs a valid booking type ID.'
      }
      if (entry.blockType !== 'helloAdaContentList') continue
      if (entry.items === undefined || entry.items === null) continue
      if (!Array.isArray(entry.items)) return `The list in section ${sectionIndex + 1} is invalid.`
      for (const [itemIndex, rawItem] of entry.items.entries()) {
        const item = rawItem && typeof rawItem === 'object' && !Array.isArray(rawItem)
          ? rawItem as Record<string, unknown>
          : {}
        const itemKeyError = addKey(item.key, `List item ${itemIndex + 1}`)
        if (itemKeyError) return itemKeyError
      }
    }
  }
  return true
}

export const validateHelloAdaNavigation = (value: unknown): true | string => {
  if (value === undefined || value === null) return true
  if (typeof value !== 'object' || Array.isArray(value)) return 'Navigation must be an object.'
  const root = value as Record<string, unknown>
  const keys = new Set<string>()
  const collect = (raw: unknown, scope: string): string | null => {
    if (raw === undefined || raw === null) return null
    if (!Array.isArray(raw)) return `${scope} must be a list.`
    for (const [index, itemValue] of raw.entries()) {
      const item = itemValue && typeof itemValue === 'object' && !Array.isArray(itemValue)
        ? itemValue as Record<string, unknown>
        : {}
      if (!stableKey(item.key)) return `${scope} item ${index + 1} needs a stable content ID.`
      const key = item.key.trim()
      if (keys.has(key)) return `The navigation ID “${key}” is used more than once.`
      keys.add(key)
      if (Array.isArray(item.items)) {
        const nested = collect(item.items, `${scope} group ${index + 1}`)
        if (nested) return nested
      }
    }
    return null
  }
  for (const field of ['items', 'footer', 'groups', 'footerGroups']) {
    const error = collect(root[field], field)
    if (error) return error
  }
  return true
}

export type NativeWriteGuard = (
  scope: string,
  documentId: unknown,
  req: { context?: Record<string, unknown> } | undefined,
  operation?: string,
  data?: unknown,
) => Promise<void>

const protectCollection = (slug: string, guard: NativeWriteGuard): CollectionConfig['hooks'] => {
  const isWrite = (operation: string) => ['create', 'update', 'updateByID', 'delete', 'deleteByID'].includes(operation)
  return {
    beforeOperation: [async ({ args, operation }) => {
      if (isWrite(operation)) {
        const operationArgs = args as unknown as { id?: unknown; data?: unknown; req?: { context?: Record<string, unknown> } }
        await guard(slug, operationArgs.id, operationArgs.req, operation, operationArgs.data)
      }
    }],
    afterOperation: [async ({ req, operation, result }) => {
      if (isWrite(operation)) await guard(slug, undefined, req, 'complete')
      return result
    }],
    afterError: [async ({ req }) => {
      await guard(slug, undefined, req, 'failed')
    }],
  }
}

const sectionCollectionHooks = (slug: string, guard: NativeWriteGuard): CollectionConfig['hooks'] => ({
  ...protectCollection(slug, guard),
  beforeValidate: [async ({ data, originalDoc }) => {
    const sections = assignHelloAdaPageKeys(data?.sections)
    const result = validateHelloAdaPageSections(sections)
    if (result !== true) throw new Error(result)
    const routeSlug = String(data?.slug || originalDoc?.slug || '').trim()
    const sourceId = String(originalDoc?.sourceId || (routeSlug ? `${slug}:${routeSlug}` : '')).trim()
    return {
      ...data,
      ...(sourceId ? { sourceId } : {}),
      ...(sections === undefined ? {} : { sections }),
    }
  }],
})

const seoFields = () => ({
  name: 'seo' as const,
  type: 'group' as const,
  label: 'Search and social preview',
  fields: [
    { name: 'title', type: 'text' as const, localized: true, label: 'Search title' },
    { name: 'description', type: 'textarea' as const, localized: true, label: 'Search description' },
    { name: 'image', type: 'upload' as const, relationTo: 'media' as const, localized: true, label: 'Social preview image' },
  ],
})

const sectionBlocks: Block[] = [
  {
    slug: 'helloAdaHeading', labels: { singular: 'Heading', plural: 'Headings' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this text is for' },
      { name: 'text', type: 'text' as const, required: true, localized: true, label: 'Text' },
      { name: 'level', type: 'select' as const, defaultValue: 'h2', options: ['h2', 'h3', 'h4'], label: 'Heading level' },
    ],
  },
  {
    slug: 'helloAdaParagraph', labels: { singular: 'Paragraph', plural: 'Paragraphs' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this text is for' },
      { name: 'text', type: 'textarea' as const, required: true, localized: true, label: 'Text' },
    ],
  },
  {
    slug: 'helloAdaRichText', labels: { singular: 'Formatted text', plural: 'Formatted text' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this content is for' },
      { name: 'value', type: 'richText' as const, localized: true, label: 'Content' },
    ],
  },
  {
    slug: 'helloAdaImage', labels: { singular: 'Image', plural: 'Images' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this image is for' },
      { name: 'image', type: 'upload' as const, relationTo: 'media' as const, required: true, label: 'Image' },
      { name: 'alt', type: 'text' as const, localized: true, label: 'Alternative text' },
      { name: 'caption', type: 'textarea' as const, localized: true, label: 'Caption' },
    ],
  },
  {
    slug: 'helloAdaLink', labels: { singular: 'Link or button', plural: 'Links and buttons' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this link is for' },
      { name: 'text', type: 'text' as const, required: true, maxLength: 160, localized: true, label: 'Button or link text' },
      { name: 'href', type: 'text' as const, required: true, localized: true, validate: validateHelloAdaLink, label: 'Page or URL' },
      { name: 'external', type: 'checkbox' as const, defaultValue: false, label: 'External website' },
      { name: 'newTab', type: 'checkbox' as const, defaultValue: false, label: 'Open in a new tab' },
    ],
  },
  {
    slug: 'helloAdaContentList', labels: { singular: 'List of items', plural: 'Lists of items' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this list is for' },
      {
        name: 'items', type: 'array' as const, maxRows: 40, labels: { singular: 'Item', plural: 'Items' },
        fields: [
          { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable item ID' },
          { name: 'title', type: 'text' as const, localized: true, label: 'Title' },
          { name: 'body', type: 'textarea' as const, localized: true, label: 'Description' },
          { name: 'image', type: 'upload' as const, relationTo: 'media' as const, localized: true, label: 'Image' },
          { name: 'alt', type: 'text' as const, localized: true, label: 'Alternative text' },
          { name: 'linkText', type: 'text' as const, localized: true, label: 'Link text' },
          { name: 'href', type: 'text' as const, localized: true, validate: (value: unknown) => value == null || value === '' ? true : validateHelloAdaLink(value), label: 'Page or URL' },
        ],
      },
    ],
  },
  {
    slug: 'helloAdaContactForm', labels: { singular: 'Contact form', plural: 'Contact forms' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this form is for' },
      { name: 'form', type: 'relationship' as const, relationTo: 'contactForms' as const, required: true, label: 'Form' },
    ],
  },
  {
    slug: 'helloAdaBooking', labels: { singular: 'Booking calendar', plural: 'Booking calendars' },
    fields: [
      { name: 'key', type: 'text' as const, required: true, admin: { readOnly: true }, label: 'Stable content ID' },
      { name: 'label', type: 'text' as const, required: true, label: 'What this booking is for' },
      { name: 'bookingTypeId', type: 'text' as const, required: true, maxLength: 43, label: 'Stable booking type ID' },
    ],
  },
]

const contentBlockSlugs = sectionBlocks.map((block) => block.slug)
const supportedContentBlocks = new Set(contentBlockSlugs)

/** Platform-owned capabilities consumed by scaffolding and release validation. */
export const HELLOADA_CAPABILITIES = {
  contract: HELLOADA_CONTENT_CONTRACT_VERSION,
  schemaRevision: HELLOADA_SCHEMA_REVISION,
  collections: ['pages', 'posts', 'postCategories', 'products', 'productCategories', 'media', 'contactForms', 'appointmentTypes', 'calendarEvents', 'calendarSlotLocks', 'contacts', 'conversations', 'messages', 'messageOperations'],
  globals: ['siteSettings', 'navigation', 'messageMailbox', 'calendarSettings'],
  contentBlocks: contentBlockSlugs,
} as const

/** Website content an Ada design operation may author. Operational collections
 * and service-owned globals are intentionally excluded even when they are part
 * of the wider Payload schema. */
export const HELLOADA_AUTHORING_CAPABILITIES = {
  collections: ['pages', 'posts', 'products'],
  globals: ['siteSettings', 'navigation'],
} as const

const AUTHORING_RESERVED_FIELDS = new Set([
  'sourceId', 'published', 'createdAt', 'updatedAt', 'deletedAt', '_status',
  'id', 'version', 'version__parent', 'version__publishedAt',
])

type AuthoringField = {
  name?: string
  type?: string
  admin?: { hidden?: boolean }
  fields?: AuthoringField[]
  blocks?: Array<{ slug?: string; fields?: AuthoringField[] }>
  options?: unknown[]
  relationTo?: string | string[]
  hasMany?: boolean
  localized?: boolean
  required?: boolean
  min?: number
  max?: number
  minLength?: number
  maxLength?: number
  minRows?: number
  maxRows?: number
}

type AuthoringFieldShape = {
  name: string
  type: string
  options?: unknown[]
  fields?: AuthoringFieldShape[]
  blocks?: Array<{ slug: string; fields: AuthoringFieldShape[] }>
  [key: string]: unknown
}

const asRow = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

const authoringFieldTypes = new Set([
  'array', 'blocks', 'checkbox', 'date', 'email', 'group', 'json', 'number',
  'relationship', 'richText', 'select', 'text', 'textarea', 'upload',
])

const authoringFieldShape = (field: AuthoringField): AuthoringFieldShape => {
  const type = String(field.type || '')
  if (!authoringFieldTypes.has(type)) {
    throw new Error(`Payload field ${String(field.name || '(unnamed)')} uses unsupported authoring type “${type}”.`)
  }
  if (type === 'select' && !Array.isArray(field.options)) {
    throw new Error(`Payload select field ${String(field.name || '(unnamed)')} has no declared options.`)
  }
  if ((type === 'group' || type === 'array') && !Array.isArray(field.fields)) {
    throw new Error(`Payload ${type} field ${String(field.name || '(unnamed)')} has no declared child fields.`)
  }
  if (type === 'blocks' && !Array.isArray(field.blocks)) {
    throw new Error(`Payload blocks field ${String(field.name || '(unnamed)')} has no declared blocks.`)
  }
  return ({
  name: String(field.name || ''),
  type: String(field.type || ''),
  ...(field.required ? { required: true } : {}),
  ...(field.localized ? { localized: true } : {}),
  ...(field.min !== undefined ? { min: field.min } : {}),
  ...(field.max !== undefined ? { max: field.max } : {}),
  ...(field.minLength !== undefined ? { minLength: field.minLength } : {}),
  ...(field.maxLength !== undefined ? { maxLength: field.maxLength } : {}),
  ...(field.minRows !== undefined ? { minRows: field.minRows } : {}),
  ...(field.maxRows !== undefined ? { maxRows: field.maxRows } : {}),
  ...(field.relationTo ? { relationTo: field.relationTo } : {}),
  ...(field.hasMany ? { hasMany: true } : {}),
  ...(Array.isArray(field.options) ? {
    options: field.options.map((option) => {
      if (typeof option === 'string' || typeof option === 'number') return option
      const row = asRow(option)
      return { label: String(row.label || row.value || ''), value: row.value }
    }),
  } : {}),
  ...(Array.isArray(field.fields) ? { fields: authoringFieldListShape(field.fields as AuthoringField[]) } : {}),
  ...(Array.isArray(field.blocks) ? {
    blocks: field.blocks.map((block) => ({
      slug: String(block.slug || ''),
      fields: authoringFieldListShape((block.fields || []) as AuthoringField[]),
    })),
  } : {}),
  })
}

const validateLexical = (value: unknown, path: string): void => {
  const row = asRow(value)
  const root = asRow(row.root)
  const extraDocumentFields = Object.keys(row).filter((key) => !['root', 'version'].includes(key))
  if (extraDocumentFields.length) throw new Error(`${path} contains unsupported rich-text fields: ${extraDocumentFields.join(', ')}.`)
  if (row.version !== undefined && typeof row.version !== 'string') throw new Error(`${path}.version must be text.`)
  if (root.type !== 'root' || !Array.isArray(root.children)) throw new Error(`${path} must be a Payload Lexical document.`)
  const walk = (nodeValue: unknown, nodePath: string, depth: number): void => {
    if (depth > 40) throw new Error(`${nodePath} exceeds the supported rich-text depth.`)
    const node = asRow(nodeValue)
    if (!node || typeof node.type !== 'string') throw new Error(`${nodePath} has an invalid Lexical node.`)
    const common = new Set(['type', 'version', 'format', 'indent', 'direction', 'textFormat', 'textStyle', 'children'])
    const byType: Record<string, readonly string[]> = {
      root: [], paragraph: [], heading: ['tag'], quote: [], list: ['listType', 'start', 'tag'],
      listitem: ['value', 'checked'], text: ['text', 'mode', 'detail', 'style'],
      linebreak: [], link: ['fields', 'url', 'newTab', 'linkType', 'doc'],
      autolink: ['fields', 'url', 'newTab', 'linkType', 'doc'], upload: ['value', 'relationTo'],
      horizontalrule: [], tab: [],
    }
    const known = byType[node.type]
    if (!known) throw new Error(`${nodePath} uses unsupported Lexical node “${node.type}”.`)
    const allowed = new Set([...common, ...known])
    const extra = Object.keys(node).filter((key) => !allowed.has(key))
    if (extra.length) throw new Error(`${nodePath} contains unsupported properties: ${extra.join(', ')}.`)
    if (node.type === 'text' && typeof node.text !== 'string') throw new Error(`${nodePath}.text must be text.`)
    if (node.type === 'heading' && !['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(String(node.tag || ''))) {
      throw new Error(`${nodePath}.tag is not a supported heading level.`)
    }
    if (node.type === 'list' && !['bullet', 'number', 'check'].includes(String(node.listType || ''))) {
      throw new Error(`${nodePath}.listType is unsupported.`)
    }
    if (node.fields !== undefined) {
      const fields = asRow(node.fields)
      const allowedFields = new Set(['url', 'newTab', 'linkType', 'doc'])
      const extras = Object.keys(fields).filter((key) => !allowedFields.has(key))
      if (extras.length) throw new Error(`${nodePath}.fields contains unsupported properties: ${extras.join(', ')}.`)
    }
    if (Array.isArray(node.children)) node.children.forEach((child, index) => walk(child, `${nodePath}.children[${index}]`, depth + 1))
  }
  walk({ ...root, type: 'root' }, `${path}.root`, 0)
}

const validateFieldValue = (field: AuthoringField, value: unknown, path: string): void => {
  const type = String(field.type || '')
  const invalid = (expected: string): never => { throw new Error(`${path} must be ${expected}.`) }
  if (!authoringFieldTypes.has(type)) throw new Error(`${path} uses unsupported Payload field type “${type}”.`)
  if (value === null && !field.required) return
  if (type === 'array' || type === 'blocks') {
    if (!Array.isArray(value)) return invalid('a list')
    const items = value as unknown[]
    if (field.minRows !== undefined && items.length < field.minRows) invalid(`a list with at least ${field.minRows} items`)
    if (field.maxRows !== undefined && items.length > field.maxRows) invalid(`a list with at most ${field.maxRows} items`)
    items.forEach((itemValue: unknown, index: number) => {
      const item = itemValue && typeof itemValue === 'object' && !Array.isArray(itemValue)
        ? itemValue as Record<string, unknown>
        : undefined
      if (!item) throw new Error(`${path}[${index}] must be an object.`)
      let children = field.fields || []
      if (type === 'blocks') {
        const block = (field.blocks || []).find((candidate) => candidate.slug === item.blockType)
        if (!block) throw new Error(`${path}[${index}] uses an unsupported content block.`)
        children = block.fields || []
      }
      validateAuthoringRecord(
        item,
        children,
        `${path}[${index}]`,
        type === 'blocks' ? String(item.blockType) : undefined,
        true,
        true,
      )
    })
    return
  }
  if (type === 'group') {
    validateAuthoringRecord(value, field.fields || [], path, undefined, false, true)
    return
  }
  if (type === 'richText') {
    validateLexical(value, path)
    return
  }
  if (type === 'upload' || type === 'relationship') {
    if (field.hasMany) {
      if (!Array.isArray(value) || value.some((item) => !isRelationIdentity(item))) invalid('a list of Payload relationship IDs')
    } else if (!isRelationIdentity(value)) invalid('a Payload relationship ID')
    return
  }
  if (['text', 'textarea', 'email', 'date', 'code', 'radio'].includes(type)) {
    if (typeof value !== 'string') return invalid('text')
    const textValue = value as string
    if (field.required && !textValue.trim()) invalid('non-empty text')
    if (field.minLength !== undefined && textValue.length < field.minLength) invalid(`text with at least ${field.minLength} characters`)
    if (field.maxLength !== undefined && textValue.length > field.maxLength) invalid(`text with at most ${field.maxLength} characters`)
    if (['href', 'promoHref', 'canonicalUrl'].includes(String(field.name)) && textValue.trim()) {
      const result = validateHelloAdaLink(textValue)
      if (result !== true) throw new Error(`${path} is not a safe link.`)
    }
  }
  if (type === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value)) return invalid('a finite number')
    const numberValue = value as number
    if (field.min !== undefined && numberValue < field.min) invalid(`at least ${field.min}`)
    if (field.max !== undefined && numberValue > field.max) invalid(`at most ${field.max}`)
  }
  if (type === 'checkbox' && typeof value !== 'boolean') invalid('true or false')
  if (type === 'select' && Array.isArray(field.options)) {
    const options = field.options.map((option) => typeof option === 'string' ? option : asRow(option).value)
    if (!options.includes(value)) invalid('a supported option')
  }
  if (type === 'date' && (typeof value !== 'string' || !Number.isFinite(Date.parse(value)))) invalid('a valid date')
  if (type === 'email' && (typeof value !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))) invalid('a valid email address')
  if (type === 'json') validateJsonValue(value, path)
}

const validateJsonValue = (value: unknown, path: string, depth = 0): void => {
  if (depth > 40) throw new Error(`${path} exceeds the supported JSON depth.`)
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`${path} must contain finite JSON numbers.`)
    return
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => validateJsonValue(item, `${path}[${index}]`, depth + 1))
    return
  }
  if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    for (const [key, child] of Object.entries(value)) validateJsonValue(child, `${path}.${key}`, depth + 1)
    return
  }
  throw new Error(`${path} must contain JSON-compatible data.`)
}

const isRelationIdentity = (value: unknown): boolean =>
  (typeof value === 'string' && value.trim().length > 0)
  || (typeof value === 'number' && Number.isSafeInteger(value) && value > 0)

const validateAuthoringRecord = (
  value: unknown,
  fields: AuthoringField[],
  path: string,
  blockType?: string,
  allowPayloadRowId = false,
  requireRequiredFields = false,
): void => {
  const row = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
  if (!row) throw new Error(`${path} must be an object.`)
  const allowed = new Map(fields
    .filter((field) => typeof field.name === 'string' && !AUTHORING_RESERVED_FIELDS.has(field.name))
    .map((field) => [field.name as string, field]))
  for (const field of allowed.values()) {
    if (!authoringFieldTypes.has(String(field.type || ''))) {
      throw new Error(`${path}.${String(field.name)} uses unsupported Payload field type “${String(field.type || '')}”.`)
    }
  }
  // Payload's own stable IDs are retained on existing array rows/blocks.
  const unknown = Object.keys(row).filter((key) =>
    !(allowPayloadRowId && key === 'id')
    && !(blockType && key === 'blockType')
    && !allowed.has(key),
  )
  if (unknown.length) throw new Error(`${path} contains unsupported fields: ${unknown.join(', ')}.`)
  if (blockType && row.blockType !== blockType) throw new Error(`${path}.blockType does not match its declared Payload block.`)
  if (requireRequiredFields) for (const field of allowed.values()) {
    if (field.required && !Object.hasOwn(row, String(field.name))) {
      throw new Error(`${path}.${String(field.name)} is required.`)
    }
  }
  if (allowPayloadRowId && Object.hasOwn(row, 'id') && !isRelationIdentity(row.id)) {
    throw new Error(`${path}.id must be a Payload row ID.`)
  }
  for (const [key, child] of Object.entries(row)) {
    const field = allowed.get(key)
    if (field) validateFieldValue(field, child, `${path}.${key}`)
  }
}

const privateOwnerAccess = {
  read: ownerCanRead,
  create: ownerCanWrite,
  update: ownerCanWrite,
  delete: serviceOnly,
}

const serviceOwnedAccess = {
  read: ownerCanRead,
  create: serviceOnly,
  update: serviceOnly,
  delete: serviceOnly,
}

export const createContactFormsCollection = (): CollectionConfig => ({
  slug: 'contactForms',
  admin: { useAsTitle: 'title', defaultColumns: ['title', 'slug', 'enabled', 'updatedAt'] },
  versions: { drafts: true, maxPerDoc: 20 },
  access: privateOwnerAccess,
  fields: [
    { name: 'title', type: 'text', required: true, localized: true, label: 'Form name' },
    { name: 'slug', type: 'text', required: true, unique: true, label: 'Form ID' },
    { name: 'intro', type: 'textarea', localized: true, label: 'Introduction' },
    { name: 'submitLabel', type: 'text', required: true, localized: true, defaultValue: 'Send message', label: 'Button text' },
    { name: 'successMessage', type: 'textarea', required: true, localized: true, defaultValue: 'Thank you. Your message has been received.', label: 'Confirmation' },
    {
      name: 'fields', type: 'array', required: true, maxRows: 12, label: 'Questions',
      fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable field ID' },
        { name: 'label', type: 'text', required: true, localized: true, label: 'Question' },
        { name: 'type', type: 'select', required: true, options: ['text', 'email', 'phone', 'textarea', 'select', 'consent'], label: 'Answer type' },
        { name: 'mapsTo', type: 'select', required: true, defaultValue: 'none', options: ['none', 'name', 'email', 'phone', 'company', 'message'], label: 'Save as contact or enquiry detail' },
        { name: 'placeholder', type: 'text', localized: true, label: 'Example text' },
        { name: 'required', type: 'checkbox', defaultValue: false, label: 'Required' },
        { name: 'maxLength', type: 'number', min: 1, max: 4000, defaultValue: 500, label: 'Maximum length' },
        { name: 'choices', type: 'array', maxRows: 20, admin: { condition: (_data: unknown, siblingData: Record<string, unknown>) => siblingData?.type === 'select' }, fields: [
          { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable choice ID' },
          { name: 'label', type: 'text', required: true, localized: true, label: 'Choice' },
        ] },
      ],
    },
    { name: 'enabled', type: 'checkbox', defaultValue: false, label: 'Accept responses' },
  ],
  hooks: {
    beforeValidate: [async ({ data, originalDoc }) => {
      const fields = assignFormFieldKeys(data?.fields ?? originalDoc?.fields)
      const result = validateHelloAdaFormFields(fields)
      if (result !== true) throw new Error(result)
      return { ...data, fields }
    }],
  },
})

export const createAppointmentTypesCollection = (): CollectionConfig => ({
  slug: 'appointmentTypes',
  admin: { hidden: true, useAsTitle: 'name', defaultColumns: ['name', 'durationMinutes', 'enabled', 'updatedAt'] },
  versions: { drafts: true, maxPerDoc: 20 },
  access: { ...privateOwnerAccess, create: () => false, update: () => false, delete: () => false },
  fields: [
    { name: 'name', type: 'text', required: true, localized: true, label: 'Appointment name' },
    { name: 'slug', type: 'text', required: true, unique: true, label: 'Appointment ID' },
    { name: 'description', type: 'textarea', localized: true, label: 'Description' },
    { name: 'durationMinutes', type: 'number', required: true, min: 10, max: 480, defaultValue: 30, label: 'Duration (minutes)' },
    { name: 'bufferMinutes', type: 'number', min: 0, max: 120, defaultValue: 0, label: 'Buffer between bookings (minutes)' },
    { name: 'weeklyAvailability', type: 'array', maxRows: 42, label: 'Weekly availability', fields: [
      { name: 'day', type: 'select', required: true, options: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] },
      { name: 'startTime', type: 'text', required: true, label: 'Start (HH:MM)' },
      { name: 'endTime', type: 'text', required: true, label: 'End (HH:MM)' },
  ] },
  { name: 'enabled', type: 'checkbox', defaultValue: false, label: 'Accept bookings' },
  ],
  hooks: { beforeValidate: [async ({ data, originalDoc }) => {
    const rawAvailability = data?.weeklyAvailability ?? originalDoc?.weeklyAvailability
    const intervals = Array.isArray(rawAvailability) ? rawAvailability as Array<Record<string, unknown>> : []
    const byDay = new Map<string, Array<{ start: string; end: string }>>()
    for (const interval of intervals) {
      for (const field of ['startTime', 'endTime']) {
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(interval[field] || ''))) throw new Error('Availability times must use 24-hour HH:MM format.')
      }
      if (String(interval.startTime) >= String(interval.endTime)) throw new Error('An availability end time must be later than its start time.')
      const day = String(interval.day || '')
      const dayIntervals = byDay.get(day) || []
      if (dayIntervals.some((existing) => String(interval.startTime) < existing.end && String(interval.endTime) > existing.start)) {
        throw new Error('Availability periods on the same day cannot overlap.')
      }
      dayIntervals.push({ start: String(interval.startTime), end: String(interval.endTime) })
      byDay.set(day, dayIntervals)
    }
    if ((data?.enabled ?? originalDoc?.enabled) === true && intervals.length === 0) throw new Error('Add at least one availability period before accepting bookings.')
    for (const field of ['durationMinutes', 'bufferMinutes']) {
      const fallback = originalDoc?.[field] ?? (field === 'durationMinutes' ? 30 : 0)
      const value = Number(data?.[field] ?? fallback)
      if (!Number.isInteger(value) || value % 5 !== 0) throw new Error('Appointment duration and buffer must use five-minute increments.')
    }
    return data
  }] },
})

export const createCalendarEventsCollection = (): CollectionConfig => ({
  slug: 'calendarEvents',
  admin: { useAsTitle: 'title', defaultColumns: ['title', 'startsAt', 'state'], hidden: true },
  access: serviceOwnedAccess,
  fields: [
    { name: 'title', type: 'text', required: true, access: { update: serviceOnly } },
    { name: 'appointmentType', type: 'relationship', relationTo: 'appointmentTypes', required: true, access: { update: serviceOnly } },
    { name: 'contact', type: 'relationship', relationTo: 'contacts', required: true, access: { update: serviceOnly } },
    { name: 'startsAt', type: 'date', required: true, index: true, access: { update: serviceOnly } },
    { name: 'endsAt', type: 'date', required: true, access: { update: serviceOnly } },
    { name: 'bufferMinutes', type: 'number', min: 0, max: 120, access: { update: serviceOnly } },
    { name: 'timeZone', type: 'text', required: true, access: { update: serviceOnly } },
    { name: 'state', type: 'select', required: true, defaultValue: 'confirmed', options: ['confirmed', 'cancelled', 'rescheduled'], access: { update: serviceOnly } },
    { name: 'sourcePage', type: 'text', access: { update: serviceOnly } },
    { name: 'receiptId', type: 'text', required: true, unique: true, index: true, access: { update: serviceOnly } },
    { name: 'answers', type: 'json', access: { update: serviceOnly } },
    { name: 'consentAcceptedAt', type: 'date', access: { update: serviceOnly } },
    { name: 'notificationState', type: 'select', defaultValue: 'pending', options: ['pending', 'accepted', 'failed', 'uncertain'], access: { update: serviceOnly } },
  ],
})

/** Short-lived unique reservations prevent two Workers from confirming the
 * same five-minute interval concurrently. Confirmed calendarEvents become the
 * durable availability source; reservations are removed after materializing. */
export const createCalendarSlotLocksCollection = (): CollectionConfig => ({
  slug: 'calendarSlotLocks',
  admin: { useAsTitle: 'slotKey', hidden: true },
  access: serviceOwnedAccess,
  fields: [
    { name: 'slotKey', type: 'text', required: true, unique: true, index: true, access: { update: serviceOnly } },
    { name: 'operationId', type: 'text', required: true, index: true, access: { update: serviceOnly } },
    { name: 'expiresAt', type: 'date', required: true, index: true, access: { update: serviceOnly } },
  ],
})

export const createContactsCollection = (): CollectionConfig => ({
  slug: 'contacts',
  admin: { useAsTitle: 'name', defaultColumns: ['name', 'email', 'source', 'updatedAt'], hidden: true },
  access: {
    read: ownerCanRead,
    create: serviceOnly,
    update: ownerCanWrite,
    delete: serviceOnly,
  },
  fields: [
    { name: 'emailKey', type: 'text', required: true, unique: true, index: true, admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'email', type: 'email', required: true, access: { update: serviceOnly } },
    { name: 'name', type: 'text', access: { update: ownerCanWrite } },
    { name: 'phone', type: 'text', access: { update: ownerCanWrite } },
    { name: 'company', type: 'text', access: { update: ownerCanWrite } },
    { name: 'notes', type: 'textarea', access: { update: ownerCanWrite } },
    { name: 'source', type: 'select', required: true, options: ['form', 'email', 'owner', 'booking'], access: { update: serviceOnly } },
    { name: 'lastSeenAt', type: 'date', access: { update: serviceOnly } },
  ],
})

export const createConversationsCollection = (): CollectionConfig => ({
  slug: 'conversations',
  admin: { useAsTitle: 'subject', defaultColumns: ['subject', 'participantEmail', 'state', 'lastActivityAt'], hidden: true },
  access: {
    read: ownerCanRead,
    create: serviceOnly,
    update: ownerCanWrite,
    delete: serviceOnly,
  },
  fields: [
    { name: 'subject', type: 'text', required: true, access: { update: serviceOnly } },
    { name: 'contact', type: 'relationship', relationTo: 'contacts', required: true, access: { update: serviceOnly } },
    { name: 'participantEmail', type: 'email', required: true, access: { update: serviceOnly } },
    { name: 'mailboxKey', type: 'text', required: true, index: true, admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'threadKey', type: 'text', required: true, unique: true, index: true, admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'state', type: 'select', required: true, defaultValue: 'needs_reply', options: ['needs_reply', 'done', 'archived', 'spam', 'trash'], access: { update: ownerCanWrite } },
    { name: 'unread', type: 'checkbox', defaultValue: true, access: { update: ownerCanWrite } },
    { name: 'source', type: 'select', required: true, options: ['form', 'email', 'owner', 'booking'], access: { update: serviceOnly } },
    { name: 'sourcePage', type: 'text', access: { update: serviceOnly } },
    { name: 'lastActivityAt', type: 'date', required: true, access: { update: serviceOnly } },
    { name: 'lastMessagePreview', type: 'textarea', maxLength: 500, access: { update: serviceOnly } },
  ],
})

export const createMessagesCollection = (): CollectionConfig => ({
  slug: 'messages',
  admin: { useAsTitle: 'subject', defaultColumns: ['subject', 'direction', 'deliveryState', 'createdAt'], hidden: true },
  access: serviceOwnedAccess,
  fields: [
    { name: 'conversation', type: 'relationship', relationTo: 'conversations', required: true, index: true, access: { update: serviceOnly } },
    { name: 'direction', type: 'select', required: true, options: ['form_enquiry', 'received_email', 'reply', 'owner_message', 'booking_notice'], access: { update: serviceOnly } },
    { name: 'from', type: 'email', access: { update: serviceOnly } },
    { name: 'to', type: 'email', access: { update: serviceOnly } },
    { name: 'ccRecipients', type: 'json', access: { update: serviceOnly } },
    { name: 'bccRecipients', type: 'json', access: { update: serviceOnly } },
    { name: 'subject', type: 'text', required: true, access: { update: serviceOnly } },
    { name: 'text', type: 'textarea', required: true, access: { update: serviceOnly } },
    { name: 'draftText', type: 'textarea', access: { update: serviceOnly } },
    { name: 'draftRevision', type: 'number', defaultValue: 0, access: { update: serviceOnly } },
    { name: 'deliveryState', type: 'select', required: true, defaultValue: 'received', options: ['draft', 'queued', 'sending', 'accepted', 'failed', 'uncertain', 'received'], access: { update: serviceOnly } },
    { name: 'form', type: 'relationship', relationTo: 'contactForms', access: { update: serviceOnly } },
    { name: 'formSnapshot', type: 'json', access: { update: serviceOnly } },
    { name: 'receiptId', type: 'text', unique: true, index: true, admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'externalMessageId', type: 'text', index: true, admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'inReplyTo', type: 'text', index: true, admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'references', type: 'json', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'rawObjectKey', type: 'text', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'attachmentManifest', type: 'json', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'approvalHash', type: 'text', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'approvedBy', type: 'text', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'approvedAt', type: 'date', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'operationId', type: 'text', unique: true, index: true, admin: { hidden: true }, access: { update: serviceOnly } },
  ],
})

export const createMessageOperationsCollection = (): CollectionConfig => ({
  slug: 'messageOperations',
  admin: { useAsTitle: 'operationId', defaultColumns: ['operationType', 'state', 'attempts', 'updatedAt'], hidden: true },
  access: serviceOwnedAccess,
  fields: [
    { name: 'operationId', type: 'text', required: true, unique: true, index: true, access: { update: serviceOnly } },
    { name: 'operationType', type: 'select', required: true, options: ['form_accept', 'inbound_email', 'owner_notification', 'save_draft', 'send_reply', 'send_message', 'book_appointment', 'booking_notification'], access: { update: serviceOnly } },
    { name: 'idempotencyKey', type: 'text', required: true, unique: true, index: true, access: { update: serviceOnly } },
    { name: 'requestHash', type: 'text', required: true, defaultValue: '', index: true, access: { update: serviceOnly } },
    { name: 'state', type: 'select', required: true, defaultValue: 'accepted', options: ['accepted', 'queued', 'processing', 'completed', 'failed', 'uncertain'], access: { update: serviceOnly } },
    { name: 'attempts', type: 'number', defaultValue: 0, access: { update: serviceOnly } },
    { name: 'nextAttemptAt', type: 'date', access: { update: serviceOnly } },
    { name: 'leaseUntil', type: 'date', access: { update: serviceOnly } },
    { name: 'payload', type: 'json', access: { update: serviceOnly } },
    { name: 'privateObjectKey', type: 'text', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'providerReference', type: 'text', access: { update: serviceOnly } },
    { name: 'errorCode', type: 'text', access: { update: serviceOnly } },
  ],
})

export const createMessageMailboxGlobal = (): GlobalConfig => ({
  slug: 'messageMailbox',
  admin: { hidden: true },
  access: { read: ownerCanRead, update: serviceOnly },
  fields: [
    { name: 'domain', type: 'text', access: { update: serviceOnly } },
    { name: 'address', type: 'email', access: { update: serviceOnly } },
    { name: 'outboundProvider', type: 'select', defaultValue: 'resend', options: ['resend'], access: { update: serviceOnly } },
    { name: 'outboundMode', type: 'select', defaultValue: 'transactional_only', options: ['transactional_only', 'business_correspondence'], access: { update: serviceOnly } },
    { name: 'state', type: 'select', required: true, defaultValue: 'domain_required', options: ['domain_required', 'provisioning', 'action_required', 'active', 'failed'], access: { update: serviceOnly } },
    { name: 'statusDetail', type: 'textarea', access: { update: serviceOnly } },
    { name: 'activatedAt', type: 'date', access: { update: serviceOnly } },
    { name: 'notificationAddress', type: 'email', label: 'Verified notification email', access: { update: serviceOnly } },
    { name: 'notificationVerifiedAt', type: 'date', access: { update: serviceOnly } },
    { name: 'notificationPendingAddress', type: 'email', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'notificationCodeHash', type: 'text', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'notificationCodeExpiresAt', type: 'date', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'notificationCodeSentAt', type: 'date', admin: { hidden: true }, access: { update: serviceOnly } },
    { name: 'notificationCodeAttempts', type: 'number', defaultValue: 0, admin: { hidden: true }, access: { update: serviceOnly } },
  ],
})

export const createCalendarSettingsGlobal = (): GlobalConfig => ({
  slug: 'calendarSettings',
  admin: { hidden: true },
  access: { read: ownerCanRead, update: ownerCanWrite },
  fields: [
    { name: 'enabled', type: 'checkbox', defaultValue: false, label: 'Offer online bookings' },
    { name: 'timeZone', type: 'text', required: true, label: 'Business time zone' },
    { name: 'minimumNoticeHours', type: 'number', min: 0, max: 8760, defaultValue: 24, label: 'Minimum booking notice (hours)' },
    { name: 'bookingWindowDays', type: 'number', min: 1, max: 365, defaultValue: 60, label: 'How far ahead visitors can book (days)' },
  ],
})

export const createPagesCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'pages',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title', defaultColumns: ['title', 'slug', '_status', 'updatedAt'] },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar', readOnly: true }, access: { update: serviceOnly } },
    { name: 'title', type: 'text', required: true, localized: true, label: 'Page title' },
    { name: 'slug', type: 'text', required: true, unique: true, label: 'Page address' },
    { name: 'summary', type: 'textarea', localized: true, label: 'Short introduction' },
    {
      name: 'sections', type: 'array', maxRows: 30, label: 'Page content',
      admin: { description: 'Add typed content and give each item a useful name. Layout remains part of the website design.' },
      fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable section ID' },
        { name: 'label', type: 'text', required: true, localized: true, label: 'Section name' },
        { name: 'entries', type: 'blocks', maxRows: 40, blocks: sectionBlocks, label: 'Content in this section' },
      ],
    },
    { name: 'body', type: 'richText', localized: true, label: 'Main text' },
    { name: 'featuredImage', type: 'upload', relationTo: 'media', localized: true, label: 'Main image' },
    { name: 'canonicalUrl', type: 'text', label: 'Canonical URL override' },
    seoFields(),
    { name: 'published', type: 'checkbox', defaultValue: true, label: 'Visible on the website' },
  ],
  hooks: sectionCollectionHooks('pages', guard),
})

export const createPostsCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'posts',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title', defaultColumns: ['title', 'publishedAt', '_status', 'updatedAt'] },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar', readOnly: true }, access: { update: serviceOnly } },
    { name: 'title', type: 'text', required: true, localized: true, label: 'Article title' },
    { name: 'slug', type: 'text', required: true, unique: true, label: 'Article address' },
    { name: 'summary', type: 'textarea', localized: true, label: 'Article excerpt' },
    {
      name: 'sections', type: 'array', maxRows: 30, label: 'Article sections',
      fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable section ID' },
        { name: 'label', type: 'text', required: true, localized: true, label: 'Section name' },
        { name: 'entries', type: 'blocks', maxRows: 40, blocks: sectionBlocks, label: 'Section content' },
      ],
    },
    { name: 'body', type: 'richText', localized: true, label: 'Article content' },
    { name: 'featuredImage', type: 'upload', relationTo: 'media', localized: true, label: 'Article cover image' },
    { name: 'gallery', type: 'upload', hasMany: true, relationTo: 'media', label: 'Article images' },
    { name: 'author', type: 'text', localized: true, label: 'Author' },
    { name: 'publishedAt', type: 'date', label: 'Publication date' },
    { name: 'modifiedAt', type: 'date', label: 'Last update' },
    { name: 'category', type: 'relationship', relationTo: 'postCategories', label: 'Journal category' },
    { name: 'canonicalUrl', type: 'text', label: 'Canonical URL override' },
    seoFields(),
    { name: 'published', type: 'checkbox', defaultValue: true, label: 'Visible on the website' },
  ],
  hooks: sectionCollectionHooks('posts', guard),
})

export const createPostCategoriesCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'postCategories',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title' },
  fields: [
    { name: 'sourceId', type: 'text', index: true, unique: true, admin: { position: 'sidebar', readOnly: true }, access: { update: serviceOnly } },
    { name: 'title', type: 'text', required: true, localized: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'sourceUrl', type: 'text' },
    { name: 'canonicalUrl', type: 'text' },
    { name: 'summary', type: 'textarea', localized: true },
    {
      name: 'sections', type: 'array', maxRows: 30, label: 'Category content',
      fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable section ID' },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'entries', type: 'blocks', maxRows: 40, blocks: sectionBlocks },
      ],
    },
    { name: 'featuredImage', type: 'upload', relationTo: 'media' },
    seoFields(),
    { name: 'published', type: 'checkbox', defaultValue: true },
  ],
  hooks: sectionCollectionHooks('postCategories', guard),
})

export const createProductsCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'products',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title' },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar', readOnly: true }, access: { update: serviceOnly } },
    { name: 'title', type: 'text', required: true, localized: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'summary', type: 'textarea', localized: true },
    {
      name: 'sections', type: 'array', maxRows: 30, label: 'Product content',
      fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable section ID' },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'entries', type: 'blocks', maxRows: 40, blocks: sectionBlocks },
      ],
    },
    { name: 'body', type: 'richText', localized: true },
    { name: 'featuredImage', type: 'upload', relationTo: 'media', localized: true },
    { name: 'price', type: 'number' },
    { name: 'currency', type: 'text' },
    { name: 'availability', type: 'text', localized: true },
    { name: 'gallery', type: 'upload', relationTo: 'media', hasMany: true, localized: true },
    { name: 'category', type: 'relationship', relationTo: 'productCategories' },
    { name: 'canonicalUrl', type: 'text' },
    seoFields(),
    { name: 'published', type: 'checkbox', defaultValue: false },
  ],
  hooks: sectionCollectionHooks('products', guard),
})

export const createProductCategoriesCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'productCategories',
  admin: { useAsTitle: 'title' },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar', readOnly: true }, access: { update: serviceOnly } },
    { name: 'sourceUrl', type: 'text' },
    { name: 'title', type: 'text', required: true, localized: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'description', type: 'textarea', localized: true },
    { name: 'featuredImage', type: 'upload', relationTo: 'media' },
    {
      name: 'sections', type: 'array', maxRows: 30, label: 'Category content',
      fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable section ID' },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'entries', type: 'blocks', maxRows: 40, blocks: sectionBlocks },
      ],
    },
    { name: 'canonicalUrl', type: 'text' },
    seoFields(),
    { name: 'published', type: 'checkbox', defaultValue: true },
  ],
  hooks: sectionCollectionHooks('productCategories', guard),
})

export const Users: CollectionConfig = {
  slug: 'users',
  // HelloAda is the identity provider. Payload sessions are created only by
  // its signed, one-use handoff; tenant owners do not get a second password.
  auth: {
    // Password login stays disabled; HelloAda-issued Payload sessions still need the built-in JWT verifier.
    disableLocalStrategy: { enableFields: true },
    useSessions: true,
    strategies: [{ name: 'helloada-payload-session', authenticate: JWTAuthentication }],
  },
  access: { create: () => false, read: () => false, update: () => false, delete: () => false },
  admin: { useAsTitle: 'email', hidden: true },
  fields: [
    {
      name: 'helloadaSubject',
      type: 'text',
      // Existing Payload owners predate HelloAda's external subject. The
      // first signed handoff creates this link; older user rows stay valid.
      required: false,
      unique: true,
      index: true,
      admin: { hidden: true },
      access: { read: serviceOnly, update: serviceOnly },
    },
  ],
}

/** Durable one-use claims prevent a valid HelloAda session grant from being replayed. */
export const OwnerHandoffGrants: CollectionConfig = {
  slug: 'owner-handoff-grants',
  admin: { hidden: true, useAsTitle: 'grantId' },
  access: { create: () => false, read: () => false, update: () => false, delete: () => false },
  fields: [
    { name: 'grantId', type: 'text', required: true, unique: true, index: true, access: { update: serviceOnly } },
    { name: 'tenantId', type: 'text', required: true, access: { update: serviceOnly } },
    { name: 'ownerSubjectHash', type: 'text', required: true, access: { update: serviceOnly } },
    { name: 'consumedAt', type: 'date', required: true, access: { update: serviceOnly } },
  ],
}

export const Media: CollectionConfig = {
  slug: 'media',
  access: {
    read: () => true,
    create: ({ req }) => Boolean(req.user),
    update: ({ req }) => Boolean(req.user),
    delete: ({ req }) => Boolean(req.user),
  },
  upload: true,
  fields: [
    { name: 'alt', type: 'text', localized: true, label: 'Alternative text' },
    { name: 'sourceId', type: 'text', required: true, index: true, unique: true, admin: { position: 'sidebar', readOnly: true }, access: { update: serviceOnly } },
    { name: 'sourceUrl', type: 'text' },
    { name: 'originalUrl', type: 'text' },
    { name: 'description', type: 'textarea', localized: true, label: 'Description' },
    { name: 'tags', type: 'array', fields: [{ name: 'value', type: 'text', required: true }] },
    { name: 'dominantColors', type: 'array', fields: [{ name: 'value', type: 'text', required: true }] },
    { name: 'suggestedUses', type: 'array', fields: [{ name: 'value', type: 'text', required: true }] },
    { name: 'qualityNotes', type: 'array', fields: [{ name: 'value', type: 'text', required: true }] },
    { name: 'ocrText', type: 'textarea' },
    { name: 'proposedKnowledge', type: 'textarea' },
    { name: 'sourceKind', type: 'text' },
    { name: 'analysisStatus', type: 'select', defaultValue: 'pending', options: ['pending', 'processing', 'ready', 'failed', 'skipped'] },
    { name: 'analysisProvider', type: 'text' },
    { name: 'analysisModel', type: 'text' },
    { name: 'analysisVersion', type: 'number', defaultValue: 1 },
    { name: 'analysisError', type: 'textarea' },
    { name: 'analysisUpdatedAt', type: 'date' },
    { name: 'analysis', type: 'json' },
  ],
  hooks: {
    beforeValidate: [async ({ data }) => {
      const sourceId = String(data?.sourceId || '').trim()
      return sourceId ? data : { ...data, sourceId: `media:${globalThis.crypto.randomUUID()}` }
    }],
  },
}

export const createNavigationGlobal = (guard: NativeWriteGuard): GlobalConfig => ({
  slug: 'navigation',
  versions: { drafts: true },
  fields: [
    { name: 'items', type: 'array', label: 'Main menu', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable menu item ID' },
      { name: 'label', type: 'text', required: true, localized: true, label: 'Menu text' },
      { name: 'href', type: 'text', required: true, localized: true, validate: validateHelloAdaLink, label: 'Page or URL' },
      { name: 'external', type: 'checkbox', defaultValue: false },
      { name: 'visible', type: 'checkbox', defaultValue: true },
    ] },
    { name: 'footer', type: 'array', label: 'Footer menu', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable menu item ID' },
      { name: 'label', type: 'text', required: true, localized: true, label: 'Menu text' },
      { name: 'href', type: 'text', required: true, localized: true, validate: validateHelloAdaLink, label: 'Page or URL' },
      { name: 'external', type: 'checkbox', defaultValue: false },
      { name: 'visible', type: 'checkbox', defaultValue: true },
    ] },
    { name: 'groups', type: 'array', label: 'Additional menu groups', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
      { name: 'label', type: 'text', required: true, localized: true },
      { name: 'items', type: 'array', fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'href', type: 'text', required: true, localized: true, validate: validateHelloAdaLink },
        { name: 'external', type: 'checkbox', defaultValue: false },
      ] },
    ] },
    { name: 'footerGroups', type: 'array', label: 'Additional footer groups', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
      { name: 'label', type: 'text', required: true, localized: true },
      { name: 'items', type: 'array', fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'href', type: 'text', required: true, localized: true, validate: validateHelloAdaLink },
        { name: 'external', type: 'checkbox', defaultValue: false },
      ] },
    ] },
  ],
  hooks: {
    beforeValidate: [async ({ data }) => {
      const navigation = assignHelloAdaNavigationKeys(data)
      const result = validateHelloAdaNavigation(navigation)
      if (result !== true) throw new Error(result)
      return navigation
    }],
    beforeOperation: [async ({ args, operation }) => {
      if (operation === 'update') await guard('global:navigation', 'navigation', args.req, operation, args.data)
    }],
    afterChange: [async ({ req }) => {
      await guard('global:navigation', 'navigation', req, 'complete')
    }],
  },
})

export const createSiteSettingsGlobal = (guard: NativeWriteGuard): GlobalConfig => ({
  slug: 'siteSettings',
  versions: { drafts: true },
  fields: [
    { name: 'siteName', type: 'text', required: true, localized: true, label: 'Business or website name' },
    { name: 'description', type: 'textarea', localized: true, label: 'Website description' },
    { name: 'tagline', type: 'text', localized: true, label: 'Short tagline' },
    { name: 'logo', type: 'upload', relationTo: 'media' },
    { name: 'email', type: 'email', label: 'Contact email' },
    { name: 'telephone', type: 'text', label: 'Contact telephone' },
    { name: 'contactLabel', type: 'text', localized: true, label: 'Contact call-to-action label' },
    { name: 'facebookUrl', type: 'text' },
    { name: 'instagramUrl', type: 'text' },
    { name: 'tiktokUrl', type: 'text' },
    { name: 'promoText', type: 'text', localized: true },
    { name: 'promoHref', type: 'text', localized: true, validate: (value: unknown) => value == null || value === '' ? true : validateHelloAdaLink(value) },
    { name: 'promoCta', type: 'text', localized: true },
    { name: 'footerKicker', type: 'text', localized: true },
    { name: 'footerTitle', type: 'textarea', localized: true },
    { name: 'footerNote', type: 'text', localized: true },
    { name: 'defaultSeoTitle', type: 'text', localized: true, label: 'Default search title' },
    { name: 'defaultSeoDescription', type: 'textarea', localized: true, label: 'Default search description' },
    { name: 'defaultSocialImage', type: 'upload', relationTo: 'media', label: 'Default social preview image' },
    { name: 'journalTitle', type: 'text', localized: true, label: 'Journal title' },
    { name: 'journalDescription', type: 'textarea', localized: true, label: 'Journal introduction' },
    { name: 'address', type: 'group', fields: [
      { name: 'streetAddress', type: 'text', localized: true },
      { name: 'postalCode', type: 'text' },
      { name: 'addressLocality', type: 'text', localized: true },
      { name: 'addressRegion', type: 'text', localized: true },
      { name: 'addressCountry', type: 'text', localized: true },
    ] },
  ],
  hooks: {
    beforeOperation: [async ({ args, operation }) => {
      if (operation === 'update') await guard('global:siteSettings', 'siteSettings', args.req, operation, args.data)
    }],
    afterChange: [async ({ req }) => {
      await guard('global:siteSettings', 'siteSettings', req, 'complete')
    }],
  },
})

const authoringFieldListShape = (fields: AuthoringField[]) => fields
  .filter((field) => asRow(field.admin).hidden !== true)
  .map(authoringFieldShape)

export const createHelloAdaSchema = (guard: NativeWriteGuard) => ({
  collections: [
    Users,
    OwnerHandoffGrants,
    createPagesCollection(guard),
    createPostsCollection(guard),
    createPostCategoriesCollection(guard),
    createProductsCollection(guard),
    createProductCategoriesCollection(guard),
    Media,
    createContactFormsCollection(),
    createAppointmentTypesCollection(),
    createCalendarEventsCollection(),
    createCalendarSlotLocksCollection(),
    createContactsCollection(),
    createConversationsCollection(),
    createMessagesCollection(),
    createMessageOperationsCollection(),
  ],
  globals: [createSiteSettingsGlobal(guard), createNavigationGlobal(guard), createMessageMailboxGlobal(), createCalendarSettingsGlobal()],
})

/**
 * Return Ada's design-facing contract from the same Payload configs installed
 * on the destination. This intentionally excludes users, operational data,
 * private messaging, and platform-controlled publication/identity fields.
 */
export const createHelloAdaAuthoringContract = () => {
  const schema = createHelloAdaSchema(async () => undefined)
  const collections = new Map(schema.collections.map((collection) => [collection.slug, collection]))
  const globals = new Map(schema.globals.map((global) => [global.slug, global]))
  const fields = (config: CollectionConfig | GlobalConfig) => config.fields
    .flatMap((field) => 'name' in field && typeof field.name === 'string' ? [field as AuthoringField] : [])
    .filter((field) => !AUTHORING_RESERVED_FIELDS.has(String(field.name || '')) && asRow(field.admin).hidden !== true)
    .map(authoringFieldShape)
  return {
    contract: HELLOADA_CONTENT_CONTRACT_VERSION,
    corePackage: '@weareheadless/helloada-payload-core',
    coreVersion: HELLOADA_CORE_VERSION,
    schemaRevision: HELLOADA_SCHEMA_REVISION,
    collections: Object.fromEntries(HELLOADA_AUTHORING_CAPABILITIES.collections.map((slug) => {
      const config = collections.get(slug)
      if (!config) throw new Error(`Authoring collection ${slug} is missing from the shared schema.`)
      return [slug, fields(config)]
    })),
    globals: Object.fromEntries(HELLOADA_AUTHORING_CAPABILITIES.globals.map((slug) => {
      const config = globals.get(slug)
      if (!config) throw new Error(`Authoring global ${slug} is missing from the shared schema.`)
      return [slug, fields(config)]
    })),
    contentBlocks: HELLOADA_CAPABILITIES.contentBlocks,
    reservedFields: [...AUTHORING_RESERVED_FIELDS].sort(),
  }
}

/** Reject data that is outside the installed canonical Payload field tree. */
export const validateHelloAdaAuthoringData = (
  kind: 'collection' | 'global',
  slug: string,
  value: unknown,
  options: { operation?: 'create' | 'update' } = {},
): true => {
  const schema = createHelloAdaSchema(async () => undefined)
  const config = kind === 'collection'
    ? schema.collections.find((item) => item.slug === slug && (HELLOADA_AUTHORING_CAPABILITIES.collections as readonly string[]).includes(slug))
    : schema.globals.find((item) => item.slug === slug && (HELLOADA_AUTHORING_CAPABILITIES.globals as readonly string[]).includes(slug))
  if (!config) throw new Error(`Unsupported website ${kind}: ${slug}.`)
  const fields = config.fields as AuthoringField[]
  validateAuthoringRecord(value, fields, slug, undefined, false, options.operation === 'create')
  const row = asRow(value)
  if (kind === 'collection' && slug === 'pages' && Object.hasOwn(row, 'sections')) {
    const result = validateHelloAdaPageSections(row.sections)
    if (result !== true) throw new Error(String(result))
  }
  if (kind === 'collection' && slug === 'posts' && Object.hasOwn(row, 'sections')) {
    const result = validateHelloAdaPageSections(row.sections)
    if (result !== true) throw new Error(String(result))
  }
  if (kind === 'collection' && slug === 'products' && Object.hasOwn(row, 'sections')) {
    const result = validateHelloAdaPageSections(row.sections)
    if (result !== true) throw new Error(String(result))
  }
  if (kind === 'global' && slug === 'navigation') {
    const result = validateHelloAdaNavigation({ ...row })
    if (result !== true) throw new Error(String(result))
  }
  return true
}

/** Generate the machine-readable bootstrap contract from the real Payload config. */
export const createHelloAdaContentContract = () => {
  const schema = createHelloAdaSchema(async () => undefined)
  const collectionConfigs = Object.fromEntries(schema.collections.map((collection) => [collection.slug, collection]))
  const globalConfigs = Object.fromEntries(schema.globals.map((global) => [global.slug, global]))
  const fields = (config: CollectionConfig | GlobalConfig) => config.fields.flatMap((field) =>
    'name' in field && typeof field.name === 'string' ? [field.name] : [],
  )

  return {
    contract: HELLOADA_CONTENT_CONTRACT_VERSION,
    corePackage: '@weareheadless/helloada-payload-core',
    coreVersion: HELLOADA_CORE_VERSION,
    schemaRevision: HELLOADA_SCHEMA_REVISION,
    collections: Object.fromEntries(HELLOADA_CAPABILITIES.collections.map((slug) => [slug, fields(collectionConfigs[slug])])),
    globals: Object.fromEntries(HELLOADA_CAPABILITIES.globals.map((slug) => [slug, fields(globalConfigs[slug])])),
    contentBlocks: HELLOADA_CAPABILITIES.contentBlocks,
  }
}
