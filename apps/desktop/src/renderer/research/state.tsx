import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import type { Experiment, FactorDefinition, JobEvent, JobKind, JsonObject, ProjectConfig } from "../../../../../packages/contracts/src/research";

export type Page = "overview" | "data" | "universe" | "factors" | "strategy" | "model" | "backtest" | "results" | "chart" | "selection";
export const pages: Record<Page, string> = { overview: "概览", data: "数据", universe: "股票池", factors: "因子", strategy: "策略", model: "模型", backtest: "回测", results: "结果", chart: "行情与批注", selection: "选股" };
export const jobLabels: Record<JobKind, string> = { "data.update": "更新数据", "data.import": "导入数据", "factor.analyze": "因子分析", "backtest.run": "回测", "model.train": "模型训练", "optimize.run": "参数寻优", "selection.run": "每日选股" };
export function jobTitle(kind: JobKind, name?: string) { return !name?.trim() ? jobLabels[kind] : name.startsWith(kind) ? jobLabels[kind] + name.slice(kind.length) : name; }
export async function request<T>(method: string, params?: object): Promise<T> {
  if (!window.v3Research) throw new Error("研究服务未连接，请从桌面应用打开。");
  return window.v3Research.request<T>(method, params);
}
export function errorText(error: unknown) { return error instanceof Error ? error.message : String(error); }
export function useResearchState() {
  const [projects, setProjects] = useState<ProjectConfig[]>([]);
  const [project, setProject] = useState<ProjectConfig | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [jobs, setJobs] = useState<JobEvent[]>([]);
  const [factors, setFactors] = useState<FactorDefinition[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState<Page>("overview");
  const [selectedExperiment, setSelectedExperiment] = useState("");
  const [selectedFactors, setSelectedFactors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [submissionVersion, setSubmissionVersion] = useState(0);
  const current = useRef(project); current.current = project;
  const openSerial = useRef(0);
  const saveQueue = useRef(Promise.resolve());
  async function act<T>(work: () => Promise<T>): Promise<T | undefined> {
    setError("");
    try { return await work(); } catch (e) { setError(errorText(e)); return undefined; }
  }
  async function refreshProjects() { setProjects(await request<ProjectConfig[]>("projects.list")); }
  async function refresh(id = current.current?.id) {
    if (!id) return;
    const [exps, tasks] = await Promise.all([request<Experiment[]>("experiments.list", { projectId: id }), request<JobEvent[]>("jobs.list", { projectId: id })]);
    if (current.current?.id === id) { setExperiments(exps); setJobs(tasks); setRevision(v => v + 1); }
  }
  async function open(path: string) {
    const serial = ++openSerial.current;
    const p = await request<ProjectConfig>("projects.open", { path });
    if (serial !== openSerial.current) return;
    current.current = p; setProject(p); setExperiments([]); setJobs([]); setSelectedFactors(Array.isArray(p.settings.selectedFactors) ? p.settings.selectedFactors.filter((v): v is string => typeof v === "string") : []); setSelectedExperiment(""); setPage("overview");
    await Promise.all([refresh(p.id), refreshProjects()]);
  }
  async function save(patch: Partial<ProjectConfig>) {
    const id = current.current?.id;
    if (!id) return;
    const next = saveQueue.current.catch(() => {}).then(async () => {
      if (current.current?.id !== id) return;
      const saved = await request<ProjectConfig>("projects.save", { project: { ...current.current, ...patch } });
      if (current.current?.id === id) { current.current = saved; setProject(saved); setProjects(list => list.map(p => p.id === id ? saved : p)); }
    });
    saveQueue.current = next;
    await next;
  }
  async function submit(kind: JobKind, parameters: JsonObject, name?: string) {
    if (!current.current) throw new Error("请先打开项目。");
    const id = current.current.id;
    const event = await request<JobEvent>("jobs.submit", { spec: { projectId: id, kind, parameters, name: jobTitle(kind, name) } });
    if (current.current?.id === id) {
      setJobs(list => [event, ...list.filter(j => j.id !== event.id)]);
      setSubmissionVersion(version => version + 1);
      setNotice(`已提交：${jobTitle(event.kind, event.name)}`);
    }
    return event;
  }
  useEffect(() => {
    void act(async () => { await refreshProjects(); setFactors(await request<FactorDefinition[]>("factors.list")); });
    return window.v3Research?.onEvent(event => {
      if (event.projectId !== current.current?.id) return;
      setJobs(list => [event, ...list.filter(j => j.id !== event.id)]);
      if (["completed", "failed", "cancelled", "interrupted"].includes(event.status)) void act(() => refresh());
    });
  }, []);
  return { projects, project, experiments, jobs, factors, error, setError, notice, setNotice, page, setPage, selectedExperiment, setSelectedExperiment, selectedFactors, setSelectedFactors, revision, submissionVersion, act, refresh, refreshProjects, open, save, submit };
}
export type ResearchState = ReturnType<typeof useResearchState>;
export const ResearchContext = createContext<ResearchState | null>(null);
export function useResearch() { const state = useContext(ResearchContext); if (!state) throw new Error("Research context missing"); return state; }
