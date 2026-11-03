import assert from 'node:assert/strict'
import test from 'node:test'
import { staticWebsiteResponse } from '../src/lib/static-website.ts'

const manifest = { kind: 'static', routes: { '/': '/index.html', '/en/': '/en/index.html' }, files: { '/index.html': 'hash', '/en/index.html': 'hash', '/assets/site.js': 'hash' } }
const env = (overrides = {}) => ({
  HELLOADA_PRESENTATION_PROFILE: 'static',
  HELLOADA_STATIC_MANIFEST: JSON.stringify(manifest),
  ASSETS: { fetch: async (request) => new URL(request.url).pathname.endsWith('.html')
    ? new Response('<html><head><title>Astrid</title></head><body>Original website</body></html>', {
      headers: { 'content-security-policy': "default-src 'self'; script-src 'self'; frame-ancestors 'none'", 'x-frame-options': 'DENY' },
    }) : new Response('original-script') },
  ...overrides,
})
const request = (path = '/', method = 'GET') => new Request('https://tenant.workers.dev' + path, { method })

test('Payload presentation and reserved platform routes stay with the platform', async () => {
  assert.equal(await staticWebsiteResponse(request(), {}), null)
  for (const path of ['/admin', '/admin/login', '/api/health', '/mail/inbox', '/blog/article', '/_next/chunk.js', '/helloada-release.json']) {
    assert.equal(await staticWebsiteResponse(request(path), env()), null)
  }
})

test('serves the declared original HTML with real runtime SEO bindings in both locales', async () => {
  for (const path of ['/', '/en/']) {
    const response = await staticWebsiteResponse(request(path), env({ GA_MEASUREMENT_ID: 'G-ABC123', GOOGLE_SITE_VERIFICATION: 'verification<"' }))
    assert.equal(response.status, 200)
    const html = await response.text()
    assert.match(html, /Original website/)
    assert.match(html, /google-site-verification/)
    assert.match(html, /verification&lt;&quot;/)
    assert.match(html, /src="\/_helloada\/analytics.js"/)
    assert.match(response.headers.get('content-security-policy'), /script-src 'self' https:\/\/www.googletagmanager.com/)
    assert.match(response.headers.get('content-security-policy'), /frame-ancestors 'self'/)
    assert.equal(response.headers.get('x-frame-options'), 'SAMEORIGIN')
  }
})

test('directory redirects retain the static website trailing-slash convention and query', async () => {
  const response = await staticWebsiteResponse(request('/en?campaign=one'), env())
  assert.equal(response.status, 308)
  assert.equal(response.headers.get('location'), 'https://tenant.workers.dev/en/?campaign=one')
})

test('analytics runtime script has only the public measurement identity', async () => {
  const response = await staticWebsiteResponse(request('/_helloada/analytics.js'), env({ GA_MEASUREMENT_ID: 'G-ABC123', PAYLOAD_SECRET: 'not-for-browser' }))
  assert.match(await response.text(), /G-ABC123/)
  assert.equal((await staticWebsiteResponse(request('/_helloada/analytics.js'), env())).status, 404)
})

test('a missing declared page is an error, never a CMS or static fallback', async () => {
  const response = await staticWebsiteResponse(request(), env({ ASSETS: { fetch: async () => new Response('missing', { status: 404 }) } }))
  assert.equal(response.status, 503)
  assert.equal((await staticWebsiteResponse(request('/missing'), env())).status, 404)
  await assert.rejects(staticWebsiteResponse(request(), env({ HELLOADA_STATIC_MANIFEST: '' })))
  await assert.rejects(staticWebsiteResponse(request(), env({ HELLOADA_PRESENTATION_PROFILE: 'other' })))
})

test('HEAD returns the same headers without HTML and asset bytes are unchanged', async () => {
  const head = await staticWebsiteResponse(request('/', 'HEAD'), env())
  assert.equal(await head.text(), '')
  const asset = await staticWebsiteResponse(request('/assets/site.js'), env())
  assert.equal(await asset.text(), 'original-script')
})
