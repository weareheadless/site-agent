import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const workspace = readFileSync(new URL('../src/components/WebsiteWorkspace.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/styles/owner-workspace.scss', import.meta.url), 'utf8');
const translations = readFileSync(new URL('../src/lib/admin-translations.ts', import.meta.url), 'utf8');

test('running build renders recorded pipeline progress, elapsed time, and Ada update', () => {
  assert.match(workspace, /designBuild\.state === 'queued' \|\| designBuild\.state === 'running'/);
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
  assert.match(workspace, /buildRunning \? 2_000 : 30_000/);
  assert.match(workspace, /loadAdaStatusRef\.current\(conversationId, true, false\)/);
  assert.match(workspace, /formatAge\(buildUpdateAge/);
  assert.match(workspace, /helloada-build-feed/);
  assert.match(styles, /helloada-build-feed/);
});

test('a silent build says so and offers a next action', () => {
  assert.match(workspace, /buildStalled/);
  assert.match(workspace, /helloada-build-stall/);
  assert.match(translations, /workspace\.buildStalled/);
  assert.match(translations, /workspace\.buildStalledAction/);
});

test('draft handover removes the build surface and failed state offers the composer action', () => {
  assert.match(workspace, /!designBuild\.draft_available/);
  assert.match(workspace, /designBuild\.state === 'failed'/);
  assert.match(workspace, /setMessage\(t\('workspace\.buildRetryPrompt'\)\)/);
  assert.match(translations, /workspace\.buildNextAction/);
  assert.match(styles, /helloada-build-surface/);
});
