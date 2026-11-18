import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'
import { readdir } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const packageRoot = path.resolve(import.meta.dirname, '..')
const siteAgentRoot = path.resolve(packageRoot, '../..')
const upstreamRoot = path.join(siteAgentRoot, 'packages/helloada-mailflare/upstream')
const outputRoot = path.join(packageRoot, 'dist')
const read = (relative) => readFileSync(path.join(outputRoot, relative), 'utf8')

const excluded = [
  'src/app/(dashboard)/agent',
  'src/app/(dashboard)/import-export',
  'src/app/(dashboard)/rules',
  'src/app/(calendar)/booking',
]
const routeGroups = ['(dashboard)', '(calendar)']

test.before(() => {
  execFileSync('node', ['scripts/build.mjs'], { cwd: packageRoot, stdio: 'pipe' })
})

test('the generated package is pinned to the shared upstream', () => {
  const pin = JSON.parse(readFileSync(path.join(siteAgentRoot, 'packages/helloada-mailflare/UPSTREAM.json'), 'utf8'))
  const manifest = JSON.parse(read('build.json'))
  assert.equal(manifest.upstreamCommit, pin.commit)
  assert.equal(manifest.upstreamPackageVersion, pin.packageVersion)
  assert.equal(manifest.integrationPatchSet, 'helloada-mailbox-ui-v1')
  assert.ok(manifest.files > 200)
})

test('every owner mailbox page is routed', async () => {
  const walk = async (directory) => {
    const pages = []
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) pages.push(...await walk(target))
      else if (entry.name === 'page.tsx') pages.push(target)
    }
    return pages
  }
  const upstreamPages = []
  for (const group of routeGroups) {
    const pages = (await walk(path.join(upstreamRoot, 'src/app', group)))
      .map((file) => path.relative(upstreamRoot, file).split(path.sep).join('/'))
      .filter((relative) => !excluded.some((entry) => relative.startsWith(entry)))
      .map((relative) => relative.replace(`src/app/${group}`, '').replace(/\/page\.tsx$/, '').replace(/\[([^\]]+)\]/g, ':$1') || '/')
    upstreamPages.push(...pages)
  }
  upstreamPages.sort()
  const routes = [...read('routes.generated.tsx').matchAll(/pattern: "([^"]+)"/g)].map((match) => match[1]).sort()
  assert.deepEqual(routes, upstreamPages)
})

