import type { TypedLocale } from 'payload'

export type HelloAdaPayloadLocale = TypedLocale

/** Validate request locales before passing them to Payload's generated API types. */
export const resolvePayloadLocale = (
  value: unknown,
  enabledLocales: readonly string[],
): HelloAdaPayloadLocale | undefined => {
  if (value === null || value === undefined || value === '') return undefined
  if (typeof value !== 'string') throw new Error('The requested locale must be a string.')

  if (!enabledLocales.includes(value)) throw new Error('The requested locale is not enabled for this website.')
  return value as TypedLocale
}
