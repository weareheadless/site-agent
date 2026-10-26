import test from 'node:test';
import assert from 'node:assert/strict';
import { activeClaim, allowed, ciState, normalizePlan, parseTask, samePlan, validatePR, validateReadiness } from './core.mjs';
import { GitHub } from './github.mjs';

const plan = (extra = {}) => ({ workId: 'UI-001', repository: 'weareheadless/crawlseo', issueNumber: 15, agentRun: 'thread-a', branch: 'codex/ui-001-contract', baseline: 'a'.repeat(40), contract: null, scope: ['contracts/**', 'tests/contracts.test.ts'], ...extra });
const receipt = (p, id = 1) => ({ id, body: `<!-- agent-claim\n${JSON.stringify({ event: 'claim', plan: p })}\n-->` });
const body = p => `<!-- agent-task\n${JSON.stringify(p)}\n-->\n## Plan\nExtend the existing contract and preserve v1 compatibility.\n## Validation\nFocused contract fixtures pass; integration proof remains pending.\n## Handoff\nManager should review the changed schema and its consumer fixture.\n`;
function snapshot() {
  const p = plan();
  return { repository: p.repository, pr: { number: 40, body: body(p), head: { ref: p.branch, repo: { full_name: p.repository } }, base: { ref: 'main' }, changed_files: 1 }, issue: { number: 15, title: '[UI-001] Contract', state: 'open' }, comments: [receipt(p)], files: [{ filename: 'contracts/profile.json' }], competing: [] };
}

test('one claim and matching bounded PR are accepted', () => assert.equal(validatePR(snapshot()).workId, 'UI-001'));
test('duplicate or malformed task blocks fail instead of choosing one', () => {
  assert.throws(() => parseTask(body(plan()) + body(plan())), /exactly one/);
  assert.throws(() => parseTask('<!-- agent-task {oops} -->'), /valid JSON/);
});
test('scope matches directories, not sibling prefixes or traversal', () => {
  assert.equal(allowed('contracts/schema.json', ['contracts/**']), true);
  assert.equal(allowed('contracts-other/schema.json', ['contracts/**']), false);
  assert.equal(allowed('contracts/../secrets.json', ['contracts/**']), false);
  for (const scope of [['**'], ['../src/**'], ['/src/**'], ['src/*'], ['src//a'], ['src\\x']]) assert.throws(() => normalizePlan(plan({ scope })));
});
test('renaming an out-of-scope file into scope is rejected', () => {
  const s = snapshot(); s.files[0].previous_filename = 'lib/protected.ts';
  assert.throws(() => validatePR(s), /exceed declared scope/);
});
test('wrong issue, repository and branch are rejected', () => {
  for (const change of [s => { s.issue.number = 16; }, s => { s.repository = 'weareheadless/site-agent'; }, s => { s.pr.head.ref = 'codex/something-else'; }, s => { s.issue.pull_request = {}; }]) {
    const s = snapshot(); change(s); assert.throws(() => validatePR(s));
  }
});
test('implementation requires an immutable contract pin', () => {
  assert.throws(() => normalizePlan(plan({ workId: 'UI-002' })), /pinned contract/);
  assert.throws(() => normalizePlan(plan({ workId: 'UI-002', contract: { repository: plan().repository, sha: 'main' } })), /full commit/);
});
test('contract field order and scope order do not fork a claim', () => {
  const p = plan({ contract: { repository: 'weareheadless/crawlseo', sha: 'b'.repeat(40) } });
  assert.equal(samePlan(p, { ...p, contract: { sha: 'b'.repeat(40), repository: 'weareheadless/crawlseo' }, scope: [...p.scope].reverse() }), true);
});
test('claim retries are idempotent; another run requires explicit release', () => {
  const p = plan();
  assert.equal(activeClaim([receipt(p), receipt(p, 2)]).agentRun, p.agentRun);
  assert.throws(() => activeClaim([receipt(p), receipt(plan({ agentRun: 'thread-b' }), 2)]), /Multiple agents/);
  const release = { id: 2, body: '<!-- agent-claim {"event":"release","agentRun":"thread-a","reason":"Manager approved handoff"} -->' };
  assert.equal(activeClaim([receipt(p), release, receipt(plan({ agentRun: 'thread-b' }), 3)]).agentRun, 'thread-b');
});
test('a widened PR scope without the same issue claim fails', () => {
  const s = snapshot(); s.pr.body = body(plan({ scope: ['contracts/**', 'lib/**'] }));
  assert.throws(() => validatePR(s), /differs from the active/);
});
test('two open PRs for one issue cannot independently pass', () => {
  const s = snapshot(); s.competing = [{ ...s.pr, number: 41, title: '[UI-001] Other' }];
  assert.throws(() => validatePR(s), /Another open PR/);
});
test('incomplete file pagination and unfilled handoffs fail', () => {
  const s = snapshot(); s.pr.changed_files = 2; assert.throws(() => validatePR(s), /Incomplete/);
  const t = snapshot(); t.pr.body = t.pr.body.replace('Manager should review the changed schema and its consumer fixture.', 'TODO provide details later');
  assert.throws(() => validatePR(t), /Handoff/);
});
test('Deferred is not eligible even after dependencies close', () => {
  assert.throws(() => validateReadiness({ readiness: 'Deferred', status: 'Specified' }, [{ state: 'CLOSED' }]), /Deferred/);
  assert.throws(() => validateReadiness({ readiness: 'Ready', status: 'Ready' }, [{ state: 'OPEN' }]), /prerequisite/);
  assert.doesNotThrow(() => validateReadiness({ readiness: 'Ready', status: 'In progress' }, [{ state: 'CLOSED' }]));
});
test('code needs an actual passing named check, not a checked checkbox', () => {
  assert.equal(ciState([], [], true), 'pending');
  assert.equal(ciState([{ id: 1, name: 'Agent code checks', status: 'completed', conclusion: 'skipped' }], [], true), 'pending');
  assert.equal(ciState([{ id: 1, name: 'Agent code checks', status: 'completed', conclusion: 'success' }], [], true), 'success');
});
test('failed or in-progress CI is not treated as completion', () => {
  const pass = { id: 1, name: 'Agent code checks', status: 'completed', conclusion: 'success' };
  assert.equal(ciState([pass, { id: 2, name: 'other', status: 'completed', conclusion: 'failure' }], [], true), 'failure');
  assert.equal(ciState([pass, { id: 2, name: 'other', status: 'in_progress' }], [], true), 'pending');
  assert.equal(ciState([pass], [{ context: 'Agent coordination', state: 'pending' }], true), 'success');
});
test('a successful rerun supersedes the earlier failed attempt of that job', () => {
  assert.equal(ciState([{ id: 2, name: 'Agent code checks', status: 'completed', conclusion: 'success' }, { id: 1, name: 'Agent code checks', status: 'completed', conclusion: 'failure' }], [], true), 'success');
});
test('head or PR-body movement invalidates the snapshot', async () => {
  const api = new GitHub('test');
  const expected = { head: { sha: 'a' }, body: 'old', base: { sha: 'b' }, state: 'open' };
  api.request = async () => ({ ...expected, body: 'new' });
  await assert.rejects(api.unchanged('weareheadless/crawlseo', 1, expected), /changed during/);
});
test('pagination refuses a truncated inventory', async () => {
  const api = new GitHub('test'); api.request = async () => Array.from({ length: 100 }, () => ({}));
  await assert.rejects(api.pages('test'), /incomplete/);
});
