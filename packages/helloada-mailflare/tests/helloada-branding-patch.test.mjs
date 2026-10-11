import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { applyHelloAdaBrandingPatch, shouldSkipUpstreamBrandIcon } from '../scripts/helloada-branding-patch.mjs'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const source = (relative) => readFile(path.join(packageRoot, 'upstream', relative), 'utf8')

test('Mailflare UI build copy uses only the canonical HelloAda identity and mark', async () => {
  const patched = applyHelloAdaBrandingPatch({
    layout: await source('src/app/layout.tsx'),
    manifest: await source('src/app/manifest.ts'),
    brandingDefaults: await source('src/components/branding-provider-utils.ts'),
    brandingProvider: await source('src/components/branding-provider.tsx'),
    brandingService: await source('src/lib/branding/service.ts'),
    brandingIconRoute: await source('src/app/api/branding/icon/route.ts'),
  }, '/mail')

  for (const name of ['layout', 'manifest', 'brandingDefaults', 'brandingProvider', 'brandingService', 'brandingIconRoute']) {
    assert.doesNotMatch(patched[name], /Mailflare/)
  }
  assert.match(patched.layout, /title: "HelloAda"/)
  assert.ok(patched.layout.includes('/mail/helloada-logo.svg'))
  assert.ok(patched.manifest.includes('start_url: "/mail/inbox"'))
  assert.ok(patched.manifest.includes('image/svg+xml'))
  assert.match(patched.brandingService, /canCustomizeBranding: false/)
  assert.match(patched.brandingService, /HelloAda branding is fixed/)
  assert.ok(patched.brandingIconRoute.includes('/mail/helloada-logo.svg'))
  assert.ok(!patched.brandingIconRoute.includes('icon-96.png'))

  const canonicalLogo = await readFile(path.resolve(packageRoot, '../../src/site_agent/templates/next-payload/public/brand/helloada-logo.svg'), 'utf8')
  assert.match(canonicalLogo, /#FF6B5E/)
  assert.match(canonicalLogo, /#FFC857/)
})

test('the built app omits the pinned upstream brand icon files', () => {
  for (const icon of ['public/favicon.ico', 'public/icon-96.png', 'public/icon-192.png', 'public/icon-512.png']) {
    assert.equal(shouldSkipUpstreamBrandIcon(icon), true)
  }
  assert.equal(shouldSkipUpstreamBrandIcon('public/helloada-logo.svg'), false)
  assert.equal(shouldSkipUpstreamBrandIcon('public/background.png'), false)
})

test('branding patch fails closed if the pinned icon contract has changed', () => {
  assert.throws(() => applyHelloAdaBrandingPatch({
    layout: '', manifest: '', brandingDefaults: '', brandingProvider: '',
    brandingService: '', brandingIconRoute: '',
  }, '/mail'), /no longer applies exactly once/)
  assert.throws(() => applyHelloAdaBrandingPatch({
    layout: '', manifest: '', brandingDefaults: '', brandingProvider: '',
    brandingService: '', brandingIconRoute: '',
  }, '/other'), /registered \/mail base path/)
})
