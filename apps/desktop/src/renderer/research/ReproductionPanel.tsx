import React, { useEffect, useRef, useState } from "react";
import type { JsonObject, ReproductionPlan, ReproductionRun, ReproductionStepAttempt, ReproductionVariant, WorkspacePanel } from "../../../../../packages/contracts/src/research";
import { errorText, request, useResearch } from "./state";
import { useWorkspace } from "./workspace";
import { fieldLabel } from "./ui";
import "./reproduction.css";

const variants: Record<ReproductionVariant, string> = { original: "原文条件复现", adapted: "用户选定适配", post_publication: "发布后独立检验", execution: "V3 现实成交口径" };
const statuses: Record<string, string> = { pending: "等待前置步骤", queued: "排队中", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断" };
const terminalStatuses: ReproductionStepAttempt["status"][] = ["failed", "interrupted", "cancelled"];
const canRetryFailed = (run: ReproductionRun) =>
  terminalStatuses.includes(run.status) &&
  !run.cancelPending &&
  run.steps.some(step => terminalStatuses.includes(step.status) && !!step.jobId);
const parameterLabels: Record<string, string> = {
  template: "复现模板",
  topN: "选取数量",
  rebalance: "调仓频率",
  capital: "初始资金",
  updateData: "准备数据时更新"
};
const hiddenParameterKeys = new Set(["code", "dailyCode"]);
function stepName(plan: ReproductionPlan, id: string) { return plan.steps.find(step => step.id === id)?.name || id; }
function stepReadinessText(plan: ReproductionPlan, id: string, dirty: boolean) {
  const globalMissing = plan.missingConditions.filter(value => value.trim());
  if (globalMissing.length) return "全局缺项阻断全部步骤：" + globalMissing.join("、");
  const localMissing = plan.steps.find(step => step.id === id)?.missingConditions?.filter(value => value.trim()) ?? [];
  if (localMissing.length) return "本步骤缺少条件：" + localMissing.join("、");
  if (dirty) return "草稿未保存；保存后重新检查此修订的就绪状态";
  const blocked = plan.readiness?.blockedSteps.find(item => item.stepId === id);
  if (blocked) {
    const reasons: string[] = [];
    if (blocked.missingConditions.length) reasons.push("缺少条件：" + blocked.missingConditions.join("、"));
    if (blocked.blockedByStepIds.length) reasons.push("依赖未就绪：" + blocked.blockedByStepIds.map(value => stepName(plan, value)).join("、"));
    return "不可运行：" + (reasons.join("；") || "后端未提供原因");
  }
  if (plan.readiness?.runnableStepIds.includes(id)) return "可运行";
  return plan.readiness ? "未返回此步骤就绪状态" : "后端未提供步骤就绪信息";
}
function runScopeDetails(run: ReproductionRun, plan: ReproductionPlan) {
  const subset = run.executionScope === "subset" || (run.executionScope === undefined && run.selectedStepIds !== undefined);
  const planMatches = run.revision === plan.revision;
  const nameForId = (id: string) => planMatches ? stepName(plan, id) : id;
  const selectedIds = run.selectedStepIds ?? [];
  const canDeriveExcluded = subset && planMatches && run.excludedStepIds === undefined;
  const excludedIds = run.excludedStepIds ?? (canDeriveExcluded ? plan.steps.filter(step => !selectedIds.includes(step.id)).map(step => step.id) : []);
  return {
    subset,
    selectedKnown: run.selectedStepIds !== undefined,
    excludedKnown: !subset || run.excludedStepIds !== undefined || canDeriveExcluded,
    selectedNames: selectedIds.map(nameForId),
    excludedNames: excludedIds.map(nameForId),
    nameForId
  };
}
function workSummary(work: NonNullable<ReproductionPlan["plannedWork"]>) {
  return "试参 " + work.trials + " 次 · 训练 " + work.trainingTasks + " 个任务 · 回测 " + work.backtestTasks + " 个任务 · 滚动 " + work.rollingTasks + " 个任务";
}
function selectedWork(steps: ReproductionPlan["steps"]) {
  const work = { trials: 0, trainingTasks: 0, backtestTasks: 0, rollingTasks: 0 };
  for (const { spec } of steps) {
    if (spec.kind === "optimize.run") {
      const trials = spec.parameters.trials ?? 20;
      if (typeof trials !== "number" || !Number.isInteger(trials) || trials < 1) return null;
      work.trials += trials;
    }
    work.trainingTasks += Number(spec.kind === "model.train");
    work.backtestTasks += Number(spec.kind === "backtest.run");
    const validation = spec.parameters.validation;
    work.rollingTasks += Number(!!validation && typeof validation === "object" && !Array.isArray(validation) && validation.mode === "rolling");
  }
  return work;
}

export function ReproductionPanel({ panel }: { panel: WorkspacePanel }) {
  const s = useResearch(), w = useWorkspace(), projectId = panel.projectId;
  const [plans, setPlans] = useState<ReproductionPlan[]>([]), [plan, setPlan] = useState<ReproductionPlan | null>(null);
  const [saved, setSaved] = useState(""), [runs, setRuns] = useState<ReproductionRun[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const [newerPlan, setNewerPlan] = useState<ReproductionPlan | null>(null);
  const [runScope, setRunScope] = useState<"full" | "subset">("full"), [selectedStepIds, setSelectedStepIds] = useState<string[]>([]);
  const current = useRef({ plan, saved });current.current = { plan, saved };
  const loadVersion = useRef(0);
  const planId = panel.reproductionId;
  const dirty = !!plan && JSON.stringify(plan) !== saved;
  useEffect(() => {
    let alive = true;setError("");
    if (!projectId) return;
    void request<ReproductionPlan[]>("reproductions.list", { projectId }).then(value => { if (alive) setPlans(value); }).catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [projectId, revision, s.revision, panel]);
  useEffect(() => {
    setPlan(null);setSaved("");setNewerPlan(null);setRuns([]);setError("");setRunScope("full");setSelectedStepIds([]);
    current.current = { plan: null, saved: "" };
  }, [projectId, planId]);
  useEffect(() => { setRunScope("full");setSelectedStepIds([]); }, [projectId, planId, plan?.revision]);
  useEffect(() => {
    let alive = true;const version = ++loadVersion.current;
    if (!projectId || !planId) return;
    void request<ReproductionPlan>("reproductions.get", { projectId, planId }).then(value => {
      if (!alive || version !== loadVersion.current) return;
      const draft = current.current;
      if (draft.plan && JSON.stringify(draft.plan) !== draft.saved) {
        setNewerPlan(value.revision > draft.plan.revision ? value : null);
        return;
      }
      if (draft.plan && value.revision < draft.plan.revision) return;
      setPlan(value);setSaved(JSON.stringify(value));setNewerPlan(null);
    }).catch(e => { if (alive && version === loadVersion.current) setError(errorText(e)); });
    return () => { alive = false; };
    // Dockview replaces panel parameters when an existing plan tab is reopened.
  }, [projectId, planId, revision, panel]);
  useEffect(() => {
    let alive = true, loading = false;
    if (!projectId || !planId) return;
    async function refresh() { if (loading) return;loading = true;try { const value = await request<ReproductionRun[]>("reproductions.runs", { projectId, planId });if (alive) setRuns(value); } catch (e) { if (alive) setError(errorText(e)); } finally { loading = false; } }
    void refresh();const timer = setInterval(() => { if (!document.hidden) void refresh(); }, 3000);
    return () => { alive = false;clearInterval(timer); };
  }, [projectId, planId, revision]);
  async function act(fn: () => Promise<void>) { if (busy) return;setBusy(true);setError("");try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } }
  async function save() {
    if (!plan || !projectId) return;
    ++loadVersion.current;
    const next = await request<ReproductionPlan>("reproductions.save", { projectId, plan });
    setPlan(next);setSaved(JSON.stringify(next));setNewerPlan(null);setRevision(v => v + 1);
  }
  function editStep(index: number, edit: (step: ReproductionPlan["steps"][number]) => ReproductionPlan["steps"][number]) { setPlan(value => value ? { ...value, steps: value.steps.map((step, i) => i === index ? edit(step) : step) } : value); }
  async function discuss() {
    await w.savePreferences({ aiVisible: true, rightPanel: "ai" });
    window.dispatchEvent(new CustomEvent("v3-ai-draft-append", { detail: { projectId, ref:{kind:"reproduction",projectId,reportId:plan?.reportId??panel.reportId,reproductionId:plan?.id,title:plan?.name??"研报复现"}, text: `请调用研报读取工具核对原文，围绕核心结论和关键检验${plan ? "修订" : "生成并保存"}复现计划，先展示引用页码、原文条件、缺失条件和适配选项，不执行。研报ID：${plan?.reportId ?? panel.reportId ?? "请先选择研报"}。${plan ? `计划ID：${plan.id}，当前修订：${plan.revision}。` : ""}原文复现、选定适配、发布后独立检验、现实成交口径分别保存；不要用发布后数据选参。` } }));
  }
  if (!projectId) return <div className="r-page"><h1>研报复现</h1><p>请从研报原文选择一个研究项目。</p></div>;
  const visiblePlans = plans.filter(item => !panel.reportId || item.reportId === panel.reportId);
  const globalMissing = plan?.missingConditions.filter(value => value.trim()) ?? [];
  const allStepIds = new Set(plan?.steps.map(step => step.id) ?? []);
  const selectedSteps = plan?.steps.filter(step => selectedStepIds.includes(step.id)) ?? [];
  const selectedWorkEstimate = selectedWork(selectedSteps);
  const selectedDependencyGaps = selectedSteps.flatMap(step => step.dependsOn.filter(id => !selectedStepIds.includes(id)).map(dependencyId => ({ stepId: step.id, dependencyId })));
  const canSelectSubsetStep = (step: ReproductionPlan["steps"][number]) =>
    !globalMissing.length &&
    !(step.missingConditions ?? []).some(value => value.trim()) &&
    (!plan?.readiness || plan.readiness.runnableStepIds.includes(step.id));
  const selectedBlockedSteps = selectedSteps.filter(step => !canSelectSubsetStep(step));
  const invalidPlanDependencies = plan?.steps.flatMap(step => step.dependsOn.filter(id => !allStepIds.has(id))) ?? [];
  const readinessBlocked = plan?.readiness?.blockedSteps ?? [];
  const classifiedReadinessIds = new Set([...(plan?.readiness?.runnableStepIds ?? []), ...readinessBlocked.map(item => item.stepId)]);
  const fullReadinessBlocked = !!plan?.readiness && (
    readinessBlocked.some(item => item.missingConditions.some(value => value.trim()) || item.blockedByStepIds.some(id => !allStepIds.has(id))) ||
    (plan?.steps ?? []).some(step => !classifiedReadinessIds.has(step.id))
  );
  const fullExecutionBlocked = !plan || globalMissing.length > 0 ||
    !!plan?.steps.some(step => (step.missingConditions ?? []).some(value => value.trim())) ||
    invalidPlanDependencies.length > 0 || fullReadinessBlocked;
  const activeRunExists = !!plan && runs.some(run => run.revision === plan.revision && (run.status === "running" || run.cancelPending));
  const subsetExecutionBlocked = !plan || globalMissing.length > 0 || selectedSteps.length === 0 ||
    selectedBlockedSteps.length > 0 || selectedDependencyGaps.length > 0;
  return <div className="r-page r-reproduction-page"><header className="r-toolbar"><h1>研报复现</h1><span className="r-spacer" /><button onClick={() => void discuss()}>与助手讨论方案</button><button disabled={busy} onClick={() => setRevision(v => v + 1)}>刷新计划</button></header><p className="r-note">{s.projects.find(item => item.id === projectId)?.name ?? projectId} · 核心结论与关键检验。已保存的运行绑定当时计划修订，修改不会改变旧结果。</p><select aria-label="复现计划" value={planId ?? ""} onChange={e => w.updatePanel(panel.id, { reproductionId: e.target.value || undefined })}><option value="">选择已保存计划</option>{visiblePlans.map(item => <option key={item.id} value={item.id}>{item.name} · 修订 {item.revision}</option>)}</select>{error && <p role="alert">{error}</p>}{!plan && <p>{visiblePlans.length ? "选择一个计划查看条件与步骤。" : "此研报在当前项目尚无复现计划。可与助手讨论，先读取原文再保存方案。"}</p>}{plan && <>{newerPlan && <div role="status"><p>已有已保存修订 {newerPlan.revision}，当前草稿基于修订 {plan.revision}。未保存修改已保留；请先复制需要保留的内容，再载入最新修订。</p><button disabled={busy} onClick={() => { setPlan(newerPlan);setSaved(JSON.stringify(newerPlan));setNewerPlan(null); }}>放弃当前草稿并载入修订 {newerPlan.revision}</button></div>}<div className="r-report-filters"><label>计划名称<input value={plan.name} onChange={e => setPlan({ ...plan, name: e.target.value })} /></label><label>研究目标<textarea value={plan.objective} onChange={e => setPlan({ ...plan, objective: e.target.value })} /></label></div><label className="r-reproduction-missing">仍缺少的条件（每行一项，解决后再移除）<textarea value={plan.missingConditions.join("\n")} onChange={e => setPlan({ ...plan, missingConditions: e.target.value.split("\n").filter(value => value.trim()) })} /></label>{plan.missingConditions.length > 0 && <p className="r-note">尚有 {plan.missingConditions.length} 项缺失条件，暂不能启动。缺少逐日数列时只对照原图或已发表指标。</p>}<div className="r-reproduction-scope"><h2>执行范围</h2><div className="r-toolbar" role="group" aria-label="运行步骤范围"><button type="button" aria-pressed={runScope === "full"} onClick={() => setRunScope("full")}>完整计划</button><button type="button" aria-pressed={runScope === "subset"} onClick={() => setRunScope("subset")}>选择步骤子集</button></div>{runScope === "subset" && <fieldset className="r-reproduction-checklist" disabled={busy || dirty || !!newerPlan}><legend>明确选择本次运行步骤，不会自动补选依赖</legend>{plan.steps.map(step => { const selected = selectedStepIds.includes(step.id);return <label className="r-reproduction-choice" key={step.id}><input type="checkbox" checked={selected} disabled={!canSelectSubsetStep(step) && !selected} onChange={event => setSelectedStepIds(ids => event.target.checked ? [...ids, step.id] : ids.filter(id => id !== step.id))} /><span><strong>{step.name || step.id}</strong><small>{stepReadinessText(plan, step.id, dirty)}</small></span></label>;})}</fieldset>}{runScope === "subset" ? <div className="r-note"><p>已选 {selectedSteps.length} 步：{selectedSteps.map(step => step.name).join("、") || "尚未选择"}</p><p>不执行：{plan.steps.filter(step => !selectedStepIds.includes(step.id)).map(step => step.name).join("、") || "无"}</p><p>本次工作量估算：{selectedWorkEstimate ? workSummary(selectedWorkEstimate) : "参数不完整，请先核对"}。实际预留由服务确认，失败与重试仍计入额度。</p></div> : <p className="r-note">{plan.plannedWork ? "完整计划工作量估算：" + workSummary(plan.plannedWork) : "完整计划工作量估算暂不可用。"}</p>}{runScope === "subset" && selectedDependencyGaps.length > 0 && <p role="alert">所选步骤依赖未选步骤：{selectedDependencyGaps.map(item => stepName(plan, item.stepId) + " → " + stepName(plan, item.dependencyId)).join("、")}。请手动选择依赖；不会自动补选。</p>}{runScope === "subset" && selectedBlockedSteps.length > 0 && <p role="alert">所选步骤当前不可运行：{selectedBlockedSteps.map(step => stepName(plan, step.id)).join("、")}。请先补齐条件或重新选择。</p>}{invalidPlanDependencies.length > 0 && <p role="alert">计划依赖了不存在的步骤：{invalidPlanDependencies.join("、")}。</p>}<div className="r-toolbar"><button disabled={busy || !!newerPlan || !dirty || !plan.name.trim()} onClick={() => void act(save)}>保存新修订</button><span>{dirty ? "有未保存修改" : "已保存修订 " + plan.revision}</span><button className="r-primary" disabled={busy || !!newerPlan || dirty || activeRunExists || (runScope === "full" ? fullExecutionBlocked : subsetExecutionBlocked)} onClick={() => void act(async () => { const frozen = { projectId, planId: plan.id, revision: plan.revision };const payload = runScope === "subset" ? { ...frozen, selectedStepIds: [...selectedStepIds] } : frozen;await request<ReproductionRun>("reproductions.run", payload);setRevision(value => value + 1); })}>{runScope === "subset" ? "运行选中步骤" : "启动完整计划"}</button></div></div><ol className="r-reproduction-steps">{plan.steps.map((step, index) => <li key={step.id}><div className="r-toolbar"><input aria-label={`步骤 ${index + 1} 名称`} value={step.name} onChange={e => editStep(index, value => ({ ...value, name: e.target.value }))} /><select aria-label={`步骤 ${index + 1} 口径`} value={step.variant} onChange={e => editStep(index, value => ({ ...value, variant: e.target.value as ReproductionVariant }))}>{Object.entries(variants).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div><p className="r-note">前置步骤：{step.dependsOn.map(id => plan.steps.find(item => item.id === id)?.name ?? id).join("、") || "无"}</p><label>与原文条件的差异<textarea value={step.differences.join("\n")} onChange={e => editStep(index, value => ({ ...value, differences: e.target.value.split("\n").filter(Boolean) }))} /></label><label>本步骤缺少条件（每行一项）<textarea value={(step.missingConditions ?? []).join("\n")} onChange={event => editStep(index, value => ({ ...value, missingConditions: event.target.value.split("\n").map(item => item.trim()).filter(Boolean) }))} /></label><p className="r-note" role="status">{stepReadinessText(plan, step.id, dirty)}</p><div className="r-report-filters">{Object.entries(step.spec.parameters).filter(([key, value]) => !hiddenParameterKeys.has(key) && ["string", "number", "boolean"].includes(typeof value)).map(([key, value]) => <label key={key}>{parameterLabels[key] ?? fieldLabel(key)}{key==="labelMode"?<select aria-label={`步骤 ${index+1} 标签口径`} value={String(value)} onChange={e=>editStep(index,step=>({...step,spec:{...step.spec,parameters:{...step.spec.parameters,labelMode:e.target.value}}}))}>{!["next_open","close"].includes(String(value))&&<option disabled value={String(value)}>未识别口径：{String(value)}</option>}<option value="next_open">下一开盘起算</option><option value="close">收盘到收盘（研究）</option></select>:typeof value === "boolean" ? <input type="checkbox" checked={value} onChange={e => editStep(index, step => ({ ...step, spec: { ...step.spec, parameters: { ...step.spec.parameters, [key]: e.target.checked } } }))} /> : <input type={typeof value === "number" ? "number" : /date$/i.test(key) ? "date" : "text"} value={String(value)} onChange={e => { const next = typeof value === "number" ? Number(e.target.value) : e.target.value;if (typeof next === "number" && !Number.isFinite(next)) return;editStep(index, step => ({ ...step, spec: { ...step.spec, parameters: { ...step.spec.parameters, [key]: next } as JsonObject } })); }} />}</label>)}</div><details><summary>完整运行参数</summary><pre>{JSON.stringify(step.spec, null, 2)}</pre></details><div className="r-toolbar">{step.citations.map((citation, i) => <button key={i} title={citation.excerpt} onClick={() => w.open({ kind: "report", title: "核对原文", projectId, reportId: citation.reportId, page: citation.page })}>原文第 {citation.page} 页</button>)}</div></li>)}</ol><h2>已保存运行</h2><p className="r-note">恢复此冻结修订会续接同次尝试；重试只针对已终止且有任务记录的步骤，保留已完成步骤并按新一次尝试计入预算。</p>{!runs.length && <p className="r-note">尚未执行。</p>}{runs.map(run => <section className="r-reproduction-run" key={run.runId}>
  <div className="r-toolbar">
    <strong>修订 {run.revision} · {runScopeDetails(run, plan).subset && run.status === "completed" ? "本次子集已完成" : statuses[run.status] ?? run.status}</strong>
    {run.cancelPending
      ? <button disabled={busy} onClick={() => void act(async () => { await request("reproductions.cancel", { projectId, runId: run.runId, planId: run.planId });setRevision(v => v + 1); })}>再次停止/核对停止</button>
      : run.status === "running"
        ? <button disabled={busy} onClick={() => void act(async () => { await request("reproductions.cancel", { projectId, runId: run.runId, planId: run.planId });setRevision(v => v + 1); })}>取消后续步骤</button>
        : run.status !== "completed" && <button disabled={busy} title="续接同次尝试；不会自动重跑失败任务" onClick={() => void act(async () => { await request("reproductions.run", { projectId, planId: run.planId, runId: run.runId });setRevision(v => v + 1); })}>恢复此冻结修订</button>}
    {canRetryFailed(run) && <button disabled={busy} title="保留已完成步骤；新一次尝试计入预算" onClick={() => void act(async () => { await request("reproductions.run", { projectId, planId: run.planId, runId: run.runId, retryFailed: true });setRevision(v => v + 1); })}>重试失败步骤</button>}
    <button disabled={busy || run.steps.filter(step => step.experimentId).length < 2} onClick={() => w.open({ kind: "compare", title: "复现口径比较", projectId, experimentRefs: run.steps.flatMap(step => step.experimentId ? [{ kind: "experiment", projectId, experimentId: step.experimentId, title: step.stepId }] : []) })}>比较真实结果</button>
  </div>
  {(() => { const scope = runScopeDetails(run, plan);return <div className="r-reproduction-scope"><p>{scope.subset ? "本次运行范围：选中步骤子集。" : "本次运行范围：完整计划。"}</p>{scope.subset && (scope.selectedKnown ? <p>选中 {scope.selectedNames.length} 步：{scope.selectedNames.join("、") || "未保存步骤清单"}</p> : <p>此运行未保存选中步骤清单。</p>)}{scope.subset && scope.excludedKnown && scope.excludedNames.length > 0 && <p>未选、未运行 {scope.excludedNames.length} 步：{scope.excludedNames.join("、")}</p>}{scope.subset && !scope.excludedKnown && <p>此运行未保存未选步骤清单。</p>}{scope.subset && run.status === "completed" && <p>未选步骤未运行；本次完成仅表示所选子集已完成。</p>}</div>;})()}
  {run.cancelPending && <p role="status">后台终止尚未确认；确认前不能恢复或重试。</p>}
  {run.message && <p role={run.status === "failed" || run.status === "interrupted" ? "alert" : undefined}>{run.message}</p>}
  {run.budget&&<div className="r-note"><p>本次运行计划工作量：{workSummary(run.budget.planned)}</p><p>本方案试参预留 {run.budget.reserved.trials} / {run.budget.trialLimit} 次</p><p>已预留任务：训练 {run.budget.reserved.trainingTasks} · 回测 {run.budget.reserved.backtestTasks} · 滚动 {run.budget.reserved.rollingTasks}</p><p>{run.budget.message}</p></div>}
  <ul>{run.steps.map(step => <li key={step.stepId}>
    <span>{runScopeDetails(run, plan).nameForId(step.stepId)} · {statuses[step.status] ?? step.status}{step.attempt !== undefined && <> · 第 {step.attempt} 次尝试</>}</span>
    {step.experimentId && <button onClick={() => w.open({ kind: "experiment", title: "复现步骤结果", projectId, experimentId: step.experimentId })}>查看实验</button>}
    {step.jobId && <><span>任务 ID：{step.jobId}</span><button onClick={() => void w.savePreferences({ rightPanel: "jobs", aiVisible: true })}>打开任务面板</button></>}
    {step.message && <p role={step.status === "failed" || step.status === "interrupted" ? "alert" : undefined}>{step.message}</p>}
    {!!step.attemptHistory?.length && <details><summary>历史尝试 · {step.attemptHistory.length}</summary><ul>{step.attemptHistory.map((attempt, index) => <li key={String(attempt.attempt) + "-" + (attempt.jobId ?? index)}>第 {attempt.attempt ?? index + 1} 次 · {statuses[attempt.status] ?? attempt.status}{attempt.jobId && <><span> · 任务 ID：{attempt.jobId}</span><button onClick={() => void w.savePreferences({ rightPanel: "jobs", aiVisible: true })}>打开任务面板</button></>}{attempt.message && <p role={attempt.status === "failed" || attempt.status === "interrupted" ? "alert" : undefined}>{attempt.message}</p>}{attempt.experimentId && <button onClick={() => w.open({ kind: "experiment", title: "查看保留实验", projectId, experimentId: attempt.experimentId })}>查看保留实验</button>}</li>)}</ul></details>}
  </li>)}</ul>
</section>)}</>}</div>;
}
