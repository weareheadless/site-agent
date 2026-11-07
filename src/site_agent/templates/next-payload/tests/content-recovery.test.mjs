import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const content = readFileSync('src/app/api/workspace/content/route.ts', 'utf8')
const global = readFileSync('src/app/api/workspace/global/route.ts', 'utf8')
const bridge = readFileSync('src/app/api/helloada/[...path]/route.ts', 'utf8')
const versions = readFileSync('src/lib/payload-versions.ts', 'utf8')

test('every content write records the exact version it replaced', () => {
  assert.match(versions, /findVersions/)
  assert.match(versions, /where: \{ parent: \{ equals: documentId \} \}/)
  assert.match(versions, /findGlobalVersions/)
  assert.match(content, /const baseVersionId = await latestCollectionVersionId\(payload, collection, id\)/)
  assert.match(content, /baseVersionId,/)
  assert.match(global, /const baseVersionId = await latestGlobalVersionId\(payload, slug\)/)
  assert.match(global, /baseVersionId,/)
})

test('a version restore is exact, idempotent and never overwrites a later edit', () => {
  const branch = content.slice(content.indexOf("if (operation === 'restore')"), content.indexOf("if (operation === 'publish')"))
  assert.ok(branch.length > 200, 'the restore branch is missing')
  assert.match(branch, /expectedHash is required for a version restore/)
  assert.match(branch, /if \(parent !== id\)/)
  assert.match(branch, /if \(currentHash === targetHash\)/)
  assert.match(branch, /alreadyRestored: true/)
  assert.match(branch, /if \(currentHash !== expectedHash\)/)
  assert.match(branch, /restoredHash !== targetHash/)
  assert.match(branch, /restoreVersion\(/)
  assert.doesNotMatch(branch, /overrideAccess: false/)

  const globalBranch = global.slice(global.indexOf("if (operation === 'restore')"), global.lastIndexOf("if (operation === 'update')"))
  assert.ok(globalBranch.length > 200, 'the global restore branch is missing')
  assert.match(globalBranch, /restoreGlobalVersion\(/)
  assert.match(globalBranch, /alreadyRestored: true/)
  assert.match(globalBranch, /if \(currentHash !== expectedHash\)/)
})

test('the owner restore path verifies identity, CAS and the restored revision', () => {
  const start = bridge.indexOf("if (path === '/content/history')", bridge.indexOf('export async function POST'))
  const branch = bridge.slice(start, bridge.indexOf('const upstream', start))
  assert.ok(branch.length > 500, 'the owner restore branch is missing')
  assert.match(branch, /findVersionByID/)
  assert.match(branch, /that version belongs to a different document/)
  assert.match(branch, /expectedHash is required for a version restore/)
  assert.match(branch, /currentHash === targetHash/)
  assert.match(branch, /alreadyRestored: true/)
  assert.match(branch, /restoredHash !== targetHash/)
  assert.match(branch, /findGlobalVersionByID/)
  assert.match(branch, /restoreGlobalVersion\(/)
})

test('the history read can target one exact document and exposes each revision', () => {
  const start = bridge.indexOf("if (path === '/content/history')")
  const branch = bridge.slice(start, bridge.indexOf("if (path === '/language')", start))
  assert.match(branch, /query\.get\('documentId'\)/)
  assert.match(branch, /where: \{ parent: \{ equals: documentId \} \}/)
  assert.match(branch, /revision: await hashJson\(withoutPayloadMetadata\(version\)\)/)
  assert.match(branch, /findGlobalVersions/)
})
