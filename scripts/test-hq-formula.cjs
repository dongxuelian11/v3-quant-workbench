const assert = require('node:assert/strict');
const { evaluate } = require('./hq-formula.cjs');
const bars = Array.from({ length: 6 }, (_, i) => ({ date: `2025-01-0${i + 1}`, open: 10 + i, high: 12 + i, low: 9 + i, close: 11 + i, volume: (i + 1) * 100, amount: (i + 1) * 1000 }));
const series = [{ symbol: 'SH600000', bars }];
(async () => {
  const formula = { script: 'M:MA(C,N);R:REF(C,1);V:VOL;A:AMOUNT;DRAWICON(C>O,L,1);', parameters: [{ name: 'N', value: 3 }] };
  const chart = await evaluate({ formula, series, purpose: 'chart' });
  const research = await evaluate({ formula, series, purpose: 'research' });
  assert.deepEqual(chart.series, research.series);
  const out = research.series[0].outputs;
  assert.deepEqual(out.find(x => x.name === 'M').values, [null, null, 12, 13, 14, 15]);
  assert.deepEqual(out.find(x => x.name === 'V').values, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(out.find(x => x.name === 'A').values, bars.map(b => b.amount));
  assert.equal(out.length, 4); assert.equal(research.series[0].drawings.length, 1);
  for (const script of ['X:REF(C,-1);', 'X:BACKSET(C>O,2);', 'X:CONST(C);', 'X:REFDATE(C,20250106);', 'X:CURRBARSCOUNT;', 'X:FINDHIGH(C,-1,3,1);']) {
    const blocked = await evaluate({ formula: { script }, series, purpose: 'research' });
    assert.equal(blocked.ok, false, script);
    assert.equal(blocked.assessment.researchAllowed, false, script);
  }
  assert.equal((await evaluate({ formula: { script: 'X:BACKSET(C>O,2);' }, series, purpose: 'chart' })).ok, true);
  await assert.rejects(evaluate({ formula: { script: 'X:NO_SUCH_FUNCTION(C);' }, series, purpose: 'chart' }));
  await assert.rejects(evaluate({ formula: { script: 'DRAWICON(C>O,L,1);', output: 'DRAWICON' }, series, purpose: 'research' }));
  // Prefix results must agree with full-series history for an ordinary rolling formula.
  const prefix = await evaluate({ formula, series: [{ symbol: 'SH600000', bars: bars.slice(0, 4) }], purpose: 'research' });
  assert.deepEqual(prefix.series[0].outputs[0].values, out[0].values.slice(0, 4));
  console.log('HQChart native formula: numeric/units/chart-research parity/prefix/repaint/drawing checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
