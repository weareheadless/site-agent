type PayloadObject = Record<string, unknown>

const normalizeJson = (value: unknown): unknown => {
  if (value === undefined) return null
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(normalizeJson)
  const object = value as PayloadObject
  return Object.fromEntries(Object.keys(object).sort().map((key) => [key, normalizeJson(object[key])]))
}

export const stableJson = (value: unknown) => JSON.stringify(normalizeJson(value))

export const hashJson = async (value: unknown) => {
  const encoded = new TextEncoder().encode(stableJson(value))
  const digest = await crypto.subtle.digest('SHA-256', encoded)
  return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

export const withoutPayloadMetadata = (value: PayloadObject) => {
  const result = { ...value }
  for (const key of ['id', 'createdAt', 'updatedAt', '_status']) delete result[key]
  return result
}
