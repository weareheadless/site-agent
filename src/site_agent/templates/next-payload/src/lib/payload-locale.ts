import type { Config } from '@/payload-types'

export type HelloAdaPayloadLocale = Config['locale'] | 'all'

/** Validate request locales before passing them to Payload's generated API types. */
export const resolvePayloadLocale = (
  value: string | null,
  enabledLocales: readonly string[],
): HelloAdaPayloadLocale | undefined => {
  if (!value) return undefined
  if (value === 'all') {
    if (enabledLocales.length === 0) throw new Error('Locale selection is unavailable for this website.')
    return 'all'
  }
  if (!enabledLocales.includes(value)) throw new Error('The requested locale is not enabled for this website.')
  return value as Config['locale']
}
