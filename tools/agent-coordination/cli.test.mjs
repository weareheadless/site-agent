import test from 'node:test';
import assert from 'node:assert/strict';
import { run } from './cli.mjs';

function fixture() {
  const plan = { workId: 'UI-001', repository: 'weareheadless/crawlseo', issueNumber: 15, agentRun: 'thread-a', branch: 'codex/ui-001-contract', baseline: 'a'.repeat(40), contract: null, scope: ['contracts/**'] };
  const issueURL = 'https://github.com/weareheadless/crawlseo/issues/15';
  const pr = { number: 40, state: 'open', draft: true, html_url: 'https://github.com/weareheadless/crawlseo/pull/40', head: { ref: plan.branch, sha: 'b'.repeat(40), repo: { full_name: plan.repository } }, base: { ref: 'main', sha: plan.baseline }, changed_files: 1, body: `<!-- agent-task\n${JSON.stringify(plan)}\n-->\n## Plan\nReuse the existing contract for this bounded change.\n## Validation\nCurrent contract fixtures and application tests pass.\n## Handoff\nManager should review the schema and its consumer compatibility.\n` };
  const writes = [];
  const api = {
    snapshot: async () => ({ repository: plan.repository, pr, issue: { number: 15, title: '[UI-001] Contract', state: 'open' }, comments: [{ id: 1, body: `<!-- agent-claim\n${JSON.stringify({ event: 'claim', plan })}\n-->` }], files: [{ filename: 'contracts/business.json' }], competing: [] }),
    ancestor: async () => {}, unchanged: async () => pr,
    request: async (path, body) => { if (body) writes.push({ path, body }); return body ? {} : { statuses: [] }; },
    pages: async () => [{ id: 1, name: 'Agent code checks', status: 'completed', conclusion: 'success' }],
    graphql: async (query, input) => {
      if (query.startsWith('mutation')) { writes.push({ query, input }); return {}; }
      return { repository: { issue: { blockedBy: { nodes: [], pageInfo: { hasNextPage: false } } } }, node: { items: { nodes: [{ id: 'item', content: { url: issueURL }, fieldValues: { nodes: [{ name: 'Ready', field: { name: 'Readiness' } }, { name: 'Ready', field: { name: 'Status' } }] } }], pageInfo: { hasNextPage: false } }, fields: { nodes: [{ id: 'status', name: 'Status', options: [{ id: 'progress', name: 'In progress' }] }] } } };
    },
  };
  return { api, writes };
}
const args = ['check', '--repository', 'weareheadless/crawlseo', '--pr', '40'];

test('check is read-only unless explicitly publishing or syncing', async () => {
  const { api, writes } = fixture();
  assert.equal((await run(args, api)).state, 'success');
  assert.equal(writes.length, 0);
});
test('dry-run prevents status and board writes even with publish and sync flags', async () => {
  const { api, writes } = fixture();
  assert.equal((await run([...args, '--publish', '--sync', '--dry-run'], api)).state, 'success');
  assert.equal(writes.length, 0);
});
test('explicit manager handoff publishes current result and syncs only the active state', async () => {
  const { api, writes } = fixture();
  const result = await run([...args, '--publish', '--sync'], api);
  assert.equal(result.reviewRequired, true);
  assert.equal(writes.length, 2);
  assert.equal(writes[1].body.context, 'Agent coordination');
  assert.equal(writes[1].body.state, 'success');
});
test('misspelled or incomplete options fail before any mutation', async () => {
  const { api, writes } = fixture();
  await assert.rejects(run([...args, '--dryrun'], api), /Unknown option/);
  await assert.rejects(run(['claim', '--plan'], api), /Missing value/);
  assert.equal(writes.length, 0);
});
