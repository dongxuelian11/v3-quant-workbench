export type AnalyticsMetricView = {
  status: "AVAILABLE" | "NOT_AVAILABLE" | "INSUFFICIENT_SAMPLE";
  value: string | null;
  reason: string | null;
};

export type ResultAnalyticsView = {
  fixtureBoundary: "DEVELOPMENT_INTEGRATION_FIXTURE";
  analyticsId: string;
  contentSha256: string;
  sourceResult: { resultId: string; contentSha256: string };
  policy: {
    policyId: string;
    contentSha256: string;
    profileName: "A_SHARE_DAILY_RESEARCH_V0" | "EXPLICIT_RESEARCH_ANALYTICS_V0";
    returnConvention: "SIMPLE_NAV_RETURN";
    annualizationSessions: number;
    volatilityDdoF: number;
    riskFreePolicy: "ZERO_RISK_FREE_ASSUMPTION";
    riskFreeAnnualRate: "0";
    sortinoTarget: string;
    drawdownConvention: "RUNNING_PEAK_TO_NAV";
    turnoverConvention: "GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV";
    periodReturnConvention: "PERIOD_END_OVER_PREVIOUS_PERIOD_END";
    missingDataPolicy: "FAIL_CLOSED_EXACT_SESSIONS";
    numericPrecision: number;
    numericRounding: "ROUND_HALF_EVEN";
  };
  truthAdmission: {
    canonicalTruthState: "UNKNOWN" | "NOT_FORMAL" | "FORMAL";
    canonicalAdmissionState: "UNKNOWN" | "PRE_ALPHA" | "FORMAL_ADMITTED";
  };
  metrics: Record<"totalReturn" | "annualizedReturn" | "annualizedVolatility" | "maxDrawdown" | "sharpe" | "sortino", AnalyticsMetricView>;
  returnSeries: readonly { sessionDate: string; nav: string; cumulativeReturn: AnalyticsMetricView }[];
  drawdownSeries: readonly { sessionDate: string; drawdown: AnalyticsMetricView }[];
  drawdownEpisode: null | { peakDate: string; troughDate: string; recoveryDate: string | null; durationSessions: number; recoveryStatus: "RECOVERED" | "UNRECOVERED" };
  monthlyReturns: readonly { periodLabel: string; startDate: string; endDate: string; periodReturn: AnalyticsMetricView }[];
  yearlyReturns: readonly { periodLabel: string; startDate: string; endDate: string; periodReturn: AnalyticsMetricView }[];
  costs: {
    fillCount: number;
    buyTradedNotional: string;
    sellTradedNotional: string;
    grossTradedNotional: string;
    commission: string;
    stampDuty: string;
    transferFee: string;
    exchangeFee: string;
    totalFees: string;
    feeOverTradedNotional: AnalyticsMetricView;
    observedFeeLoadOverStartNav: AnalyticsMetricView;
  };
  turnover: { averageDailyNav: string; turnover: AnalyticsMetricView };
  benchmark: {
    status: "AVAILABLE" | "BENCHMARK_NOT_AVAILABLE";
    name: string | null;
    seriesId: string | null;
    contentSha256: string | null;
    totalReturn: AnalyticsMetricView;
    trackingDifference: AnalyticsMetricView;
    trackingError: AnalyticsMetricView;
    alpha: AnalyticsMetricView;
    beta: AnalyticsMetricView;
    relativeReturns: readonly { sessionDate: string; relativeNav: AnalyticsMetricView; sessionExcessReturn: AnalyticsMetricView }[];
  };
};

export type ResultAnalyticsSurfaceState =
  | { boundary: "CONNECTED_NO_ANALYTICS"; reason: "NO_RESULT_ANALYTICS_AVAILABLE"; analytics: null }
  | { boundary: "BACKEND_DISCONNECTED"; reason: "RESULT_ANALYTICS_SOURCE_NOT_CONNECTED"; analytics: null }
  | { boundary: "DEVELOPMENT_INTEGRATION_FIXTURE"; reason: null; analytics: ResultAnalyticsView };

export const RESULT_ANALYTICS_PRODUCTION_DEFAULT: ResultAnalyticsSurfaceState = {
  boundary: "CONNECTED_NO_ANALYTICS",
  reason: "NO_RESULT_ANALYTICS_AVAILABLE",
  analytics: null
};

export const available = (value: string): AnalyticsMetricView => ({ status: "AVAILABLE", value, reason: null });
export const unavailable = (reason: string): AnalyticsMetricView => ({ status: "NOT_AVAILABLE", value: null, reason });
export const insufficient = (reason: string): AnalyticsMetricView => ({ status: "INSUFFICIENT_SAMPLE", value: null, reason });

