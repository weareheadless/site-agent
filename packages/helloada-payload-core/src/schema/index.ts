import type { Block, CollectionConfig, GlobalConfig } from 'payload'

export const HELLOADA_CONTENT_CONTRACT_VERSION = 'helloada-content-v1'

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

const supportedContentBlocks = new Set([
  'helloAdaHeading', 'helloAdaParagraph', 'helloAdaRichText',
  'helloAdaImage', 'helloAdaLink', 'helloAdaContentList',
])

const stableKey = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0 && value.trim().length <= 120

const newStableKey = () => `ha-${globalThis.crypto.randomUUID()}`

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
      { name: 'href', type: 'text' as const, required: true, validate: validateHelloAdaLink, label: 'Page or URL' },
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
          { name: 'href', type: 'text' as const, validate: (value: unknown) => value == null || value === '' ? true : validateHelloAdaLink(value), label: 'Page or URL' },
        ],
      },
    ],
  },
]

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
  hooks: {
    ...protectCollection('pages', guard),
    beforeValidate: [async ({ data }) => {
      const sections = assignHelloAdaPageKeys(data?.sections)
      const result = validateHelloAdaPageSections(sections)
      if (result !== true) throw new Error(result)
      return sections === undefined ? data : { ...data, sections }
    }],
  },
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
    { name: 'body', type: 'richText', localized: true, label: 'Article content' },
    { name: 'featuredImage', type: 'upload', relationTo: 'media', localized: true, label: 'Article cover image' },
    { name: 'gallery', type: 'upload', hasMany: true, relationTo: 'media', label: 'Article images' },
    { name: 'author', type: 'text', localized: true, label: 'Author' },
    { name: 'publishedAt', type: 'date', label: 'Publication date' },
    { name: 'modifiedAt', type: 'date', label: 'Last update' },
    { name: 'category', type: 'text', localized: true, label: 'Category' },
    { name: 'canonicalUrl', type: 'text', label: 'Canonical URL override' },
    seoFields(),
    { name: 'published', type: 'checkbox', defaultValue: true, label: 'Visible on the website' },
  ],
  hooks: protectCollection('posts', guard),
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
    { name: 'body', type: 'richText', localized: true },
    { name: 'featuredImage', type: 'upload', relationTo: 'media', localized: true },
    { name: 'price', type: 'number' },
    { name: 'category', type: 'relationship', relationTo: 'productCategories' },
    { name: 'published', type: 'checkbox', defaultValue: false },
  ],
  hooks: protectCollection('products', guard),
})

export const createProductCategoriesCollection = (guard: NativeWriteGuard): CollectionConfig => ({
  slug: 'productCategories',
  admin: { useAsTitle: 'title' },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
    { name: 'title', type: 'text', required: true, localized: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'description', type: 'textarea', localized: true },
    { name: 'featuredImage', type: 'upload', relationTo: 'media' },
    { name: 'published', type: 'checkbox', defaultValue: true },
  ],
  hooks: protectCollection('productCategories', guard),
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
    { name: 'description', type: 'textarea', localized: true, label: 'Description' },
    { name: 'tags', type: 'array', fields: [{ name: 'value', type: 'text', required: true }] },
  ],
}

export const createNavigationGlobal = (guard: NativeWriteGuard): GlobalConfig => ({
  slug: 'navigation',
  versions: { drafts: true },
  fields: [
    { name: 'items', type: 'array', label: 'Main menu', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable menu item ID' },
      { name: 'label', type: 'text', required: true, localized: true, label: 'Menu text' },
      { name: 'href', type: 'text', required: true, validate: validateHelloAdaLink, label: 'Page or URL' },
      { name: 'external', type: 'checkbox', defaultValue: false },
      { name: 'visible', type: 'checkbox', defaultValue: true },
    ] },
    { name: 'footer', type: 'array', label: 'Footer menu', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true }, label: 'Stable menu item ID' },
      { name: 'label', type: 'text', required: true, localized: true, label: 'Menu text' },
      { name: 'href', type: 'text', required: true, validate: validateHelloAdaLink, label: 'Page or URL' },
      { name: 'external', type: 'checkbox', defaultValue: false },
      { name: 'visible', type: 'checkbox', defaultValue: true },
    ] },
    { name: 'groups', type: 'array', label: 'Additional menu groups', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
      { name: 'label', type: 'text', required: true, localized: true },
      { name: 'items', type: 'array', fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'href', type: 'text', required: true, validate: validateHelloAdaLink },
        { name: 'external', type: 'checkbox', defaultValue: false },
      ] },
    ] },
    { name: 'footerGroups', type: 'array', label: 'Additional footer groups', fields: [
      { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
      { name: 'label', type: 'text', required: true, localized: true },
      { name: 'items', type: 'array', fields: [
        { name: 'key', type: 'text', required: true, admin: { readOnly: true } },
        { name: 'label', type: 'text', required: true, localized: true },
        { name: 'href', type: 'text', required: true, validate: validateHelloAdaLink },
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
    { name: 'facebookUrl', type: 'text' },
    { name: 'instagramUrl', type: 'text' },
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
  collections: [Users, createPagesCollection(guard), createPostsCollection(guard), createProductsCollection(guard), createProductCategoriesCollection(guard), Media],
  globals: [createSiteSettingsGlobal(guard), createNavigationGlobal(guard)],
})
