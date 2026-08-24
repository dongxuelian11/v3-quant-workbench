export type ProductNavigationItem = Readonly<{
  id: "home" | "data" | "research" | "backtest" | "results";
  label: string;
  available: boolean;
  reason: string | null;
}>;

export const PRODUCT_NAVIGATION: readonly ProductNavigationItem[] = Object.freeze([
  Object.freeze({ id: "home", label: "首页 / 项目", available: true, reason: null }),
  Object.freeze({ id: "data", label: "数据", available: false, reason: "NOT_AVAILABLE · V1_1_C2_DATA_NOT_CONNECTED" }),
  Object.freeze({ id: "research", label: "研究", available: false, reason: "NOT_AVAILABLE · V1_1_C2_FACTOR_NOT_CONNECTED" }),
  Object.freeze({ id: "backtest", label: "回测", available: false, reason: "NOT_AVAILABLE · V1_1_C3_BACKTEST_NOT_CONNECTED" }),
  Object.freeze({ id: "results", label: "结果", available: false, reason: "NOT_AVAILABLE · V1_1_C3_RESULTS_NOT_CONNECTED" }),
]);

export function productNavigationFor(
  dataConnected: boolean,
  factorConnected = false,
  backtestConnected = false,
  resultsConnected = false
): readonly ProductNavigationItem[] {
  return Object.freeze(PRODUCT_NAVIGATION.map((item) => (
    (item.id === "data" && dataConnected)
      || (item.id === "research" && factorConnected)
      || (item.id === "backtest" && backtestConnected)
      || (item.id === "results" && resultsConnected)
  ) ? Object.freeze({ ...item, available: true, reason: null }) : item));
}

export function selectCurrentProjectLabel(
  boundProject: Readonly<{ projectId: string }> | null,
  projects: readonly Readonly<{ projectId: string; displayName: string }>[],
): string {
  if (boundProject === null) return "尚未绑定";
  return projects.find((project) => project.projectId === boundProject.projectId)?.displayName
    ?? boundProject.projectId;
}
