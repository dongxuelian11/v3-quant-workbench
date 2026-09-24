import React, { useEffect, useState } from "react";
import type { ExperimentDetails, JsonObject, JsonValue, ProjectConfig, StrategyConfig } from "../../../../../packages/contracts/src/research";
import { useResearch, request, errorText } from "./state";
import { useObjectPanel, useWorkspace, hasPendingDrafts } from "./workspace";
import { object } from "./configuration";
import { fieldLabel } from "./ui";

const same = (a: JsonValue | undefined, b: JsonValue | undefined): boolean => {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every(key => same(a[key], b[key]));
  }
  return a === b;
};
export function configurationDifferences(before: JsonObject, after: JsonObject, prefix = ""): { key: string; before: JsonValue | undefined; after: JsonValue | undefined }[] {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap(key => {
    const a = before[key], b = after[key], path = prefix ? `${prefix}.${key}` : key;
    if (same(a, b)) return [];
    if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) return configurationDifferences(a, b, path);
    return [{ key: path, before: a, after: b }];
  });
}
const display = (value: JsonValue | undefined) => value === undefined ? "未记录" : value === "" ? "未设置" : value === null ? "空值" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
const settingsKeys = ["selectedFactors", "factorAnalysis", "factorProcessing", "customFactors", "model", "backtest"];
function comparable(config: JsonObject): JsonObject {
  const settings = object(config.settings);
  return Object.fromEntries(["startDate", "endDate", "universe"].filter(key => key in config).map(key => [key, config[key]]).concat(settingsKeys.filter(key => key in settings).map(key => [key, settings[key]])));
}
export function SnapshotDifference({ detail }: { detail: ExperimentDetails }) {
  const s = useResearch(), w = useWorkspace();
  const scope=`${detail.experiment.projectId}:${detail.experiment.strategyId}`;
  const [pending,setPending]=useState(()=>hasPendingDrafts(scope));
  useEffect(()=>{const refresh=()=>setPending(hasPendingDrafts(scope));refresh();window.addEventListener("v3-drafts-changed",refresh);window.addEventListener("v3-drafts-saved",refresh);return()=>{window.removeEventListener("v3-drafts-changed",refresh);window.removeEventListener("v3-drafts-saved",refresh);};},[scope]);
  const snapshot = object(detail.details.projectSnapshot);
  const [live,setLive]=useState<{base?:ProjectConfig;strategy?:StrategyConfig}|null>(null),[error,setError]=useState('');
  useEffect(()=>{let alive=true;setLive(null);setError('');void Promise.all([request<ProjectConfig[]>('projects.list'),detail.experiment.strategyId?request<StrategyConfig[]>('strategies.list',{projectId:detail.experiment.projectId}):Promise.resolve([])]).then(([projects,strategies])=>{if(alive)setLive({base:projects.find(p=>p.id===detail.experiment.projectId),strategy:detail.experiment.strategyId?strategies.find(st=>st.id===detail.experiment.strategyId):undefined});}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[detail.experiment.id,detail.experiment.projectId,detail.experiment.strategyId,s.revision,s.projects,w.strategies]);
  const base=live?.base,strategy=live?.strategy;
  if (!Object.keys(snapshot).length) return <p className="r-note">本实验未提供冻结配置，无法完整比较当前草稿；下方输入参数仍为实验记录。</p>;
  if(error)return <p role="alert">当前草稿读取失败：{error}</p>;
  if(!live)return <p role="status">正在读取原研究对象的当前草稿…</p>;
  if (!base || detail.experiment.strategyId && !strategy) return <p className="r-note">原项目或策略已不可用；实验冻结配置保留，无法比较当前草稿。</p>;
  const current = strategy ? { ...base, settings: strategy.settings, universe: strategy.universe, startDate: String(strategy.settings.startDate || base.startDate), endDate: String(strategy.settings.endDate || base.endDate) } : base;
  const rows = configurationDifferences(comparable(snapshot), comparable(current as unknown as JsonObject));
  return <>{(pending||rows.length>0)&&<p className="r-draft-result-notice" role="status"><strong>{pending?"关联草稿正在修改或保存":"当前草稿与本实验不同"}</strong> · 本页仍是 {new Date(detail.experiment.createdAt).toLocaleString("zh-CN")} 的原实验（{detail.experiment.id.slice(0,8)}），编辑参数不会更新这些结果。</p>}<details className="r-snapshot-difference"><summary>本次实验与当前已保存草稿 · {rows.length ? `${rows.length} 项差异` : "所比较配置一致"}</summary><p className="r-note">比较研究区间、股票池、所选因子、处理配置、模型和回测参数；不据此判断原数据文件是否发生修订。编辑当前草稿不会改变本实验。</p>{rows.length > 0 && <div className="r-table-scroll"><table><thead><tr><th>配置</th><th>实验冻结值</th><th>当前已保存草稿</th></tr></thead><tbody>{rows.map(row => <tr key={row.key}><th>{row.key.split(".").map(key => fieldLabel(key)).join(" / ")}</th><td><pre>{display(row.before)}</pre></td><td><pre>{display(row.after)}</pre></td></tr>)}</tbody></table></div>}<details><summary>原始冻结研究配置</summary><pre>{JSON.stringify(comparable(snapshot), null, 2)}</pre></details></details></>;
}
export function PreparationHistory({ detail }: { detail: ExperimentDetails }) {
  return <PreparationRecords preparation={object(detail.details.preparation)} projectId={detail.experiment.projectId} strategyId={detail.experiment.strategyId}/>;
}
export function PreparationRecords({preparation,projectId,strategyId}:{preparation:JsonObject;projectId?:string;strategyId?:string}) {
  const w=useWorkspace();
  if (!Object.keys(preparation).length) return <p className="r-note">本实验未记录前置准备步骤。模型自身过程可在训练事件和原生训练评估中查看。</p>;
  const steps = Array.isArray(preparation.steps) ? preparation.steps.map(object) : [];
  const coverage = object(preparation.actualCoverage);
  const labels: Record<string, string> = { running: "开始", completed: "完成", reused: "复用已有结果", failed: "停止" };
  return <details className="r-preparation-history"><summary>实际前置准备 · {steps.length} 条步骤记录</summary><p className="r-note">请求区间 {display(preparation.requestedStart)} — {display(preparation.requestedEnd)} · 预热需求 {display(preparation.warmupSessions)} 个交易日</p><ol>{steps.map((step, i) => <li key={i}><strong>{display(step.name)}</strong> · {labels[String(step.status)] ?? display(step.status)}{step.source != null && <span> · {display(step.source)}</span>}{step.startDate != null && <span> · {display(step.startDate)} — {display(step.endDate)}</span>}{step.message != null && <p role={step.status === "failed" ? "alert" : undefined}>{display(step.message)}</p>}{typeof step.experimentId === "string" && <button onClick={() => w.open({ kind: "experiment", title: "前置模型实验", projectId, strategyId, experimentId: String(step.experimentId) })}>查看模型实验</button>}</li>)}</ol>{Object.keys(coverage).length > 0 && <p className="r-note">实际行情覆盖 {display(coverage.startDate)} — {display(coverage.endDate)} · {display(coverage.rows)} 行 · {Array.isArray(coverage.symbols) ? coverage.symbols.length : "未记录"} 只证券</p>}</details>;
}
export function ModelRunStatus() {
  const s = useResearch(), w = useWorkspace(), panel = useObjectPanel();
  const jobs = s.jobs.filter(j => j.kind === "model.train" && j.projectId === panel?.projectId && j.strategyId === panel?.strategyId).slice(0, 3);
  const labels: Record<string, string> = { queued: "排队", running: "运行中", completed: "完成", failed: "失败", cancelled: "已取消", interrupted: "已中断" };
  if (!jobs.length) return null;
  return <section className="r-model-run-status"><h3>实际训练进度</h3>{jobs.map(job => <div key={job.id}><strong>{labels[job.status]}</strong><span>{job.message}</span><progress aria-label="训练进度" value={Math.max(0, Math.min(1, job.progress))} max={1}/>{["running", "queued"].includes(job.status) && <button onClick={() => void s.act(() => request("jobs.cancel", { jobId: job.id }))}>取消任务</button>}{job.experimentId && job.resultAvailable !== false && <button onClick={() => w.open({ kind: "experiment", title: job.name, projectId: job.projectId, strategyId: job.strategyId, experimentId: job.experimentId })}>结果与过程记录</button>}{job.preparation&&<PreparationRecords preparation={job.preparation} projectId={job.projectId} strategyId={job.strategyId}/>}</div>)}</section>;
}
