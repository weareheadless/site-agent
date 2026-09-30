/** Payload's complete accepted language list, kept in one small client-safe module. */
export const PAYLOAD_LANGUAGES = [
  'ar', 'az', 'bg', 'bn-BD', 'bn-IN', 'ca', 'cs', 'da', 'de', 'en', 'es', 'et', 'fa', 'fr',
  'he', 'hr', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'ko', 'lt', 'lv', 'my', 'nb', 'nl', 'pl',
  'pt', 'ro', 'rs', 'rs-latin', 'ru', 'sk', 'sl', 'sv', 'ta', 'th', 'tr', 'uk', 'vi', 'zh', 'zh-TW',
] as const

export type PayloadLanguage = (typeof PAYLOAD_LANGUAGES)[number]

export const isPayloadLanguage = (value: string): value is PayloadLanguage =>
  (PAYLOAD_LANGUAGES as readonly string[]).includes(value)

/**
 * The custom HelloAda UI is currently LTR-only. Payload's own translation
 * bundle still contains the excluded languages, but they are not offered by
 * the workspace selector until the custom UI has deliberate RTL support.
 */
export const EXCLUDED_HELLOADA_LANGUAGES = ['ar', 'fa', 'he', 'rs', 'rs-latin'] as const

export const HELLOADA_LANGUAGES = PAYLOAD_LANGUAGES.filter(
  (language) => !(EXCLUDED_HELLOADA_LANGUAGES as readonly string[]).includes(language),
) as unknown as readonly Exclude<PayloadLanguage, (typeof EXCLUDED_HELLOADA_LANGUAGES)[number]>[]

export type HelloAdaLanguage = (typeof HELLOADA_LANGUAGES)[number]

/** English is the product default; French is a customer locale, not the fallback. */
export const DEFAULT_LANGUAGE: HelloAdaLanguage = 'en'

export const isHelloAdaLanguage = (value: string): value is HelloAdaLanguage =>
  (HELLOADA_LANGUAGES as readonly string[]).includes(value)
