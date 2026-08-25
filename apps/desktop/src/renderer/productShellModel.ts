import type { ProductProjectHomeView } from "../../../../packages/contracts/src/index";

export type ProductPageId = "home" | "data" | "research" | "backtest" | "results";

export type ProductNavigationItem = Readonly<{
  id: ProductPageId;
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

export type ProductHomeNextAction = Readonly<{
  page: ProductPageId;
  label: string;
  reason: string;
}>;

export function selectProductHomeNextAction(
  home: ProductProjectHomeView | null,
): ProductHomeNextAction {
  if (home === null) {
    return Object.freeze({
      page: "home",
      label: "等待项目概览",
      reason: "PROJECT_HOME_NOT_READY",
    });
  }
  if (home.dataState !== "AVAILABLE") {
    return Object.freeze({
      page: "data",
      label: "导入研究数据",
      reason: home.dataUnavailableReason,
    });
  }
  if (home.factorState !== "AVAILABLE") {
    return Object.freeze({
      page: "research",
      label: "创建并运行因子研究",
      reason: home.factorUnavailableReason,
    });
  }
  if (home.strategyState !== "AVAILABLE") {
    return Object.freeze({
      page: "backtest",
      label: "创建研究策略",
      reason: home.strategyUnavailableReason,
    });
  }
  if (home.backtestState !== "AVAILABLE" || home.backtest?.resultState !== "VALID") {
    return Object.freeze({
      page: "backtest",
      label: "运行研究回测",
      reason: home.backtestUnavailableReason,
    });
  }
  return Object.freeze({
    page: "results",
    label: "查看最新有效结果",
    reason: "VALID_RESULT_AVAILABLE",
  });
}
