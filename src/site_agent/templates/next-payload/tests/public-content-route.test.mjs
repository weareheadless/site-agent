import assert from 'node:assert/strict'
import test from 'node:test'

import { pathForDocument } from '../src/lib/content-routes.ts'
import { publicRouteForDocument, withPublicRoute } from '../src/lib/public-content-route.ts'
import { hashJson, withoutPayloadMetadata } from '../src/lib/payload-hash.ts'

test('workspace content uses the configured shared resolver for pages and posts', () => {
  const page = { id: 'page-1', slug: 'about' }
  const post = { id: 'post-1', slug: 'resolver-fixture-post' }
  assert.equal(publicRouteForDocument('pages', page), pathForDocument('pages', 'about'))
  assert.equal(publicRouteForDocument('posts', post), pathForDocument('posts', 'resolver-fixture-post'))
  assert.equal(publicRouteForDocument('posts', post), '/blog/resolver-fixture-post')
})

test('workspace content preserves the established explicit-route precedence without mutating source data', () => {
  const source = { id: 'post-2', slug: 'ignored-by-explicit-route', route: '/news/feature/' }
  const output = withPublicRoute('posts', source)
  assert.equal(output.route, '/news/feature')
  assert.equal(source.route, '/news/feature/')
})

test('workspace content refuses unsafe explicit routes and missing route slugs', () => {
  for (const route of ['//foreign.example/path', '/../../admin', '/%2e%2e/admin', '/%2f%2fforeign.example/path',
    '/post?draft=1', '/post#fragment']) {
    assert.throws(() => publicRouteForDocument('posts', { id: 'p', route }), /route|traversal/i)
  }
  assert.throws(() => publicRouteForDocument('posts', { id: 'p' }), /slug/i)
})

test('workspace document route projection adds only the derived response field', () => {
  const source = { id: 'page-2', slug: 'contact', title: 'Contact' }
  const projected = withPublicRoute('pages', source)
  assert.equal(projected.route, pathForDocument('pages', 'contact'))
  assert.deepEqual(source, { id: 'page-2', slug: 'contact', title: 'Contact' })
})

test('derived response routes do not change the canonical Payload document hash', async () => {
  const source = { id: 'post-hash', slug: 'hash-fixture', title: 'Hash fixture', _status: 'published' }
  const before = await hashJson(withoutPayloadMetadata(source))
  withPublicRoute('posts', source)
  const after = await hashJson(withoutPayloadMetadata(source))
  assert.equal(after, before)
})
