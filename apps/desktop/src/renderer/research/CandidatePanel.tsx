import React, { useEffect, useState } from "react";
import type { JsonObject, ResearchCandidate, ResearchCandidateCode, WorkspacePanel } from "../../../../../packages/contracts/src/research";
import { request, errorText, useResearch } from "./state";
import { flushDrafts, useWorkspace } from "./workspace";
import { CodeEditor, DataTable, Empty, Field, Heading, fieldLabel, valueText } from "./ui";
import { object } from "./configuration";
import { RDStageEvent } from "./RDStagePanel";

function flatten(value: JsonObject, prefix = ""): Record<string, string> {
  return Object.fromEntries(Object.entries(value).flatMap(([key, entry]) => {
    const name = prefix ? `${prefix}.${key}` : key;
    return entry && typeof entry === "object" && !Array.isArray(entry)
      ? Object.entries(flatten(entry, name)) : [[name, valueText(entry)]];
  }));
}

export function CandidatePanel({ panel }: { panel: WorkspacePanel }) {
  const s = useResearch(), w = useWorkspace();
  const [library,setLibrary]=useState<{id:string;name:string;sourceRevision:number;candidate:{kind:ResearchCandidate["kind"]}}[]>([]);
  const [list, setList] = useState<ResearchCandidate[]>([]);
  const [candidate, setCandidate] = useState<ResearchCandidate | null>(null);
  const [name, setName] = useState(""), [description, setDescription] = useState("");
  const [summary, setSummary] = useState(""), [text, setText] = useState("{}");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [targetStrategy, setTargetStrategy] = useState("");
  const [libraryTargets,setLibraryTargets]=useState<Record<string,string>>({});
  const [sources, setSources] = useState<Record<string, { code?: ResearchCandidateCode; content: string; error?: string }>>({});
  const sourceDirty = Object.values(sources).some(source => source.code && source.content !== source.code.content);
  const install = (value: ResearchCandidate) => {
    setCandidate(value); setTargetStrategy(value.strategyId ?? ""); setName(value.name); setDescription(value.description ?? "");
    setSummary(value.changeSummary ?? ""); setText(JSON.stringify(value.spec.parameters, null, 2)); setDirty(false);
  };
  const refreshList = async () => {
    const values = await request<ResearchCandidate[]>("candidates.list", { projectId: panel.projectId, strategyId: panel.strategyId });
    setList(values); return values;
  };
  useEffect(() => {
    let alive = true; setCandidate(null); setError("");
    void (async () => {
      const values = await refreshList();
      const value = panel.candidateId
        ? await request<ResearchCandidate>("candidates.get", { projectId: panel.projectId, candidateId: panel.candidateId }) : values[0];
      if (alive && value) install(value);
    })().catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [panel.projectId, panel.strategyId, panel.candidateId]);
  useEffect(() => {
    let alive = true;
    setSources({});
    if (!candidate) return;
    const params = candidate.spec.parameters;
    const targets = [
      ...(typeof params.codePath === "string" && params.codePath ? [{ key: "model", factorId: undefined }] : []),
      ...(Array.isArray(params.customFactors) ? params.customFactors.flatMap(value => {
        const factor = object(value);
        return factor.source === "parquet" && typeof factor.id === "string" && factor.codePath ? [{ key: `factor:${factor.id}`, factorId: factor.id }] : [];
      }) : [])
    ];
    setSources(Object.fromEntries(targets.map(target => [target.key, { content: "" }])));
    for (const target of targets) void request<ResearchCandidateCode>("candidates.code.get", {
      projectId: panel.projectId, candidateId: candidate.id, factorId: target.factorId
    }).then(code => { if (alive) setSources(current => ({ ...current, [target.key]: { code, content: code.content } })); })
      .catch(e => { if (alive) setSources(current => ({ ...current, [target.key]: { content: "", error: errorText(e) } })); });
    return () => { alive = false; };
  }, [panel.projectId, candidate?.id]);
  useEffect(() => window.v3Research?.onEvent(event => {
    if (event.projectId === panel.projectId && ["completed", "failed", "cancelled", "interrupted"].includes(event.status)) {
      void refreshList().then(values => {
        // Completed experiments may be appended while this candidate is being edited.
        setCandidate(current => current ? { ...current, experiments: values.find(v => v.id === current.id)?.experiments ?? current.experiments } : current);
      }).catch(e => setError(errorText(e)));
    }
  }), [panel.projectId, panel.strategyId]);
  let parameters: JsonObject = {}, parseError = "";
  try {
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("运行参数须为 JSON 对象。");
    parameters = parsed as JsonObject;
  } catch (e) { parseError = errorText(e); }
  const save = async () => {
    if (!candidate || parseError || !name.trim()) throw new Error(parseError || "请填写候选名称。");
    const edits = Object.entries(sources).filter(([, source]) => source.code && source.content !== source.code.content);
    for (const [, source] of edits) {
      const code = source.code!;
      const path = code.factorId ? (Array.isArray(parameters.customFactors) ? parameters.customFactors.map(object).find(f => f.id === code.factorId)?.codePath : undefined) : parameters.codePath;
      if (path !== code.path) throw new Error("源码编辑期间请保留对应的代码路径和因子编号，再保存候选。");
    }
    let saved = await request<ResearchCandidate>("candidates.save", { projectId: panel.projectId, candidate: {
      id: candidate.id, name: name.trim(), description, changeSummary: summary, spec: { ...candidate.spec, parameters }
    } });
    try {
      for (const [key, source] of edits) {
        const result = await request<{ candidate: ResearchCandidate; code: ResearchCandidateCode }>("candidates.code.save", {
          projectId: panel.projectId, candidateId: saved.id, factorId: source.code!.factorId, content: source.content
        });
        saved = result.candidate;
        setSources(current => ({ ...current, [key]: { code: result.code, content: result.code.content } }));
      }
    } catch (e) {
      install(saved);
      throw new Error(`参数已保存；部分源码未保存，请修正后重试。${errorText(e)}`);
    }
    install(saved); await refreshList(); w.updatePanel(panel.id, { candidateId: saved.id, title: saved.name }); return saved;
  };
  const act = (work: () => Promise<unknown>) => {
    setBusy(true); setError(""); void work().catch(e => setError(errorText(e))).finally(() => setBusy(false));
  };
  const strategy = w.strategies.find(value => value.projectId === panel.projectId && value.id === (candidate?.strategyId || targetStrategy));
  const section = candidate?.kind === "factor" ? "factorAnalysis" : candidate?.kind === "model" ? "model" : "backtest";
  const baseline = { ...object(strategy?.settings[section]), ...Object.fromEntries(
    [["selectedFactors", "factorIds"], ["factorProcessing", "factorProcessing"], ["customFactors", "customFactors"]]
      .flatMap(([source, target]) => strategy?.settings[source] === undefined ? [] : [[target, strategy.settings[source]]])
  ) };
  const left = flatten(baseline), right = flatten(parameters);
  const differences = [...new Set([...Object.keys(left), ...Object.keys(right)])].filter(key => left[key] !== right[key]);
  const codeKeys=["dailyCode","code"].filter(key=>typeof parameters[key]==="string");
  const originJob=candidate?.sourceConversationId?s.jobs.find(job=>job.kind==='rdagent.run'&&job.projectId===candidate.projectId&&job.strategyId===candidate.strategyId&&job.spec?.parameters.sourceConversationId===candidate.sourceConversationId):undefined;
  const sourceEditor = (key: string) => {
    const source = sources[key];
    return !source ? <p className="r-note">未记录可载入的源代码。修改代码路径后请重新打开候选。</p> : source.error ? <p role="alert">源码载入失败：{source.error}</p> : !source.code ? <p className="r-note">正在载入真实 Python 源码…</p> : <>
      <p className="r-note">{source.code.path} · 修改后保存为新的候选代码版本；需要重新运行实验。</p>
      <CodeEditor label="候选 Python 源码" value={source.content} onChange={content => { if (!busy) setSources(current => ({ ...current, [key]: { ...source, content } })); }} />
    </>;
  };
  return <div className="r-page"><Heading title="研究候选" description="独立保存、运行和比较候选；明确采用后才更新研究草稿。" />
    {error && <p role="alert">{error}</p>}
    <details onToggle={e=>{if(e.currentTarget.open)void request<typeof library>("candidates.library.list").then(setLibrary).catch(error=>setError(errorText(error)));}}><summary>个人候选库 · 导入独立副本</summary><p className="r-note">收藏与导入均由你手动发起；另一项目的副本不会改动原项目或共用库。</p>{library.map(item=><div className="r-toolbar" key={item.id}><span>{item.name} · {({factor:"因子",model:"模型",strategy:"策略"})[item.candidate.kind]} · 收藏版本 {item.sourceRevision}</span>{item.candidate.kind!=="factor"&&<select aria-label={`${item.name}导入目标策略`} value={libraryTargets[item.id]??""} onChange={e=>setLibraryTargets(values=>({...values,[item.id]:e.target.value}))}><option value="">选择目标策略</option>{w.strategies.filter(value=>value.projectId===panel.projectId).map(value=><option key={value.id} value={value.id}>{value.name}</option>)}</select>}<button disabled={busy||dirty||sourceDirty||(item.candidate.kind!=="factor"&&!libraryTargets[item.id])} onClick={()=>act(async()=>{const value=await request<ResearchCandidate>("candidates.library.import",{projectId:panel.projectId,libraryId:item.id,...(item.candidate.kind!=="factor"?{strategyId:libraryTargets[item.id]}:{})});install(value);await refreshList();w.updatePanel(panel.id,{candidateId:value.id,strategyId:value.strategyId,title:value.name});})}>导入当前项目</button><button disabled={busy} onClick={()=>act(async()=>{await request("candidates.library.delete",{libraryId:item.id});setLibrary(await request("candidates.library.list"));})}>移出共用库</button></div>)}{!library.length&&<p className="r-note">暂无手动收藏的因子、模型或策略。</p>}</details>
    <select aria-label="选择研究候选" value={candidate?.id ?? ""} disabled={busy || dirty || sourceDirty} onChange={event => w.updatePanel(panel.id, { candidateId: event.target.value })}>
      {!candidate && <option value="">暂无候选</option>}{list.map(value => <option key={value.id} value={value.id}>{value.name} · 版本 {value.revision}</option>)}
    </select>
    {!candidate ? <Empty title="还没有可编辑的候选">在研究助手中提出因子、模型或日线策略方案后，打开候选查看。</Empty> : <>
      <p className="r-note">{candidate.strategyId ? `关联策略：${strategy?.name ?? candidate.strategyId}` : "项目独立因子候选 · 尚未关联策略"} · 候选版本 {candidate.revision}{dirty || sourceDirty ? " · 有未保存修改" : " · 已保存"} · {candidate.adoptedRevision ? `曾采用版本 ${candidate.adoptedRevision}` : "尚未采用"}</p>
      <Field label="候选名称"><input disabled={busy} value={name} onChange={e => { setName(e.target.value); setDirty(true); }} /></Field>
      <Field label="中文逻辑说明"><textarea disabled={busy} rows={3} value={description} onChange={e => { setDescription(e.target.value); setDirty(true); }} /></Field>
      <Field label="修改摘要"><textarea disabled={busy} rows={2} value={summary} onChange={e => { setSummary(e.target.value); setDirty(true); }} /></Field>
      <h3>{strategy ? "与所选策略草稿的参数差异" : "独立候选参数"}</h3>
      {!parseError && <DataTable table={{ name: "候选参数差异", columns: ["参数", "当前草稿", "候选"], rows: differences.map(key => ({ 参数: fieldLabel(key), 当前草稿: left[key] ?? "未设置", 候选: right[key] ?? "未设置" })) }} />}
      {!parseError && codeKeys.map(codeKey=><details key={codeKey}><summary>{codeKey==="dailyCode"?"完整日线决策 Python":"高级评分 Python"} · 可编辑</summary><CodeEditor value={String(parameters[codeKey])} onChange={code => { if (!busy) { setText(JSON.stringify({ ...parameters, [codeKey]: code }, null, 2)); setDirty(true); } }} /></details>)}
      {!parseError&&Array.isArray(parameters.customFactors)&&parameters.customFactors.map((value,index)=>{const factor=object(value);if(factor.source==='parquet')return <details key={String(factor.id??index)}><summary>{String(factor.name??factor.id??'生成因子')} · Python 生成因子</summary>{sourceEditor(`factor:${String(factor.id??index)}`)}<p>已生成数据：{String(factor.dataPath??'未记录数据路径')}</p></details>;return <details key={String(factor.id??index)}><summary>{String(factor.name??factor.id??'自定义因子')} · 因子公式</summary><CodeEditor language="plaintext" label="候选因子公式" value={String(factor.expression??'')} onChange={expression=>{if(!busy){setText(JSON.stringify({...parameters,customFactors:(parameters.customFactors as unknown[]).map((entry,i)=>i===index?{...factor,expression}:entry)},null,2));setDirty(true);}}}/></details>;})}
      {!parseError && typeof parameters.codePath === "string" && <details><summary>模型 Python 源码 · 可编辑</summary>{sourceEditor("model")}</details>}
      <details><summary>完整运行参数 · JSON / 公式</summary><textarea aria-label="候选完整参数" disabled={busy} rows={14} value={text} onChange={e => { setText(e.target.value); setDirty(true); }} /></details>
      {parseError && <p role="alert">{parseError}</p>}
      {!candidate.strategyId&&<Field label="采用到策略（仅在点击采用时更新）"><select aria-label="因子候选采用目标策略" value={targetStrategy} onChange={e=>setTargetStrategy(e.target.value)}><option value="">选择目标策略</option>{w.strategies.filter(value=>value.projectId===panel.projectId).map(value=><option key={value.id} value={value.id}>{value.name}</option>)}</select></Field>}
      <div className="r-toolbar">
        {<button disabled={busy||!!parseError||!name.trim()} onClick={()=>act(async()=>{const saved=await save();await request("candidates.library.save",{projectId:panel.projectId,candidateId:saved.id});setLibrary(await request("candidates.library.list"));s.setNotice("已手动收藏候选版本，其他项目导入时创建独立副本。");})}>收藏到个人候选库</button>}
        <button disabled={busy || !!parseError || !name.trim()} onClick={() => act(save)}>保存候选版本</button>
        <button disabled={busy || !!parseError || !name.trim()} onClick={() => act(async () => { const saved = await save(); await request("jobs.submit", { spec: { ...saved.spec, candidateId: saved.id } }); s.setNotice(`候选版本 ${saved.revision} 已提交实验`); })}>保存并运行实验</button>
        <button className="r-primary" disabled={busy || !!parseError || !name.trim() || !(candidate.strategyId || targetStrategy)} onClick={() => act(async () => { const adoptedStrategy=candidate.strategyId || targetStrategy; await flushDrafts(); const saved = await save(); const result = await request<{ candidate: ResearchCandidate }>("candidates.adopt", { projectId: panel.projectId, candidateId: saved.id, strategyId: adoptedStrategy }); install(result.candidate); await w.reload(); s.setNotice("候选已采用为研究草稿；每日选股启用版本和实际持仓未改变"); })}>采用到所选策略草稿</button>
      </div>
      {candidate.sourceConversationId&&<button onClick={()=>act(()=>w.savePreferences({activeConversationId:candidate.sourceConversationId,aiVisible:true,rightPanel:"ai"}))}>返回来源会话</button>}
      {originJob&&<details><summary>来源会话的原生研究阶段 · {originJob.name}</summary><RDStageEvent job={originJob} blocked={busy||dirty||sourceDirty} onSubmitted={async()=>{await s.refresh();s.setNotice("已按本次确认继续来源研究阶段。");}}/></details>}
      <h3>对应真实实验</h3>{candidate.experiments.length>=2&&<button onClick={()=>w.open({kind:"compare",title:`${candidate.name} · 版本实验比较`,experimentRefs:candidate.experiments.map(ref=>({kind:"experiment",projectId:ref.projectId,strategyId:candidate.strategyId,experimentId:ref.experimentId,title:`版本 ${ref.revision}`}))})}>比较各版本实验</button>}<p className="r-note">修改后的版本需要重新运行；旧版本实验继续保留，不代表新版本的效果。</p>
      {candidate.experiments.length ? <div className="r-experiment-list">{candidate.experiments.map(ref => <button key={ref.experimentId} onClick={() => w.open({ kind: "experiment", projectId: ref.projectId, strategyId: candidate.strategyId, experimentId: ref.experimentId, title: `${candidate.name} · 版本 ${ref.revision} 实验` })}>版本 {ref.revision} · {ref.experimentId}</button>)}</div> : <Empty title="这个候选尚无已完成实验" />}
    </>}
  </div>;
}
