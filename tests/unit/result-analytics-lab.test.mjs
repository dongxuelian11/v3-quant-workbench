import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { LAB_IDS } from "../../packages/contracts/src/index.ts";
import { buildResultChartSeries, insufficient, RESULT_ANALYTICS_DEVELOPMENT_STATE, RESULT_ANALYTICS_PRODUCTION_DEFAULT, RESULT_LAB_ANALYTICS_V0, unavailable, validateResultAnalyticsView } from "../../apps/desktop/src/renderer/resultAnalyticsViewModel.ts";

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
  assert.deepEqual(chart.cumulativeReturnPercent, value.returnSeries.map((row) => Number(row.cumulativeReturn.value) * 100));
  assert.deepEqual(chart.drawdownPercent, value.drawdownSeries.map((row) => Number(row.drawdown.value) * 100));
  assert.deepEqual(chart.relativeNav, value.benchmark.relativeReturns.map((row) => Number(row.relativeNav.value)));
  assert.deepEqual(chart.relativePerformancePercent, value.benchmark.relativeReturns.map((row) => (Number(row.relativeNav.value) - 1) * 100));
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
  assert.match(panel, /buildResultChartSeries\(analytics\)/);
  assert.doesNotMatch(panel, /沪深300|fetch\s*\(/i);
  assert.equal("preCostReturn" in RESULT_LAB_ANALYTICS_V0.costs, false);
  assert.equal(RESULT_LAB_ANALYTICS_V0.benchmark.status, "AVAILABLE");
});

test("production default is connected-empty and development fixture requires explicit mode", async () => {
  const panel = await readFile(panelPath, "utf8");
  assert.equal(RESULT_ANALYTICS_PRODUCTION_DEFAULT.boundary, "CONNECTED_NO_ANALYTICS");
  assert.equal(RESULT_ANALYTICS_PRODUCTION_DEFAULT.analytics, null);
  assert.equal(RESULT_ANALYTICS_DEVELOPMENT_STATE.boundary, "DEVELOPMENT_INTEGRATION_FIXTURE");
  assert.match(panel, /resultAnalyticsFixture/);
  assert.match(panel, /DEVELOPMENT \/ INTEGRATION FIXTURE/);
  assert.match(panel, /Development fixtures are never substituted silently/);
});

test("view validator distinguishes frozen and explicit policy profiles and validates truth lattice", () => {
  const explicit = structuredClone(RESULT_LAB_ANALYTICS_V0);
  explicit.policy.profileName = "EXPLICIT_RESEARCH_ANALYTICS_V0";
  explicit.policy.annualizationSessions = 250;
  explicit.policy.sortinoTarget = "0.001";
  explicit.truthAdmission = { canonicalTruthState: "FORMAL", canonicalAdmissionState: "FORMAL_ADMITTED" };
  validateResultAnalyticsView(explicit);
  const invalid = structuredClone(RESULT_LAB_ANALYTICS_V0);
  invalid.truthAdmission = { canonicalTruthState: "UNKNOWN", canonicalAdmissionState: "PRE_ALPHA" };
  assert.throws(() => validateResultAnalyticsView(invalid), /truth\/admission/);
});

test("benchmark absent is typed and omits relative-performance chart data", () => {
  const value = structuredClone(RESULT_LAB_ANALYTICS_V0);
  value.benchmark = {
    status: "BENCHMARK_NOT_AVAILABLE",
    name: null,
    seriesId: null,
    contentSha256: null,
    totalReturn: unavailable("BENCHMARK_NOT_AVAILABLE"),
    trackingDifference: unavailable("BENCHMARK_NOT_AVAILABLE"),
    trackingError: unavailable("BENCHMARK_NOT_AVAILABLE"),
    alpha: unavailable("OUTSIDE_V0_CLOSED_FORMULA"),
    beta: unavailable("OUTSIDE_V0_CLOSED_FORMULA"),
    relativeReturns: []
  };
  validateResultAnalyticsView(value);
  const chart = buildResultChartSeries(value);
  assert.equal(chart.relativeNav, null);
  assert.equal(chart.relativePerformancePercent, null);
});

test("drawdown none and unrecovered states are valid without fake recovery date", () => {
  const none = structuredClone(RESULT_LAB_ANALYTICS_V0);
  none.drawdownEpisode = null;
  validateResultAnalyticsView(none);
  const unrecovered = structuredClone(RESULT_LAB_ANALYTICS_V0);
  unrecovered.drawdownEpisode.recoveryDate = null;
  unrecovered.drawdownEpisode.recoveryStatus = "UNRECOVERED";
  validateResultAnalyticsView(unrecovered);
});

test("unavailable and insufficient metrics preserve status/reason and chart nulls", async () => {
  const value = structuredClone(RESULT_LAB_ANALYTICS_V0);
  value.metrics.sharpe = unavailable("ZERO_VARIANCE");
  value.metrics.sortino = insufficient("REQUIRES_ONE_SESSION_RETURN");
  value.returnSeries[2].cumulativeReturn = unavailable("MISSING_SESSION_VALUE");
  validateResultAnalyticsView(value);
  assert.equal(buildResultChartSeries(value).cumulativeReturnPercent[2], null);
  const panel = await readFile(panelPath, "utf8");
  assert.match(panel, /metric\.reason/);
  assert.doesNotMatch(panel, /Number\(null\)/);
  assert.doesNotMatch(panel, /\?\?\s*0/);
});

test("Result Lab remains dense, supplied-view ECharts presentation", async () => {
  const panel = await readFile(panelPath, "utf8");
  assert.match(panel, /echarts\.init/);
  assert.match(panel, /ResultAnalyticsChart analytics=\{a\}/);
  assert.match(panel, /BENCHMARK NOT AVAILABLE/);
  assert.match(panel, /NO NEGATIVE DRAWDOWN EPISODE/);
  assert.match(panel, /episode\.recoveryStatus/);
});

test("five Lab contracts stay unchanged and Result uses the Track L owner component", async () => {
  assert.deepEqual([...LAB_IDS], ["research", "strategy", "model", "backtest", "result"]);
  const workbench = await readFile(workbenchPath, "utf8");
  assert.match(workbench, /import \{ ResultPanel \} from "\.\/ResultAnalyticsPanel"/);
  for (const lab of LAB_IDS) assert.match(workbench, new RegExp(`${lab}:`));
});
