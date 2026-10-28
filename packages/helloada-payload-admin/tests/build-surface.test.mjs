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
  assert.match(workspace, /elapsed_seconds \/ 60/);
  assert.match(workspace, /currentAdaProgress/);
  assert.match(translations, /workspace\.buildProgress/);
});

test('draft handover removes the build surface and failed state offers the composer action', () => {
  assert.match(workspace, /!designBuild\.draft_available/);
  assert.match(workspace, /designBuild\.state === 'failed'/);
  assert.match(workspace, /setMessage\(t\('workspace\.buildRetryPrompt'\)\)/);
  assert.match(translations, /workspace\.buildNextAction/);
  assert.match(styles, /helloada-build-surface/);
});
