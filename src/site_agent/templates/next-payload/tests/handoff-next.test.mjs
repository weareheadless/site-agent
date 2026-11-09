import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const handoff = readFileSync('src/app/api/helloada/handoff/route.ts', 'utf8')

test('the owner handoff can land on a local tenant surface', () => {
  assert.match(handoff, /function handoffNext\(value: string, origin: string\)/)
  assert.match(handoff, /next\.startsWith\('\/'\)/)
  assert.match(handoff, /next\.startsWith\('\/\/'\)/)
  assert.match(handoff, /next\.includes\('\\\\'\)/)
  assert.match(handoff, /resolved\.origin !== origin/)
  assert.match(handoff, /fields\.get\('next'\)/)
  assert.match(handoff, /location: new URL\(next, requestOrigin\)\.toString\(\)/)
})

test('the handoff form accepts only the token and one local destination', () => {
  assert.match(handoff, /fields\.size < 1 \|\| fields\.size > 2/)
  assert.match(handoff, /key !== 'token' && key !== 'next'/)
})
