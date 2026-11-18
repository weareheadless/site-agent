import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { helloAdaAdminEntry, helloAdaMailboxEntry, helloAdaWorkspaceHref } from '../src/lib/helloada-admin-entry.ts'

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('tenant login returns to its central account entry without caching', () => {
  const response = helloAdaAdminEntry('https://helloada.app', 'atelier-harmonie')
  assert.equal(response.status, 303)
  assert.equal(response.headers.get('location'), 'https://helloada.app/admin-entry/atelier-harmonie')
  assert.match(response.headers.get('cache-control'), /no-store/)
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer')
})

test('the admin links back to the owner workspace through the platform', () => {
  // The control plane resolves a runtime tenant to the address its owner uses,
  // so the link is stable for a readable tenant and for a legacy digest one.
  assert.equal(helloAdaWorkspaceHref('https://helloada.app', 'superincompetence'),
    'https://helloada.app/admin-entry/superincompetence/workspace')
  assert.equal(helloAdaMailboxEntry('https://helloada.app', 'superincompetence'),
    'https://helloada.app/admin-entry/superincompetence/mail')
  assert.equal(helloAdaWorkspaceHref('https://helloada.app', 'site-be8225c72f3ba01a'),
    'https://helloada.app/admin-entry/site-be8225c72f3ba01a/workspace')
})

test('an unresolved identity has no workspace link rather than a guessed one', () => {
  for (const [issuer, tenant] of [
    [undefined, 'superincompetence'], ['https://helloada.app', undefined],
    ['http://helloada.app', 'superincompetence'], ['https://helloada.app/path', 'superincompetence'],
    ['https://helloada.app', '../other'], ['https://user@helloada.app', 'superincompetence'],
  ]) {
    assert.equal(helloAdaWorkspaceHref(issuer, tenant), undefined)
  }
})

test('the tenant admin registers and resolves the workspace link it ships', () => {
  const config = read('payload.config.ts')
  const importMap = read('src/app/(payload)/admin/importMap.js')
  assert.match(config, /beforeNavLinks: \['@\/components\/admin\/HelloAdaBackToWorkspace#HelloAdaBackToWorkspace'\]/)
  assert.match(importMap, /@\/components\/admin\/HelloAdaBackToWorkspace#HelloAdaBackToWorkspace/)
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
