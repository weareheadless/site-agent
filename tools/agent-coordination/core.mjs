const sha = /^[a-f0-9]{40}$/;
const work = /^(UI|OPS)-\d{3}$/;
export const repositories = new Set(['weareheadless/crawlseo', 'weareheadless/site-agent', 'weareheadless/helloada', 'weareheadless/wix-site-bridge']);

export function demand(ok, message) {
  if (!ok) throw new Error(message);
}

function block(body, marker) {
  const matches = [...String(body ?? '').matchAll(new RegExp(`<!-- ${marker}\\s+([\\s\\S]*?)-->`, 'g'))];
  demand(matches.length === 1, `Provide exactly one ${marker} JSON block.`);
  try { return JSON.parse(matches[0][1]); } catch { throw new Error(`${marker} must contain valid JSON.`); }
}

export function normalizePlan(value) {
  demand(value && typeof value === 'object' && !Array.isArray(value), 'Plan must be an object.');
  const keys = ['workId', 'repository', 'issueNumber', 'agentRun', 'branch', 'baseline', 'contract', 'scope'];
  demand(Object.keys(value).every(k => keys.includes(k)), 'Plan has unknown fields.');
  demand(work.test(value.workId), 'Use a UI-000 or OPS-000 work ID.');
  demand(repositories.has(value.repository), 'Repository is outside this initiative.');
  demand(Number.isSafeInteger(value.issueNumber) && value.issueNumber > 0, 'issueNumber must be positive.');
  demand(typeof value.agentRun === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{2,119}$/.test(value.agentRun), 'Provide a stable agent/thread/run identifier.');
  demand(typeof value.branch === 'string' && /^codex\/[a-z0-9][a-z0-9._/-]+$/.test(value.branch) && !value.branch.includes('..'), 'Use a codex/ task branch.');
  demand(sha.test(value.baseline), 'Pin the full baseline commit SHA.');
  if (value.contract === null) {
    demand(['UI-001', 'UI-013', 'OPS-001'].includes(value.workId), 'Implementation work needs a pinned contract.');
  } else {
    demand(value.contract && repositories.has(value.contract.repository) && sha.test(value.contract.sha), 'contract requires an initiative repository and full commit SHA.');
    demand(Object.keys(value.contract).every(k => ['repository', 'sha'].includes(k)), 'Unknown contract field.');
  }
  demand(Array.isArray(value.scope) && value.scope.length > 0 && value.scope.length <= 30, 'Declare 1–30 exact paths or directory/** prefixes.');
  for (const p of value.scope) {
    demand(typeof p === 'string' && p.length <= 240 && !p.startsWith('/') && !/[\\\x00-\x1f]/.test(p), 'Scope paths must be repository-relative.');
    demand(!p.split('/').some(s => s === '.' || s === '..' || s === ''), 'Scope paths cannot traverse directories.');
    const plain = p.endsWith('/**') ? p.slice(0, -3) : p;
    demand(plain && !/[?*{}]/.test(plain), 'Only exact paths and trailing directory/** are supported; no repository-wide wildcard.');
  }
  return Object.fromEntries(keys.map(k => [k, k === 'scope' ? [...new Set(value[k])].sort() : k === 'contract' && value[k] ? { repository: value[k].repository, sha: value[k].sha } : value[k]]));
}

export function parseTask(body) { return normalizePlan(block(body, 'agent-task')); }

export function activeClaim(comments) {
  let active = null;
  for (const c of [...comments].sort((a, b) => a.id - b.id)) {
    if (!String(c.body).includes('<!-- agent-claim')) continue;
    const event = block(c.body, 'agent-claim');
    if (event.event === 'claim') {
      const plan = normalizePlan(event.plan);
      demand(!active || samePlan(active, plan), 'Multiple agents claimed this issue; reconcile the claims before continuing.');
      active = plan;
    } else if (event.event === 'release') {
      demand(typeof event.reason === 'string' && event.reason.trim().length >= 5, 'A release needs a reason.');
      demand(active && event.agentRun === active.agentRun, 'Release does not match the active agent run.');
      active = null;
    } else throw new Error('Unknown agent-claim event.');
  }
  return active;
}

