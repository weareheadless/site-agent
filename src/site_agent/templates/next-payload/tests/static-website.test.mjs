import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { staticWebsiteResponse } from '../src/lib/static-website.ts'

const manifest = { kind: 'static', routes: { '/': '/index.html', '/en/': '/en/index.html' }, files: { '/index.html': 'hash', '/en/index.html': 'hash', '/assets/site.js': 'hash' } }
const page = () => new Response('<html><head><title>Astrid</title></head><body>Original website</body></html>', {
  headers: { 'content-security-policy': "default-src 'self'; script-src 'self'; frame-ancestors 'none'", 'x-frame-options': 'DENY' },
})
const assets = (servedManifest = manifest, pageResponse = page) => ({
  fetch: async (request) => {
    const pathname = new URL(request.url).pathname
    if (pathname === '/_helloada/static-manifest.json') {
      return new Response(JSON.stringify(servedManifest), { headers: { 'content-type': 'application/json' } })
    }
    return pathname.endsWith('.html') ? pageResponse() : new Response('original-script')
  },
})
const env = (overrides = {}, servedManifest = manifest) => ({
  HELLOADA_PRESENTATION_PROFILE: 'static',
  ASSETS: assets(servedManifest),
  ...overrides,
})
const request = (path = '/', method = 'GET') => new Request('https://tenant.workers.dev' + path, { method })

test('the tenant Worker passes the configured admin preview mount into static routing', () => {
  const worker = readFileSync(new URL('../worker.ts', import.meta.url), 'utf8')
  assert.match(worker, /staticWebsiteResponse\(request, env, helloAdaSite\.routes\.preview\)/)
})

test('the committed route inventory ships as an asset, never as a text binding', async () => {
  const fetched = []
  const settings = env({ ASSETS: { fetch: async (request) => {
    const pathname = new URL(request.url).pathname
    fetched.push(pathname)
    if (pathname === '/_helloada/static-manifest.json') return new Response(JSON.stringify(manifest))
    return pathname.endsWith('.html') ? page() : new Response('original-script')
  } } })
  await staticWebsiteResponse(request('/'), settings)
  await staticWebsiteResponse(request('/en/'), settings)
  assert.deepEqual(fetched, ['/_helloada/static-manifest.json', '/index.html', '/en/index.html'])
})

test('the configured Workspace preview mount serves the same static HTML in both locales', async () => {
  const mount = '/tenant-preview'
  for (const path of [mount, `${mount}/`, `${mount}/en/`]) {
    const fetched = []
    const settings = env({ ASSETS: { fetch: async (request) => {
      const pathname = new URL(request.url).pathname
      fetched.push(pathname)
      if (pathname === '/_helloada/static-manifest.json') return new Response(JSON.stringify(manifest))
      return new Response('<html><head></head><body>Original website</body></html>', {
        headers: { 'content-security-policy': "frame-ancestors 'none'", 'x-frame-options': 'DENY' },
      })
    } } })
    const response = await staticWebsiteResponse(request(path), settings, mount)
    assert.equal(response.status, 200)
    assert.match(await response.text(), /Original website/)
    assert.deepEqual(fetched, ['/_helloada/static-manifest.json', path.endsWith('/en/') ? '/en/index.html' : '/index.html'])
    assert.equal(response.headers.get('x-frame-options'), 'SAMEORIGIN')
    assert.match(response.headers.get('content-security-policy'), /frame-ancestors 'self'/)
    assert.equal(response.headers.get('x-robots-tag'), 'noindex, nofollow')
  }
})

test('preview alias redirects preserve its mount and cannot alias platform APIs', async () => {
  const mount = '/tenant-preview'
  const response = await staticWebsiteResponse(request(`${mount}/en?revision=one`), env(), mount)
  assert.equal(response.status, 308)
  assert.equal(response.headers.get('location'), `https://tenant.workers.dev${mount}/en/?revision=one`)
  assert.equal((await staticWebsiteResponse(request(`${mount}/api/health`), env(), mount)).status, 404)
  assert.equal((await staticWebsiteResponse(request('/wrong-preview/'), env(), mount)).status, 404)
})

test('Payload presentation and reserved platform routes stay with the platform', async () => {
  assert.equal(await staticWebsiteResponse(request(), {}), null)
  for (const path of ['/admin', '/admin/login', '/api/health', '/mail/inbox', '/blog/article', '/_next/chunk.js', '/helloada-release.json', '/helloada-preview/signed-token']) {
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
  const response = await staticWebsiteResponse(request(), env({ ASSETS: assets(manifest, () => new Response('missing', { status: 404 })) }))
  assert.equal(response.status, 503)
  assert.equal((await staticWebsiteResponse(request('/missing'), env())).status, 404)
  await assert.rejects(staticWebsiteResponse(request(), env({ ASSETS: { fetch: async () => new Response('missing', { status: 404 }) } })))
  await assert.rejects(staticWebsiteResponse(request(), env({}, { kind: 'static', routes: {}, files: {} })))
  await assert.rejects(staticWebsiteResponse(request(), env({ HELLOADA_PRESENTATION_PROFILE: 'other' })))
})

test('the original error document is used only for unknown paths, with a real 404 status', async () => {
  const errorManifest = { ...manifest, files: { ...manifest.files, '/404.html': 'hash' } }
  const settings = env({ GOOGLE_SITE_VERIFICATION: 'not-for-error-pages',
    ASSETS: { fetch: async (request) => new URL(request.url).pathname === '/_helloada/static-manifest.json'
      ? new Response(JSON.stringify(errorManifest))
      : new Response('<html lang="es"><title>Not found</title><main>Not found</main></html>') } }, errorManifest)
  const response = await staticWebsiteResponse(request('/unknown'), settings)
  assert.equal(response.status, 404)
  assert.doesNotMatch(await response.text(), /not-for-error-pages/)
  const broken = await staticWebsiteResponse(request(), { ...settings, ASSETS: assets(errorManifest, () => new Response('missing', { status: 404 })) })
  assert.equal(broken.status, 503)
})

test('HEAD returns the same headers without HTML and asset bytes are unchanged', async () => {
  const head = await staticWebsiteResponse(request('/', 'HEAD'), env())
  assert.equal(await head.text(), '')
  const asset = await staticWebsiteResponse(request('/assets/site.js'), env())
  assert.equal(await asset.text(), 'original-script')
})
