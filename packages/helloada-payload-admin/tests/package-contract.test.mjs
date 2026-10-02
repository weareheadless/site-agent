import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = async (path) => readFile(resolve(root, path), 'utf8')

test('approved HelloAda logo is unchanged and rendered exactly', async () => {
  const asset = await source('src/brand/helloada-mark.svg')
  assert.equal(createHash('sha256').update(asset).digest('hex'), '929ec100918ec19fd32319d083bb961ca60d7373da41b7622e5568a260eeaa1f')
  const component = await source('src/components/HelloAdaLogo.tsx')
  for (const geometry of ['viewBox="0 0 1024 1024"', 'cx="426" cy="522" rx="222" ry="236"', 'd="M648 286V684"', 'x="596" y="650" width="148" height="148"']) {
    assert.ok(component.includes(geometry), geometry)
  }
})

test('owner controls preserve publication approval and accessible management', async () => {
  const workspace = await source('src/components/WebsiteWorkspace.tsx')
  assert.match(workspace, /publishDialogRef\.current\?\.showModal\(\)/)
  assert.match(workspace, /aria-labelledby="helloada-publish-title"/)
  const nav = await source('src/components/HelloAdaNav.tsx')
  assert.match(nav, /aria-label=\{t\('owner\.manage'\)\}/)
  assert.match(nav, /useAdaConnection\(\)/)
  assert.match(nav, /helloada-manage-advanced/)
})

test('shared package is customer-neutral', async () => {
  const files = ['src/components/WebsiteWorkspace.tsx', 'src/components/HelloAdaNav.tsx', 'src/styles/admin.scss']
  const contents = await Promise.all(files.map(source))
  const combined = contents.join('\n')
  assert.doesNotMatch(combined, /Atelier|atelier|OceanicVibes|oceanicvibes|\/api\/atelier/)
  assert.match(combined, /HelloAda/)
})

test('shared package has a tenant configuration boundary', async () => {
  const config = await source('src/config/site.tsx')
  assert.match(config, /defineHelloAdaSite/)
  assert.match(config, /workspaceApi/)
  assert.match(config, /preview/)
  assert.match(config, /previewRouteForTenant/)
  assert.match(config, /tenantId/)
})

test('functional dashboard uses the space for work and retains growth access', async () => {
  const workspace = await source('src/components/WebsiteWorkspace.tsx')
  assert.doesNotMatch(workspace, /helloada-workspace-intro/)
  assert.match(workspace, /HelloAdaGrowth/)
  const nav = await source('src/components/HelloAdaNav.tsx')
  assert.match(nav, /view=growth/)
  const growth = await source('src/components/HelloAdaGrowth.tsx')
  for (const feature of ['\/growth', '\/seo\/analytics', 'weeklyReports', 'monthlyReports', 'articleIdeas', 'dataforseo']) assert.ok(growth.includes(feature), feature)
  assert.doesNotMatch(growth, /method:\s*['"]POST['"]|\.random\(/)
})
