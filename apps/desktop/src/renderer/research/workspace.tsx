import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import type { Experiment, JobEvent, JobKind, JsonObject, ProjectConfig, StrategyConfig, WorkspacePanel, WorkspaceState } from "../../../../../packages/contracts/src/research";
import { ResearchContext, request, useResearch, jobTitle, type Page, type ResearchState } from "./state";
import { Empty } from "./ui";
export interface WorkspaceActions { createProject: () => void; openProjectDirectory: () => Promise<void>; updatePanel: (id: string, patch: Partial<WorkspacePanel>) => void; open: (panel: Omit<WorkspacePanel, "id"> & { id?: string }, split?: "right" | "below") => void; strategies: StrategyConfig[]; reload: () => Promise<void>; active?: WorkspacePanel; preferences: WorkspaceState; savePreferences: (patch: Partial<WorkspaceState>) => Promise<void>; linkStock: (symbol: string) => void; }
const ObjectPanelContext = createContext<WorkspacePanel | null>(null);
export function useObjectPanel() { return useContext(ObjectPanelContext); }
export const WorkspaceContext = createContext<WorkspaceActions | null>(null);
export function useWorkspace() { const value = useContext(WorkspaceContext); if (!value) throw new Error("Workspace missing"); return value; }
export const pageKind = { overview: "today", backtest: "strategy", results: "experiment", chart: "stock", data: "data", universe: "universe", factors: "factors", strategy: "strategy", model: "model", selection: "selection" } as const;
/** Only changed leaves are sent; the backend merges them against the live strategy. */
export function changedSettings(before: JsonObject, after: JsonObject): JsonObject {
  const entries: [string, JsonObject[string]][] = [];
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const previous = before[key], next = after[key];
    if (JSON.stringify(previous) === JSON.stringify(next)) continue;
    const previousObject = previous !== null && typeof previous === "object" && !Array.isArray(previous);
    const nextObject = next !== null && typeof next === "object" && !Array.isArray(next);
    entries.push([key, previousObject && nextObject ? changedSettings(previous as JsonObject, next as JsonObject) : next ?? null]);
  }
  return Object.fromEntries(entries);
}
/** Merge only editor changes so another module's saved settings survive. */
export function mergeSettingsChanges(latest:JsonObject,before:JsonObject,after:JsonObject):JsonObject {
 const result={...latest};
 for(const key of new Set([...Object.keys(before),...Object.keys(after)])) {
  if(JSON.stringify(before[key])===JSON.stringify(after[key]))continue;
  if(!(key in after)){delete result[key];continue;}
  const a=before[key],b=after[key],c=latest[key];
  result[key]=a&&b&&typeof a==='object'&&typeof b==='object'&&!Array.isArray(a)&&!Array.isArray(b)?mergeSettingsChanges(c&&typeof c==='object'&&!Array.isArray(c)?c:{},a,b):b;
 }
 return result;
}
function strategyDates(project: ProjectConfig, strategy: StrategyConfig) {
  return { startDate: typeof strategy.settings.startDate === "string" && strategy.settings.startDate.trim() ? strategy.settings.startDate : project.startDate, endDate: typeof strategy.settings.endDate === "string" && strategy.settings.endDate.trim() ? strategy.settings.endDate : project.endDate };
}
const strategySaves = new Map<string, Promise<void>>();
/** Existing quantitative editors receive an object-bound context, never the active tab's context. */
export function ObjectScope({ panel, children }: { panel: WorkspacePanel; children: React.ReactNode }) {
  const root = useResearch(); const w = useWorkspace();
  const [project, setProject] = useState<ProjectConfig | null>(null); const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedExperiment, setSelectedExperiment] = useState(panel.experimentId ?? ""); const experimentRef = useRef(selectedExperiment); experimentRef.current = selectedExperiment;
  const [selectedFactors, setSelectedFactors] = useState<string[]>([]); const [revision, setRevision] = useState(0); const [configurationVersions, setConfigurationVersions] = useState<Record<string,number>>({});
  const selectionRef=useRef(selectedFactors);selectionRef.current=selectedFactors;const syncGeneration=useRef(0);
  const strategy = w.strategies.find(x => x.id === panel.strategyId && x.projectId === panel.projectId);
  const current = useRef(project); current.current = project; const saveQueue = useRef(Promise.resolve());
  async function refresh() { const next = await request<Experiment[]>("experiments.list", { projectId: panel.projectId, strategyId: panel.strategyId, ...(["today", "compare", "selection"].includes(panel.kind) ? { all: true } : {}) }); setExperiments(next); setRevision(x => x + 1); }
  useEffect(() => { let alive = true; void root.act(async () => { const [projects, strategies] = await Promise.all([request<ProjectConfig[]>("projects.list"), panel.strategyId ? request<StrategyConfig[]>("strategies.list", { projectId: panel.projectId }) : Promise.resolve([])]); const p = projects.find(x => x.id === panel.projectId); const strategy = strategies.find(x => x.id === panel.strategyId); if (alive) { const scoped = p ? { ...p, ...(strategy ? { settings: strategy.settings, universe: strategy.universe, ...strategyDates(p, strategy) } : {}) } : null; setProject(scoped); current.current = scoped; setSelectedFactors(Array.isArray(scoped?.settings.selectedFactors) ? scoped!.settings.selectedFactors.filter((x): x is string => typeof x === "string") : []); } await refresh(); }); return () => { alive = false; }; }, [panel.projectId, panel.strategyId]);
  useEffect(() => window.v3Research?.onEvent(e => { if (e.projectId === panel.projectId && (!panel.strategyId || e.strategyId === panel.strategyId) && ["completed", "failed", "cancelled", "interrupted"].includes(e.status)) void root.act(refresh); }), [panel.projectId, panel.strategyId]);
  const [draftSync,setDraftSync]=useState(0);
  useEffect(()=>{const sync=()=>setDraftSync(v=>v+1);window.addEventListener("v3-drafts-saved",sync);return()=>window.removeEventListener("v3-drafts-saved",sync);},[]);
  useEffect(() => {
    const scope=`${panel.projectId}:${panel.strategyId}`;
    if(!current.current||hasPendingDrafts(scope))return;
    let active=true;const generation=syncGeneration.current;
    // Sidebar caches can lag a successful save. Reconcile from persisted scope data,
    // and recheck local edits after the asynchronous read before applying it.
    void Promise.all([request<ProjectConfig[]>("projects.list"),panel.strategyId?request<StrategyConfig[]>("strategies.list",{projectId:panel.projectId}):Promise.resolve([])]).then(([projects,strategies])=>{
    if(!active||generation!==syncGeneration.current||hasPendingDrafts(scope))return;
    const previous=current.current,base=projects.find(p=>p.id===panel.projectId);
    const liveStrategy=strategies.find(item=>item.id===panel.strategyId&&item.projectId===panel.projectId);
    if(!previous||!base||panel.strategyId&&!liveStrategy)return;
    const incoming=liveStrategy??base;
    const incomingSelection=Array.isArray(incoming.settings.selectedFactors)?incoming.settings.selectedFactors.filter((value):value is string=>typeof value==="string"):[];
    if(JSON.stringify(selectionRef.current)!==JSON.stringify(incomingSelection))setSelectedFactors(incomingSelection);
    const dates = liveStrategy?strategyDates(base,liveStrategy):{startDate:base.startDate,endDate:base.endDate};
    if (previous.startDate===dates.startDate && previous.endDate===dates.endDate && JSON.stringify(previous.settings) === JSON.stringify(incoming.settings) && JSON.stringify(previous.universe) === JSON.stringify(incoming.universe)) return;
    const changed = (key: string) => JSON.stringify(previous.settings[key]) !== JSON.stringify(incoming.settings[key]);
    const versions = [previous.startDate!==dates.startDate||previous.endDate!==dates.endDate ? "data" : "",changed("backtest") ? "strategy" : "", changed("model") ? "model" : "", changed("factorAnalysis") || changed("factorProcessing") || changed("customFactors") ? "factors" : "", JSON.stringify(previous.universe) !== JSON.stringify(incoming.universe) ? "universe" : ""].filter(Boolean);
    const next = { ...previous, settings: incoming.settings, universe: incoming.universe, ...dates }; current.current = next; setProject(next);
    if (changed("selectedFactors")) setSelectedFactors(Array.isArray(incoming.settings.selectedFactors) ? incoming.settings.selectedFactors.filter((v): v is string => typeof v === "string") : []);
    setConfigurationVersions(value => Object.fromEntries([...new Set([...Object.keys(value), ...versions])].map(key => [key, (value[key] ?? 0) + (versions.includes(key) ? 1 : 0)])));
    }).catch(error=>{if(active)root.setError(String(error));});
    return()=>{active=false;};
  }, [w.strategies,root.projects,draftSync,panel.projectId,panel.strategyId]);
  async function save(patch: Partial<ProjectConfig>) {
    syncGeneration.current++;
    const beforeSettings=current.current?.settings??{};
    const settingsPatch = patch.settings ? changedSettings(current.current?.settings ?? {}, patch.settings) : {};
    if(panel.strategyId){for(const field of ["startDate","endDate"] as const)if(Object.prototype.hasOwnProperty.call(patch,field))settingsPatch[field]=patch[field]??"";}
    const key = `${panel.projectId}:${panel.strategyId}`;
    const next = (strategySaves.get(key) ?? saveQueue.current).catch(() => {}).then(async () => {
      if (!current.current) return;
      if (panel.strategyId) {
        const saved = await request<StrategyConfig>("strategies.save", { projectId: panel.projectId, strategy: { id: panel.strategyId, ...(patch.universe ? { universe: patch.universe } : {}) }, settingsPatch });
        const baseProject = root.projects.find(p=>p.id===panel.projectId)??current.current;
        const p = { ...current.current, ...patch, settings:saved.settings, universe:saved.universe, ...strategyDates(baseProject,saved) }; current.current = p; setProject(p); await w.reload();
      } else { const latest=(await request<ProjectConfig[]>("projects.list")).find(p=>p.id===panel.projectId);if(!latest)throw new Error("研究项目不存在，请重新打开。");const saved = await request<ProjectConfig>("projects.save", { project: { ...latest, ...patch,...(patch.settings?{settings:mergeSettingsChanges(latest.settings,beforeSettings,patch.settings)}:{}) } }); current.current = saved; setProject(saved);await w.reload(); }
    }); saveQueue.current = next; strategySaves.set(key, next); await next;
  }
  async function submit(kind: JobKind, parameters: JsonObject, name?: string) { await saveQueue.current; const event = await request<JobEvent>("jobs.submit", { spec: { projectId: panel.projectId, strategyId: panel.strategyId, kind, parameters, name } }); root.setNotice(`已提交：${event.name}`); return event; }
  const navigate = (value: React.SetStateAction<Page>) => { const page = typeof value === "function" ? value("overview") : value; w.open({ kind: pageKind[page], ...(page === "backtest" ? {view:"backtest" as const} : {}), title: page === "results" ? "实验结果" : page === "chart" ? "行情" : ({ factors: "因子", model: "模型", strategy: "策略", backtest: "回测", universe: "股票池", data: "数据", overview: "今日", selection: "每日选股" }[page] ?? page), projectId: panel.projectId, strategyId: panel.strategyId, ...(page === "results" && experimentRef.current ? { experimentId: experimentRef.current } : {}) }); };
  const value: ResearchState = { ...root, project, experiments: ["today", "compare", "selection"].includes(panel.kind) ? root.experiments : experiments, selectedExperiment, setSelectedExperiment: v => { const next = typeof v === "function" ? v(experimentRef.current) : v; experimentRef.current = next; setSelectedExperiment(next); if(panel.kind === "experiment") { const experiment=experiments.find(e=>e.id===next); w.updatePanel(panel.id,{experimentId:next||undefined,title:experiment?jobTitle(experiment.kind,experiment.name):"实验结果"}); } }, selectedFactors, setSelectedFactors: value=>{syncGeneration.current++;setSelectedFactors(value);}, configurationVersions, setConfigurationVersions, revision: revision + root.revision, save, submit, refresh, setPage: navigate };
  if (panel.projectId && !project) return <Empty title="正在读取研究对象…" />;
  return <ObjectPanelContext.Provider value={panel}><ResearchContext.Provider value={value}>{children}</ResearchContext.Provider></ObjectPanelContext.Provider>;
}
const pendingDrafts = new Set<() => Promise<void>>();
const dirtyDrafts = new Map<() => boolean,string>();
function hasPendingDrafts(scope:string) { return [...dirtyDrafts].some(([check,key]) => key===scope&&check()); }
export async function flushDrafts() { await Promise.all([...pendingDrafts].map(flush => flush())); }
/** Valid drafts autosave; activation and native moves flush the same pending values. */
export function useDraftAutosave(snapshot: () => Partial<ProjectConfig>) {
  const panel=useObjectPanel();const scope=`${panel?.projectId}:${panel?.strategyId}`;
  const s = useResearch(); const callback = useRef(snapshot); callback.current = snapshot; const state = useRef(s); state.current = s;
  let serialized = ""; try { serialized = JSON.stringify(snapshot()); } catch { /* incomplete JSON stays in the editor */ }
  const saved = useRef(serialized); const value = useRef(serialized); value.current = serialized;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null); const queue = useRef(Promise.resolve());
  const inFlight=useRef(0),submitted=useRef("");
  const flush = useRef(async () => {
    if (timer.current) clearTimeout(timer.current);
    if (!value.current || value.current === saved.current&&!inFlight.current || value.current === submitted.current) return queue.current;
    const next = value.current; const patch = callback.current();submitted.current=next;inFlight.current++;
    queue.current = queue.current.catch(() => {}).then(() => state.current.save(patch)).then(()=>{saved.current=next;}).catch(error => { saved.current = ""; throw error; }).finally(()=>{inFlight.current--;if(submitted.current===next)submitted.current="";});
    await queue.current;window.dispatchEvent(new Event("v3-drafts-saved"));
  });
  useEffect(() => { const dirty = () => inFlight.current>0||!!value.current && value.current !== saved.current; dirtyDrafts.set(dirty,scope); pendingDrafts.add(flush.current); return () => { void state.current.act(async()=>{try{await flush.current();}finally{dirtyDrafts.delete(dirty);pendingDrafts.delete(flush.current);}}); }; }, []);
  useEffect(() => { if (!serialized || serialized === saved.current&&!inFlight.current) return; timer.current = setTimeout(() => void state.current.act(flush.current), 700); return () => { if (timer.current) clearTimeout(timer.current); }; }, [serialized]);
}
