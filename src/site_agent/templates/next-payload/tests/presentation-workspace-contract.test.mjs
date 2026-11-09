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
test('the control plane reaches the tenant workspace as an owner, not as a browser session', () => {
  const auth = read('src/lib/helloada-auth.ts')
  const route = read('src/app/api/helloada/[...path]/route.ts')

  // The service token alone is not an owner: the trusted caller must name the
  // HelloAda subject, and the Worker links it to one durable Payload user.
  assert.match(auth, /if \(serviceAuthorized\(request\)\)/)
  assert.match(auth, /x-helloada-owner-subject/)
  assert.match(auth, /helloadaSubject: \{ equals: subject \}/)
  assert.match(auth, /helloadaSubject: subject/)
  // A browser cannot choose its own subject: the Payload session path remains
  // the only browser path.
  assert.match(auth, /payload\.auth\(\{ headers: request\.headers, req: localRequest \}\)/)

  // The snapshot carries the tenant's own site configuration so the control
  // plane does not guess locales, modules or preview mounts.
  assert.match(route, /defaultLocale: helloAdaSite\.defaultLocale/)
  assert.match(route, /preview: helloAdaSite\.routes\.preview/)
  assert.match(route, /content: helloAdaSite\.content/)
  assert.match(route, /features: helloAdaSite\.features/)
})
