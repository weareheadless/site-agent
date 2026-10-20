import assert from 'node:assert/strict'
import test from 'node:test'
import { helloAdaAdminEntry } from '../src/lib/helloada-admin-entry.ts'

test('tenant login returns to its central account entry without caching', () => {
  const response = helloAdaAdminEntry('https://helloada.app', 'atelier-harmonie')
  assert.equal(response.status, 303)
  assert.equal(response.headers.get('location'), 'https://helloada.app/admin-entry/atelier-harmonie')
  assert.match(response.headers.get('cache-control'), /no-store/)
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer')
})

test('invalid identity settings fail closed rather than redirect elsewhere', () => {
  for (const [issuer, tenant] of [
    [undefined, 'atelier-harmonie'], ['http://helloada.app', 'atelier-harmonie'],
    ['https://helloada.app/path', 'atelier-harmonie'], ['https://helloada.app', '../other'],
    ['https://helloada.app', undefined], ['https://user@helloada.app', 'atelier-harmonie'],
  ]) {
    const response = helloAdaAdminEntry(issuer, tenant)
    assert.equal(response.status, 503)
    assert.equal(response.headers.get('location'), null)
  }
})
