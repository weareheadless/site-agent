import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { GitHub, projectItem, setStatus } from './github.mjs';
import { activeClaim, ciState, demand, needsCodeChecks, normalizePlan, parseTask, repositories, samePlan, validatePR, validateReadiness } from './core.mjs';

function options(args) {
  const result = {};
  for (let i = 0; i < args.length; i++) {
    demand(args[i].startsWith('--'), 'Expected --option value.');
    const key = args[i].slice(2);
    result[key] = ['publish', 'sync', 'dry-run'].includes(key) ? true : args[++i];
  }
  return result;
}

async function pin(api, plan, head = null) {
  await api.ancestor(plan.repository, plan.baseline, 'main');
  if (head) await api.ancestor(plan.repository, plan.baseline, head);
  if (plan.contract) await api.ancestor(plan.contract.repository, plan.contract.sha, 'main');
}

export async function run(args, api) {
  const [command, ...rest] = args;
  const opt = options(rest);
  if (command === 'claim') {
    demand(opt.plan, 'claim --plan plan.json [--dry-run]');
    const plan = normalizePlan(JSON.parse(await readFile(opt.plan, 'utf8')));
    const issue = await api.request(`repos/${plan.repository}/issues/${plan.issueNumber}`);
    demand(issue.state === 'open' && !issue.pull_request && issue.title.startsWith(`[${plan.workId}]`), 'Select the matching open task issue.');
    const context = await projectItem(api, plan.repository, plan.issueNumber);
    validateReadiness(context.item, context.dependencies);
    await pin(api, plan);
    const comments = await api.pages(`repos/${plan.repository}/issues/${plan.issueNumber}/comments`);
    const current = activeClaim(comments);
    demand(!current || samePlan(current, plan), 'Another run owns this task. Reconcile and explicitly release it first.');
    if (!opt['dry-run']) {
      // Use one manager for claims. GitHub comments are a log, not an atomic lock.
      const recheck = activeClaim(await api.pages(`repos/${plan.repository}/issues/${plan.issueNumber}/comments`));
      demand(!recheck || samePlan(recheck, plan), 'Claim changed; ask the manager to reconcile.');
      if (!recheck) await api.request(`repos/${plan.repository}/issues/${plan.issueNumber}/comments`, { body: `Agent pickup: ${plan.agentRun}. Scope is declared here; manager review remains required.\n\n<!-- agent-claim\n${JSON.stringify({ event: 'claim', plan }, null, 2)}\n-->` });
      await setStatus(api, context, 'In progress');
    }
    return { result: opt['dry-run'] ? 'claim-ready' : 'claimed', workId: plan.workId, agentRun: plan.agentRun };
  }
  demand(repositories.has(opt.repository) && Number.isSafeInteger(Number(opt.pr)) && Number(opt.pr) > 0, 'Use --repository owner/repo --pr number.');
  const repository = opt.repository;
  const number = Number(opt.pr);
  if (command === 'sync') {
    const pr = await api.request(`repos/${repository}/pulls/${number}`);
    const task = parseTask(pr.body);
    demand(task.repository === repository, 'PR task belongs to another repository.');
    const context = await projectItem(api, repository, task.issueNumber);
    const status = pr.merged_at ? 'Merged' : pr.state === 'closed' ? 'Specified' : pr.draft ? 'In progress' : 'In review';
    if (!opt['dry-run']) await setStatus(api, context, status);
    return { workId: task.workId, status, note: 'Never marks Verified or promotes Deferred work.' };
  }
  demand(command === 'check', 'Commands: claim, check, sync.');
  const snapshot = await api.snapshot(repository, number);
  let state = 'failure';
  let reason;
  let plan;
  let context;
  try {
    demand(snapshot.pr.state === 'open', 'Check the open PR before merge; use sync for terminal state.');
    plan = validatePR(snapshot);
    context = await projectItem(api, repository, plan.issueNumber);
    validateReadiness(context.item, context.dependencies);
    await pin(api, plan, snapshot.pr.head.sha);
    const [checks, combined] = await Promise.all([
      api.pages(`repos/${repository}/commits/${snapshot.pr.head.sha}/check-runs`, 'check_runs'),
      api.request(`repos/${repository}/commits/${snapshot.pr.head.sha}/status`),
    ]);
    state = ciState(checks, combined.statuses, needsCodeChecks(snapshot.files));
    reason = state === 'success' ? 'Task, dependencies, scope, pins and current CI passed; review still required.' : state === 'pending' ? 'Waiting for current-head code checks.' : 'A current-head check failed.';
    await api.unchanged(repository, number, snapshot.pr);
    if (opt.sync && state === 'success') await setStatus(api, context, snapshot.pr.draft ? 'In progress' : 'In review');
  } catch (e) { reason = e.message; }
  if (opt.publish && !opt['dry-run']) {
    await api.unchanged(repository, number, snapshot.pr);
    await api.request(`repos/${repository}/statuses/${snapshot.pr.head.sha}`, { state, context: 'Agent coordination', description: reason.slice(0, 140), target_url: snapshot.pr.html_url });
  }
  return { state, reason, head: snapshot.pr.head.sha, reviewRequired: true };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const result = await run(process.argv.slice(2), new GitHub(process.env.GH_TOKEN));
    console.log(JSON.stringify(result, null, 2));
    if (result.state && result.state !== 'success') process.exitCode = result.state === 'pending' ? 2 : 1;
  } catch (e) { console.error(e.message); process.exitCode = 1; }
}
