export type PortableMediaLike = {
  id?: string | number | null
  sourceId?: string | null
  url?: string | null
  sourceUrl?: string | null
  originalUrl?: string | null
}

/** Resolve a portable media reference without coupling the admin to a customer migration model. */
export const mediaReferenceId = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  if (!value || typeof value !== 'object') return ''
  const candidate = value as PortableMediaLike
  return String(candidate.sourceId || candidate.id || '').trim()
}

export const mediaUrl = (value: PortableMediaLike | null | undefined): string => {
  if (!value) return ''
  return String(value.url || value.sourceUrl || value.originalUrl || '').trim()
}
