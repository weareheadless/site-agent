import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const bridge = readFileSync('src/app/api/helloada/[...path]/route.ts', 'utf8')
const workspace = readFileSync('src/admin/components/WebsiteWorkspace.tsx', 'utf8')

test('the bridge mints an owner-only exact preview token for one draft document', () => {
  const start = bridge.indexOf("if (path === '/preview')")
  const branch = bridge.slice(start, bridge.indexOf("if (path === '/language')", start))
  assert.ok(start >= 0 && branch.length > 200, 'the preview branch is missing')
  // The branch runs after authentication, reads the exact draft revision and
  // never writes, publishes or falls back to another reader.
  assert.match(bridge, /const auth = await authenticateHelloAdaRequest\(request\)[\s\S]*?if \(path === '\/preview'\)/)
  assert.match(branch, /draft: true/)
  assert.match(branch, /overrideAccess: false/)
  assert.match(branch, /purpose: 'workspace'/)
  assert.match(branch, /pathForDocument\(collection, slug\)/)
  assert.match(branch, /helloAdaPreviewLifetime\('workspace'\)/)
  assert.doesNotMatch(branch, /auth\.payload\.(update|create)\(/)
})

test('the workspace shows the exact pending revision instead of the published alias', () => {
  assert.match(workspace, /fetchHelloAda\('\/api\/helloada\/preview'/)
  assert.match(workspace, /draftPreview && draftPreview\.key === draftPreviewKey/)
  assert.match(workspace, /siteOrigin\}\$\{draftPreview\.url\}/)
  // The published alias remains the fallback for documents without a draft.
  assert.match(workspace, /previewAlias\}/)
  // The signed token is not handed to the model as conversation context.
  assert.match(workspace, /url: draftPreview && draftPreview\.key === draftPreviewKey/)
})