export function samePlan(a, b) { return JSON.stringify(normalizePlan(a)) === JSON.stringify(normalizePlan(b)); }

export function isManaged(pr) {
  return /\[(?:UI|OPS)-\d{3}\]/.test(pr.title ?? '') || /^codex\/(?:ui|ops)-\d{3}(?:[-/]|$)/.test(pr.head?.ref ?? '') || String(pr.body).includes('<!-- agent-task');
}

export function allowed(file, scope) {
  if (typeof file !== 'string' || file.startsWith('/') || file.split('/').includes('..') || file.includes('\\')) return false;
  return scope.some(p => p.endsWith('/**') ? file.startsWith(p.slice(0, -2)) : file === p);
}

export function validatePR({ repository, pr, issue, comments, files, competing = [] }) {
  const plan = parseTask(pr.body);
  demand(plan.repository === repository, 'Task repository does not match this PR.');
  demand(pr.base.ref === 'main' && pr.head.repo?.full_name === repository, 'Use the managed repository task branch targeting main.');
  demand(pr.head.ref === plan.branch, 'PR branch differs from the recorded plan.');
  demand(issue.number === plan.issueNumber && issue.state === 'open' && !issue.pull_request, 'Link one open implementation issue, not a PR.');
  demand(issue.title.startsWith(`[${plan.workId}]`), 'Issue work ID differs from the PR task.');
  const claim = activeClaim(comments);
  demand(claim && samePlan(claim, plan), 'PR plan differs from the active issue claim. Release/reclaim explicitly after manager scope review.');
  demand(files.length === pr.changed_files, 'Incomplete changed-file inventory; retry instead of guessing scope.');
  const outside = files.flatMap(f => [f.filename, f.previous_filename].filter(Boolean)).filter(f => !allowed(f, plan.scope));
  demand(!outside.length, `Changes exceed declared scope: ${outside.slice(0, 8).join(', ')}`);
  for (const other of competing) {
    if (other.number === pr.number || !isManaged(other)) continue;
    let task;
    try { task = parseTask(other.body); } catch { continue; }
    demand(task.issueNumber !== plan.issueNumber || task.repository !== repository, `Another open PR (#${other.number}) uses this issue. Reconcile it first.`);
  }
  for (const heading of ['Plan', 'Validation', 'Handoff']) {
    const section = String(pr.body).match(new RegExp(`^## ${heading}\\s*\\n([\\s\\S]*?)(?=^## |$(?![\\s\\S]))`, 'm'))?.[1]?.trim();
    demand(section && section.length >= 15 && !/^TODO\b|^TBD\b|^Replace\b/i.test(section), `Complete the ${heading} section.`);
  }
  return plan;
}

export function validateReadiness(item, dependencies) {
  demand(item, 'Issue is not on the shared Project.');
  demand(item.readiness === 'Ready', `Task is ${item.readiness || 'unclassified'}; manager must explicitly select it first.`);
  demand(['Ready', 'In progress', 'In review'].includes(item.status), 'Task is not in an active work state.');
  demand(dependencies.every(d => d.state === 'CLOSED'), 'An implementation prerequisite is still open.');
}

export function ciState(checks, statuses, requireCode) {
  const latest = new Map();
  for (const c of checks) if (!latest.has(c.name) || latest.get(c.name).id < c.id) latest.set(c.name, c);
  const conclusions = new Set(['success', 'neutral', 'skipped']);
  if ([...latest.values()].some(c => c.status === 'completed' && !conclusions.has(c.conclusion))) return 'failure';
  const external = statuses.filter(s => s.context !== 'Agent coordination');
  if (external.some(s => s.state === 'failure' || s.state === 'error')) return 'failure';
  if ([...latest.values()].some(c => c.status !== 'completed') || external.some(s => s.state === 'pending')) return 'pending';
  if (requireCode && ![...latest.values()].some(c => c.name === 'Agent code checks' && c.status === 'completed' && c.conclusion === 'success')) return 'pending';
  return 'success';
}

export const needsCodeChecks = files => files.some(f => !f.filename.endsWith('.md'));
