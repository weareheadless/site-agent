import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('the workspace lists committed pages and the release rejects a site without them', () => {
  const route = read('src/app/api/helloada/[...path]/route.ts')
  const verifier = read('scripts/verify-payload-contract.ts')

  assert.match(route, /presentationRoutes\(\)/)
  assert.match(route, /routes\.some\(\(route\) => route\.path === declared\)/)
  assert.match(verifier, /committed presentation routes including its home page/)
  assert.match(verifier, /previewMount/)
  // The control plane reads the same snapshot server-to-server; the browser
  // never holds the tenant workspace token.
  assert.match(route, /path === '\/workspace' && serviceAuthorized\(request\)/)
  assert.match(route, /workspaceSnapshotResponse\(request, await getPayload\(\{ config \}\)\)/)
})