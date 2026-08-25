import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  PRODUCT_NAVIGATION,
  productNavigationFor,
  selectCurrentProjectLabel,
  selectProductHomeNextAction,
} from "../../apps/desktop/src/renderer/productShellModel.ts";

test("PRODUCT navigation enables only the connected Home and gives every deferred page a reason", () => {
  assert.deepEqual(PRODUCT_NAVIGATION.map((item) => item.id), ["home", "data", "research", "backtest", "results"]);
  assert.deepEqual(PRODUCT_NAVIGATION.filter((item) => item.available).map((item) => item.id), ["home"]);
  for (const item of PRODUCT_NAVIGATION.filter((candidate) => !candidate.available)) {
    assert.match(item.reason, /^NOT_AVAILABLE · V1_1_C[23]_[A-Z_]+_NOT_CONNECTED$/);
  }
});

test("Data navigation becomes available only after the real Data product path is connected", () => {
  assert.deepEqual(productNavigationFor(false).filter((item) => item.available).map((item) => item.id), ["home"]);
  assert.deepEqual(productNavigationFor(true).filter((item) => item.available).map((item) => item.id), ["home", "data"]);
  assert.equal(productNavigationFor(true).find((item) => item.id === "research").reason, "NOT_AVAILABLE · V1_1_C2_FACTOR_NOT_CONNECTED");
  assert.deepEqual(productNavigationFor(true, true).filter((item) => item.available).map((item) => item.id), ["home", "data", "research"]);
  assert.equal(productNavigationFor(true, true).find((item) => item.id === "research").reason, null);
  assert.deepEqual(productNavigationFor(true, true, true).filter((item) => item.available).map((item) => item.id), ["home", "data", "research", "backtest"]);
  assert.equal(productNavigationFor(true, true, true).find((item) => item.id === "backtest").reason, null);
  assert.deepEqual(productNavigationFor(true, true, true, true).filter((item) => item.available).map((item) => item.id), ["home", "data", "research", "backtest", "results"]);
  assert.equal(productNavigationFor(true, true, true, true).find((item) => item.id === "results").reason, null);
});

test("Home labels only the currently bound project and never falls back to another project", () => {
  const projects = [
    { projectId: "prj_A", displayName: "项目 A" },
    { projectId: "prj_B", displayName: "项目 B" },
  ];
  assert.equal(selectCurrentProjectLabel({ projectId: "prj_B" }, projects), "项目 B");
  assert.equal(selectCurrentProjectLabel({ projectId: "prj_C" }, projects), "prj_C");
  assert.equal(selectCurrentProjectLabel(null, projects), "尚未绑定");
});

test("V1.1 Home is a canonical project overview with switching and one backend-derived next action", async () => {
  const source = await readFile(
    new URL("../../apps/desktop/src/renderer/components/ProductRuntimePanel.tsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /onNavigate/);
  assert.match(source, /dataHome/);
  assert.match(source, /最近数据/);
  assert.match(source, /最近研究/);
  assert.match(source, /最近策略/);
  assert.match(source, /最近回测与结果/);
  assert.match(source, /下一步/);
  assert.match(source, /切换项目/);
  assert.match(source, /selectProductHomeNextAction/);
  assert.match(source, /高级兼容入口（不属于 V1\.1 Golden Journey）/);
});

test("Home next action advances only from canonical Project Home states", () => {
  const base = {
    dataState: "EMPTY",
    dataUnavailableReason: "NO_SNAPSHOT",
    factorState: "EMPTY",
    factorUnavailableReason: "NO_SNAPSHOT",
    strategyState: "EMPTY",
    strategyUnavailableReason: "NO_FACTOR_STUDY",
    backtestState: "EMPTY",
    backtestUnavailableReason: "NO_RESEARCH_STRATEGY",
    backtest: null,
  };
  assert.deepEqual(selectProductHomeNextAction(null), {
    page: "home",
    label: "等待项目概览",
    reason: "PROJECT_HOME_NOT_READY",
  });
  assert.deepEqual(selectProductHomeNextAction(base), {
    page: "data",
    label: "导入研究数据",
    reason: "NO_SNAPSHOT",
  });
  assert.equal(selectProductHomeNextAction({ ...base, dataState: "AVAILABLE", factorUnavailableReason: "NO_FACTOR_STUDY" }).page, "research");
  assert.deepEqual(selectProductHomeNextAction({
    ...base,
    dataState: "AVAILABLE",
    factorState: "AVAILABLE",
  }), {
    page: "backtest",
    label: "创建研究策略",
    reason: "NO_FACTOR_STUDY",
  });
  assert.deepEqual(selectProductHomeNextAction({
    ...base,
    dataState: "AVAILABLE",
    factorState: "AVAILABLE",
    strategyState: "AVAILABLE",
  }), {
    page: "backtest",
    label: "运行研究回测",
    reason: "NO_RESEARCH_STRATEGY",
  });
  assert.deepEqual(selectProductHomeNextAction({
    ...base,
    dataState: "AVAILABLE",
    factorState: "AVAILABLE",
    strategyState: "AVAILABLE",
    backtestState: "AVAILABLE",
    backtest: { resultState: "VALID" },
  }), {
    page: "results",
    label: "查看最新有效结果",
    reason: "VALID_RESULT_AVAILABLE",
  });
});

test("Backtest workspace exposes owner policy bounds, preview-before-publish, and durable phase feedback", async () => {
  const source = await readFile(
    new URL("../../apps/desktop/src/renderer/components/ProductBacktestWorkspace.tsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /home\.backtestPolicyCoverage\.coverageStart/);
  assert.match(source, /min=\{allowedStart\}/);
  assert.match(source, /max=\{allowedEnd\}/);
  assert.match(source, /验证并生成编译预览/);
  assert.match(source, /disabled=\{busy \|\| !previewMatches\}/);
  assert.match(source, /尚未创建 Task 或发布 Artifact/);
  assert.match(source, /backtestProgress\?\.phase \?\? "QUEUED"/);
  assert.match(source, /COMPLETE · 4\/4/);
  assert.match(source, /从头重试/);
  assert.match(source, /isRetryableProductBacktestTask/);
});
