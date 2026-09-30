'use client'

import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { useConfig } from '@payloadcms/ui'

import type { TypedUser } from 'payload'
import { HELLOADA_LANGUAGES, DEFAULT_LANGUAGE, isHelloAdaLanguage } from '../lib/languages'
import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { HelloAdaMark } from './HelloAdaLogo'
import { useHelloAdaSite } from '../config/site'

type HelloAdaNavProps = {
  user?: TypedUser | null
}

const primaryCollectionLabels: Record<string, string> = {
  pages: 'collection.pages',
  posts: 'collection.posts',
  products: 'collection.products',
  media: 'collection.media',
}

const collectionLabels: Record<string, string> = {
  ...primaryCollectionLabels,
  postCategories: 'collection.postCategories',
  productCategories: 'collection.productCategories',
  users: 'collection.users',
}

const globalLabels: Record<string, string> = {
  siteSettings: 'global.siteSettings',
  navigation: 'global.navigation',
}

const titleize = (slug: string) => slug
  .replace(/([a-z])([A-Z])/g, '$1 $2')
  .replace(/[-_]/g, ' ')
  .replace(/\b\w/g, (letter) => letter.toUpperCase())

const labelKeyFor = (slug: string, labels: Record<string, string>) => labels[slug] || titleize(slug)

const userLabel = (user: TypedUser | null | undefined, fallback: string) => {
  const email = typeof user?.email === 'string' ? user.email : ''
  return email.split('@')[0]?.trim() || fallback
}

const languageLabel = (code: string, locale: string) => {
  try {
    return new Intl.DisplayNames([locale, 'en'], { type: 'language' }).of(code) || code
  } catch {
    return code
  }
}

