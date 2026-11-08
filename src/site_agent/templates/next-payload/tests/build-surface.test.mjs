import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const workspace = readFileSync(new URL('../src/admin/components/WebsiteWorkspace.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/admin/styles/owner-workspace.scss', import.meta.url), 'utf8');
const translations = readFileSync(new URL('../src/admin/lib/admin-translations.ts', import.meta.url), 'utf8');

test('candidate preview replaces the large build panel with a compact progress strip', () => {
  assert.match(workspace, /helloada-build-strip/);
  assert.match(workspace, /<progress[^>]*max=\{DESIGN_BUILD_STAGES\.length\}/);
  assert.match(workspace, /<details className="helloada-build-details"/);
  assert.match(workspace, /onLoad=\{handlePreviewLoad\}/);
  assert.doesNotMatch(workspace, /helloada-early-candidate-preview/);
  assert.match(workspace, /websitePresent \|\| buildSurfaceVisible \? '' : 'is-chat-only'/);
  assert.match(styles, /helloada-build-canvas[^}]*flex:\s*1[^}]*min-height:\s*0/);
  assert.match(workspace, /websitePresent \|\| buildSurfaceVisible \? <div className="helloada-pane-switch"/);
  assert.match(styles, /shows-ada \.helloada-build-surface[^}]*display: none/);
});

test('running build renders recorded pipeline progress, elapsed time, and Ada update', () => {
  assert.match(workspace, /designBuild\?\.state === 'queued' \|\| designBuild\?\.state === 'running'/);
  assert.match(workspace, /DESIGN_BUILD_STAGES\.map/);
  assert.match(workspace, /stage\.state === 'done'/);
  assert.match(workspace, /buildElapsedSeconds/);
  assert.match(workspace, /formatDuration\(buildElapsedSeconds\)/);
  assert.match(workspace, /designBuild\?\.update/);
  assert.match(workspace, /designBuild\?\.updates/);
  assert.match(translations, /workspace\.buildProgress/);
  assert.match(translations, /workspace\.buildElapsedLive/);
});

test('the build surface keeps moving without a reload', () => {
  assert.match(workspace, /setBuildClock\(Date\.now\(\)\)/);
  assert.match(workspace, /1_000\)/);
  assert.match(workspace, /buildRunning \|\| candidatePreviewRunning \? 2_000 : 30_000/);
  assert.match(workspace, /loadAdaStatusRef\.current\(conversationId, true, false\)/);
  assert.match(workspace, /formatAge\(buildUpdateAge/);
  assert.match(workspace, /helloada-build-feed/);
  assert.match(styles, /helloada-build-feed/);
});

test('the exact unapproved design candidate is visible while checks continue', () => {
  assert.match(workspace, /candidatePreviewReady/);
  assert.match(workspace, /designBuild\.preview\?\.candidate_sha/);
  assert.match(workspace, /designBuild\.preview\?\.job_id/);
  assert.match(workspace, /workspace\.candidateNotApproved/);
  assert.match(workspace, /workspace\.candidatePreviewFailed/);
  assert.match(translations, /workspace\.candidatePreviewPreparing/);
});

test('a silent build says so and offers a next action', () => {
  assert.match(workspace, /buildStalled/);
  assert.match(workspace, /helloada-build-stall/);
  assert.match(translations, /workspace\.buildStalled/);
  assert.match(translations, /workspace\.buildStalledAction/);
});

test('a retained candidate remains visible after its review draft is linked', () => {
  assert.match(workspace, /candidatePreviewReady/);
  assert.match(workspace, /candidatePreviewPreparing/);
  assert.match(workspace, /candidatePreviewFailed/);
  assert.match(workspace, /buildSurfaceVisible && designBuild/);
  assert.match(workspace, /buildSurfaceVisible \? 'has-build-surface' : ''/);
  assert.match(workspace, /designBuild\.state === 'failed'/);
  assert.match(workspace, /setMessage\(t\('workspace\.buildRetryPrompt'\)\)/);
  assert.match(translations, /workspace\.buildNextAction/);
  assert.match(styles, /helloada-build-surface/);
});

test('established-site review uses the candidate preview only for the exact draft and SHA', () => {
  assert.match(workspace, /sourceReview\.draftId === designBuild\.draft_id/);
  assert.match(workspace, /sourceReview\.sha\.toLowerCase\(\) === String\(designBuild\.candidate_sha/);
  assert.match(workspace, /designBuild\.preview\?\.run_id === designBuild\.run_id/);
  assert.match(workspace, /candidateReviewPreviewReady/);
  assert.match(workspace, /candidateNotApproved/);
});
