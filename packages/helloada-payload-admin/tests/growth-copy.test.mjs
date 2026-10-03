import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

// Execute the real import graph: source-text checks miss module-load crashes.
function load(url) {
  const source = readFileSync(url, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {}, require: name => load(new URL(`${name}.ts`, url)) }
  vm.runInNewContext(compiled, sandbox, { filename: url.pathname })
  return sandbox.exports
}

test('Growth translations load and contain the unified plan for every supported locale', () => {
  const { growthCopy } = load(new URL('../src/lib/growth-copy.ts', import.meta.url))
  assert.deepEqual(Object.keys(growthCopy).sort(), ['en', 'es', 'fr'])
  for (const language of ['en', 'es', 'fr']) {
    for (const key of ['growth.overview', 'growth.taskTitle', 'growth.task_needs_you', 'growth.growth_weekly']) {
      assert.equal(typeof growthCopy[language][key], 'string', `${language}: ${key}`)
      assert.ok(growthCopy[language][key].length > 0)
    }
  }
})
