import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const read = path => readFileSync(new URL(`../src/styles/${path}`, import.meta.url), 'utf8');
const surfaces = read('_surfaces.scss');
const paper = surfaces.split('@mixin paper {')[1].split('@mixin chrome')[0];
const chrome = surfaces.split('@mixin chrome {')[1];
const token = (surface, name) => {
  const match = surface.match(new RegExp(`--helloada-${name}: (#[0-9a-f]{6});`));
  assert.ok(match, `missing ${name}`);
  return match[1];
};
const luminance = hex => {
  const channels = hex.slice(1).match(/../g).map(x => parseInt(x, 16) / 255).map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4);
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
};
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);

test('paper foundation matches the HelloAda homepage control room', () => {
  assert.equal(token(paper, 'bg'), '#eee6da');
  assert.equal(token(paper, 'ink'), '#211b17');
  assert.match(read('admin.scss'), /\[data-theme='light'\] \{\s*@include surfaces\.paper;/);
});
test('navigation and Ada are explicitly dark; review and Growth inherit paper', () => {
  assert.match(read('admin.scss'), /\.template-default \.nav \{\s*@include surfaces\.chrome;/);
  assert.match(read('owner-workspace.scss'), /\.helloada-owner-workspace \.helloada-ada-panel \{ @include surfaces\.chrome;/);
  assert.match(read('owner-workspace.scss'), /\.helloada-review-window \{ grid-column: 2/);
  assert.doesNotMatch(read('growth.scss'), /@include surfaces\.chrome/);
});
test('nested tool windows explicitly restore paper instead of inheriting dark chat', () => {
  const owner = read('owner-workspace.scss');
  for (const name of ['manage-drawer', 'chat-gallery', 'publish-dialog']) assert.match(owner, new RegExp(`\\.helloada-${name} \\{\\s*@include surfaces\\.paper;`));
  for (const name of ['field-popover', 'page-editor']) assert.match(read('admin.scss'), new RegExp(`\\.helloada-${name} \\{\\s*@include surfaces\\.paper;`));
});
test('primary, secondary, caption and action text meet AA on both surfaces', () => {
  for (const [name, surface] of [['paper', paper], ['chrome', chrome]]) {
    for (const bg of ['bg', 'panel', 'panel-raised', 'panel-soft']) {
      for (const ink of ['ink', 'muted', 'dim', 'cyan', 'violet', 'positive', 'negative']) {
        const ratio = contrast(token(surface, ink), token(surface, bg));
        assert.ok(ratio >= 4.5, `${name} ${ink}/${bg}: ${ratio.toFixed(2)}`);
      }
    }
    assert.ok(contrast(token(surface, 'action-ink'), token(surface, 'cyan')) >= 4.5, `${name} action text`);
  }
});
test('charts and status text use surface-aware accents rather than pale dark-only colors', () => {
  const growth = read('growth.scss');
  assert.match(growth, /stroke: var\(--helloada-cyan\);/);
  assert.match(growth, /color: var\(--helloada-positive\);/);
  assert.doesNotMatch(growth, /#ff9989|#ffa69a|#b4d990|#ffdc91/);
});
