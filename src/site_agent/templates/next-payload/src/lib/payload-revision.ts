import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'

/**
 * A reviewed revision is identified by a hash of the document as it is read
 * without relation population. Depth 0 is part of the contract: populated
 * relations depend on the caller's depth and locale fallbacks, so including
 * them would make the same revision hash differently for different readers.
 */
export const REVISION_DEPTH = 0

type Document = Record<string, unknown>
type WriteRequest = { context?: Record<string, unknown>; locale?: unknown; payload?: any }

export type ExpectedRevision =
  | { kind: 'collection'; collection: string; id: string; hash: string; locale?: string }
  | { kind: 'global'; global: string; hash: string; locale?: string }

const conflict = (message: string) =>
  Object.assign(new Error(message), { status: 409, statusCode: 409 })

export const revisionHash = (document: Document) => hashJson(withoutPayloadMetadata(document))

export const isRevisionHash = (value: unknown) =>
  typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)

/**
 * Read the revision marker from a Payload request context.
 *
 * A malformed marker is an error, never "no expectation": silently dropping it
 * would turn an atomic compare-and-swap into an unconditional overwrite.
 */
export const expectedRevisionOf = (req: WriteRequest | undefined): ExpectedRevision | undefined => {
  const raw = req?.context?.helloAdaExpectedRevision
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw conflict('The reviewed revision marker is malformed. Reload the document before saving.')
  }
  const row = raw as Record<string, unknown>
  const hash = row.hash
  if (!isRevisionHash(hash)) {
    throw conflict('The reviewed revision hash is malformed. Reload the document before saving.')
  }
  const locale = typeof row.locale === 'string' && row.locale ? row.locale : undefined
  if (row.kind === 'collection') {
    const collection = String(row.collection || '')
    const id = String(row.id ?? '')
    if (!collection || !id) throw conflict('The reviewed revision is missing its document identity.')
    return { kind: 'collection', collection, id, hash: hash as string, locale }
  }
  if (row.kind === 'global') {
    const global = String(row.global || '')
    if (!global) throw conflict('The reviewed revision is missing its global identity.')
    return { kind: 'global', global, hash: hash as string, locale }
  }
  throw conflict('The reviewed revision marker has an unknown scope. Reload the document before saving.')
}

const assertLocale = (req: WriteRequest, expected: ExpectedRevision) => {
  const writing = typeof req.locale === 'string' ? req.locale : undefined
  if (expected.locale && writing && writing !== expected.locale) {
    throw conflict('This write targets a different locale than the one that was reviewed.')
  }
}

export const readCollectionRevision = async (
  payload: any,
  // `null` is Payload's "all locales" value; a generated TypedLocale narrows it
  // away, but a tenant without generated types still passes it through.
  options: { collection: string; id: string; locale?: string | null; draft?: boolean },
): Promise<Document> => payload.findByID({
  collection: options.collection,
  id: options.id,
  draft: options.draft ?? true,
  locale: options.locale,
  depth: REVISION_DEPTH,
  overrideAccess: true,
}) as unknown as Document

export const readGlobalRevision = async (
  payload: any,
  options: { global: string; locale?: string | null; draft?: boolean },
): Promise<Document> => payload.findGlobal({
  slug: options.global,
  draft: options.draft ?? true,
  locale: options.locale,
  depth: REVISION_DEPTH,
  overrideAccess: true,
}) as unknown as Document

/**
 * Compare the revision a caller reviewed with the revision Payload has loaded
 * for this write. The hook runs after the shared write lease is acquired, so
 * this comparison and the following persistence share one serialized writer.
 */
export const collectionRevisionGuard = (slug: string) => async ({
  req, data, operation, originalDoc,
}: { req?: WriteRequest; data?: unknown; operation?: string; originalDoc?: Document }) => {
  const expected = expectedRevisionOf(req)
  if (!expected) return data
  if (expected.kind !== 'collection' || expected.collection !== slug) {
    throw conflict('The reviewed revision belongs to a different document. Reload this one before saving.')
  }
  if (operation === 'create') {
    throw conflict('A new document has no reviewed revision to replace.')
  }
  const id = String(originalDoc?.id ?? '')
  if (!id || id !== expected.id) {
    throw conflict('The reviewed document identity does not match the document being written.')
  }
  assertLocale(req as WriteRequest, expected)
  const current = await readCollectionRevision(req?.payload, {
    collection: slug, id, locale: req?.locale as string | undefined,
  })
  if (await revisionHash(current) !== expected.hash) {
    throw conflict('The document changed after it was read. Reload and review the current revision before saving.')
  }
  return data
}

export const globalRevisionGuard = (slug: string) => async ({
  req, data,
}: { req?: WriteRequest; data?: unknown }) => {
  const expected = expectedRevisionOf(req)
  if (!expected) return data
  if (expected.kind !== 'global' || expected.global !== slug) {
    throw conflict('The reviewed revision belongs to a different global. Reload this one before saving.')
  }
  assertLocale(req as WriteRequest, expected)
  const current = await readGlobalRevision(req?.payload, {
    global: slug, locale: req?.locale as string | undefined,
  })
  if (await revisionHash(current) !== expected.hash) {
    throw conflict('The settings changed after they were read. Reload and review the current revision before saving.')
  }
  return data
}

type HookCollection = {
  slug: string
  hooks?: Record<string, unknown[]>
}

type HookGlobal = {
  slug: string
  hooks?: Record<string, unknown[]>
}

const withHook = <T extends HookCollection | HookGlobal>(
  item: T,
  name: 'beforeChange',
  hook: unknown,
): T => ({
  ...item,
  hooks: {
    ...(item.hooks || {}),
    [name]: [...((item.hooks?.[name] as unknown[]) || []), hook],
  },
})

/** Apply the revision contract to every collection and global of a schema. */
export const withCollectionRevisionGuard = <T extends HookCollection>(collections: T[]): T[] =>
  collections.map((item) => withHook(item, 'beforeChange', collectionRevisionGuard(item.slug)))

export const withGlobalRevisionGuard = <T extends HookGlobal>(globals: T[]): T[] =>
  globals.map((item) => withHook(item, 'beforeChange', globalRevisionGuard(item.slug)))
