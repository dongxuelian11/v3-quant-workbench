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
    profileName: "A_SHARE_DAILY_RESEARCH_V0";
    annualizationSessions: 252;
    volatilityDdoF: 1;
    riskFreePolicy: "ZERO_RISK_FREE_ASSUMPTION";
    sortinoTarget: "0";
    turnoverConvention: "GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV";
    numericPrecision: 12;
  };
  truthAdmission: {
    canonicalTruthState: "NOT_FORMAL";
    canonicalAdmissionState: "PRE_ALPHA";
  };
  metrics: Record<"totalReturn" | "annualizedReturn" | "annualizedVolatility" | "maxDrawdown" | "sharpe" | "sortino", AnalyticsMetricView>;
  returnSeries: readonly { sessionDate: string; nav: string; cumulativeReturn: string }[];
  drawdownSeries: readonly { sessionDate: string; drawdown: string }[];
  drawdownEpisode: { peakDate: string; troughDate: string; recoveryDate: string; durationSessions: number; recoveryStatus: "RECOVERED" };
  monthlyReturns: readonly { periodLabel: string; startDate: string; endDate: string; periodReturn: string }[];
  yearlyReturns: readonly { periodLabel: string; startDate: string; endDate: string; periodReturn: string }[];
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
    status: "AVAILABLE";
    name: string;
    seriesId: string;
    contentSha256: string;
    totalReturn: AnalyticsMetricView;
    trackingDifference: AnalyticsMetricView;
    trackingError: AnalyticsMetricView;
    alpha: AnalyticsMetricView;
    beta: AnalyticsMetricView;
    relativeReturns: readonly { sessionDate: string; relativeNav: string; sessionExcessReturn: AnalyticsMetricView }[];
  };
};

const available = (value: string): AnalyticsMetricView => ({ status: "AVAILABLE", value, reason: null });
const unavailable = (reason: string): AnalyticsMetricView => ({ status: "NOT_AVAILABLE", value: null, reason });

function exactIdentity(id: string, prefix: string, hash: string, name: string): void {
  if (!new RegExp(`^${prefix}[0-9a-f]{64}$`).test(id) || id !== `${prefix}${hash}`) throw new TypeError(`${name} identity is not exact`);
}

export function validateResultAnalyticsView(value: ResultAnalyticsView): ResultAnalyticsView {
  exactIdentity(value.analyticsId, "bra_sha256_", value.contentSha256, "analytics");
  exactIdentity(value.sourceResult.resultId, "btrr_sha256_", value.sourceResult.contentSha256, "result");
  exactIdentity(value.policy.policyId, "rap_sha256_", value.policy.contentSha256, "policy");
  exactIdentity(value.benchmark.seriesId, "bmsv_sha256_", value.benchmark.contentSha256, "benchmark");
  const dates = value.returnSeries.map((row) => row.sessionDate);
  if (dates.length < 2 || new Set(dates).size !== dates.length || dates.join("|") !== value.drawdownSeries.map((row) => row.sessionDate).join("|") || dates.join("|") !== value.benchmark.relativeReturns.map((row) => row.sessionDate).join("|")) throw new TypeError("Result Lab series dates are not exactly aligned");
  for (const numeric of [
    ...Object.values(value.metrics).map((metric) => metric.value),
    ...value.returnSeries.flatMap((row) => [row.nav, row.cumulativeReturn]),
    ...value.drawdownSeries.map((row) => row.drawdown),
    ...value.benchmark.relativeReturns.map((row) => row.relativeNav)
  ]) {
    if (numeric === null || !Number.isFinite(Number(numeric))) throw new TypeError("Result Lab contains a nonfinite available value");
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
    annualizationSessions: 252,
    volatilityDdoF: 1,
    riskFreePolicy: "ZERO_RISK_FREE_ASSUMPTION",
    sortinoTarget: "0",
    turnoverConvention: "GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV",
    numericPrecision: 12
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
    { sessionDate: "2026-01-29", nav: "100000", cumulativeReturn: "0" },
    { sessionDate: "2026-01-30", nav: "100200", cumulativeReturn: "0.002" },
    { sessionDate: "2026-02-02", nav: "99900", cumulativeReturn: "-0.001" },
    { sessionDate: "2026-02-03", nav: "100400", cumulativeReturn: "0.004" },
    { sessionDate: "2026-03-02", nav: "100100", cumulativeReturn: "0.001" },
    { sessionDate: "2026-03-03", nav: "100600", cumulativeReturn: "0.006" }
  ],
  drawdownSeries: [
    { sessionDate: "2026-01-29", drawdown: "0" },
    { sessionDate: "2026-01-30", drawdown: "0" },
    { sessionDate: "2026-02-02", drawdown: "-0.002994011976" },
    { sessionDate: "2026-02-03", drawdown: "0" },
    { sessionDate: "2026-03-02", drawdown: "-0.002988047809" },
    { sessionDate: "2026-03-03", drawdown: "0" }
  ],
  drawdownEpisode: { peakDate: "2026-01-30", troughDate: "2026-02-02", recoveryDate: "2026-02-03", durationSessions: 2, recoveryStatus: "RECOVERED" },
  monthlyReturns: [
    { periodLabel: "2026-01", startDate: "2026-01-29", endDate: "2026-01-30", periodReturn: "0.002" },
    { periodLabel: "2026-02", startDate: "2026-02-02", endDate: "2026-02-03", periodReturn: "0.001996007984" },
    { periodLabel: "2026-03", startDate: "2026-03-02", endDate: "2026-03-03", periodReturn: "0.001992031873" }
  ],
  yearlyReturns: [{ periodLabel: "2026", startDate: "2026-01-29", endDate: "2026-03-03", periodReturn: "0.006" }],
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
      { sessionDate: "2026-01-29", relativeNav: "1", sessionExcessReturn: unavailable("NO_PRIOR_SESSION") },
      { sessionDate: "2026-01-30", relativeNav: "1.000999000999", sessionExcessReturn: available("0.001") },
      { sessionDate: "2026-02-02", relativeNav: "0.998500749625", sessionExcessReturn: available("-0.002494511477") },
      { sessionDate: "2026-02-03", relativeNav: "1.001996007984", sessionExcessReturn: available("0.00350575463") },
      { sessionDate: "2026-03-02", relativeNav: "0.998503740648", sessionExcessReturn: available("-0.003487049805") },
      { sessionDate: "2026-03-03", relativeNav: "1.002991026919", sessionExcessReturn: available("0.004496251878") }
    ]
  }
});

export function buildResultChartSeries(value: ResultAnalyticsView) {
  return {
    dates: value.returnSeries.map((row) => row.sessionDate),
    nav: value.returnSeries.map((row) => Number(row.nav)),
    cumulativeReturnPercent: value.returnSeries.map((row) => Number(row.cumulativeReturn) * 100),
    drawdownPercent: value.drawdownSeries.map((row) => Number(row.drawdown) * 100),
    relativeNav: value.benchmark.relativeReturns.map((row) => Number(row.relativeNav)),
    relativePerformancePercent: value.benchmark.relativeReturns.map((row) => (Number(row.relativeNav) - 1) * 100)
  };
}
