import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { LAB_IDS } from "../../packages/contracts/src/index.ts";
import { buildResultChartSeries, RESULT_LAB_ANALYTICS_V0, validateResultAnalyticsView } from "../../apps/desktop/src/renderer/resultAnalyticsViewModel.ts";

const panelPath = new URL("../../apps/desktop/src/renderer/components/ResultAnalyticsPanel.tsx", import.meta.url);
const workbenchPath = new URL("../../apps/desktop/src/renderer/components/Workbench.tsx", import.meta.url);

test("Track L view model preserves exact result, policy, benchmark, and analytics identities", () => {
  const value = validateResultAnalyticsView(RESULT_LAB_ANALYTICS_V0);
  assert.equal(value.analyticsId, `bra_sha256_${value.contentSha256}`);
  assert.equal(value.sourceResult.resultId, `btrr_sha256_${value.sourceResult.contentSha256}`);
  assert.equal(value.policy.policyId, `rap_sha256_${value.policy.contentSha256}`);
  assert.equal(value.benchmark.seriesId, `bmsv_sha256_${value.benchmark.contentSha256}`);
  assert.equal(value.policy.annualizationSessions, 252);
  assert.equal(value.policy.riskFreePolicy, "ZERO_RISK_FREE_ASSUMPTION");
  assert.equal(value.truthAdmission.canonicalTruthState, "NOT_FORMAL");
  assert.equal(value.truthAdmission.canonicalAdmissionState, "PRE_ALPHA");
});

test("Result Lab chart series are projections of actual analytics values", () => {
  const value = RESULT_LAB_ANALYTICS_V0;
  const chart = buildResultChartSeries(value);
  assert.deepEqual(chart.dates, value.returnSeries.map((row) => row.sessionDate));
  assert.deepEqual(chart.nav, value.returnSeries.map((row) => Number(row.nav)));
  assert.deepEqual(chart.cumulativeReturnPercent, value.returnSeries.map((row) => Number(row.cumulativeReturn) * 100));
  assert.deepEqual(chart.drawdownPercent, value.drawdownSeries.map((row) => Number(row.drawdown) * 100));
  assert.deepEqual(chart.relativeNav, value.benchmark.relativeReturns.map((row) => Number(row.relativeNav)));
  assert.deepEqual(chart.relativePerformancePercent, value.benchmark.relativeReturns.map((row) => (Number(row.relativeNav) - 1) * 100));
  assert.equal(value.metrics.totalReturn.value, "0.006");
  assert.equal(value.metrics.maxDrawdown.value, "-0.002994011976");
});

test("Result Lab exposes complete professional views without fake cost or default benchmark semantics", async () => {
  const panel = await readFile(panelPath, "utf8");
  assert.match(panel, /KpiStrip/);
  assert.match(panel, /ResultAnalyticsChart/);
  assert.match(panel, /Period Returns/);
  assert.match(panel, /Trading & Cost/);
  assert.match(panel, /Benchmark/);
  assert.match(panel, /Policy & Identity/);
  assert.match(panel, /data-result-analytics-id/);
  assert.match(panel, /buildResultChartSeries\(RESULT_LAB_ANALYTICS_V0\)/);
  assert.doesNotMatch(panel, /沪深300|fetch\s*\(/i);
  assert.equal("preCostReturn" in RESULT_LAB_ANALYTICS_V0.costs, false);
  assert.equal(RESULT_LAB_ANALYTICS_V0.benchmark.status, "AVAILABLE");
});

test("five Lab contracts stay unchanged and Result uses the Track L owner component", async () => {
  assert.deepEqual([...LAB_IDS], ["research", "strategy", "model", "backtest", "result"]);
  const workbench = await readFile(workbenchPath, "utf8");
  assert.match(workbench, /import \{ ResultPanel \} from "\.\/ResultAnalyticsPanel"/);
  for (const lab of LAB_IDS) assert.match(workbench, new RegExp(`${lab}:`));
});
