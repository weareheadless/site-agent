import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const root = new URL('../src/', import.meta.url)

test('ready attachment markup shows filename and translated status with removable chip', async () => {
  const source = await readFile(new URL('components/WebsiteWorkspace.tsx', root), 'utf8')
  assert.match(source, /attachment\.name[^\n]*\n[\s\S]{0,180}attachmentReady/)
  assert.match(source, /t\('workspace\.attachmentReady'\)/)
  assert.match(source, /onClick=\{\(\) => setPendingAttachments\(\(current\) => current\.filter/)
})

test('translations retain ready status and French preview messages', async () => {
  const source = await readFile(new URL('lib/admin-translations.ts', root), 'utf8')
  for (const key of ['workspace.attachmentReady', 'workspace.previewBuildRequired', 'workspace.previewError']) {
    assert.ok(source.includes(`'${key}'`), `missing ${key}`)
  }
  assert.ok(source.includes("'workspace.previewBuildRequired': 'Ce changement de code nécessite un aperçu compilé.'"))
  assert.ok(source.includes("'workspace.previewError': 'L’aperçu n’a pas pu être actualisé.'"))
})

test('ready chip thumbnail is bounded to 46px and retains wrapping and removal affordance', async () => {
  const source = await readFile(new URL('styles/admin.scss', root), 'utf8')
  const rules = source.slice(source.indexOf('.helloada-pending-attachment {'), source.indexOf('.helloada-pending-attachment b {'))
  assert.match(rules, /\.helloada-pending-attachment img[\s\S]*?width:\s*46px/)
  assert.match(rules, /height:\s*46px/)
  assert.match(rules, /overflow-wrap:\s*anywhere/)
  assert.match(source, /\.helloada-pending-attachment b \{[\s\S]*?position:\s*absolute/)
})
