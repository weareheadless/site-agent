import { appendFile } from 'node:fs/promises';
import { GitHub } from './github.mjs';
import { isManaged, validatePR } from './core.mjs';

// Pinned checker code, no PR checkout/execution and no Project secret in CI.
// Metadata changes invalidate the head's previous manager coordination result.
try {
  const api = new GitHub(process.env.GITHUB_TOKEN);
  const repository = process.env.TARGET_REPOSITORY;
  const number = Number(process.env.PR_NUMBER);
  const pr = await api.request(`repos/${repository}/pulls/${number}`);
  if (!isManaged(pr)) {
    console.log('Not a UI/OPS task PR; ordinary repository review still applies.');
  } else {
    await api.request(`repos/${repository}/statuses/${pr.head.sha}`, { state: 'pending', context: 'Agent coordination', description: 'Manager must recheck this task revision and current CI.' });
    const snapshot = await api.snapshot(repository, number);
    const plan = validatePR(snapshot);
    await api.ancestor(repository, plan.baseline, snapshot.pr.base.sha);
    await api.ancestor(repository, plan.baseline, snapshot.pr.head.sha);
    await api.unchanged(repository, number, snapshot.pr);
    console.log('Task format, active claim, declared scope and duplicate-PR checks passed. Manager review and code CI are still required.');
  }
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, 'Task-format feedback only. Manager coordination check, actual code tests and latest-diff review remain required.\n');
} catch (e) { console.error(e.message); process.exitCode = 1; }
