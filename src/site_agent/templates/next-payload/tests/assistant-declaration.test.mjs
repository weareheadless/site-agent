import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { readAssistantDeclaration } from '../scripts/assistant-declaration.mjs'

const declaration = (value) => {
  const directory = mkdtempSync(path.join(tmpdir(), 'assistant-declaration-'))
  const file = path.join(directory, 'assistant.json')
  writeFileSync(file, typeof value === 'string' ? value : JSON.stringify(value))
  return file
}

test('a site that never authored a declaration ships no assistant', () => {
  assert.deepEqual(readAssistantDeclaration('/nonexistent/src/site/assistant.json'), { enabled: false })
})

test('a complete declaration is carried into the generated contract', () => {
  const file = declaration({ purpose: 'Answer visitor questions.', sources: 'site', model: 'provider/model' })

  assert.deepEqual(readAssistantDeclaration(file), {
    enabled: true,
    purpose: 'Answer visitor questions.',
    sources: 'site',
    model: 'provider/model',
  })
})

test('an incomplete declaration fails the build instead of disabling quietly', () => {
  for (const value of [
    { sources: 'site', model: 'provider/model' },
    { purpose: 'Answer visitors.', model: '' },
    { purpose: 'Answer visitors.' },
    { purpose: 'Answer visitors.', model: 'provider/model', sources: 'everything' },
    '{ not json',
  ]) {
    assert.throws(() => readAssistantDeclaration(declaration(value)), undefined, JSON.stringify(value))
  }
})
