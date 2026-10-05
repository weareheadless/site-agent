import type { Block, CollectionConfig, GlobalConfig } from 'payload'

export const HELLOADA_CONTENT_CONTRACT_VERSION = 'helloada-content-v3'
export const HELLOADA_CORE_VERSION = '0.4.0'
export const HELLOADA_SCHEMA_REVISION = 4

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
) => Promise<void>

const protectCollection = (slug: string, guard: NativeWriteGuard): CollectionConfig['hooks'] => ({
  beforeOperation: [async ({ args, operation }) => {
    if (operation === 'update' || operation === 'delete') {
      const operationArgs = args as unknown as { id?: unknown; req?: { context?: Record<string, unknown> } }
      await guard(slug, operationArgs.id, operationArgs.req)
    }
  }],
})

const sectionCollectionHooks = (slug: string, guard: NativeWriteGuard): CollectionConfig['hooks'] => ({
  ...protectCollection(slug, guard),
  beforeValidate: [async ({ data }) => {
    const sections = assignHelloAdaPageKeys(data?.sections)
    const result = validateHelloAdaPageSections(sections)
    if (result !== true) throw new Error(result)
    return sections === undefined ? data : { ...data, sections }
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
]

const contentBlockSlugs = sectionBlocks.map((block) => block.slug)
const supportedContentBlocks = new Set(contentBlockSlugs)

/** Platform-owned capabilities consumed by scaffolding and release validation. */
export const HELLOADA_CAPABILITIES = {
  contract: HELLOADA_CONTENT_CONTRACT_VERSION,
  schemaRevision: HELLOADA_SCHEMA_REVISION,
  collections: ['pages', 'posts', 'postCategories', 'products', 'productCategories', 'media', 'contactForms', 'contacts', 'conversations', 'messages', 'messageOperations'],
  globals: ['siteSettings', 'navigation', 'messageMailbox'],
  contentBlocks: contentBlockSlugs,
} as const

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
    { name: 'source', type: 'select', required: true, options: ['form', 'email', 'owner'], access: { update: serviceOnly } },
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
    { name: 'state', type: 'select', required: true, defaultValue: 'needs_reply', options: ['needs_reply', 'done', 'archived', 'spam'], access: { update: ownerCanWrite } },
    { name: 'unread', type: 'checkbox', defaultValue: true, access: { update: ownerCanWrite } },
    { name: 'source', type: 'select', required: true, options: ['form', 'email'], access: { update: serviceOnly } },
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
    { name: 'direction', type: 'select', required: true, options: ['form_enquiry', 'received_email', 'reply'], access: { update: serviceOnly } },
    { name: 'from', type: 'email', access: { update: serviceOnly } },
    { name: 'to', type: 'email', access: { update: serviceOnly } },
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
    { name: 'operationType', type: 'select', required: true, options: ['form_accept', 'inbound_email', 'owner_notification', 'save_draft', 'send_reply'], access: { update: serviceOnly } },
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

export const createPagesCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'pages',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title', defaultColumns: ['title', 'slug', '_status', 'updatedAt'] },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
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
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
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
    { name: 'sourceId', type: 'text', index: true, unique: true, admin: { position: 'sidebar' } },
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
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
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
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
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
  slug: 'users', auth: true, admin: { useAsTitle: 'email' }, fields: [],
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
    { name: 'sourceId', type: 'text', required: true, index: true, unique: true, admin: { position: 'sidebar' } },
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
      if (operation === 'update') await guard('global:navigation', 'navigation', args.req)
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
      if (operation === 'update') await guard('global:siteSettings', 'siteSettings', args.req)
    }],
  },
})

export const createHelloAdaSchema = (guard: NativeWriteGuard) => ({
  collections: [
    Users,
    createPagesCollection(guard),
    createPostsCollection(guard),
    createPostCategoriesCollection(guard),
    createProductsCollection(guard),
    createProductCategoriesCollection(guard),
    Media,
    createContactFormsCollection(),
    createContactsCollection(),
    createConversationsCollection(),
    createMessagesCollection(),
    createMessageOperationsCollection(),
  ],
  globals: [createSiteSettingsGlobal(guard), createNavigationGlobal(guard), createMessageMailboxGlobal()],
})

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
