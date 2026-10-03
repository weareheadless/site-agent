import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
test('competitor view is accessible from the central Growth navigation', () => {
  const growth = read('components/HelloAdaGrowth.tsx');
  assert.match(growth, /"competitionTab"/);
  assert.match(growth, /<GrowthCompetition revision=\{revision\} ask=\{ask\}/);
});
test('competitor screen reads scoped completed evidence and does not dispatch paid work', () => {
  const view = read('components/GrowthCompetition.tsx');
  assert.match(view, /section=competition/);
  assert.match(view, /AbortController/);
  assert.match(view, /value == null/);
  assert.match(view, /ownPosition == null/);
  assert.match(view, /const activeView\s*=\s*view\s*\|\|/);
  assert.match(view, /ProductAction href=\{ask\(prompt\)\}/);
  assert.doesNotMatch(view, /method:.*POST|request_research|dispatch|dangerouslySetInnerHTML/);
});
test('all supported languages disclose estimates, sampling and owner approval', () => {
  const copy = read('lib/competition-copy.ts');
  for (const key of ['competitionTab', 'competitorSource', 'sampleNote', 'competitorApproval', 'notInSample']) assert.equal((copy.match(new RegExp(`${key}:`, 'g')) || []).length, 3);
});
