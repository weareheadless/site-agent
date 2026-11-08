import subprocess
from pathlib import Path


def test_remote_verifier_deadline_precedes_initialization_and_fails_closed():
    source = Path(__file__).resolve().parents[1] / 'src/site_agent/templates/next-payload/scripts/verify-payload-contract.ts'
    # Exercise the actual guard without a real timer, production bindings or a
    # duplicated implementation. The prefix ends before dynamic dependencies.
    script = r'''
const assert = require('node:assert/strict')
const fs = require('node:fs')
const source = fs.readFileSync(process.argv[1], 'utf8')
const prefix = source.split("const { getPayload }")[0].replace(/^import\s+[^\n]*\n/gm, '')
let callback, milliseconds, unref = false, exit, diagnostic
new Function('setTimeout', 'process', 'console', prefix)(
  (fn, ms) => {callback = fn; milliseconds = ms; return {unref() {unref = true}}},
  {env: {}, exit(code) {exit = code}}, {error(message) {diagnostic = message}},
)
assert.equal(milliseconds, 600000)
assert.equal(unref, true)
callback()
assert.equal(exit, 1)
assert.match(diagnostic, /Payload initialization/)
assert.match(diagnostic, /no promotion permitted/)
assert.match(source, /activeCheck = label/)
assert.ok(source.indexOf('clearTimeout(verificationDeadline)') > source.indexOf('await payload.destroy()'))
'''
    subprocess.run(['node', '-e', script, str(source)], check=True, capture_output=True, text=True)
