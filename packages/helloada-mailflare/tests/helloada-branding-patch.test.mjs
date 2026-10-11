import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { applyHelloAdaBrandingPatch, sanitizeHelloAdaBrandCopy, sanitizeHelloAdaLocaleValues, shouldSkipUpstreamBrandIcon } from '../scripts/helloada-branding-patch.mjs'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const source = (relative) => readFile(path.join(packageRoot, 'upstream', relative), 'utf8')

async function getBrandingSources() {
  return {
    layout: await source('src/app/layout.tsx'),
    manifest: await source('src/app/manifest.ts'),
    brandingDefaults: await source('src/components/branding-provider-utils.ts'),
    brandingProvider: await source('src/components/branding-provider.tsx'),
    brandingService: await source('src/lib/branding/service.ts'),
    brandingIconRoute: await source('src/app/api/branding/icon/route.ts'),
    sidebarFooter: await source('src/components/sidebar-footer.tsx'),
  }
}

test('the disposable mailbox UI uses only the canonical HelloAda identity and mark', async () => {
  const patched = applyHelloAdaBrandingPatch(await getBrandingSources(), '/mail')

  for (const name of ['layout', 'manifest', 'brandingDefaults', 'brandingProvider', 'brandingService', 'brandingIconRoute', 'sidebarFooter']) {
    assert.doesNotMatch(patched[name], /Mailflare/)
  }
  assert.match(patched.layout, /title: "HelloAda"/)
  assert.ok(patched.layout.includes('/brand/helloada-logo.svg'))
  assert.ok(patched.manifest.includes('name: "HelloAda"'))
  assert.ok(patched.manifest.includes('short_name: "HelloAda"'))
  assert.ok(patched.manifest.includes('start_url: "/mail/inbox"'))
  assert.ok(patched.manifest.includes('image/svg+xml'))
  assert.match(patched.brandingService, /canCustomizeBranding: false/)
  assert.match(patched.brandingService, /HelloAda branding is fixed/)
  assert.ok(patched.brandingIconRoute.includes('/brand/helloada-logo.svg'))
  assert.ok(patched.sidebarFooter.includes('https://helloada.app'))
  assert.ok(patched.sidebarFooter.includes('HelloAda'))
  assert.ok(!patched.brandingIconRoute.includes('icon-96.png'))

  const canonicalLogo = await readFile(path.resolve(packageRoot, '../../src/site_agent/templates/next-payload/public/brand/helloada-logo.svg'), 'utf8')
  assert.match(canonicalLogo, /#FF6B5E/)
  assert.match(canonicalLogo, /#FFC857/)
})

test('the build omits every pinned upstream brand icon', () => {
  for (const icon of ['public/favicon.ico', 'public/icon-48.png', 'public/icon-96.png', 'public/icon-192.png', 'public/icon-512.png']) {
    assert.equal(shouldSkipUpstreamBrandIcon(icon), true)
  }
  assert.equal(shouldSkipUpstreamBrandIcon('public/helloada-logo.svg'), false)
  assert.equal(shouldSkipUpstreamBrandIcon('public/background.png'), false)
})

test('branding patch fails closed when its pinned source contract changes', () => {
  const empty = {
    layout: '', manifest: '', brandingDefaults: '', brandingProvider: '',
    brandingService: '', brandingIconRoute: '', sidebarFooter: '',
  }
  assert.throws(() => applyHelloAdaBrandingPatch(empty, '/mail'), /no longer applies exactly once/)
  assert.throws(() => applyHelloAdaBrandingPatch(empty, '/other'), /registered \/mail base path/)
})

test('customer-facing copy is HelloAda-branded without renaming internal identifiers', () => {
  assert.equal(
    sanitizeHelloAdaBrandCopy('Mailflare Inbox · MailflareD1 · MAILFLARE_DB · mailflare:messages-changed'),
    'HelloAda Inbox · MailflareD1 · MAILFLARE_DB · mailflare:messages-changed',
  )
  assert.deepEqual(
    sanitizeHelloAdaLocaleValues({
      title: 'Mailflare Inbox',
      identifiers: ['MailflareD1', 'MAILFLARE_DB', 'mailflare:messages-changed'],
      nested: { help: 'Connect to Mailflare' },
    }),
    {
      title: 'HelloAda Inbox',
      identifiers: ['MailflareD1', 'MAILFLARE_DB', 'mailflare:messages-changed'],
      nested: { help: 'Connect to HelloAda' },
    },
  )
})