function exactIdentity(id: string, prefix: string, hash: string, name: string): void {
  if (!new RegExp(`^${prefix}[0-9a-f]{64}$`).test(id) || id !== `${prefix}${hash}`) throw new TypeError(`${name} identity is not exact`);
}

export function validateResultAnalyticsView(value: ResultAnalyticsView): ResultAnalyticsView {
  if (value.fixtureBoundary !== "DEVELOPMENT_INTEGRATION_FIXTURE") throw new TypeError("fixture boundary is not explicit");
  exactIdentity(value.analyticsId, "bra_sha256_", value.contentSha256, "analytics");
  exactIdentity(value.sourceResult.resultId, "btrr_sha256_", value.sourceResult.contentSha256, "result");
  exactIdentity(value.policy.policyId, "rap_sha256_", value.policy.contentSha256, "policy");
  const policy = value.policy;
  if (policy.returnConvention !== "SIMPLE_NAV_RETURN" || policy.riskFreePolicy !== "ZERO_RISK_FREE_ASSUMPTION" || policy.riskFreeAnnualRate !== "0" || policy.drawdownConvention !== "RUNNING_PEAK_TO_NAV" || policy.turnoverConvention !== "GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV" || policy.periodReturnConvention !== "PERIOD_END_OVER_PREVIOUS_PERIOD_END" || policy.missingDataPolicy !== "FAIL_CLOSED_EXACT_SESSIONS" || policy.numericRounding !== "ROUND_HALF_EVEN") throw new TypeError("Result Lab policy is not execution-compatible");
  if (!Number.isInteger(policy.annualizationSessions) || policy.annualizationSessions <= 0 || !Number.isInteger(policy.volatilityDdoF) || policy.volatilityDdoF < 0 || !Number.isInteger(policy.numericPrecision) || policy.numericPrecision < 1 || policy.numericPrecision > 28 || !Number.isFinite(Number(policy.sortinoTarget))) throw new TypeError("Result Lab numeric policy is invalid");
  if (policy.profileName === "A_SHARE_DAILY_RESEARCH_V0" && (policy.annualizationSessions !== 252 || policy.volatilityDdoF !== 1 || policy.sortinoTarget !== "0" || policy.numericPrecision !== 12)) throw new TypeError("A-share policy profile is not frozen");
  const allowedAdmissions = { UNKNOWN: ["UNKNOWN"], NOT_FORMAL: ["UNKNOWN", "PRE_ALPHA"], FORMAL: ["UNKNOWN", "PRE_ALPHA", "FORMAL_ADMITTED"] } as const;
  if (!(allowedAdmissions[value.truthAdmission.canonicalTruthState] as readonly string[]).includes(value.truthAdmission.canonicalAdmissionState)) throw new TypeError("truth/admission shape is invalid");
  const dates = value.returnSeries.map((row) => row.sessionDate);
  if (!dates.length || new Set(dates).size !== dates.length || dates.join("|") !== [...dates].sort().join("|") || dates.join("|") !== value.drawdownSeries.map((row) => row.sessionDate).join("|")) throw new TypeError("Result Lab series dates are not exactly aligned");
  const metric = (item: AnalyticsMetricView, name: string): void => {
    if (item.status === "AVAILABLE") {
      if (item.value === null || item.reason !== null || !Number.isFinite(Number(item.value))) throw new TypeError(`${name} AVAILABLE shape is invalid`);
    } else if (item.value !== null || typeof item.reason !== "string" || item.reason.trim() === "") throw new TypeError(`${name} unavailable shape is invalid`);
  };
  Object.entries(value.metrics).forEach(([name, item]) => metric(item, name));
  value.returnSeries.forEach((row) => { if (!Number.isFinite(Number(row.nav))) throw new TypeError("NAV must be finite"); metric(row.cumulativeReturn, "cumulative return"); });
  value.drawdownSeries.forEach((row) => metric(row.drawdown, "drawdown"));
  [...value.monthlyReturns, ...value.yearlyReturns].forEach((row) => metric(row.periodReturn, "period return"));
  [value.costs.feeOverTradedNotional, value.costs.observedFeeLoadOverStartNav, value.turnover.turnover].forEach((item) => metric(item, "cost/turnover"));
  if (value.drawdownEpisode) {
    const episode = value.drawdownEpisode;
    if (!Number.isInteger(episode.durationSessions) || episode.durationSessions < 0 || episode.peakDate > episode.troughDate) throw new TypeError("drawdown episode chronology is invalid");
    if (episode.recoveryStatus === "RECOVERED" ? episode.recoveryDate === null || episode.recoveryDate < episode.troughDate : episode.recoveryDate !== null) throw new TypeError("drawdown recovery shape is invalid");
  }
  const benchmarkMetrics = [value.benchmark.totalReturn, value.benchmark.trackingDifference, value.benchmark.trackingError, value.benchmark.alpha, value.benchmark.beta];
  benchmarkMetrics.forEach((item) => metric(item, "benchmark metric"));
  if (value.benchmark.status === "AVAILABLE") {
    if (value.benchmark.name === null || value.benchmark.seriesId === null || value.benchmark.contentSha256 === null) throw new TypeError("available benchmark binding is incomplete");
    exactIdentity(value.benchmark.seriesId, "bmsv_sha256_", value.benchmark.contentSha256, "benchmark");
    if (dates.join("|") !== value.benchmark.relativeReturns.map((row) => row.sessionDate).join("|")) throw new TypeError("benchmark dates are not exactly aligned");
    value.benchmark.relativeReturns.forEach((row) => { metric(row.relativeNav, "relative NAV"); metric(row.sessionExcessReturn, "session excess return"); });
  } else {
    if (value.benchmark.name !== null || value.benchmark.seriesId !== null || value.benchmark.contentSha256 !== null || value.benchmark.relativeReturns.length) throw new TypeError("absent benchmark must be unbound and empty");
    if (benchmarkMetrics.some((item) => item.status === "AVAILABLE")) throw new TypeError("absent benchmark metrics must be unavailable");
  }
  return value;
}

