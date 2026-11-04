type PayloadDocument = Record<string, unknown>

const payloadMetadata = ['createdAt', 'updatedAt', '_status']

function normalize(value: unknown, requested?: unknown): unknown {
  if (Array.isArray(value)) return value.map((child, index) =>
    normalize(child, Array.isArray(requested) ? requested[index] : undefined))
  if (!value || typeof value !== 'object') return value

  const row = value as Record<string, unknown>
  // Collection relationships may be populated without any media/collection
  // marker. Only project them to an ID when the request expects an identity;
  // groups and array rows must still have their requested fields compared.
  if (Object.hasOwn(row, 'id') && (typeof requested === 'string' || typeof requested === 'number')) {
    return row.id
  }
  if (Object.hasOwn(row, 'id') && (Object.hasOwn(row, 'url') || Object.hasOwn(row, 'filename') || Object.hasOwn(row, 'collection'))) {
    return row.id
  }

  const meaningfulKeys = Object.keys(row).filter((key) => !payloadMetadata.includes(key))
  if (meaningfulKeys.length === 1 && meaningfulKeys[0] === 'id') return row.id
  return Object.fromEntries(Object.entries(row)
    .filter(([key]) => !['id', ...payloadMetadata].includes(key))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, child]) => [key, normalize(child,
      requested && typeof requested === 'object' ? (requested as PayloadDocument)[key] : undefined)]))
}

function requestedValueMatches(actual: unknown, requested: unknown): boolean {
  if (Array.isArray(requested)) {
    return Array.isArray(actual) && actual.length === requested.length
      && requested.every((value, index) => requestedValueMatches(actual[index], value))
  }
  if (requested && typeof requested === 'object') {
    return Boolean(actual && typeof actual === 'object' && !Array.isArray(actual))
      && Object.entries(requested).every(([key, value]) =>
        requestedValueMatches((actual as PayloadDocument)[key], value))
  }
  return Object.is(actual, requested)
}

export function fieldMismatchKeys(document: PayloadDocument, input: PayloadDocument): string[] {
  return Object.entries(input)
    .filter(([key, value]) => {
      const requested = normalize(value)
      return !requestedValueMatches(normalize(document[key], requested), requested)
    })
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
