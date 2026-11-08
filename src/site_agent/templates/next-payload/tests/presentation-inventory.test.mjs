import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { createPresentationInventory, discoverPresentationRoutes } from '../../../../../scripts/presentation-inventory.mjs'

const fixture = async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'helloada-presentation-'))
  t.after(async () => { await rm(root, { recursive: true, force: true }) })
  return root
}

const page = async (root, route) => {
  const directory = path.join(root, route)
  await mkdir(directory, { recursive: true })
  await writeFile(path.join(directory, 'page.tsx'), 'export default function Page() { return null }\n')
}

test('committed pages become the owner-visible route inventory', async (t) => {
  const app = await fixture(t)
  await page(app, '')
  await page(app, '(frontend)/courses')
  await page(app, '(frontend)/courses/[slug]')
  await page(app, 'about/team')
  await page(app, 'api/health')
  await page(app, '(payload)/admin/[[...segments]]')
  await page(app, 'helloada-preview/[token]')
  await page(app, 'preview/listing/[slug]')
  await page(app, '_components/widget')

  assert.deepEqual(discoverPresentationRoutes(app), ['/', '/about/team', '/courses'])
})

test('a built site cannot ship without an explicit preview mount', async (t) => {
  const app = await fixture(t)
  await page(app, '')
  const inventory = createPresentationInventory(app, '/tenant-preview')
  assert.deepEqual(inventory, { schema: 1, previewMount: '/tenant-preview', routes: [{ path: '/' }] })
  assert.throws(() => createPresentationInventory(app, '/'), /preview mount/)
  assert.throws(() => createPresentationInventory(app, 'tenant-preview'), /preview mount/)
  assert.throws(() => createPresentationInventory(app, '/tenant-preview/'), /preview mount/)
})