import Link from 'next/link'
import type { ReactNode } from 'react'
import { helloAdaGlobalBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { validateHelloAdaLink } from '@weareheadless/helloada-payload-core/schema'
import { mediaAlt, mediaUrl } from '@/lib/content'
import { presentationRoutes } from '@/lib/content-routes'

type RecordValue = Record<string, unknown>

const navList = (value: unknown) => Array.isArray(value) ? value as RecordValue[] : []
const safeHref = (value: unknown) => {
  const validation = validateHelloAdaLink(value)
  if (validation !== true) throw new Error(`Payload navigation: ${validation}`)
  return String(value).trim()
}

/**
 * The menu a site has before anyone writes one.
 *
 * A site with published pages and an empty `navigation` global used to render
 * an empty `<nav>`: every page existed and none of them was reachable from the
 * chrome. The routes are already known — the release generator writes the
 * committed inventory and Payload owns the published documents — so the menu is
 * derived from the same route list the sitemap uses rather than from a second
 * declaration someone has to remember to fill in.
 *
 * Only committed presentation pages are offered. A Payload document's route is
 * content, and changing it must not silently rewrite the chrome of a site whose
 * owner did author a menu; this default is the floor, not the design.
 */
const defaultItems = (): RecordValue[] =>
  presentationRoutes()
    .filter((route) => route !== '/' && route !== '/blog')
    .map((route) => ({
      key: `route:${route}`,
      label: route.split('/').filter(Boolean).pop()!.replace(/[-_]+/g, ' ').replace(/^./, (c) => c.toUpperCase()),
      href: route,
    }))

function NavItems({ items, global, derived = false }: { items: RecordValue[]; global: 'navigation'; derived?: boolean }) {
  return <>
    {items.filter((item) => item.visible !== false).map((item) => {
      const key = String(item.key || '').trim()
      const label = String(item.label || '').trim()
      const href = safeHref(item.href)
      if (!key || !label) throw new Error('Payload navigation items need stable IDs and labels.')
      // A derived item is not a Payload field, so it carries no edit binding.
      const labelBinding = derived ? undefined : helloAdaGlobalBindingId(global, key, 'label')
      const hrefBinding = derived ? undefined : helloAdaGlobalBindingId(global, key, 'href')
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
  const siteName = String(settings.siteName || '').trim() || 'HelloAda site'
  const logo = mediaUrl(settings.logo)
  const authored = navList(navigation.items)
  const primary = authored.length ? authored : defaultItems()
  const footer = navList(navigation.footer)
  const footerGroups = navList(navigation.footerGroups)

  return <>
    <header className="site-header">
      <Link href="/" className="site-brand" data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'siteName')}>
        {logo ? <img src={logo} alt={mediaAlt(settings.logo) || siteName} data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'logo')} /> : siteName}
      </Link>
      <nav aria-label="Primary navigation">
        <NavItems items={primary} global="navigation" derived={!authored.length} />
      </nav>
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
