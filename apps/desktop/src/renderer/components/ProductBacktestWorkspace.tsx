import React, { useEffect, useMemo, useState } from "react";
import type { ProductStrategyPositionSizing } from "../../../../../packages/contracts/src/index";
import { isRetryableProductBacktestTask, useProductRuntime } from "../productRuntimeStore";

export function ProductBacktestWorkspace() {
  const home = useProductRuntime((state) => state.dataHome);
  const busy = useProductRuntime((state) => state.entryBusy);
  const strategyTask = useProductRuntime((state) => state.strategyTask);
  const backtestTask = useProductRuntime((state) => state.backtestTask);
  const backtestProgress = useProductRuntime((state) => state.backtestProgress);
  const backtestPreview = useProductRuntime((state) => state.backtestPreview);
  const backtestPreviewIntent = useProductRuntime((state) => state.backtestPreviewIntent);
  const error = useProductRuntime((state) => state.errorMessage);
  const strategyPreview = useProductRuntime((state) => state.strategyPreview);
  const strategyPreviewIntent = useProductRuntime((state) => state.strategyPreviewIntent);
  const previewStrategy = useProductRuntime((state) => state.previewResearchStrategy);
  const publishStrategy = useProductRuntime((state) => state.publishResearchStrategy);
  const runBacktest = useProductRuntime((state) => state.submitResearchBacktest);
  const previewBacktest = useProductRuntime((state) => state.previewResearchBacktest);
  const retryBacktest = useProductRuntime((state) => state.retryResearchBacktest);
  const booleanOutputs = useMemo(() => home?.factor?.outputs.filter((output) => output.outputType === "BOOLEAN_SERIES") ?? [], [home]);
  const [entryFactorId, setEntryFactorId] = useState("");
  const [exitFactorId, setExitFactorId] = useState("");
  const [positionSizing, setPositionSizing] = useState<ProductStrategyPositionSizing>("EQUAL_WEIGHT_ACTIVE_SIGNALS");
  const [maxPositions, setMaxPositions] = useState(10);
  const [grossExposure, setGrossExposure] = useState("1");
  const [initialCash, setInitialCash] = useState("1000000");
  const [assumptionProfileId, setAssumptionProfileId] = useState("");
  const [sessionStart, setSessionStart] = useState("");
  const [sessionEnd, setSessionEnd] = useState("");
  const [slippageBps, setSlippageBps] = useState("10");
  const [participation, setParticipation] = useState("0.1");
  const strategyIntent = useMemo(() => ({
    entrySignalFactorVersionId: entryFactorId,
    exitSignalFactorVersionId: exitFactorId,
    positionSizing,
    maxPositions,
    grossExposure,
    initialCash,
    assumptionProfileId,
  }), [entryFactorId, exitFactorId, positionSizing, maxPositions, grossExposure, initialCash, assumptionProfileId]);
  const previewMatches = strategyPreview !== null && strategyPreviewIntent !== null
    && strategyPreviewIntent.entrySignalFactorVersionId === strategyIntent.entrySignalFactorVersionId
    && strategyPreviewIntent.exitSignalFactorVersionId === strategyIntent.exitSignalFactorVersionId
    && strategyPreviewIntent.positionSizing === strategyIntent.positionSizing
    && strategyPreviewIntent.maxPositions === strategyIntent.maxPositions
    && strategyPreviewIntent.grossExposure === strategyIntent.grossExposure
    && strategyPreviewIntent.initialCash === strategyIntent.initialCash
    && strategyPreviewIntent.assumptionProfileId === strategyIntent.assumptionProfileId;
  const allowedStart = home?.data === null || home?.data === undefined
    ? ""
    : home.data.dateCoverageStart > home.backtestPolicyCoverage.coverageStart
      ? home.data.dateCoverageStart : home.backtestPolicyCoverage.coverageStart;
  const allowedEnd = home?.data === null || home?.data === undefined
    ? ""
    : home.backtestPolicyCoverage.coverageEnd !== null
      && home.backtestPolicyCoverage.coverageEnd < home.data.dateCoverageEnd
      ? home.backtestPolicyCoverage.coverageEnd : home.data.dateCoverageEnd;
  const backtestIntent = useMemo(() => ({
    sessionStart,
    sessionEnd,
    slippageBps,
    dailyVolumeParticipationRate: participation,
  }), [sessionStart, sessionEnd, slippageBps, participation]);
  const backtestPreviewMatches = backtestPreview !== null && backtestPreviewIntent !== null
    && home?.strategy?.researchStrategySpecId === backtestPreview.researchStrategySpecId
    && backtestPreviewIntent.sessionStart === backtestIntent.sessionStart
    && backtestPreviewIntent.sessionEnd === backtestIntent.sessionEnd
    && backtestPreviewIntent.slippageBps === backtestIntent.slippageBps
    && backtestPreviewIntent.dailyVolumeParticipationRate === backtestIntent.dailyVolumeParticipationRate;

  useEffect(() => {
    if (!booleanOutputs.some((output) => output.factorDefinitionVersionId === entryFactorId)) {
      setEntryFactorId(booleanOutputs[0]?.factorDefinitionVersionId ?? "");
    }
    if (!booleanOutputs.some((output) => output.factorDefinitionVersionId === exitFactorId)) {
      setExitFactorId(booleanOutputs[1]?.factorDefinitionVersionId ?? booleanOutputs[0]?.factorDefinitionVersionId ?? "");
    }
  }, [booleanOutputs, entryFactorId, exitFactorId]);

  useEffect(() => {
    if (home?.data !== null && home?.data !== undefined) {
      setSessionStart(allowedStart);
      setSessionEnd(allowedEnd);
    }
  }, [allowedStart, allowedEnd, home?.data]);

  const strategyReady = home?.factorState === "AVAILABLE" && booleanOutputs.length > 0;
  const backtestReady = home?.strategyState === "AVAILABLE" && home.strategy !== null;
  const profile = home?.strategyAuthoringProfile;
  const retryableBacktest = isRetryableProductBacktestTask(backtestTask);

  useEffect(() => {
    if (profile === undefined) {
      setAssumptionProfileId("");
      return;
    }
    if (!profile.assumptionProfiles.some((item) => item.assumptionProfileId === assumptionProfileId)) {
      setAssumptionProfileId(profile.profileRefs.assumptionProfileId);
    }
  }, [profile, assumptionProfileId]);

  return <main className="product-c3-workspace" data-product-page="backtest">
    <header className="product-c3-heading">
      <div>
        <small>STRATEGY → BACKTEST · PRODUCT_CONNECTED</small>
        <h1>策略与回测</h1>
        <p>表单只表达研究意图。Universe、成本、执行、风险与假设引用来自当前 Project Home；权重、行情与结果由 canonical owners 生成。</p>
      </div>
      <div className="product-c3-badges"><span>PRE_ALPHA</span><span>RESEARCH_ONLY</span><span>NOT_FORMAL</span></div>
    </header>

    <section className="product-c3-stage" aria-labelledby="strategy-authoring-title">
      <div className="product-c3-stage-title">
        <span>01</span><div><h2 id="strategy-authoring-title">发布研究策略</h2><p>{home?.strategyState ?? "UNAVAILABLE"} · {home?.strategyUnavailableReason ?? "PROJECT_HOME_NOT_AVAILABLE"}</p></div>
      </div>
      <div className="product-c3-form">
        <label>入场布尔因子<select value={entryFactorId} disabled={busy || !strategyReady} onChange={(event) => setEntryFactorId(event.target.value)}>{booleanOutputs.map((output) => <option key={output.factorDefinitionVersionId} value={output.factorDefinitionVersionId}>{output.name}</option>)}</select></label>
        <label>离场布尔因子<select value={exitFactorId} disabled={busy || !strategyReady} onChange={(event) => setExitFactorId(event.target.value)}>{booleanOutputs.map((output) => <option key={output.factorDefinitionVersionId} value={output.factorDefinitionVersionId}>{output.name}</option>)}</select></label>
        <label>持仓方法<select value={positionSizing} disabled={busy} onChange={(event) => {
          const next = event.target.value as ProductStrategyPositionSizing;
          setPositionSizing(next);
          if (next === "SINGLE_ASSET_FULL_WEIGHT") setMaxPositions(1);
        }}>{profile?.positionSizingOptions.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
        <label>最大持仓数<input type="number" min={profile?.maxPositionsMin ?? 1} max={profile?.maxPositionsMax ?? 20} value={maxPositions} disabled={busy || positionSizing === "SINGLE_ASSET_FULL_WEIGHT"} onChange={(event) => setMaxPositions(Number(event.target.value))} /></label>
        <label>总敞口<input inputMode="decimal" value={grossExposure} disabled={busy} onChange={(event) => setGrossExposure(event.target.value)} /></label>
        <label>初始资金 CNY<input inputMode="decimal" value={initialCash} disabled={busy} onChange={(event) => setInitialCash(event.target.value)} /></label>
        <label>执行假设<select value={assumptionProfileId} disabled={busy || !strategyReady} onChange={(event) => setAssumptionProfileId(event.target.value)}>{profile?.assumptionProfiles.map((item) => <option key={item.assumptionProfileId} value={item.assumptionProfileId}>{item.mode === "STRICT_FAIL_CLOSED" ? "严格缺失即拒绝 · STRICT_FAIL_CLOSED" : "研究近似 · RESEARCH_APPROXIMATE"}</option>)}</select></label>
      </div>
      <div className="product-c3-command-row">
        <button type="button" disabled={busy || !strategyReady || entryFactorId.length === 0 || exitFactorId.length === 0 || assumptionProfileId.length === 0} onClick={() => { void previewStrategy(strategyIntent); }}>{busy ? "正在验证…" : "验证并生成编译预览"}</button>
        <button type="button" disabled={busy || !previewMatches} onClick={() => { void publishStrategy(strategyIntent); }}>{strategyTask !== null && !["SUCCEEDED", "FAILED", "CANCELLED"].includes(strategyTask.state) ? `策略任务 · ${strategyTask.state}` : busy ? "正在发布…" : "确认发布策略"}</button>
        <span>{booleanOutputs.length === 0 ? "需要已发布的 BOOLEAN_SERIES 因子" : previewMatches ? "预览与当前输入一致，可确认发布" : `${booleanOutputs.length} 个 canonical 布尔输出可用 · 修改后须重新验证`}</span>
      </div>
      {previewMatches && strategyPreview !== null && <dl className="product-c3-lineage" aria-label="策略编译预览">
        <div><dt>策略规范预览</dt><dd>{strategyPreview.researchStrategySpecId}</dd></div>
        <div><dt>编译定义预览</dt><dd>{strategyPreview.strategyDefinitionVersionId}</dd></div>
        <div><dt>状态迁移 / 计划决策</dt><dd>{strategyPreview.transitionCount} / {strategyPreview.plannedDecisionChainCount}</dd></div>
        <div><dt>副作用</dt><dd>{strategyPreview.sideEffects} · 尚未创建 Task 或发布 Artifact</dd></div>
      </dl>}
      {home?.strategy !== null && home?.strategy !== undefined && <dl className="product-c3-lineage">
        <div><dt>策略规范 · StrategySpec</dt><dd>{home.strategy.researchStrategySpecId}</dd></div>
        <div><dt>策略版本 · StrategyVersion</dt><dd>{home.strategy.strategyVersionId}</dd></div>
        <div><dt>决策 / 状态迁移</dt><dd>{home.strategy.decisionChainCount} / {home.strategy.transitionCount}</dd></div>
        <div><dt>执行假设</dt><dd>{profile?.assumptionProfiles.find((item) => item.assumptionProfileId === home.strategy?.profileRefs.assumptionProfileId)?.mode ?? "NOT_AVAILABLE"}</dd></div>
      </dl>}
    </section>

    <section className="product-c3-stage" aria-labelledby="research-backtest-title">
      <div className="product-c3-stage-title">
        <span>02</span><div><h2 id="research-backtest-title">运行研究回测</h2><p>{home?.backtestState ?? "EMPTY"} · {home?.backtestUnavailableReason ?? "NO_RESEARCH_STRATEGY"}</p></div>
      </div>
      <div className="product-c3-form">
        <label>开始日期<input type="date" min={allowedStart} max={allowedEnd} value={sessionStart} disabled={busy || !backtestReady} onChange={(event) => setSessionStart(event.target.value)} /></label>
        <label>结束日期<input type="date" min={allowedStart} max={allowedEnd} value={sessionEnd} disabled={busy || !backtestReady} onChange={(event) => setSessionEnd(event.target.value)} /></label>
        <label>滑点 bps<input inputMode="decimal" value={slippageBps} disabled={busy || !backtestReady} onChange={(event) => setSlippageBps(event.target.value)} /></label>
        <label>日成交量参与率<input inputMode="decimal" value={participation} disabled={busy || !backtestReady} onChange={(event) => setParticipation(event.target.value)} /></label>
      </div>
      <div className="product-c3-command-row">
        <button type="button" disabled={busy || !backtestReady || sessionStart.length === 0 || sessionEnd.length === 0} onClick={() => { void previewBacktest(backtestIntent); }}>{busy ? "正在预检…" : "运行前预检"}</button>
        <button type="button" disabled={busy || !backtestPreviewMatches} onClick={() => { void runBacktest(backtestIntent); }}>{backtestTask !== null && !["SUCCEEDED", "FAILED", "CANCELLED"].includes(backtestTask.state) ? `回测任务 · ${backtestProgress?.phase ?? "QUEUED"}${backtestProgress === null ? "" : ` · ${backtestProgress.completedUnits}/${backtestProgress.totalUnits}`}` : backtestTask?.state === "SUCCEEDED" ? "回测任务 · COMPLETE · 4/4" : busy ? "正在执行…" : "运行研究回测"}</button>
        {retryableBacktest && <button type="button" disabled={busy} onClick={() => { void retryBacktest(); }}>从头重试</button>}
        <span>允许区间 {allowedStart || "NOT_AVAILABLE"} 至 {allowedEnd || "NOT_AVAILABLE"} · 下一已准入开盘执行 · checkpoint UNAVAILABLE</span>
      </div>
      <dl className="product-c3-lineage" aria-label="回测输入与准入">
        <div><dt>StrategyVersion</dt><dd>{home?.strategy?.strategyVersionId ?? "NOT_AVAILABLE"}</dd></div>
        <div><dt>Snapshot / Universe</dt><dd>{home?.strategy?.snapshotId ?? "NOT_AVAILABLE"} / {home?.strategy?.universeVersionId ?? "NOT_AVAILABLE"}</dd></div>
        <div><dt>Policy coverage</dt><dd>{home?.backtestPolicyCoverage.ruleProfileId ?? "NOT_AVAILABLE"} · {allowedStart || "NOT_AVAILABLE"} 至 {allowedEnd || "NOT_AVAILABLE"}</dd></div>
        <div><dt>佣金 / 最低佣金 / 卖出印花税</dt><dd>{home?.backtestPolicyCoverage.commissionRate ?? "NOT_AVAILABLE"} / {home?.backtestPolicyCoverage.minimumCommissionCny ?? "NOT_AVAILABLE"} CNY / {home?.backtestPolicyCoverage.stampDutySellRate ?? "NOT_AVAILABLE"}</dd></div>
        <div><dt>资源估算</dt><dd>{home == null ? "NOT_AVAILABLE" : `${home.backtestPolicyCoverage.resourceEstimate.cpuSlots} CPU · ${home.backtestPolicyCoverage.resourceEstimate.memoryLimitBytes} B memory · ${home.backtestPolicyCoverage.resourceEstimate.scratchLimitBytes} B scratch`}</dd></div>
        <div><dt>预检状态</dt><dd>{backtestPreviewMatches ? "PASS · side effects NONE" : "NOT_RUN · 修改输入后须重新预检"}</dd></div>
      </dl>
      {backtestTask?.state === "FAILED" && <dl className="product-c3-lineage" aria-label="回测失败详情">
        <div><dt>失败类别</dt><dd>{backtestTask.attempt.errorCategory ?? "INTERNAL_ERROR"}</dd></div>
        <div><dt>Attempt</dt><dd>{backtestTask.attempt.ordinal} · {backtestTask.attempt.attemptId ?? "NOT_AVAILABLE"}</dd></div>
        <div><dt>可执行动作</dt><dd>{retryableBacktest ? "Retry from start · NEW_ATTEMPT_SAME_RUN_FROM_START" : "查看错误详情 · 当前失败不可自动重试"}</dd></div>
      </dl>}
      {home?.backtest !== null && home?.backtest !== undefined && <dl className="product-c3-lineage">
        <div><dt>有效结果 · VALID Result</dt><dd>{home.backtest.resultId}</dd></div>
        <div><dt>回测引擎 · Engine</dt><dd>{home.backtest.engineVersion}</dd></div>
        <div><dt>执行假设</dt><dd>{home.backtest.assumptionMode}</dd></div>
        <div><dt>订单 / 成交 / 诊断</dt><dd>{home.backtest.orderCount} / {home.backtest.fillCount} / {home.backtest.diagnosticCount}</dd></div>
      </dl>}
    </section>
    {error !== null && <p className="product-c3-error" role="alert">{error}</p>}
  </main>;
}
