import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {selectReviewDraft} from '../src/admin/lib/select-review-draft.ts';

const draft4 = {id: 4, kind: 'design'};
const draft5 = {id: 5, kind: 'design'};
const merge = {id: 3, kind: 'merge'};

test('selects the projected design draft rather than an older pending design', () => {
  assert.equal(selectReviewDraft([draft4, draft5], 5), draft5);
});

test('does not fall back to an unrelated draft while the projected draft is absent', () => {
  assert.equal(selectReviewDraft([draft4], 5), undefined);
});

test('without a projected design id, preserves the first eligible draft in API order', () => {
  assert.equal(selectReviewDraft([draft4, merge]), draft4);
  assert.equal(selectReviewDraft([merge, draft4]), merge);
});

test('preview-plan refresh is keyed to projected draft and ignores stale request responses', () => {
  const workspace = readFileSync(new URL('../src/admin/components/WebsiteWorkspace.tsx', import.meta.url), 'utf8');
  assert.match(workspace, /\[designBuild\?\.draft_id, t\]/);
  assert.match(workspace, /const requestId = \+\+previewPlanRequestRef\.current/);
  assert.match(workspace, /if \(!isCurrentRequest\(\)\) return/g);
  assert.match(workspace, /selectReviewDraft\(body\.drafts \|\| \[\], projectedDraftId\)/);
});
