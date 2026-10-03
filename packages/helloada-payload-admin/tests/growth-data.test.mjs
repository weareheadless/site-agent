import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = readFileSync(new URL('../src/lib/growth-data.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
const sandbox = {exports: {}, Intl};
vm.runInNewContext(compiled, sandbox);
const {growthDate, growthNumber, growthSeries, growthCSV} = sandbox.exports;

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
test('CSV preserves raw measurements and quotes spreadsheet formulas safely', () => {
  assert.equal(growthCSV([{keyword: '=HYPERLINK("bad")', ctr: .2}], [['keyword', 'Keyword'], ['ctr', 'CTR']]), '"Keyword","CTR"\r\n"\'=HYPERLINK(""bad"")","0.2"');
});