test('the owner calendar ships with the mailbox and owns no second route', () => {
  const routes = read('routes.generated.tsx')
  assert.match(routes, /pattern: "\/calendar"/)
  // The tenant booking API is HelloAda's settings model, not the upstream
  // events model this editor reads, so it must not be generated.
  assert.doesNotMatch(routes, /pattern: "\/booking"/)

  const calendar = read('src/app/(calendar)/calendar/page.tsx')
  assert.match(calendar, /authFetch\(`\/api\/calendar\/events/)
  const layout = read('src/app/(calendar)/layout.tsx')
  assert.match(layout, /useMailboxPathname\(\)/)
  assert.doesNotMatch(layout, /\/booking/, 'the calendar layout still offers a booking section')
})

test('the generated tree carries no tenant auth and no root-relative api calls', async () => {
  const walk = async (directory) => {
    const files = []
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) files.push(...await walk(target))
      else if (/\.(?:ts|tsx)$/.test(entry.name)) files.push(target)
    }
    return files
  }
  for (const file of await walk(path.join(outputRoot, 'src'))) {
    const source = readFileSync(file, 'utf8')
    const relative = path.relative(outputRoot, file)
    assert.doesNotMatch(source, /from\s+["']@\//, relative)
    assert.doesNotMatch(source, /fetch\(\s*["'`]\/api/, relative)
    assert.doesNotMatch(source, /window\.location\.assign\("\/login"\)/, relative)
    assert.doesNotMatch(source, /\bAuthGuard\b/, relative)
    assert.doesNotMatch(source, /from\s+["']cloudflare:workers["']/, relative)
    assert.doesNotMatch(source, /\bh-dvh\b/, relative)
  }
})

test('navigation and requests go through the mailbox base and owner proxy', () => {
  const base = read('base.tsx')
  assert.match(base, /export const apiUrl/)
  assert.match(base, /export const mb/)
  assert.match(base, /export const useMailboxPathname/)
  assert.match(base, /export const useMailboxParams/)

  const auth = read('src/lib/auth/client.ts')
  assert.match(auth, /fetch\(resolveApiInput\(input\)/)
  assert.doesNotMatch(auth, /location\.assign/)

  const nav = read('src/components/dashboard-nav.tsx')
  assert.match(nav, /useMailboxPathname\(\)/)
})

test('routes keep their nested layouts', () => {
  const routes = read('routes.generated.tsx')
  const line = (pattern) => routes.split('\n').find((entry) => entry.includes(`pattern: "${pattern}"`))
  assert.match(line('/inbox'), /^import|element: <Layout/)
  assert.match(line('/inbox'), /<Layout\d+_\d+><Layout\d+_\d+><Page\d+ \/><\/Layout\d+_\d+><\/Layout\d+_\d+>/)
  assert.match(line('/folders/:folderId/:messageId'), /<Layout\d+_\d+><Layout\d+_\d+><Page\d+ \/><\/Layout\d+_\d+><\/Layout\d+_\d+>/)
})

test('locale catalogs are bundled with the package', async () => {
  const catalogs = await readdir(path.join(outputRoot, 'locales'))
  assert.ok(catalogs.length >= 30)
  assert.ok(catalogs.includes('fr.json'))
  const i18n = read('src/lib/i18n/utils.ts')
  assert.match(i18n, /const catalogs = \{/)
  assert.match(i18n, /"fr": \(\) => import\("\.\.\/\.\.\/\.\.\/locales\/fr\.json"\)/)
})

test('the package exposes one entry and one stylesheet', () => {
  const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
  assert.equal(pkg.exports['.'], './dist/index.tsx')
  assert.equal(pkg.exports['./styles.css'], './dist/styles.css')
  assert.ok(existsSync(path.join(outputRoot, 'index.tsx')))
  assert.match(read('styles.css'), /\.helloada-mailbox/)
})

test('client-only route pages read their params from the mailbox provider', () => {
  const drafts = read('src/app/(dashboard)/drafts/[messageId]/page.tsx')
  assert.match(drafts, /^"use client";/)
  assert.match(drafts, /useMailboxParams\(\)/)
  assert.doesNotMatch(drafts, /await params/)
  assert.match(drafts, /<OpenDraftOnRoute draftId=\{messageId\} \/>/)
})

test('the star toggle stores the boolean the API returns', () => {
  const actions = read('src/components/messages/thread-message-actions.tsx')
  assert.match(actions, /const starred = await toggleMessageStar\(message\.id\);/)
  assert.match(actions, /setStarred\(starred\.starred\);/)
  assert.doesNotMatch(actions, /setStarred\(await toggleMessageStar/)
})

test('authFetch is imported from its own module, never from the adapter', () => {
  for (const file of ['src/components/sidebar-state.tsx', 'src/components/branding-provider-utils.ts']) {
    const source = read(file)
    assert.match(source, /import \{ authFetch \} from "[^"]*lib\/auth\/client"/, file)
    assert.doesNotMatch(source, /import \{ authFetch \} from "[^"]*base"/, file)
  }
})

test('the package carries the vendor type shim it needs', () => {
  assert.ok(existsSync(path.join(outputRoot, 'vendor.d.ts')))
  assert.match(read('index.tsx'), /^\/\/\/ <reference path="\.\/vendor\.d\.ts" \/>/)
  const actions = read('src/components/message-actions/message-actions.tsx')
  assert.match(actions, /^\/\/ @ts-nocheck/)
})

test('the mailbox shell leaves the brand to the control plane', () => {
  // The workspace header above the mailbox already renders the HelloAda mark
  // and name. A second sidebar brand is either a duplicate or a broken icon
  // path the control plane does not serve, so the shell keeps only its
  // collapse control.
  const header = read('src/components/sidebar-header.tsx')
  assert.doesNotMatch(header, /<img/, 'sidebar header renders a brand image')
  assert.doesNotMatch(header, /iconUrl/, 'sidebar header reads a branding icon')
  assert.doesNotMatch(header, /branding\.appName/, 'sidebar header renders a brand name')
  assert.match(header, /TextAlignJustify/, 'sidebar header keeps its collapse control')

  const footer = read('src/components/sidebar-footer.tsx')
  assert.doesNotMatch(footer, /<PoweredBy \/>/, 'sidebar footer still renders the vendor credit')
})

test('every internal link and router push goes through the mailbox base', async () => {
  const walk = async (directory) => {
    const files = []
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) files.push(...await walk(target))
      else if (/\.(?:ts|tsx)$/.test(entry.name)) files.push(target)
    }
    return files
  }
  for (const file of await walk(path.join(outputRoot, 'src'))) {
    const source = readFileSync(file, 'utf8')
    const relative = path.relative(outputRoot, file)
    assert.doesNotMatch(source, /from "next\/link"/, relative)
    assert.doesNotMatch(source, /\buseRouter\(\)/, relative)
    assert.doesNotMatch(source, /\buseParams(?:<[^>]*>)?\(\)/, relative)
    assert.doesNotMatch(source, /href=\{`\/api/, relative)
    if (/router\.(push|replace)\("\//.test(source)) assert.match(source, /useMailboxRouter\(\)/, relative)
  }
  const base = read('base.tsx')
  assert.match(base, /export function MailboxLink/)
  assert.match(base, /export function useMailboxRouter/)
})
