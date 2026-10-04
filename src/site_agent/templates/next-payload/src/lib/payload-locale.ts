import type { Config } from '@/payload-types'

export type HelloAdaPayloadLocale = Config['locale'] | 'all'

/** Validate request locales before passing them to Payload's generated API types. */
export const resolvePayloadLocale = (
  value: unknown,
  enabledLocales: readonly string[],
): HelloAdaPayloadLocale | undefined => {
  if (value === null || value === undefined || value === '') return undefined
  if (typeof value !== 'string') throw new Error('The requested locale must be a string.')

  if (value === 'all') {
    if (enabledLocales.length === 0) throw new Error('Locale selection is unavailable for this website.')
    return 'all'
  }
  if (!enabledLocales.includes(value)) throw new Error('The requested locale is not enabled for this website.')
  return value as Config['locale']
}
