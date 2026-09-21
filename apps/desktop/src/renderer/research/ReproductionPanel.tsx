import React, { useEffect, useRef, useState } from "react";
import type { JsonObject, ReproductionPlan, ReproductionRun, ReproductionVariant, WorkspacePanel } from "../../../../../packages/contracts/src/research";
import { errorText, request, useResearch } from "./state";
import { useWorkspace } from "./workspace";
import { fieldLabel } from "./ui";

const variants: Record<ReproductionVariant, string> = { original: "原文条件复现", adapted: "用户选定适配", post_publication: "发布后独立检验", execution: "V3 现实成交口径" };
const statuses: Record<string, string> = { pending: "等待前置步骤", queued: "排队中", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断" };
export function ReproductionPanel({ panel }: { panel: WorkspacePanel }) {
  const s = useResearch(), w = useWorkspace(), projectId = panel.projectId;
  const [plans, setPlans] = useState<ReproductionPlan[]>([]), [plan, setPlan] = useState<ReproductionPlan | null>(null);
  const [saved, setSaved] = useState(""), [runs, setRuns] = useState<ReproductionRun[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const [newerPlan, setNewerPlan] = useState<ReproductionPlan | null>(null);
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
    setPlan(null);setSaved("");setNewerPlan(null);setRuns([]);setError("");
    current.current = { plan: null, saved: "" };
  }, [projectId, planId]);
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
  return <div className="r-page r-reproduction-page"><header className="r-toolbar"><h1>研报复现</h1><span className="r-spacer" /><button onClick={() => void discuss()}>与助手讨论方案</button><button disabled={busy} onClick={() => setRevision(v => v + 1)}>刷新计划</button></header><p className="r-note">{s.projects.find(item => item.id === projectId)?.name ?? projectId} · 核心结论与关键检验。已保存的运行绑定当时计划修订，修改不会改变旧结果。</p><select aria-label="复现计划" value={planId ?? ""} onChange={e => w.updatePanel(panel.id, { reproductionId: e.target.value || undefined })}><option value="">选择已保存计划</option>{visiblePlans.map(item => <option key={item.id} value={item.id}>{item.name} · 修订 {item.revision}</option>)}</select>{error && <p role="alert">{error}</p>}{!plan && <p>{visiblePlans.length ? "选择一个计划查看条件与步骤。" : "此研报在当前项目尚无复现计划。可与助手讨论，先读取原文再保存方案。"}</p>}{plan && <>{newerPlan && <div role="status"><p>已有已保存修订 {newerPlan.revision}，当前草稿基于修订 {plan.revision}。未保存修改已保留；请先复制需要保留的内容，再载入最新修订。</p><button disabled={busy} onClick={() => { setPlan(newerPlan);setSaved(JSON.stringify(newerPlan));setNewerPlan(null); }}>放弃当前草稿并载入修订 {newerPlan.revision}</button></div>}<div className="r-report-filters"><label>计划名称<input value={plan.name} onChange={e => setPlan({ ...plan, name: e.target.value })} /></label><label>研究目标<textarea value={plan.objective} onChange={e => setPlan({ ...plan, objective: e.target.value })} /></label></div><label className="r-reproduction-missing">仍缺少的条件（每行一项，解决后再移除）<textarea value={plan.missingConditions.join("\n")} onChange={e => setPlan({ ...plan, missingConditions: e.target.value.split("\n").filter(value => value.trim()) })} /></label>{plan.missingConditions.length > 0 && <p className="r-note">尚有 {plan.missingConditions.length} 项缺失条件，暂不能启动。缺少逐日数列时只对照原图或已发表指标。</p>}<div className="r-toolbar"><button disabled={busy || !!newerPlan || !dirty || !plan.name.trim()} onClick={() => void act(save)}>保存新修订</button><span>{dirty ? "有未保存修改" : `已保存修订 ${plan.revision}`}</span><button className="r-primary" disabled={busy || !!newerPlan || dirty || !!plan.missingConditions.length || !plan.steps.length || runs.some(run => run.revision === plan.revision && run.status === "running")} onClick={() => void act(async () => { const frozen = { projectId, planId: plan.id, revision:plan.revision };await request<ReproductionRun>("reproductions.run", frozen);setRevision(v => v + 1); })}>启动已保存计划</button></div>{plan.plannedWork&&<p className="r-note">{dirty?'上次保存方案的工作量（修改后需保存更新）':'已保存方案工作量'}：试参 {plan.plannedWork.trials} 次 · 训练 {plan.plannedWork.trainingTasks} 个任务 · 回测 {plan.plannedWork.backtestTasks} 个任务 · 滚动 {plan.plannedWork.rollingTasks} 个任务</p>}<ol className="r-reproduction-steps">{plan.steps.map((step, index) => <li key={step.id}><div className="r-toolbar"><input aria-label={`步骤 ${index + 1} 名称`} value={step.name} onChange={e => editStep(index, value => ({ ...value, name: e.target.value }))} /><select aria-label={`步骤 ${index + 1} 口径`} value={step.variant} onChange={e => editStep(index, value => ({ ...value, variant: e.target.value as ReproductionVariant }))}>{Object.entries(variants).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div><p className="r-note">前置步骤：{step.dependsOn.map(id => plan.steps.find(item => item.id === id)?.name ?? id).join("、") || "无"}</p><label>与原文条件的差异<textarea value={step.differences.join("\n")} onChange={e => editStep(index, value => ({ ...value, differences: e.target.value.split("\n").filter(Boolean) }))} /></label><div className="r-report-filters">{Object.entries(step.spec.parameters).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value)).map(([key, value]) => <label key={key}>{fieldLabel(key)}{key==="labelMode"?<select aria-label={`步骤 ${index+1} 标签口径`} value={String(value)} onChange={e=>editStep(index,step=>({...step,spec:{...step.spec,parameters:{...step.spec.parameters,labelMode:e.target.value}}}))}>{!["next_open","close"].includes(String(value))&&<option disabled value={String(value)}>未识别口径：{String(value)}</option>}<option value="next_open">下一开盘起算</option><option value="close">收盘到收盘（研究）</option></select>:typeof value === "boolean" ? <input type="checkbox" checked={value} onChange={e => editStep(index, step => ({ ...step, spec: { ...step.spec, parameters: { ...step.spec.parameters, [key]: e.target.checked } } }))} /> : <input type={typeof value === "number" ? "number" : /date$/i.test(key) ? "date" : "text"} value={String(value)} onChange={e => { const next = typeof value === "number" ? Number(e.target.value) : e.target.value;if (typeof next === "number" && !Number.isFinite(next)) return;editStep(index, step => ({ ...step, spec: { ...step.spec, parameters: { ...step.spec.parameters, [key]: next } as JsonObject } })); }} />}</label>)}</div><details><summary>完整运行参数</summary><pre>{JSON.stringify(step.spec, null, 2)}</pre></details><div className="r-toolbar">{step.citations.map((citation, i) => <button key={i} title={citation.excerpt} onClick={() => w.open({ kind: "report", title: "核对原文", projectId, reportId: citation.reportId, page: citation.page })}>原文第 {citation.page} 页</button>)}</div></li>)}</ol><h2>已保存运行</h2>{!runs.length && <p className="r-note">尚未执行。</p>}{runs.map(run => <section className="r-reproduction-run" key={run.runId}><div className="r-toolbar"><strong>修订 {run.revision} · {statuses[run.status] ?? run.status}</strong>{run.status === "running" ? <button disabled={busy} onClick={() => void act(async () => { await request("reproductions.cancel", { projectId, runId: run.runId, planId: plan.id });setRevision(v => v + 1); })}>取消后续步骤</button> : run.status !== "completed" && <button disabled={busy} onClick={() => void act(async () => { await request("reproductions.run", { projectId, planId: plan.id, runId: run.runId });setRevision(v => v + 1); })}>恢复此冻结修订</button>}<button disabled={run.steps.filter(step => step.experimentId).length < 2} onClick={() => w.open({ kind: "compare", title: "复现口径比较", projectId, experimentRefs: run.steps.flatMap(step => step.experimentId ? [{ kind: "experiment", projectId, experimentId: step.experimentId, title: step.stepId }] : []) })}>比较真实结果</button></div>{run.message && <p>{run.message}</p>}{run.budget&&<div className="r-note"><p>本方案试参预留 {run.budget.reserved.trials} / {run.budget.trialLimit} 次 · 计划试参 {run.budget.planned.trials} 次</p><p>已预留任务：训练 {run.budget.reserved.trainingTasks} · 回测 {run.budget.reserved.backtestTasks} · 滚动 {run.budget.reserved.rollingTasks}</p><p>{run.budget.message}</p></div>}<ul>{run.steps.map(step => <li key={step.stepId}>{step.stepId} · {statuses[step.status] ?? step.status}{step.experimentId && <button onClick={() => w.open({ kind: "experiment", title: "复现步骤结果", projectId, experimentId: step.experimentId })}>查看实验</button>}</li>)}</ul></section>)}</>}</div>;
}
