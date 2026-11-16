import type { Metadata } from 'next'

import { helloAdaSite } from '@/helloada.config'

export const dynamic = 'force-dynamic'

/**
 * The home page of a new website.
 *
 * This route, its components and its styles are the tenant's to author: Ada
 * replaces this scaffold with the first real page. The platform owns the route
 * shell around it (`layout.tsx`, the Payload catch-all, chrome, bridge), never
 * this file. Until it is replaced, the site answers a real 200 with framed
 * empty sections instead of a 404, so the workspace, the release gate and the
 * owner all see a website that exists and has not been designed yet.
 */
const sections = [
  { label: 'Introduction' },
  { label: 'What we do' },
  { label: 'Contact' },
]

export async function generateMetadata(): Promise<Metadata> {
  const name = String(helloAdaSite.siteName || '').trim()
  return {
    title: name || 'New website',
    description: 'This website is being designed.',
  }
}

export default function HomePage() {
  const name = String(helloAdaSite.siteName || '').trim()
  return (
    <main className="content-page scaffold">
      <header className="scaffold-intro">
        <p className="eyebrow">New website</p>
        <h1>{name || 'Your website'}</h1>
        <p className="scaffold-lead">
          This page is the starting point for the design. The sections below are
          empty frames waiting for copy, imagery and motion.
        </p>
      </header>

      <div className="scaffold-sections">
        {sections.map((section, index) => (
          <section className="scaffold-section" key={section.label} aria-label={section.label}>
            <p className="scaffold-index">{String(index + 1).padStart(2, '0')}</p>
            <h2>{section.label}</h2>
            <p className="scaffold-note">Content for this section is still to be written.</p>
          </section>
        ))}
      </div>

      <footer className="scaffold-foot">
        <span>{name || 'Your website'}</span>
        <span>HelloAda</span>
      </footer>
    </main>
  )
}
