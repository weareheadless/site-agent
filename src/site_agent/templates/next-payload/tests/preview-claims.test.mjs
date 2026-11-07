import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildHelloAdaPreviewClaims,
  helloAdaPreviewLifetime,
  validHelloAdaPreviewClaims,
} from '../src/lib/helloada-preview-claims.ts'

const hash = (character) => `sha256:${character.repeat(64)}`
const now = 1_800_000_000

const input = (overrides = {}) => ({
  tenantId: 'oceanicvibes',
  principal: { type: 'owner', ownerId: '7' },
  collection: 'pages',
  documentId: '2',
  documentHash: hash('a'),
  locale: 'en',
  globals: [
    { slug: 'siteSettings', hash: hash('b') },
    { slug: 'navigation', hash: hash('c') },
  ],
  route: '/about',
  state: 'draft',
  ...overrides,
})

test('verification tokens stay short-lived and reject a longer lifetime', () => {
  const claims = buildHelloAdaPreviewClaims(input(), now)
  assert.equal(claims.purpose, 'verification')
  assert.equal(claims.expiresAt, now + 180)
  assert.ok(validHelloAdaPreviewClaims(claims, 'oceanicvibes', now))
  assert.equal(validHelloAdaPreviewClaims({ ...claims, expiresAt: now + 600 }, 'oceanicvibes', now), false)
})

test('workspace preview tokens let the owner browse one exact revision for an hour', () => {
  const claims = buildHelloAdaPreviewClaims(input({ purpose: 'workspace' }), now)
  assert.equal(helloAdaPreviewLifetime('workspace'), 3600)
  assert.equal(claims.expiresAt, now + 3600)
  assert.ok(validHelloAdaPreviewClaims(claims, 'oceanicvibes', now))
  assert.ok(validHelloAdaPreviewClaims(claims, 'oceanicvibes', now + 1800))
  assert.equal(validHelloAdaPreviewClaims(claims, 'oceanicvibes', now + 3600), false)
  assert.equal(validHelloAdaPreviewClaims({ ...claims, expiresAt: now + 7200 }, 'oceanicvibes', now), false)
})

test('a workspace token is owner-only and tenant-bound', () => {
  assert.throws(
    () => buildHelloAdaPreviewClaims(input({ purpose: 'workspace', principal: { type: 'service' } }), now),
    /preview claims are invalid/,
  )
  const claims = buildHelloAdaPreviewClaims(input({ purpose: 'workspace' }), now)
  assert.equal(validHelloAdaPreviewClaims(claims, 'atelier-harmonie', now), false)
})

test('claims reject a different route, document or hash identity', () => {
  const claims = buildHelloAdaPreviewClaims(input({ purpose: 'workspace' }), now)
  assert.equal(validHelloAdaPreviewClaims({ ...claims, route: '//evil.example' }, 'oceanicvibes', now), false)
  assert.equal(validHelloAdaPreviewClaims({ ...claims, documentHash: 'sha256:short' }, 'oceanicvibes', now), false)
  assert.equal(validHelloAdaPreviewClaims({ ...claims, documentId: '' }, 'oceanicvibes', now), false)
  assert.equal(validHelloAdaPreviewClaims({ ...claims, globals: claims.globals.slice(0, 1) }, 'oceanicvibes', now), false)
})
