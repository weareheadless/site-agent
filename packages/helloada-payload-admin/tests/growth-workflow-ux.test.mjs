import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const component = readFileSync(new URL('../src/components/GrowthTasks.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/styles/growth.scss', import.meta.url), 'utf8');

test('Ada’s work is one task list, not separate status buckets or counters', () => {
  assert.match(component, /const workRows = tasks\.filter/);
  assert.match(component, /workRows\.map\(task =>/);
  assert.doesNotMatch(component, /workSections|workGroups|helloada-growth-work-section|helloada-growth-task-group-heading/);
  assert.doesNotMatch(styles, /helloada-growth-work-section|helloada-growth-task-group-heading|helloada-growth-work-affected/);
});

test('Ada’s work links to evidence instead of asking the owner to launch the analysis pipeline', () => {
  assert.match(component, /onNavigate\("results", "search"\)/);
  assert.doesNotMatch(component, /effect\(undefined, "check"\)/);
});
