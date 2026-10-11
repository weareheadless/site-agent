import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path) => readFileSync(new URL(path, root), 'utf8')

test('the shared admin routes mailbox and calendar users into the Mailflare application', () => {
  const navigation = read('src/components/HelloAdaNav.tsx')
  const workspace = read('src/components/WebsiteWorkspace.tsx')
  assert.match(navigation, /href="\/mail\/inbox"/)
  assert.match(workspace, /MailflareRedirect href="\/mail\/inbox"/)
  assert.match(workspace, /MailflareRedirect href="\/mail\/calendar"/)
})

test('the Payload admin package does not ship a parallel mailbox or calendar UI', () => {
  const exports = read('src/index.ts')
  const styles = read('src/styles/admin.scss')
  assert.doesNotMatch(exports, /HelloAdaMessages|HelloAdaCalendar/)
  assert.doesNotMatch(styles, /messages/)
  assert.equal(existsSync(new URL('../src/components/HelloAdaMessages.tsx', import.meta.url)), false)
  assert.equal(existsSync(new URL('../src/components/HelloAdaCalendar.tsx', import.meta.url)), false)
})