export function HelloAdaNav({ user }: HelloAdaNavProps) {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const { config } = useConfig()
  const site = useHelloAdaSite()
  const [language, setLanguage] = useState(DEFAULT_LANGUAGE)
  const { t } = useHelloAdaTranslations(language)
  const [languageSaving, setLanguageSaving] = useState(false)
  const [languageError, setLanguageError] = useState(false)
  const languages = useMemo(
    () => [...HELLOADA_LANGUAGES].sort((a, b) => languageLabel(a, language).localeCompare(languageLabel(b, language))),
    [language],
  )
  const collections = config.collections.map((collection) => ({
    label: t(labelKeyFor(collection.slug, collectionLabels)),
    slug: collection.slug,
    href: `/admin/collections/${collection.slug}`,
  }))
  const globals = config.globals.map((global) => ({
    label: t(globalLabels[global.slug] || titleize(global.slug)),
    slug: global.slug,
    href: `/admin/globals/${global.slug}`,
  }))
  const primaryCollectionSlugs = ['pages', 'posts', 'products', 'media']
  const primaryCollections = primaryCollectionSlugs
    .map((slug) => collections.find((item) => item.slug === slug))
    .filter((item): item is (typeof collections)[number] => Boolean(item))
  const settings = globals.find((item) => item.slug === 'siteSettings')
  const additionalCollections = collections.filter((item) => !primaryCollectionSlugs.includes(item.slug))
  const additionalGlobals = globals.filter((item) => item.slug !== 'siteSettings')
  const isHistory = pathname === '/admin' && searchParams.get('view') === 'history'
  const isActive = (href: string, exact = false) => exact ? pathname === href : pathname.startsWith(href)
  const hasAdditionalActive = [...additionalCollections, ...additionalGlobals].some((item) => isActive(item.href))

  useEffect(() => {
    let cancelled = false
    void fetchHelloAda('/api/helloada/language', { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error('language_load_failed')
        return response.json() as Promise<{ language?: string }>
      })
      .then((data) => {
        const nextLanguage = data.language
        if (!cancelled && nextLanguage && isHelloAdaLanguage(nextLanguage)) setLanguage(nextLanguage)
      })
      .catch(() => {
        if (!cancelled) setLanguageError(true)
      })
    return () => { cancelled = true }
    }, [])

  const changeLanguage = async (nextLanguage: string) => {
    if (!isHelloAdaLanguage(nextLanguage)) return
    setLanguage(nextLanguage)
    setLanguageSaving(true)
    setLanguageError(false)
    try {
      const response = await fetchHelloAda('/api/helloada/language', {
        body: JSON.stringify({ language: nextLanguage }),
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        method: 'POST',
      })
      if (!response.ok) throw new Error('language_update_failed')
      window.location.reload()
    } catch {
      setLanguageError(true)
      setLanguageSaving(false)
    }
  }

  return (
    <nav className="helloada-payload-nav" aria-label={t('nav.studioConsole')}>
      <Link className="helloada-payload-brand" href="/admin" aria-label={t('nav.studioConsole')}>
        <HelloAdaMark size={30} />
        <span>
        <strong>HelloAda</strong>
          <small>{t('nav.studioConsole')}</small>
        </span>
      </Link>

      <Link className="helloada-payload-user" href="/admin/account" aria-label={t('nav.account')}>
        {userLabel(user, t('nav.account'))}
      </Link>

      <div className="helloada-payload-links">
        <Link className={pathname === '/admin' && !isHistory ? 'is-active' : undefined} href="/admin" aria-current={pathname === '/admin' && !isHistory ? 'page' : undefined}>
          {t('nav.review')}
        </Link>
        <Link className={isHistory ? 'is-active' : undefined} href="/admin?view=history" aria-current={isHistory ? 'page' : undefined}>
          {t('nav.history')}
        </Link>
        {primaryCollections.map((item) => {
          const active = isActive(item.href)
          return (
            <Link className={active ? 'is-active' : undefined} href={item.href} key={item.slug} aria-current={active ? 'page' : undefined}>
              {item.label}
            </Link>
          )
        })}
        {settings ? (
          <Link className={isActive(settings.href) ? 'is-active' : undefined} href={settings.href} aria-current={isActive(settings.href) ? 'page' : undefined}>
            {t('nav.settings')}
          </Link>
        ) : null}
        <details className={`helloada-payload-menu${hasAdditionalActive ? ' is-active' : ''}`}>
          <summary>
            {t('nav.allContent')}
            <span aria-hidden="true">⌄</span>
          </summary>
          <div className="helloada-payload-menu-panel">
            {additionalCollections.length > 0 ? (
              <div className="helloada-payload-menu-section">
                <strong>{t('nav.collections')}</strong>
                {additionalCollections.map((item) => (
                  <Link href={item.href} key={item.slug} aria-current={isActive(item.href) ? 'page' : undefined}>
                    {item.label}
                  </Link>
                ))}
              </div>
            ) : null}
            {additionalGlobals.length > 0 ? (
              <div className="helloada-payload-menu-section">
                <strong>{t('nav.siteSetup')}</strong>
                {additionalGlobals.map((item) => (
                  <Link href={item.href} key={item.slug} aria-current={isActive(item.href) ? 'page' : undefined}>
                    {item.label}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        </details>
      </div>

      <div className="helloada-payload-context">
        <span>{t('nav.websiteWorkspace')}</span>
        <strong>{site.siteName}</strong>
      </div>

      <div className="helloada-payload-actions">
        <label className="helloada-payload-language">
          <span>{t('nav.language')}</span>
          <select aria-label={t('nav.language')} disabled={languageSaving || languages.length === 0} value={language} onChange={(event) => void changeLanguage(event.target.value)}>
            {languages.map((code) => <option key={code} value={code}>{languageLabel(code, language)} ({code})</option>)}
          </select>
        </label>
        {languageError ? <span className="helloada-payload-language-error" role="status">{t('nav.languageUnavailable')}</span> : null}
        <span className="helloada-payload-status">
          <i aria-hidden="true" />
          {t('nav.adaConnected')}
        </span>
        <button type="button" onClick={() => window.location.reload()} aria-label={t('nav.refreshWorkspace')}>
          ↻
        </button>
      </div>
    </nav>
  )
}
