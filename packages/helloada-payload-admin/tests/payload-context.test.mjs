import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'

test('navigation consumes the public Payload client context singleton', () => {
  const source = readFileSync(new URL('../src/components/HelloAdaNav.tsx', import.meta.url), 'utf8')
  assert.match(source, /import \{ useConfig \} from '@payloadcms\/ui'/)
  assert.doesNotMatch(source, /@payloadcms\/ui\/providers\/Config/)
})

test('server configuration has a dedicated entry point without the client barrel', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
  assert.equal(pkg.exports['./config'], './src/config/site.ts')
  const source = readFileSync(new URL('../src/config/site.ts', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /@payloadcms\/ui|\.\/components/)
})
