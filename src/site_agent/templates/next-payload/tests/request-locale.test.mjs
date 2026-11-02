import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/lib/request-locale.ts', import.meta.url), 'utf8')
const js = ts.transpile(source, { module: ts.ModuleKind.CommonJS })
const module = { exports: {} }
new Function('module', 'exports', 'require', js)(module, module.exports, (name) => name === 'next/headers' ? {} : { helloAdaSite: { locales: ['en', 'fr'], defaultLocale: 'en' } })
const { resolveRequestLocale } = module.exports

test('explicit locale, cookie preference, configured default and invalid inputs', () => {
  assert.deepEqual(resolveRequestLocale(['fr'], 'en', ['en', 'fr'], 'en'), { ok: true, locale: 'fr' })
  assert.deepEqual(resolveRequestLocale([], 'fr', ['en', 'fr'], 'en'), { ok: true, locale: 'fr' })
  assert.deepEqual(resolveRequestLocale([], undefined, ['en', 'fr'], 'en'), { ok: true, locale: 'en' })
  assert.deepEqual(resolveRequestLocale(['xx'], undefined, ['en', 'fr'], 'en'), { ok: false })
  assert.deepEqual(resolveRequestLocale([], 'xx', ['en', 'fr'], 'en'), { ok: false })
  assert.deepEqual(resolveRequestLocale(['en', 'fr'], undefined, ['en', 'fr'], 'en'), { ok: false })
})
