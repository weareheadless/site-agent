'use client'

import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useConfig } from '@payloadcms/ui'
import type { TypedUser } from 'payload'

import { HELLOADA_LANGUAGES, isHelloAdaLanguage } from '../lib/languages'
import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { useAdaConnection } from '../api/useAdaConnection'
import { HelloAdaMark } from './HelloAdaLogo'
import { WorkspaceIcon } from './WorkspaceIcon'
import { useHelloAdaSite } from '../config/provider'

const collectionLabels: Record<string, string> = {
  pages: 'collection.pages', posts: 'collection.posts', products: 'collection.products',
  media: 'collection.media', postCategories: 'collection.postCategories',
  productCategories: 'collection.productCategories', users: 'collection.users',
}
const globalLabels: Record<string, string> = { siteSettings: 'global.siteSettings', navigation: 'global.navigation' }
const titleize = (slug: string) => slug.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[-_]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
const languageLabel = (code: string, locale: string) => {
  try { return new Intl.DisplayNames([locale, 'en'], { type: 'language' }).of(code) || code } catch { return code }
}

export function HelloAdaNav({ user }: { user?: TypedUser | null }) {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const { config } = useConfig()
  const site = useHelloAdaSite()
  const { language: currentLanguage } = useHelloAdaTranslations()
  const [language, setLanguage] = useState(currentLanguage)
  const { t } = useHelloAdaTranslations(language)
  const [languageSaving, setLanguageSaving] = useState(false)
  const [languageError, setLanguageError] = useState(false)
  const drawerRef = useRef<HTMLDialogElement>(null)
  const connection = useAdaConnection()
  const languages = useMemo(() => [...HELLOADA_LANGUAGES].sort((a, b) => languageLabel(a, language).localeCompare(languageLabel(b, language))), [language])
  const collections = config.collections.map((item) => ({ slug: item.slug, label: t(collectionLabels[item.slug] || titleize(item.slug)), href: `/admin/collections/${item.slug}` }))
  const globals = config.globals.map((item) => ({ slug: item.slug, label: t(globalLabels[item.slug] || titleize(item.slug)), href: `/admin/globals/${item.slug}` }))
  const primary = collections.filter((item) => site.content.primaryCollections.includes(item.slug))
  const advanced = collections.filter((item) => !site.content.primaryCollections.includes(item.slug))
  const isHistory = pathname === '/admin' && searchParams.get('view') === 'history'
  const isGrowth = pathname === '/admin' && searchParams.get('view') === 'growth'
  const isGallery = pathname === '/admin' && searchParams.get('view') === 'gallery'
  const isActive = (href: string) => pathname.startsWith(href)
  const managing = pathname.startsWith('/admin/collections') || pathname.startsWith('/admin/globals') || pathname.startsWith('/admin/account')

  useEffect(() => { drawerRef.current?.close() }, [pathname, searchParams])
  useEffect(() => {
    const controller = new AbortController()
    void fetchHelloAda('/api/helloada/language', { credentials: 'include', signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error('language_load_failed'); return response.json() as Promise<{ language?: string }> })
      .then((data) => { if (!controller.signal.aborted && data.language && isHelloAdaLanguage(data.language)) setLanguage(data.language) })
      .catch(() => { /* Keep the Payload session locale when the bridge is unavailable. */ })
    return () => controller.abort()
  }, [])

  const changeLanguage = async (next: string) => {
    if (!isHelloAdaLanguage(next)) return
    setLanguageSaving(true)
    setLanguageError(false)
    try {
      const response = await fetchHelloAda('/api/helloada/language', { body: JSON.stringify({ language: next }), credentials: 'include', headers: { 'content-type': 'application/json' }, method: 'POST' })
      if (!response.ok) throw new Error('language_update_failed')
      window.location.reload()
    } catch { setLanguageError(true); setLanguageSaving(false) }
  }

  return <>
    <nav className="helloada-payload-nav" aria-label={t('owner.navigation')}>
      <Link className="helloada-payload-brand" href="/admin" aria-label="HelloAda">
        <HelloAdaMark size={34} /><strong>HelloAda</strong>
      </Link>
      <span className="helloada-nav-divider" aria-hidden="true" />
      <span className="helloada-nav-site" title={site.siteName}>{site.siteName}</span>
      <div className="helloada-payload-links">
        <Link className={pathname === '/admin' && !isHistory && !isGrowth && !isGallery ? 'is-active' : undefined} href="/admin" aria-current={pathname === '/admin' && !isHistory && !isGrowth && !isGallery ? 'page' : undefined}>{t('owner.workspace')}</Link>
        <Link className={isGrowth ? 'is-active' : undefined} href="/admin?view=growth" aria-current={isGrowth ? 'page' : undefined}>{t('growth.title')}</Link>
        <Link className={isGallery ? 'is-active' : undefined} href="/admin?view=gallery" aria-current={isGallery ? 'page' : undefined}>{t('owner.gallery')}</Link>
        <Link className={isHistory ? 'is-active' : undefined} href="/admin?view=history" aria-current={isHistory ? 'page' : undefined}>{t('owner.activity')}</Link>
      </div>
      <div className="helloada-payload-actions">
        <span className={`helloada-payload-status is-${connection}`} role="status"><i aria-hidden="true" />{t(`owner.connection.${connection}`)}</span>
        <button className={`helloada-manage-trigger${managing ? ' is-active' : ''}`} type="button" aria-label={t('owner.manage')} aria-haspopup="dialog" onClick={() => drawerRef.current?.showModal()}><WorkspaceIcon name="settings" /><span>{t('owner.manage')}</span></button>
      </div>
    </nav>

    <dialog className="helloada-manage-drawer" ref={drawerRef} aria-labelledby="helloada-manage-title" onClick={(event) => { if (event.target === event.currentTarget) drawerRef.current?.close() }}>
      <header className="helloada-manage-header">
        <div><span className="helloada-eyebrow">{site.siteName}</span><h2 id="helloada-manage-title">{t('owner.manageTitle')}</h2></div>
        <button type="button" className="helloada-icon-button" onClick={() => drawerRef.current?.close()} aria-label={t('owner.close')} autoFocus><WorkspaceIcon name="close" /></button>
      </header>
      <p className="helloada-manage-intro">{t('owner.manageIntro')}</p>
      <div className="helloada-manage-scroll">
        <section className="helloada-manage-section" aria-labelledby="helloada-content-title">
          <h3 id="helloada-content-title">{t('owner.content')}</h3>
          {primary.map((item) => <Link key={item.slug} href={item.href} aria-current={isActive(item.href) ? 'page' : undefined}><span>{item.slug === 'media' ? t('owner.library') : item.label}</span><WorkspaceIcon name="arrow" size={16} /></Link>)}
        </section>
        {globals.length ? <section className="helloada-manage-section" aria-labelledby="helloada-settings-title">
          <h3 id="helloada-settings-title">{t('nav.settings')}</h3>
          {globals.map((item) => <Link key={item.slug} href={item.href} aria-current={isActive(item.href) ? 'page' : undefined}><span>{item.label}</span><WorkspaceIcon name="arrow" size={16} /></Link>)}
        </section> : null}
        {advanced.length ? <details className="helloada-manage-advanced"><summary>{t('owner.advanced')}<WorkspaceIcon name="chevron" size={16} /></summary><div className="helloada-manage-section">{advanced.map((item) => <Link href={item.href} key={item.slug} aria-current={isActive(item.href) ? 'page' : undefined}><span>{item.label}</span><WorkspaceIcon name="arrow" size={16} /></Link>)}</div></details> : null}
        <label className="helloada-manage-language"><span>{t('nav.language')}</span><select value={language} disabled={languageSaving} onChange={(event) => void changeLanguage(event.target.value)}>{languages.map((code) => <option value={code} key={code}>{languageLabel(code, language)}</option>)}</select></label>
        {languageError ? <p role="alert">{t('nav.languageUnavailable')}</p> : null}
      </div>
      <footer className="helloada-manage-footer"><Link href="/admin/account"><span>{t('nav.account')}</span><small>{user?.email || ''}</small></Link><a href={site.routes.liveSite} target="_blank" rel="noopener noreferrer">{t('owner.openSite')}<WorkspaceIcon name="external" size={16} /></a></footer>
    </dialog>
  </>
}
