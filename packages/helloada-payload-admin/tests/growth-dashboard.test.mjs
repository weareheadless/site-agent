import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const root = new URL('../', import.meta.url);
const source = (path) => readFileSync(new URL(path, root), 'utf8');
const compiled = ts.transpileModule(source('src/lib/growth-data.ts'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const sandbox = { exports: {}, Intl, Date };
vm.runInNewContext(compiled, sandbox);
function load(url) {
  const moduleSource = readFileSync(url, 'utf8');
  const moduleCompiled = ts.transpileModule(moduleSource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const moduleSandbox = { exports: {}, require: (name) => load(new URL(`${name}.ts`, url)) };
  vm.runInNewContext(moduleCompiled, moduleSandbox, { filename: url.pathname });
  return moduleSandbox.exports;
}

const areaIds = ['content', 'search_visibility', 'website_health', 'audience_competitors', 'speed_experience'];
const work = [
  { id: 'decision-1', draftId: 41, ownerActionId: 12, approvalId: 12, reviewPackageHash: 'hash-1',
    primaryArea: 'search_visibility', secondaryAreas: ['website_health'], title: 'Review a verified search change',
    why: 'Search evidence supports review.', scope: '/services', state: 'awaiting_owner', executionState: 'ready',
    actor: 'owner', canApprove: true, evidenceRefs: ['gsc:snapshot-1'], updatedAt: '2026-10-22T10:00:00Z',
    nextRun: null, executionIssue: false, dispositionReason: null, reassessWhen: null },
  { id: 'initiative:88', primaryArea: null, secondaryAreas: [], title: 'Older unclassified work',
    why: 'Historical work has no explicit area.', scope: null, state: 'deferred', executionState: 'deferred',
    actor: 'ada', canApprove: false, evidenceRefs: [], updatedAt: '2026-10-01T10:00:00Z', nextRun: null,
    executionIssue: false, dispositionReason: 'deferred', reassessWhen: 'new evidence' },
  { id: 'preparing-1', primaryArea: 'content', secondaryAreas: ['speed_experience'], title: 'Prepare a content finding',
    why: 'A recorded finding is waiting for capacity.', scope: null, state: 'preparing', executionState: 'pending',
    actor: 'ada', canApprove: false, evidenceRefs: ['inventory:home'], updatedAt: null, nextRun: null,
    executionIssue: false, dispositionReason: null, reassessWhen: null },
];

const areas = areaIds.map((id) => ({
  id,
  state: id === 'search_visibility' || id === 'website_health' ? 'needs_decision' : id === 'content' || id === 'speed_experience' ? 'preparing' : 'assessed',
  workIds: work.filter((row) => row.primaryArea === id || row.secondaryAreas.includes(id)).map((row) => row.id),
  capability: { scope: `${id}_scope`, sourceIds: id === 'search_visibility' ? ['gsc'] : [], automatedMeasurement: 'configured_sources' },
  evidenceState: id === 'audience_competitors' ? 'recorded' : 'unavailable',
  decisionIds: ['search_visibility', 'website_health'].includes(id) ? ['decision-1'] : [],
  blockedWorkIds: [], activeWorkIds: id === 'content' || id === 'speed_experience' ? ['preparing-1'] : [], deferredWorkIds: [],
  pendingRunIds: id === 'content' || id === 'speed_experience' ? [72] : [],
  summary: id === 'audience_competitors' ? 'No material change in the recorded comparison.' : null,
  evidenceRefs: id === 'audience_competitors' ? ['ga4:period-1'] : [],
  unresolvedEvidenceRefs: [], limitations: id === 'audience_competitors' ? ['Competitor coverage is limited.'] : ['No explicit area assessment has been recorded.'],
  lastAssessedAt: id === 'audience_competitors' ? '2026-10-20T12:00:00Z' : null,
  nextAssessment: { activityId: 'growth_weekly', at: '2026-10-28T08:00:00Z', scope: 'shared_growth_review' },
}));

const serviceModel = {
  contractVersion: 'growth-service-v1', websitePresent: true, areas, work,
  decisionIds: ['decision-1'],
  recentResults: [{ id: 'result-1', title: 'Verified page revision', state: 'verified', publishedRevision: 19,
    releaseId: 'rel-19', sourceSha: 'a'.repeat(40), implementedAt: '2026-10-18T12:00:00Z', impactState: 'awaiting_data',
    impact: [], nextMeasurement: { horizonDays: 30, at: '2026-11-17T12:00:00Z', state: 'scheduled' } },
  { id: 'result-2', title: 'Verified observed revision', state: 'verified', publishedRevision: 'rev-20',
    releaseId: null, sourceSha: null, implementedAt: null, impactState: 'observed',
    impact: [{ id: 33, horizonDays: 30, measuredAt: '2026-10-22T12:00:00Z', assessment: 'mixed', confidence: 'medium',
      metric: 'sessions', baseline: 100, observed: 106, notes: 'Observed values; no causal attribution.', causalAttribution: false }],
    nextMeasurement: null }],
  preparation: [{ runId: 72, state: 'waiting_for_capacity', areaIds: ['content', 'speed_experience'], findingCount: 2,
    eligibleAt: '2026-10-24T08:00:00Z', executor: 'growth_pending', nextReconciliationAt: '2026-10-23T08:00:00Z' }],
  unassignedWorkIds: ['initiative:88'], overdueActivityIds: [],
  sources: [{ id: 'gsc', state: 'ready', reason: null, observedAt: '2026-10-22T10:00:00Z', sourceRef: 'gsc-property', freshnessHours: 168 }],
};

test('accepts the growth-service-v1 projection shape and all five canonical areas', () => {
  assert.equal(sandbox.exports.isGrowthServiceModel(serviceModel), true);
  assert.deepEqual(Array.from(serviceModel.areas, (area) => area.id), areaIds);
  assert.equal(serviceModel.areas.length, 5);
});

test('uses primary/secondary area relations and keeps one canonical decision across areas', () => {
  assert.deepEqual(serviceModel.areas.find((area) => area.id === 'search_visibility').workIds, ['decision-1']);
  assert.deepEqual(serviceModel.areas.find((area) => area.id === 'website_health').workIds, ['decision-1']);
  assert.deepEqual(serviceModel.areas.find((area) => area.id === 'search_visibility').decisionIds, ['decision-1']);
  assert.deepEqual(serviceModel.areas.find((area) => area.id === 'website_health').decisionIds, ['decision-1']);
  assert.deepEqual(serviceModel.decisionIds, ['decision-1']);
});

test('preserves owner queue decision priority independently of service model order', () => {
  const rawDecisionIds = ['initiative:4', 'initiative:7', 'initiative:8'];
  const ownerQueue = { featuredDecisionId: 'initiative:8', additionalDecisionIds: ['initiative:7', 'initiative:4'], decisionCount: 3 };
  assert.deepEqual(Array.from(sandbox.exports.growthDecisionOrder(ownerQueue, rawDecisionIds)), [
    'initiative:8', 'initiative:7', 'initiative:4',
  ]);
  assert.equal(sandbox.exports.growthDecisionOrder({ ...ownerQueue, additionalDecisionIds: ['initiative:7', 'initiative:7'] }, rawDecisionIds), null);
  assert.equal(sandbox.exports.growthDecisionOrder({ ...ownerQueue, decisionCount: 2 }, rawDecisionIds), null);
  assert.equal(sandbox.exports.growthDecisionOrder({ ...ownerQueue, additionalDecisionIds: ['initiative:7', 'initiative:9'] }, rawDecisionIds), null);
  const parent = source('src/components/HelloAdaGrowth.tsx');
  const component = source('src/components/GrowthTasks.tsx');
  assert.match(parent, /growthDecisionOrder\(body\.ownerQueue, body\.serviceModel\.decisionIds\)/);
  assert.match(parent, /Owner queue and Growth service decisions are incompatible/);
  assert.match(component, /decisionOrder\.map\(agendaTask\)/);
  assert.match(component, /area\.decisionIds/);
});

test('renders owner review through a sparse field comparison instead of full raw objects', () => {
  const before = { title: 'Same title', description: 'Old SEO description' };
  const after = { title: 'Same title', description: 'New SEO description' };
  assert.deepEqual(Object.keys(after).filter(key => before[key] !== after[key]), ['description']);
  const component = source('src/components/GrowthTasks.tsx');
  assert.match(component, /<GrowthChangeReview review=\{selectedTask\.review\}/);
  assert.doesNotMatch(component, /Object\.entries\(selectedTask\.review\.changes\)/);
});

test('overview, recommendations and activity stay distinct while related fields keep separate review actions', () => {
  const component = source('src/components/GrowthTasks.tsx');
  const shell = source('src/components/HelloAdaGrowth.tsx');
  assert.match(shell, /panel === "home"\} onClick=\{\(\) => navigatePanel\("home"\)\}/);
  assert.match(shell, /panel === "decisions"\} onClick=\{\(\) => navigatePanel\("decisions"\)\}/);
  assert.match(shell, /panel === "work"\} onClick=\{\(\) => navigatePanel\("work"\)\}/);
  assert.match(component, /groupReviewDecisions\(rows\)/);
  assert.match(component, /getReviewTarget\(task\.review\)/);
  assert.match(component, /featuredRelatedGroup[\s\S]*groupReviewDecisions\(decisionRows\)/);
  assert.match(component, /featuredRelatedGroup\.tasks\.map\(task =>/);
  assert.match(component, /featuredRelatedIds\.has\(task\.id\)/);
  assert.match(component, /clarityRelatedDecisionHeading/);
  assert.match(component, /data-growth-task-id=\{task\.id\}[\s\S]*aria-label=\{`\$\{title\(task\)\}\.[\s\S]*onClick=\{\(\) => openTask\(task\)\}/);
  assert.match(component, /data-growth-task-id=\{task\.id\} onClick=\{\(\) => openTask\(task\)\}/);
  assert.match(component, /key=\{task\.id\}/);
  assert.match(component, /growth\.clarityRelatedFields/);
  assert.match(component, /conciseText\(selectedTask\.scope \|\| title\(selectedTask\)\)/);
  assert.match(component, /growth\.clarityScopeDetails/);
  assert.match(component, /<summary>\{t\("growth\.clarityScopeDetails"\)\}<\/summary><p>\{selectedTask\.scope\}<\/p>/);
});

test('keeps unknown historical work explicitly unassigned and displayable without keyword inference', () => {
  const historical = serviceModel.work.find((row) => row.id === 'initiative:88');
  assert.equal(historical.primaryArea, null);
  assert.deepEqual(historical.secondaryAreas, []);
  assert.deepEqual(serviceModel.unassignedWorkIds, ['initiative:88']);
  const component = source('src/components/GrowthTasks.tsx');
  assert.match(component, /serviceModel\.unassignedWorkIds\.map/);
  assert.doesNotMatch(component, /task\.area|growthAreaTasks/);
});

test('rejects absent or incompatible projection instead of falling back to tasks', () => {
  assert.equal(sandbox.exports.isGrowthServiceModel(undefined), false);
  assert.equal(sandbox.exports.isGrowthServiceModel({ ...serviceModel, contractVersion: 'growth-service-v2' }), false);
  assert.equal(sandbox.exports.isGrowthServiceModel({ ...serviceModel, areas: areas.slice(0, 4) }), false);
  assert.equal(sandbox.exports.isGrowthServiceModel({ ...serviceModel, decisionIds: ['missing'] }), false);
  const parent = source('src/components/HelloAdaGrowth.tsx');
  assert.match(parent, /!isGrowthServiceModel\(body\.serviceModel\)/);
  assert.match(parent, /Growth service decision has no canonical review task/);
});

test('renders preparation, next assessment, verified results and area evidence from the service projection', () => {
  const component = source('src/components/GrowthTasks.tsx');
  for (const field of ['serviceModel.preparation', 'area.workIds', 'area.decisionIds', 'area.state', 'area.evidenceState',
    'area.summary', 'area.limitations', 'area.lastAssessedAt', 'area.nextAssessment', 'serviceModel.recentResults',
    'serviceModel.unassignedWorkIds']) assert.ok(component.includes(field), `missing binding: ${field}`);
  assert.match(component, /"growth\.resultVerified"/);
  assert.match(component, /taskById\.get\(result\.id\)/);
  assert.match(component, /openTask\(taskById\.get\(result\.id\)!\)/);
  assert.match(component, /<details className="helloada-growth-result-receipt"/);
  assert.match(component, /result\.releaseId/);
  assert.match(component, /result\.sourceSha/);
  assert.match(component, /"growth\.nextReconciliation"/);
  assert.match(component, /overdueActivityIds\.map\(\(id\) => t\("growth\." \+ id\)\)/);
  assert.match(component, /unassignedWorkIds\.length \? <details/);
  assert.match(component, /serviceModel\.preparation\.map\(\(run\) => <li/);
  assert.match(component, /growth\.scopeSharedGrowthReview/);
  assert.doesNotMatch(component, /\{nextAssessment\.scope\}/);
  assert.match(source('src/styles/growth.scss'), /helloada-growth-agenda-status small \{ font-size: 11px; \}/);
});

test('area and evidence UI copy exists in English, French and Mexican Spanish', () => {
  const { growthCopy } = load(new URL('../src/lib/growth-copy.ts', import.meta.url));
  for (const language of ['en', 'fr', 'es']) {
    for (const key of ['growth.areasTitle', 'growth.areaContent', 'growth.areaSearchVisibility', 'growth.areaWebsiteHealth',
      'growth.areaAudienceCompetitors', 'growth.areaSpeedExperience', 'growth.areaNoAssessmentSummary',
      'growth.areaState_needs_decision', 'growth.evidence_recorded', 'growth.preparationTitle', 'growth.resultVerified',
      'growth.unassignedWork', 'growth.secondaryAreaLinks', 'growth.scopeSharedGrowthReview', 'growth.scopeGenericAssessment',
      'growth.receiptDetails', 'growth.releaseId', 'growth.sourceSha']) {
      assert.equal(typeof growthCopy[language][key], 'string', `${language}: ${key}`);
      assert.ok(growthCopy[language][key].length > 0);
    }
  }
});

test('area work cannot create a second approval widget and review remains on canonical handlers', () => {
  const component = source('src/components/GrowthTasks.tsx');
  const areaMarkup = component.slice(component.indexOf('<details className="helloada-growth-areas"'), component.indexOf('{error ?'));
  assert.match(areaMarkup, /canonicalDecisionIds\.has\(row\.id\)/);
  assert.doesNotMatch(areaMarkup, /fetchHelloAda|review_package_hash|onClick=\{\(\) => void effect/);
  assert.match(component, /openTask\(task\)/);
  assert.match(component, /loaded\.reviewPackageHash === selectedTask\.reviewPackageHash/);
  assert.match(component, /task \? "\/api\/helloada\/drafts\/" \+ task\.draftId \+ "\/" \+ operation/);
  assert.match(component, /review_package_hash: task\?\.reviewPackageHash/);
  assert.match(component, /selectedTask\.canApprove && selectedTask\.draftId && selectedTask\.reviewPackageHash/);
  assert.match(component, /growth\.taskResolvePrompt/);
  assert.match(component, /growth\.articleAskChanges/);
});
