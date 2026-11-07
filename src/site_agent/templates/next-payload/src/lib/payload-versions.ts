import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import type { Payload } from 'payload'

type VersionReader = Pick<Payload, 'findVersions' | 'findGlobalVersions'>

/**
 * The exact Payload version that a write replaced.
 *
 * A version id is the only durable handle on a prior revision: revision hashes
 * are computed from a document read, and a version row can be restored without
 * re-deriving anything. Recording the id before a write makes a later revert
 * exact instead of "the version that looks like the old content".
 */
export const latestCollectionVersionId = async (
  payload: VersionReader,
  collection: string,
  documentId: string,
): Promise<string> => {
  const result = await payload.findVersions({
    collection: collection as never,
    where: { parent: { equals: documentId } },
    sort: '-createdAt',
    limit: 1,
    depth: 0,
    pagination: false,
    overrideAccess: true,
  })
  return String(result?.docs?.[0]?.id || '')
}

export const latestGlobalVersionId = async (
  payload: VersionReader,
  slug: string,
): Promise<string> => {
  const result = await payload.findGlobalVersions({
    slug: slug as never,
    sort: '-createdAt',
    limit: 1,
    depth: 0,
    pagination: false,
    overrideAccess: true,
  })
  return String(result?.docs?.[0]?.id || '')
}

export const versionRevision = async (value: unknown) =>
  hashJson(withoutPayloadMetadata(
    value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {},
  ))
