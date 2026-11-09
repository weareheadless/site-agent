'use client'

import { useCallback, useSyncExternalStore } from 'react'

import { DEFAULT_LANGUAGE, isHelloAdaLanguage, type HelloAdaLanguage } from '../lib/languages'
import { adminText, normalizeAdminLanguage } from '../lib/admin-translations'

const browserLanguage = (): HelloAdaLanguage => {
  if (typeof document === 'undefined') return DEFAULT_LANGUAGE
  const match = document.cookie.match(/(?:^|;\s*)payload-lng=([^;]+)/i)
  return normalizeAdminLanguage(match?.[1] ? decodeURIComponent(match[1]) : undefined)
}

export const useHelloAdaTranslations = (language?: string) => {
  const activeLanguage = useSyncExternalStore(
    () => () => {},
    () => (language && isHelloAdaLanguage(language) ? language : browserLanguage()),
    () => normalizeAdminLanguage(language),
  )

  const t = useCallback((key: string) => adminText(key, activeLanguage), [activeLanguage])
  return { language: activeLanguage, t }
}
