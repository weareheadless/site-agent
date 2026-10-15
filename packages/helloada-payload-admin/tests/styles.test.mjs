import assert from 'node:assert/strict'
import test from 'node:test'
import { compile } from 'sass'

test('the shared Payload admin stylesheet compiles, including Growth', () => {
  const result = compile('src/styles/admin.scss', { quietDeps: true })
  assert.match(result.css, /\.helloada-growth-featured-decision/)
})
