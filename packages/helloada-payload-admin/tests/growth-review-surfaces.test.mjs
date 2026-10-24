import assert from 'node:assert/strict'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { compile } from 'sass'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const css = compile(path.join(packageRoot, 'src/styles/admin.scss'), { quietDeps: true }).css

function declarationBlocks(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const matches = [...css.matchAll(new RegExp(`${escaped}(?:\\s*,[^{}]*)?\\s*\\{([^}]*)\\}`, 'g'))]
  assert.ok(matches.length, `expected compiled admin CSS rule for ${selector}`)
  return matches.map((match) => match[1])
}

const declarationBlock = (selector) => declarationBlocks(selector).at(-1)

test('Growth reading panels override Payload chat surfaces without recoloring actions or status panels', () => {
  const globalChat = css.indexOf('.helloada-chat-message-body {')
  const growthChat = css.lastIndexOf('.helloada-growth-task-core .helloada-chat-message-body {')
  assert.ok(globalChat >= 0 && growthChat > globalChat, 'task-specific rule must follow Payload global chat styles')

  const chat = declarationBlock('.helloada-growth-task-core .helloada-chat-message-body')
  assert.match(chat, /background:\s*#fff;/)
  assert.match(chat, /color:\s*#263548;/)
  assert.match(chat, /border-color:\s*#dbe2e9;/)
  assert.match(declarationBlock('.helloada-growth-task-core .helloada-chat-message-body p'), /color:\s*#263548;/)
  assert.match(declarationBlock('.helloada-growth-task-core .helloada-chat-message-body a'), /color:\s*#a83b27;/)

  assert.ok(declarationBlocks('.helloada-growth-task-core .helloada-growth-change-review__target')
    .some((rule) => /background:\s*#fff;/.test(rule)))
  assert.match(declarationBlock('.helloada-growth-task-core .helloada-growth-task-analysis-note'), /background:\s*#fff;/)
  assert.match(declarationBlock('.helloada-growth-task-core .helloada-growth-task-analysis-note p'), /color:\s*#263548;/)
  assert.ok(declarationBlocks('.helloada-growth-task-core .helloada-growth-owner-evidence')
    .some((rule) => /background:\s*#fff;/.test(rule)))

  assert.match(declarationBlock('.helloada-growth-task-block'), /background:\s*#fff8ee;/)
  assert.match(declarationBlock('.helloada-growth-task-block'), /color:\s*#744a1c;/)
  assert.doesNotMatch(css, /\.helloada-growth-task-core\s+\*/)
})
