import assert from 'node:assert/strict'
import test from 'node:test'
import { compile } from 'sass'

test('the shared Payload admin stylesheet compiles, including Growth', () => {
  const result = compile('src/styles/admin.scss', { quietDeps: true })
  assert.match(result.css, /\.helloada-growth-featured-decision/)
  for (const selector of ['.helloada-field-popover-scroll', '.helloada-page-editor-scroll']) {
    assert.match(result.css, new RegExp(`${selector.replaceAll('.', '\\.')}[^}]*overflow-y: auto`))
  }
  assert.match(result.css, /\.helloada-publish-dialog[^}]*max-height: calc\(100vh - 48px\)/)
  assert.match(result.css, /\.helloada-field-popover-footer[^}]*flex: 0 0 auto/)
  assert.match(result.css, /\.helloada-page-editor-footer[^}]*flex: 0 0 auto/)
})