export const RESULT_LAB_ANALYTICS_V0 = validateResultAnalyticsView({
  fixtureBoundary: "DEVELOPMENT_INTEGRATION_FIXTURE",
  analyticsId: "bra_sha256_f1456d4c45105340a8cebcde39bd1fe5a5f8448999e256a18c0c05b406793829",
  contentSha256: "f1456d4c45105340a8cebcde39bd1fe5a5f8448999e256a18c0c05b406793829",
  sourceResult: {
    resultId: "btrr_sha256_ef4e4591b3b72ec8a802c72394aff6bd1fc198aa823d14fba0f03d450e367e05",
    contentSha256: "ef4e4591b3b72ec8a802c72394aff6bd1fc198aa823d14fba0f03d450e367e05"
  },
  policy: {
    policyId: "rap_sha256_cbab7fdbcd14c3f2ef210bfff68a9c9f8e3aa62396ad111b55e3f0ca9e78d442",
    contentSha256: "cbab7fdbcd14c3f2ef210bfff68a9c9f8e3aa62396ad111b55e3f0ca9e78d442",
    profileName: "A_SHARE_DAILY_RESEARCH_V0",
    returnConvention: "SIMPLE_NAV_RETURN",
    annualizationSessions: 252,
    volatilityDdoF: 1,
    riskFreePolicy: "ZERO_RISK_FREE_ASSUMPTION",
    riskFreeAnnualRate: "0",
    sortinoTarget: "0",
    drawdownConvention: "RUNNING_PEAK_TO_NAV",
    turnoverConvention: "GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV",
    periodReturnConvention: "PERIOD_END_OVER_PREVIOUS_PERIOD_END",
    missingDataPolicy: "FAIL_CLOSED_EXACT_SESSIONS",
    numericPrecision: 12,
    numericRounding: "ROUND_HALF_EVEN"
  },
  truthAdmission: { canonicalTruthState: "NOT_FORMAL", canonicalAdmissionState: "PRE_ALPHA" },
  metrics: {
    totalReturn: available("0.006"),
    annualizedReturn: available("0.351880265324"),
    annualizedVolatility: available("0.063819441984"),
    maxDrawdown: available("-0.002994011976"),
    sharpe: available("4.752543761254"),
    sortino: available("10.100151584028")
  },
  returnSeries: [
    { sessionDate: "2026-01-29", nav: "100000", cumulativeReturn: available("0") },
    { sessionDate: "2026-01-30", nav: "100200", cumulativeReturn: available("0.002") },
    { sessionDate: "2026-02-02", nav: "99900", cumulativeReturn: available("-0.001") },
    { sessionDate: "2026-02-03", nav: "100400", cumulativeReturn: available("0.004") },
    { sessionDate: "2026-03-02", nav: "100100", cumulativeReturn: available("0.001") },
    { sessionDate: "2026-03-03", nav: "100600", cumulativeReturn: available("0.006") }
  ],
  drawdownSeries: [
    { sessionDate: "2026-01-29", drawdown: available("0") },
    { sessionDate: "2026-01-30", drawdown: available("0") },
    { sessionDate: "2026-02-02", drawdown: available("-0.002994011976") },
    { sessionDate: "2026-02-03", drawdown: available("0") },
    { sessionDate: "2026-03-02", drawdown: available("-0.002988047809") },
    { sessionDate: "2026-03-03", drawdown: available("0") }
  ],
  drawdownEpisode: { peakDate: "2026-01-30", troughDate: "2026-02-02", recoveryDate: "2026-02-03", durationSessions: 2, recoveryStatus: "RECOVERED" },
  monthlyReturns: [
    { periodLabel: "2026-01", startDate: "2026-01-29", endDate: "2026-01-30", periodReturn: available("0.002") },
    { periodLabel: "2026-02", startDate: "2026-02-02", endDate: "2026-02-03", periodReturn: available("0.001996007984") },
    { periodLabel: "2026-03", startDate: "2026-03-02", endDate: "2026-03-03", periodReturn: available("0.001992031873") }
  ],
  yearlyReturns: [{ periodLabel: "2026", startDate: "2026-01-29", endDate: "2026-03-03", periodReturn: available("0.006") }],
  costs: {
    fillCount: 2,
    buyTradedNotional: "1000",
    sellTradedNotional: "600",
    grossTradedNotional: "1600",
    commission: "2.5",
    stampDuty: "1.5",
    transferFee: "0.3",
    exchangeFee: "0.5",
    totalFees: "4.8",
    feeOverTradedNotional: available("0.003"),
    observedFeeLoadOverStartNav: available("0.000048")
  },
  turnover: { averageDailyNav: "100200", turnover: available("0.015968063872") },
  benchmark: {
    status: "AVAILABLE",
    name: "CN_LARGE_CAP_RESEARCH_BENCHMARK_V0",
    seriesId: "bmsv_sha256_142e644ad028fa438e89557368abc609d7b5d165017c51fde06171ae88367b77",
    contentSha256: "142e644ad028fa438e89557368abc609d7b5d165017c51fde06171ae88367b77",
    totalReturn: available("0.003"),
    trackingDifference: available("0.003"),
    trackingError: available("0.056160815471"),
    alpha: unavailable("OUTSIDE_V0_CLOSED_FORMULA"),
    beta: unavailable("OUTSIDE_V0_CLOSED_FORMULA"),
    relativeReturns: [
      { sessionDate: "2026-01-29", relativeNav: available("1"), sessionExcessReturn: unavailable("NO_PRIOR_SESSION") },
      { sessionDate: "2026-01-30", relativeNav: available("1.000999000999"), sessionExcessReturn: available("0.001") },
      { sessionDate: "2026-02-02", relativeNav: available("0.998500749625"), sessionExcessReturn: available("-0.002494511477") },
      { sessionDate: "2026-02-03", relativeNav: available("1.001996007984"), sessionExcessReturn: available("0.00350575463") },
      { sessionDate: "2026-03-02", relativeNav: available("0.998503740648"), sessionExcessReturn: available("-0.003487049805") },
      { sessionDate: "2026-03-03", relativeNav: available("1.002991026919"), sessionExcessReturn: available("0.004496251878") }
    ]
  }
});

export const RESULT_ANALYTICS_DEVELOPMENT_STATE: ResultAnalyticsSurfaceState = {
  boundary: "DEVELOPMENT_INTEGRATION_FIXTURE",
  reason: null,
  analytics: RESULT_LAB_ANALYTICS_V0
};

const chartValue = (metric: AnalyticsMetricView): number | null => metric.status === "AVAILABLE" && metric.value !== null ? Number(metric.value) : null;

export function buildResultChartSeries(value: ResultAnalyticsView) {
  const relativeNav = value.benchmark.status === "AVAILABLE" ? value.benchmark.relativeReturns.map((row) => chartValue(row.relativeNav)) : null;
  return {
    dates: value.returnSeries.map((row) => row.sessionDate),
    nav: value.returnSeries.map((row) => Number(row.nav)),
    cumulativeReturnPercent: value.returnSeries.map((row) => { const observed = chartValue(row.cumulativeReturn); return observed === null ? null : observed * 100; }),
    drawdownPercent: value.drawdownSeries.map((row) => { const observed = chartValue(row.drawdown); return observed === null ? null : observed * 100; }),
    relativeNav,
    relativePerformancePercent: relativeNav?.map((observed) => observed === null ? null : (observed - 1) * 100) ?? null
  };
}
