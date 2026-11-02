import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/lib/locale-routing.ts', import.meta.url), 'utf8')
const js = ts.transpile(source, { module: ts.ModuleKind.CommonJS })
const module = { exports: {} }
new Function('module', 'exports', js)(module, module.exports)
const { resolveRequestLocale, localeSwitchHref, LOCALE_HEADER, LOCALE_COOKIE } = module.exports

test('explicit locale, cookie preference, configured default and invalid inputs', () => {
  assert.deepEqual(resolveRequestLocale(['fr'], 'en', ['en', 'fr'], 'en'), { ok: true, locale: 'fr' })
  assert.deepEqual(resolveRequestLocale([], 'fr', ['en', 'fr'], 'en'), { ok: true, locale: 'fr' })
  assert.deepEqual(resolveRequestLocale([], undefined, ['en', 'fr'], 'en'), { ok: true, locale: 'en' })
  assert.deepEqual(resolveRequestLocale(['xx'], undefined, ['en', 'fr'], 'en'), { ok: false })
  assert.deepEqual(resolveRequestLocale([], 'xx', ['en', 'fr'], 'en'), { ok: false })
  assert.deepEqual(resolveRequestLocale(['en', 'fr'], undefined, ['en', 'fr'], 'en'), { ok: false })
})

test('switch link preserves route and other query parameters', () => {
  assert.equal(localeSwitchHref('/about?campaign=spring&locale=en', 'fr'), '/about?campaign=spring&locale=fr')
})

test('middleware validates query and cookie and overrides spoofed request header; preview keeps rewrite/noindex', async () => {
  const middlewareSource = readFileSync(new URL('../src/middleware.ts', import.meta.url), 'utf8')
  const middlewareJs = ts.transpile(middlewareSource, { module: ts.ModuleKind.CommonJS })
  const outcomes = {}
  class Response {
    constructor(kind, destination, options) { this.kind = kind; this.destination = destination; this.options = options; this.status = options?.status ?? destination?.status; this.headers = new Map(); this.cookies = { set: (...args) => { this.cookie = args } } }
    static next(options) { return new Response('next', null, options) }
    static rewrite(destination, options) { return new Response('rewrite', destination, options) }
  }
  const cfg = { locales: ['en', 'fr'], defaultLocale: 'en', routes: { preview: '/preview' } }
  const loaded = { exports: {} }
  new Function('module', 'exports', 'require', 'Headers', 'process', middlewareJs)(loaded, loaded.exports, (name) => name === 'next/server' ? { NextResponse: Response } : name.endsWith('helloada.config') ? { helloAdaSite: cfg } : name.endsWith('workspace-preview-path') ? { workspacePreviewPath: (p) => p.startsWith('/workspace-preview') ? p.slice('/workspace-preview'.length) || '/' : undefined } : module.exports, Headers, { env: { NODE_ENV: 'test' } })
  const run = (path, search, cookie, inbound = 'xx') => {
    const nextUrl = new URL(`https://site.test${path}${search}`)
    nextUrl.clone = () => new URL(nextUrl)
    const headers = new Headers({ [LOCALE_HEADER]: inbound })
    return loaded.exports.middleware({ nextUrl, headers, cookies: { get: () => cookie ? { value: cookie } : undefined } })
  }
  const query = run('/about', '?locale=fr&x=1', 'en')
  assert.equal(query.options.request.headers.get(LOCALE_HEADER), 'fr')
  assert.deepEqual(query.cookie.slice(0, 2), [LOCALE_COOKIE, 'fr'])
  assert.equal(run('/about', '', 'fr').options.request.headers.get(LOCALE_HEADER), 'fr')
  assert.equal(run('/about', '', undefined).options.request.headers.get(LOCALE_HEADER), 'en')
  assert.equal(run('/about', '?locale=xx', 'en').status, 400)
  const excluded = run('/api/health', '', undefined)
  assert.equal(excluded.options.request.headers.has(LOCALE_HEADER), false)
  const preview = run('/workspace-preview/about', '', 'xx')
  assert.equal(preview.kind, 'rewrite')
  assert.equal(preview.destination.pathname, '/about')
  assert.equal(preview.headers.get('X-Robots-Tag'), 'noindex, nofollow')
})
