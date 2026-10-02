import Link from 'next/link'
import type { ReactNode } from 'react'

import { getNavigation, getSiteSettings, navigationItems } from '@/lib/content'

const hrefFor = (href: string) => href.startsWith('/') || href.startsWith('#') ? href : `/${href}`

export default async function SiteChrome({ children }: { children: ReactNode }) {
  const [navigation, settings] = await Promise.all([getNavigation(), getSiteSettings()])
  const items = navigationItems(navigation.items)
  const footer = navigationItems(navigation.footer)
  const siteName = String(settings.siteName || 'Your website')

  return (
    <>
      <header className="site-header">
        <Link href="/" className="site-brand">{siteName}</Link>
        <nav aria-label="Primary navigation">
          {items.map((item: { label: string; href: string; external: boolean }) => item.external ? (
            <a key={`${item.label}-${item.href}`} href={item.href} target="_blank" rel="noreferrer">{item.label}</a>
          ) : (
            <Link key={`${item.label}-${item.href}`} href={hrefFor(item.href)}>{item.label}</Link>
          ))}
        </nav>
      </header>
      {children}
      <footer className="site-footer">
        <div>
          <strong>{siteName}</strong>
          {settings.tagline ? <p>{settings.tagline}</p> : null}
          {settings.description ? <p>{settings.description}</p> : null}
        </div>
        <nav aria-label="Footer navigation">
          {footer.map((item: { label: string; href: string; external: boolean }) => item.external ? (
            <a key={`${item.label}-${item.href}`} href={item.href} target="_blank" rel="noreferrer">{item.label}</a>
          ) : (
            <Link key={`${item.label}-${item.href}`} href={hrefFor(item.href)}>{item.label}</Link>
          ))}
        </nav>
        {settings.email ? <a href={`mailto:${settings.email}`}>{settings.email}</a> : null}
      </footer>
    </>
  )
}
