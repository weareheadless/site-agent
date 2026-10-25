import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = readFileSync(new URL('../src/lib/growth-data.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
const sandbox = {exports: {}, Intl, URLSearchParams};
vm.runInNewContext(compiled, sandbox);
const {growthDate, growthNumber, growthSeries, growthCSV} = sandbox.exports;

test('the owner research budget panel is addressable and restored from navigation state', () => {
  assert.equal(sandbox.exports.growthPanelFromSearch('?growth_panel=budget'), 'budget');
  assert.equal(sandbox.exports.growthPanelFromSearch('?growth_panel=unknown'), 'home');
});

test('the owner plan exposes upcoming work, not stale dates on disabled tasks', () => {
  const plan = sandbox.exports.growthPlan([
    {id: 'article', enabled: false, nextRun: '2026-10-04T09:00:00Z'},
    {id: 'weekly_report', enabled: true, nextRun: '2026-10-05T09:00:00Z'},
    {id: 'seo_insight', enabled: true, nextRun: '2026-10-04T10:00:00Z'},
  ]);
  assert.deepEqual(Array.from(plan.upcoming, row => row.id), ['seo_insight', 'weekly_report']);
  assert.equal(plan.unscheduled.length, 1);
  assert.equal(plan.nextRun, '2026-10-04T10:00:00Z');
  assert.equal(sandbox.exports.growthPlan([{id: 'article', enabled: false, nextRun: '2026-10-04T09:00:00Z'}]).nextRun, null);
});

test('Growth has one task list, not separate advice, schedule and approval windows', () => {
  const component = readFileSync(new URL('../src/components/HelloAdaGrowth.tsx', import.meta.url), 'utf8');
  assert.match(component, /\(growth\?\.sources \|\| \[\]\)\.map\(\(source\) =>/);
  assert.match(component, /source\.provider \|\| id/);
  assert.match(component, /source\.sourceRef/);
  assert.match(component, /source\.retrievedAt/);
  assert.match(component, /timeZone: budget\.timeZone/);
  assert.match(component, /helloada-research-budget-timezone/);
  const analytics = readFileSync(new URL('../src/components/GrowthAnalytics.tsx', import.meta.url), 'utf8');
  assert.match(analytics, /provider\.reason \? `growth\.\$\{provider\.reason\}`/);
  assert.doesNotMatch(component, /helloada-growth-work-strip|backgroundIdle/);
  assert.ok(component.includes('<GrowthTasks'));
  assert.ok(component.includes('tasks={growth?.tasks}'));
  assert.ok(component.includes('serviceModel={growth.serviceModel}'));
  assert.doesNotMatch(component, /reviewQueue\?\.map|reviewCandidates|helloada-growth-side|helloada-growth-advice/);
  const tasks = readFileSync(new URL('../src/components/GrowthTasks.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(tasks, /role="tablist" aria-label=\{t\("growth\.taskFocus"\)\}/);
  assert.match(tasks, /const visible = decisionRows/);
  assert.doesNotMatch(tasks, /rows: tasks\.filter\(row => row\.focus === "needs_you"\)/);
  assert.match(tasks, /const workRows = tasks\.filter/);
  assert.match(tasks, /workRows\.map\(task =>/);
  assert.doesNotMatch(tasks, /workSections|workGroups|const canGroup|Run analysis/);
  assert.match(tasks, /helloada-growth-task-list/);
  assert.doesNotMatch(tasks, /helloada-growth-sidebar/);
  assert.doesNotMatch(tasks, /helloada-growth-support-rail/);
  assert.match(tasks, /const recentWork = serviceModel\.recentResults/);
  assert.match(tasks, /serviceModel\.preparation\.length/);
  assert.match(tasks, /serviceModel\.areas\.map\(\(area\) => area\.nextAssessment\)/);
  assert.match(tasks, /task\.kind === "assessment" \? "growth\.assessmentNextRetry"/);
  assert.ok(tasks.includes("[taskSummary(task) || stateLabel(task), task.nextRun"));
  assert.match(tasks, /growth_task/);
  assert.match(tasks, /lastOpenedTask/);
  assert.match(tasks, /writeGrowthLocation\(task\.focus, task\.id, "pushState"\)/);
  assert.equal([...tasks.matchAll(/className="helloada-growth-task-list/g)].length, 1);
  assert.match(tasks, /renderDecisionGroups\(visible, "helloada-growth-task-list helloada-growth-related-groups"\)/);
  assert.match(tasks, /review_package_hash: task\?\.reviewPackageHash/);
  assert.match(tasks, /fetchHelloAda\("\/api\/helloada\/growth\/articles\/"/);
  assert.match(tasks, /if \(!articleKey \|\| !selectedTask\?\.draftId\)/);
  assert.match(tasks, /loaded\.reviewPackageHash === selectedTask\.reviewPackageHash/);
  assert.match(tasks, /renderLexicalNode\(loaded\.article\.body, "article"\)/);
  assert.doesNotMatch(tasks, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(tasks, /\?draft=/);
});

test('Activity is a read-only timeline with a frontend-only restore preparation action', () => {
  const activity = readFileSync(new URL('../src/components/HelloAdaHistory.tsx', import.meta.url), 'utf8');
  assert.match(activity, /history\/\$\{endpoint\}\/\$\{report\.id\}/);
  assert.match(activity, /report\.source === 'seo' \? 'seo-reports' : 'drafts'/);
  assert.match(activity, /execution_log/);
  assert.match(activity, /helloada-history-execution/);
  assert.match(activity, /history\.websiteVersions/);
  assert.match(activity, /versions\/\$\{version\.id\}\/restore/);
  assert.doesNotMatch(activity, /drafts\/\$\{[^}]+\}\/(approve|discard)/);
  assert.doesNotMatch(activity, /content\/history|content\/discard|worktree\/discard/);
  assert.doesNotMatch(activity, /Published content|Publish content/);
});

test('report dates are normalized and sorted without filling missing days', () => {
  assert.equal(growthDate('20261001'), '2026-10-01');
  assert.deepEqual(JSON.parse(JSON.stringify(growthSeries([{date: '20261003', visits: 0}, {date: '20261001', visits: 5}, {date: 'bad', visits: 12}, {date: '20261002'}], 'visits', 'date'))), [{date: '2026-10-01', value: 5}, {date: '2026-10-03', value: 0}]);
});
test('zero is a measurement; missing data is not zero; rates are percentages', () => {
  assert.equal(growthNumber(0, 'en', 'ctr'), '0%');
  assert.equal(growthNumber(.123, 'en', 'ctr'), '12.3%');
  assert.equal(growthNumber(undefined, 'en'), '—');
  assert.equal(growthNumber(null, 'fr'), '—');
});

test('an area is featured only when it has explicitly linked current decisions or active/blocked work', () => {
  const base = { decisionIds: [], activeWorkIds: [], blockedWorkIds: [], deferredWorkIds: [], pendingRunIds: [],
    evidenceState: 'recorded', lastAssessedAt: '2026-10-24T12:00:00Z' };
  const areas = [{ ...base, id: 'content' }, { ...base, id: 'search_visibility', pendingRunIds: [null] },
    { ...base, id: 'website_health', activeWorkIds: ['task-1'] }];
  assert.equal(sandbox.exports.growthFeaturedAreaId(areas), 'website_health');
  assert.equal(sandbox.exports.growthFeaturedAreaId(areas.slice(0, 2)), undefined);
});
test('CSV preserves raw measurements and quotes spreadsheet formulas safely', () => {
  assert.equal(growthCSV([{keyword: '=HYPERLINK("bad")', ctr: .2}], [['keyword', 'Keyword'], ['ctr', 'CTR']]), '"Keyword","CTR"\r\n"\'=HYPERLINK(""bad"")","0.2"');
  assert.equal(growthCSV([{delta: -12}], [['delta', 'Change']]), '"Change"\r\n"-12"');
});
