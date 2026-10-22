import Link from 'next/link'
import type { ReactNode } from 'react'
import { helloAdaGlobalBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { validateHelloAdaLink } from '@weareheadless/helloada-payload-core/schema'
import { mediaAlt, mediaUrl } from '@/lib/content'

type RecordValue = Record<string, unknown>

const navList = (value: unknown) => Array.isArray(value) ? value as RecordValue[] : []
const safeHref = (value: unknown) => {
  const validation = validateHelloAdaLink(value)
  if (validation !== true) throw new Error(`Payload navigation: ${validation}`)
  return String(value).trim()
}

function NavItems({ items, global }: { items: RecordValue[]; global: 'navigation' }) {
  return <>
    {items.filter((item) => item.visible !== false).map((item) => {
      const key = String(item.key || '').trim()
      const label = String(item.label || '').trim()
      const href = safeHref(item.href)
      if (!key || !label) throw new Error('Payload navigation items need stable IDs and labels.')
      const labelBinding = helloAdaGlobalBindingId(global, key, 'label')
      const hrefBinding = helloAdaGlobalBindingId(global, key, 'href')
      return item.external
        ? <a key={key} data-helloada-field={hrefBinding} href={href} target="_blank" rel="noreferrer"><span data-helloada-field={labelBinding}>{label}</span></a>
        : <Link key={key} data-helloada-field={hrefBinding} href={href}><span data-helloada-field={labelBinding}>{label}</span></Link>
    })}
  </>
}

export default function TenantChrome({ children, navigation, settings }: {
  children: ReactNode
  navigation: RecordValue
  settings: RecordValue
}) {
  const siteName = String(settings.siteName || '').trim()
  if (!siteName) throw new Error('Payload site settings are not initialized.')
  const logo = mediaUrl(settings.logo)
  const primary = navList(navigation.items)
  const footer = navList(navigation.footer)
  const footerGroups = navList(navigation.footerGroups)

  return <>
    <header className="site-header">
      <Link href="/" className="site-brand" data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'siteName')}>
        {logo ? <img src={logo} alt={mediaAlt(settings.logo) || siteName} data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'logo')} /> : siteName}
      </Link>
      <nav aria-label="Primary navigation"><NavItems items={primary} global="navigation" /></nav>
    </header>
    {children}
    <footer className="site-footer">
      <div>
        <strong data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'siteName')}>{siteName}</strong>
        {settings.tagline ? <p data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'tagline')}>{String(settings.tagline)}</p> : null}
        {settings.description ? <p data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'description')}>{String(settings.description)}</p> : null}
        {settings.footerTitle ? <p data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'footerTitle')}>{String(settings.footerTitle)}</p> : null}
        {settings.footerNote ? <small data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'footerNote')}>{String(settings.footerNote)}</small> : null}
        {settings.email ? <a href={`mailto:${String(settings.email)}`} data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'email')}>{String(settings.email)}</a> : null}
      </div>
      <nav aria-label="Footer navigation"><NavItems items={footer} global="navigation" /></nav>
      {footerGroups.map((group) => <div key={String(group.key || '')}>
        <h2 data-helloada-field={helloAdaGlobalBindingId('navigation', String(group.key || ''), 'label')}>{String(group.label || '')}</h2>
        <NavItems items={navList(group.items)} global="navigation" />
      </div>)}
    </footer>
  </>
}
