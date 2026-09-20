import React, { useEffect, useRef, useState } from "react";
import type { JobSpec, JsonObject } from "../../../../../packages/contracts/src/research";
import { request, useResearch } from "./state";
import { Field } from "./ui";
import { object } from "./configuration";

interface Settings { ai: { baseUrl: string; model: string; apiKey: string; temperature: number }; defaultDataSource: "baostock" | "akshare" }
interface Proposal { title: string; description: string; spec: JobSpec }
interface Answer { message: string; phase: string; proposals: Proposal[]; experimentIds: string[] }
interface Message { role: "user" | "assistant"; content: string; phase?: string; experimentIds?: string[] }
interface ChatState { messages: Message[]; phase: string; proposals: Proposal[]; stageJobIds: string[]; mode: "ask" | "assist" | "research" }
export function AiPanel({ settingsOpen, closeSettings, hidden = false }: { settingsOpen: boolean; closeSettings: () => void; hidden?: boolean }) {
  const s = useResearch();
  const [mode, setMode] = useState<"ask" | "assist" | "research">("assist"); const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]); const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false); const [stageJobs, setStageJobs] = useState<string[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null); const [showSettings, setShowSettings] = useState(false);
  const [endpoint, setEndpoint] = useState<"online" | "local">("online");
  const projectRef = useRef(s.project?.id); projectRef.current = s.project?.id;
  const [loaded, setLoaded] = useState(false);
  function restore(state: ChatState) { setMessages(state.messages); setMode(state.mode); setStageJobs(state.stageJobIds); setAnswer({ message: "", phase: state.phase, proposals: state.proposals, experimentIds: [] }); }
  async function refreshChat(projectId: string) { const state = await request<ChatState>("ai.state.get", { projectId }); if (projectRef.current === projectId) restore(state); }
  useEffect(() => { if (settingsOpen) setShowSettings(true); }, [settingsOpen]);
  useEffect(() => { if (showSettings) void s.act(async () => { const loaded = await request<Settings>("settings.get"); setSettings(loaded); setEndpoint(/localhost|127\.0\.0\.1|\[::1\]/.test(loaded.ai.baseUrl) ? "local" : "online"); }); }, [showSettings]);
  useEffect(() => { let active = true; setMessages([]); setAnswer(null); setStageJobs([]); setInput(""); setLoaded(false); const projectId = s.project?.id; if (projectId) void s.act(async () => { const state = await request<ChatState>("ai.state.get", { projectId }); if (active) { restore(state); setLoaded(true); } }); return () => { active = false; }; }, [s.project?.id]);
  const terminal = stageJobs.length > 0 && stageJobs.every(id => s.jobs.some(j => j.id === id && ["completed", "failed", "cancelled", "interrupted"].includes(j.status)));
  async function send(text = input) {
    if (!s.project || !text.trim() || busy || !loaded) return;
    const projectId = s.project.id; const history = messages;
    setBusy(true); setInput(""); setMessages([...history, { role: "user", content: text }]);
    await s.act(async () => {
      try { await request<Answer>("ai.chat", { projectId, mode, message: text, history }); }
      finally { await refreshChat(projectId); }
    });
    setBusy(false);
  }
  async function applyProposal(proposal: Proposal) {
    const project = s.project;
    if (!project || proposal.spec.projectId !== project.id) throw new Error("方案不属于当前项目。");
    const parameters = proposal.spec.parameters;
    const kind = proposal.spec.kind;
    if (kind === "selection.run") {
      if (Object.keys(parameters).length) {
        await s.save({ settings: { ...project.settings, selection: { ...object(project.settings.selection), ...parameters, enabled: false } } });
        s.setConfigurationVersions(v => ({ ...v, selection: (v.selection ?? 0) + 1 }));
        s.setNotice("选股建议已保存为草稿，请核对后明确启用。");
      }
      s.setPage("selection"); return;
    }
    const key = kind === "factor.analyze" ? "factorAnalysis" : kind === "model.train" ? "model" : kind === "backtest.run" ? "backtest" : null;
    if (!key) { s.setNotice("此建议请切换研究模式，查看后运行对应阶段。"); return; }
    const ids = Array.isArray(parameters.factorIds) ? parameters.factorIds.filter((v): v is string => typeof v === "string") : undefined;
    const settings: JsonObject = { ...project.settings, [key]: { ...object(project.settings[key]), ...parameters } };
    if (ids) settings.selectedFactors = ids;
    if (parameters.factorProcessing) settings.factorProcessing = parameters.factorProcessing;
    if (Array.isArray(parameters.customFactors)) { const incoming = parameters.customFactors; const ids = new Set(incoming.map(f => object(f).id)); settings.customFactors = [...(Array.isArray(project.settings.customFactors) ? project.settings.customFactors.filter(f => !ids.has(object(f).id)) : []), ...incoming]; }
    await s.save({ settings });
    if (ids) s.setSelectedFactors(ids);
    const page = key === "factorAnalysis" ? "factors" : key;
    s.setConfigurationVersions(v => ({ ...v, [page]: (v[page] ?? 0) + 1 }));
    s.setPage(page); s.setNotice("已应用方案参数，请查看后运行。");
  }
  async function runStage() {
    if (!answer || !s.project || busy) return;
    const proposals = answer.proposals;
    if (proposals.some(p => p.spec.projectId !== s.project!.id)) { s.setError("AI 方案包含其他项目，未执行。"); return; }
    setBusy(true); const submitted: string[] = [];
    await s.act(async () => {
      for (let index = 0; index < proposals.length; index++) {
        if (projectRef.current !== s.project!.id) break;
        const proposal = proposals[index];
        const event = await s.submit(proposal.spec.kind, proposal.spec.parameters, proposal.spec.name ?? proposal.title);
        submitted.push(event.id); const remaining = proposals.slice(index + 1);
        setStageJobs([...submitted]); setAnswer(current => current ? { ...current, proposals: remaining } : current);
        await request("ai.state.save", { projectId: s.project!.id, state: { proposals: remaining, stageJobIds: [...submitted] } });
      }
    });
    setStageJobs(submitted); setBusy(false);
  }
  return <aside className="r-ai" style={hidden ? { display: "none" } : undefined}><div className="r-toolbar"><h2>AI 研究助手</h2><span className="r-tag">辅助研究</span></div><nav className="r-subtabs" aria-label="AI 模式">{([ ["ask", "问答"], ["assist", "辅助配置"], ["research", "自主研究"] ] as const).map(([id, title]) => <button key={id} className={mode === id ? "active" : ""} disabled={busy || !loaded} onClick={() => void s.act(async () => { await request("ai.state.save", { projectId: s.project!.id, state: { mode: id } }); setMode(id); })}>{title}</button>)}</nav>
    {showSettings ? <div className="r-ai-settings"><h3>模型设置</h3><div className="r-toolbar"><button className={endpoint === "online" ? "active" : ""} onClick={() => setEndpoint("online")}>在线兼容服务</button><button className={endpoint === "local" ? "active" : ""} onClick={() => setEndpoint("local")}>本地服务</button></div>{settings && <><Field label={endpoint === "local" ? "本地服务地址" : "兼容 API 地址"}><input placeholder={endpoint === "local" ? "http://localhost:8000/v1" : "https://…/v1"} value={settings.ai.baseUrl} onChange={e => setSettings({ ...settings, ai: { ...settings.ai, baseUrl: e.target.value } })} /></Field><Field label="模型名称"><input value={settings.ai.model} onChange={e => setSettings({ ...settings, ai: { ...settings.ai, model: e.target.value } })} /></Field><Field label="API Key"><input autoComplete="off" type="password" value={settings.ai.apiKey} onChange={e => setSettings({ ...settings, ai: { ...settings.ai, apiKey: e.target.value } })} /></Field><Field label="Temperature"><input type="number" min={0} max={2} step={0.1} value={settings.ai.temperature} onChange={e => setSettings({ ...settings, ai: { ...settings.ai, temperature: Number(e.target.value) } })} /></Field><Field label="默认数据源"><select value={settings.defaultDataSource} onChange={e => setSettings({ ...settings, defaultDataSource: e.target.value as Settings["defaultDataSource"] })}><option value="baostock">BaoStock</option><option value="akshare">AKShare</option></select></Field><button onClick={() => { setEndpoint("online"); setSettings({ ...settings, ai: { ...settings.ai, baseUrl: "https://openrouter.ai/api/v1", model: "inclusionai/ling-3.0-flash-fin:free" } }); }}>使用 OpenRouter · Ling 默认值</button><button className="r-primary" onClick={() => void s.act(async () => { await request("settings.save", { settings }); setShowSettings(false); closeSettings(); s.setNotice("模型设置已保存；连接情况以实际请求结果为准"); })}>保存设置</button><button disabled={busy || !s.project || !loaded} onClick={() => { const projectId = s.project!.id; setBusy(true); void s.act(async () => { await request("settings.save", { settings }); await request("ai.chat", { projectId, mode: "ask", message: "请简短回复，确认本次真实请求已收到。" }); await refreshChat(projectId); s.setNotice("服务已返回本次真实请求；研究工具能力仍以实际实验为准。"); }).finally(() => setBusy(false)); }}>保存并发送连接请求</button>{!s.project && <p className="r-note">先打开项目，再发送真实连接请求。</p>}</>}<button onClick={() => { setShowSettings(false); closeSettings(); }}>返回对话</button><p className="r-note">本地模型需先启动兼容服务，模型权重不随桌面程序分发。</p></div> : <><div className="r-chat-log" aria-live="polite">{!messages.length && <><div className="r-chat-intro"><span className="r-ai-symbol">◎</span><p>围绕你的研究目标，挑选因子、调整参数，或解释已有实验。</p></div><h3>你可以尝试</h3><button className="r-suggestion" disabled={!s.project} onClick={() => setInput("请根据项目目标规划一次因子比较，先讨论方案。")}>规划一次因子比较 <span>→</span></button><button className="r-suggestion" disabled={!s.project} onClick={() => setInput("请解释当前项目最近实验的结果、局限和下一步。")}>解释实验结果 <span>→</span></button></>}{messages.map((m, i) => <div key={i} className={`r-message ${m.role}`}><small>{m.role === "user" ? "你" : "研究助手"}</small><p>{m.content}</p>{m.phase && <small>{m.phase}</small>}{m.experimentIds?.map(id => <button key={id} onClick={() => { s.setSelectedExperiment(id); s.setPage("results"); }}>{s.experiments.find(e => e.id === id)?.name ?? id} →</button>)}</div>)}{busy && <p role="status">正在处理…</p>}{answer?.phase && <p className="r-note">研究阶段：{answer.phase}</p>}{answer?.proposals.map((proposal, i) => <section className="r-proposal" key={i}><h3>{proposal.title}</h3><p>{proposal.description}</p><details><summary>查看参数</summary><pre>{JSON.stringify(proposal.spec.parameters, null, 2)}</pre></details>{mode === "assist" && <button disabled={busy} onClick={() => void s.act(() => applyProposal(proposal))}>应用参数</button>}</section>)}{mode === "research" && !!answer?.proposals.length && <button className="r-primary" disabled={busy || stageJobs.length > 0 && !terminal} onClick={() => void runStage()}>运行这一阶段（{answer.proposals.length} 项）</button>}{stageJobs.length > 0 && <div className="r-note">{stageJobs.map(id => { const job = s.jobs.find(j => j.id === id); return <p key={id}>{job?.name ?? id} · {job ? ({ queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断" } as Record<string, string>)[job.status] ?? job.status : "正在读取任务状态"}</p>; })}</div>}{terminal && <button className="r-primary" disabled={busy} onClick={() => void send(`本阶段任务已结束。请读取这些任务及其结果，讨论下一阶段，先不要执行：${stageJobs.join(", ")}`)}>携本阶段结果继续讨论</button>}</div><form className="r-chat-compose" onSubmit={e => { e.preventDefault(); void send(); }}><textarea aria-label="研究问题" placeholder={s.project ? "描述你的研究问题…" : "先创建或打开一个项目"} value={input} onChange={e => setInput(e.target.value)} disabled={!s.project} /><button type="submit" className="r-send" aria-label="发送研究问题" disabled={busy || !loaded || !input.trim() || !s.project}>→</button></form><div className="r-toolbar r-ai-footer"><button onClick={() => setShowSettings(true)}>模型设置</button><span>{mode === "research" ? "每阶段结束后讨论" : "结果以实验为准"}</span></div></>}
  </aside>;
}
