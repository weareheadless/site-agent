type PayloadDocument = Record<string, unknown>

const payloadMetadata = ['createdAt', 'updatedAt', '_status']

function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize)
  if (!value || typeof value !== 'object') return value

  const row = value as Record<string, unknown>
  if (Object.hasOwn(row, 'id') && (Object.hasOwn(row, 'url') || Object.hasOwn(row, 'filename') || Object.hasOwn(row, 'collection'))) {
    return row.id
  }

  const meaningfulKeys = Object.keys(row).filter((key) => !payloadMetadata.includes(key))
  if (meaningfulKeys.length === 1 && meaningfulKeys[0] === 'id') return row.id
  return Object.fromEntries(Object.entries(row)
    .filter(([key]) => !['id', ...payloadMetadata].includes(key))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, child]) => [key, normalize(child)]))
}

export function fieldMismatchKeys(document: PayloadDocument, input: PayloadDocument): string[] {
  return Object.entries(input)
    .filter(([key, value]) => JSON.stringify(normalize(document[key])) !== JSON.stringify(normalize(value)))
    .map(([key]) => key)
}

export function fieldValueMatches(document: PayloadDocument, input: PayloadDocument): boolean {
  return fieldMismatchKeys(document, input).length === 0
}

export function fieldMismatchDiagnostic(keys: readonly string[]): string {
  return keys.length
    ? `Payload did not persist the exact requested draft fields: ${keys.join(', ')}`
    : 'Payload did not persist the exact requested draft fields'
}
