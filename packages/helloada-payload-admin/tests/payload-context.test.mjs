import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'

test('navigation consumes the public Payload client context singleton', () => {
  const source = readFileSync(new URL('../src/components/HelloAdaNav.tsx', import.meta.url), 'utf8')
  assert.match(source, /import \{ useConfig \} from '@payloadcms\/ui'/)
  assert.doesNotMatch(source, /@payloadcms\/ui\/providers\/Config/)
})
