import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import type { Experiment, JobEvent, JobKind, JsonObject, ProjectConfig, StrategyConfig, WorkspacePanel, WorkspaceState } from "../../../../../packages/contracts/src/research";
import { ResearchContext, request, useResearch, type Page, type ResearchState } from "./state";
import { Empty } from "./ui";
export interface WorkspaceActions { updatePanel: (id: string, patch: Partial<WorkspacePanel>) => void; open: (panel: Omit<WorkspacePanel, "id"> & { id?: string }, split?: "right" | "below") => void; strategies: StrategyConfig[]; reload: () => Promise<void>; active?: WorkspacePanel; preferences: WorkspaceState; savePreferences: (patch: Partial<WorkspaceState>) => Promise<void>; linkStock: (symbol: string) => void; }
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
const strategySaves = new Map<string, Promise<void>>();
/** Existing quantitative editors receive an object-bound context, never the active tab's context. */
export function ObjectScope({ panel, children }: { panel: WorkspacePanel; children: React.ReactNode }) {
  const root = useResearch(); const w = useWorkspace();
  const [project, setProject] = useState<ProjectConfig | null>(null); const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedExperiment, setSelectedExperiment] = useState(panel.experimentId ?? ""); const experimentRef = useRef(selectedExperiment); experimentRef.current = selectedExperiment;
  const [selectedFactors, setSelectedFactors] = useState<string[]>([]); const [revision, setRevision] = useState(0); const [configurationVersions, setConfigurationVersions] = useState<Record<string,number>>({});
  const strategy = w.strategies.find(x => x.id === panel.strategyId && x.projectId === panel.projectId);
  const current = useRef(project); current.current = project; const saveQueue = useRef(Promise.resolve());
  async function refresh() { const next = await request<Experiment[]>("experiments.list", { projectId: panel.projectId, strategyId: panel.strategyId, ...(["today", "compare", "selection"].includes(panel.kind) ? { all: true } : {}) }); setExperiments(next); setRevision(x => x + 1); }
  useEffect(() => { let alive = true; void root.act(async () => { const [projects, strategies] = await Promise.all([request<ProjectConfig[]>("projects.list"), panel.strategyId ? request<StrategyConfig[]>("strategies.list", { projectId: panel.projectId }) : Promise.resolve([])]); const p = projects.find(x => x.id === panel.projectId); const strategy = strategies.find(x => x.id === panel.strategyId); if (alive) { const scoped = p ? { ...p, ...(strategy ? { settings: strategy.settings, universe: strategy.universe } : {}) } : null; setProject(scoped); current.current = scoped; setSelectedFactors(Array.isArray(scoped?.settings.selectedFactors) ? scoped!.settings.selectedFactors.filter((x): x is string => typeof x === "string") : []); } await refresh(); }); return () => { alive = false; }; }, [panel.projectId, panel.strategyId]);
  useEffect(() => window.v3Research?.onEvent(e => { if (e.projectId === panel.projectId && (!panel.strategyId || e.strategyId === panel.strategyId) && ["completed", "failed", "cancelled", "interrupted"].includes(e.status)) void root.act(refresh); }), [panel.projectId, panel.strategyId]);
  useEffect(() => {
    const previous = current.current;
    if (!strategy || !previous || hasPendingDrafts()) return;
    if (JSON.stringify(previous.settings) === JSON.stringify(strategy.settings) && JSON.stringify(previous.universe) === JSON.stringify(strategy.universe)) return;
    const changed = (key: string) => JSON.stringify(previous.settings[key]) !== JSON.stringify(strategy.settings[key]);
    const versions = [changed("backtest") ? "strategy" : "", changed("model") ? "model" : "", changed("factorAnalysis") || changed("factorProcessing") || changed("customFactors") ? "factors" : "", JSON.stringify(previous.universe) !== JSON.stringify(strategy.universe) ? "universe" : ""].filter(Boolean);
    const next = { ...previous, settings: strategy.settings, universe: strategy.universe }; current.current = next; setProject(next);
    if (changed("selectedFactors")) setSelectedFactors(Array.isArray(strategy.settings.selectedFactors) ? strategy.settings.selectedFactors.filter((v): v is string => typeof v === "string") : []);
    setConfigurationVersions(value => Object.fromEntries([...new Set([...Object.keys(value), ...versions])].map(key => [key, (value[key] ?? 0) + (versions.includes(key) ? 1 : 0)])));
  }, [w.strategies]);
  async function save(patch: Partial<ProjectConfig>) {
    const settingsPatch = patch.settings ? changedSettings(current.current?.settings ?? {}, patch.settings) : {};
    const key = `${panel.projectId}:${panel.strategyId}`;
    const next = (strategySaves.get(key) ?? saveQueue.current).catch(() => {}).then(async () => {
      if (!current.current) return;
      if (panel.strategyId) {
        await request<StrategyConfig>("strategies.save", { projectId: panel.projectId, strategy: { id: panel.strategyId, ...(patch.universe ? { universe: patch.universe } : {}) }, settingsPatch });
        // Keep the submitted editor snapshot until reload reconciles external fields.
        // Otherwise a merged server response can make unchanged local controls look like edits.
        const p = { ...current.current, ...patch }; current.current = p; setProject(p); await w.reload();
      } else { const saved = await request<ProjectConfig>("projects.save", { project: { ...current.current, ...patch } }); current.current = saved; setProject(saved); }
    }); saveQueue.current = next; strategySaves.set(key, next); await next;
  }
  async function submit(kind: JobKind, parameters: JsonObject, name?: string) { await saveQueue.current; const event = await request<JobEvent>("jobs.submit", { spec: { projectId: panel.projectId, strategyId: panel.strategyId, kind, parameters, name } }); root.setNotice(`已提交：${event.name}`); return event; }
  const navigate = (value: React.SetStateAction<Page>) => { const page = typeof value === "function" ? value("overview") : value; w.open({ kind: pageKind[page], title: page === "results" ? "实验结果" : page === "chart" ? "行情" : ({ factors: "因子", model: "模型", strategy: "策略", backtest: "回测", universe: "股票池", data: "数据", overview: "今日", selection: "每日选股" }[page] ?? page), projectId: panel.projectId, strategyId: panel.strategyId, ...(page === "results" && experimentRef.current ? { experimentId: experimentRef.current } : {}) }); };
  const value: ResearchState = { ...root, project, experiments: ["today", "compare", "selection"].includes(panel.kind) ? root.experiments : experiments, selectedExperiment, setSelectedExperiment: v => { const next = typeof v === "function" ? v(experimentRef.current) : v; experimentRef.current = next; setSelectedExperiment(next); }, selectedFactors, setSelectedFactors, configurationVersions, setConfigurationVersions, revision: revision + root.revision, save, submit, refresh, setPage: navigate };
  if (panel.projectId && !project) return <Empty title="正在读取研究对象…" />;
  return <ResearchContext.Provider value={value}>{children}</ResearchContext.Provider>;
}
const pendingDrafts = new Set<() => Promise<void>>();
const dirtyDrafts = new Set<() => boolean>();
function hasPendingDrafts() { return [...dirtyDrafts].some(check => check()); }
export async function flushDrafts() { await Promise.all([...pendingDrafts].map(flush => flush())); }
/** Valid drafts autosave; activation and native moves flush the same pending values. */
export function useDraftAutosave(snapshot: () => Partial<ProjectConfig>) {
  const s = useResearch(); const callback = useRef(snapshot); callback.current = snapshot; const state = useRef(s); state.current = s;
  let serialized = ""; try { serialized = JSON.stringify(snapshot()); } catch { /* incomplete JSON stays in the editor */ }
  const saved = useRef(serialized); const value = useRef(serialized); value.current = serialized;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null); const queue = useRef(Promise.resolve());
  const flush = useRef(async () => {
    if (timer.current) clearTimeout(timer.current);
    if (!value.current || value.current === saved.current) return queue.current;
    const next = value.current; const patch = callback.current(); saved.current = next;
    queue.current = queue.current.catch(() => {}).then(() => state.current.save(patch)).catch(error => { saved.current = ""; throw error; });
    await queue.current;
  });
  useEffect(() => { const dirty = () => !!value.current && value.current !== saved.current; dirtyDrafts.add(dirty); pendingDrafts.add(flush.current); return () => { dirtyDrafts.delete(dirty); pendingDrafts.delete(flush.current); void state.current.act(flush.current); }; }, []);
  useEffect(() => { if (!serialized || serialized === saved.current) return; timer.current = setTimeout(() => void state.current.act(flush.current), 700); return () => { if (timer.current) clearTimeout(timer.current); }; }, [serialized]);
}
