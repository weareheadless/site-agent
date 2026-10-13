const OWNER_MANAGED_COLLECTIONS = new Set([
  'pages', 'posts', 'postCategories', 'products', 'productCategories', 'media', 'contactForms',
])
const OWNER_MANAGED_GLOBALS = new Set(['siteSettings', 'navigation'])

type SluggedItem = { slug: string }

/** The client Payload config omits some admin metadata; expose only deliberate owner surfaces. */
export const selectOwnerCollections = <T extends SluggedItem>(items: T[]): T[] =>
  items.filter((item) => OWNER_MANAGED_COLLECTIONS.has(item.slug))

/** Service-owned globals are never linked from the owner settings drawer. */
export const selectOwnerGlobals = <T extends SluggedItem>(items: T[], configured: readonly string[]): T[] =>
  items.filter((item) => OWNER_MANAGED_GLOBALS.has(item.slug) && configured.includes(item.slug))
