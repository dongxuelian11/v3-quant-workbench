import React, { useState } from "react";
import { modelFamilies, runs } from "../demo";
import { useWorkbench } from "../store";
import { commandRegistry } from "../commandRegistry";
import { Icon, MetricRail, TruthMark } from "./PresentationSystem";

type ModelPhase = "dataset" | "configure" | "run" | "study" | "compare" | "version";

export function ModelWorkflowPanel() {
  const [phase, setPhase] = useState<ModelPhase>("dataset");
  const phases: { id: ModelPhase; step: string; title: string; detail: string }[] = [
    { id: "dataset", step: "01", title: "Dataset", detail: "数据与切分" },
    { id: "configure", step: "02", title: "Configure", detail: "模型与守卫" },
    { id: "run", step: "03", title: "Run", detail: "运行与产物" },
    { id: "study", step: "04", title: "Study", detail: "Trial / HPO" },
    { id: "compare", step: "05", title: "Compare", detail: "候选比较" },
    { id: "version", step: "06", title: "Version", detail: "信号与交接" }
  ];
  return <section className="panel-page model-workspace" data-primary-panel="model-workflow" data-major-panel>
    <header className="workflow-header"><div><small>MODEL LAB · PHASED WORKFLOW</small><h1>{phases.find((item) => item.id === phase)?.title}</h1><span>Study S-014 · {phase === "version" ? "release review" : "working session"}</span></div><nav aria-label="模型工作流阶段" role="tablist">{phases.map((item) => <button key={item.id} role="tab" aria-selected={phase === item.id} aria-controls="model-active-phase" data-model-phase={item.id} className={phase === item.id ? "active" : ""} onClick={() => setPhase(item.id)}><i>{item.step}</i><span><b>{item.title}</b><small>{item.detail}</small></span></button>)}</nav><TruthMark detail="lineage guarded"/></header>
    <div id="model-active-phase" role="tabpanel" className="model-phase" data-model-active-phase={phase}>{phase === "dataset" ? <ModelDatasetPanel onNext={() => setPhase("configure")}/> : phase === "configure" ? <ModelConfigurePanel onNext={() => setPhase("run")}/> : phase === "run" ? <ModelRunsContent onCompare={() => setPhase("compare")}/> : phase === "study" ? <ModelStudyPanel/> : phase === "compare" ? <ModelComparePanel onVersion={() => setPhase("version")}/> : <ModelVersionPanel/>}</div>
  </section>;
}

function ModelDatasetPanel({ onNext }: { onNext: () => void }) {
  const model = useWorkbench((state) => state.model);
  const focusContext = useWorkbench((state) => state.focusContext);
  const [split, setSplit] = useState(model.splitPlan);
  return <div className="model-stage dataset-stage" data-major-panel>
    <div className="stage-intro"><small>01 · INPUT CONTRACT</small><h2>锁定可复现的数据边界</h2><p>先确认 DatasetVersion、标签与时序切分，再进入模型配置。当前阶段只展示输入契约和泄漏守卫。</p><TruthMark detail="Demo dataset"/></div>
    <div className="dataset-contract primary-canvas" data-primary-canvas>
      <div className="section-head"><div><small>DATASET / SPLIT</small><h2>{model.datasetVersion}</h2></div><span className="version">available 2026-06-30 15:05 CST</span></div>
      <div className="contract-fields"><label>DatasetVersion<select defaultValue={model.datasetVersion}><option>{model.datasetVersion}</option><option>DatasetVersion/demo-cn-factor-v11</option></select></label><label>Label<select defaultValue={model.label}><option>{model.label}</option><option>next_5d_rank_return</option></select></label><label>SplitPlan<select value={split} onChange={(event) => setSplit(event.target.value as typeof split)}><option value="chronological">Chronological</option><option value="rolling">Rolling</option><option value="expanding">Expanding</option><option value="purge-embargo">Purge / Embargo</option><option value="walk-forward">Walk-forward</option></select></label></div>
      <div className="split-timeline"><div className="train"><span>TRAIN</span><b>2021-01 → 2024-12</b></div><i/><div className="validation"><span>VALIDATE</span><b>2025-01 → 2025-12</b></div><i/><div className="test"><span>TEST</span><b>2026-01 → 2026-06</b></div></div>
      <div className="leakage-audit"><div><small>TEMPORAL GUARDS</small><h3>Leakage audit passed</h3></div><p><span className="ok">✓ 时序边界</span><span className="ok">✓ 标签延迟 20D</span><span>purge 5D · embargo 2D</span></p><button onClick={() => focusContext({ kind: "model-run", eyebrow: "LEAKAGE AUDIT", title: "Dataset / Split temporal guard", summary: "时序边界、标签延迟、purge 与 embargo 证据已映射到当前输入契约。", facts: [{ label: "SplitPlan", value: split }, { label: "Purge", value: "5D" }, { label: "Embargo", value: "2D" }], provenance: "DeterministicFrontendDemoProvider/v1", trace: "dataset.locked → split.guarded → inspector.explained" })}>检查证据</button></div>
      <div className="stage-next"><span>输入契约完整 · 可进入模型配置</span><button className="primary" onClick={onNext}>继续配置 <Icon name="chevron" size={14}/></button></div>
    </div>
  </div>;
}

function ModelConfigurePanel({ onNext }: { onNext: () => void }) {
  const model = useWorkbench((state) => state.model);
  const setFamily = useWorkbench((state) => state.setModelFamily);
  return <div className="model-stage configure-stage" data-major-panel>
    <div className="stage-intro"><small>02 · RUN CONFIGURATION</small><h2>选择模型族与训练守卫</h2><p>七类模型族共享相同的版本、审计与运行契约；参数只影响当前 Demo 运行配置。</p><TruthMark detail="Demo configuration"/></div>
    <div className="configure-canvas primary-canvas" data-primary-canvas>
      <div className="family-selector"><small>MODEL FAMILY</small><h3>{model.family}</h3><select aria-label="模型族" value={model.family} onChange={(event) => setFamily(event.target.value as typeof model.family)}>{modelFamilies.map((family) => <option data-model-family={family} key={family}>{family}</option>)}</select><div className="family-list">{modelFamilies.map((family, index) => <button key={family} className={model.family === family ? "active" : ""} onClick={() => setFamily(family)}><i>{String(index + 1).padStart(2,"0")}</i><span>{family}</span></button>)}</div></div>
      <div className="parameter-sheet"><div className="section-head"><div><small>TRAINING CONTRACT</small><h2>{model.family} / demo-run-config-v5</h2></div><span className="state">DRAFT</span></div><div className="parameter-grid"><label>learning_rate<input type="number" defaultValue="0.028" step="0.001"/></label><label>num_leaves<input type="number" defaultValue="31"/></label><label>max_depth<input type="number" defaultValue="8"/></label><label>objective<select><option>rank_xendcg</option><option>regression_l2</option></select></label><label>seed<input type="number" defaultValue="20260809"/></label><label>early_stopping<input type="number" defaultValue="50"/></label></div><div className="guard-lines"><span className="ok">✓ deterministic seed</span><span className="ok">✓ feature schema locked</span><span className="ok">✓ runtime budget 45m</span></div><div className="config-lineage"><small>CONFIG LINEAGE</small><code>{model.datasetVersion} → {model.splitPlan} → {model.family} → demo-run-config-v5</code></div><div className="stage-next"><span>配置守卫完整 · 尚未产生正式模型输出</span><button className="primary" onClick={onNext}>创建 Demo Run <Icon name="chevron" size={14}/></button></div></div>
    </div>
  </div>;
}

export function ModelRunsPanel() { return <ModelRunsContent/>; }

function ModelRunsContent({ onCompare }: { onCompare?: () => void }) {
  const model = useWorkbench((state) => state.model);
  const toggle = useWorkbench((state) => state.toggleRun);
  const [compareReceipt, setCompareReceipt] = useState("选择运行后可进行上下文比较");
  return <div className="model-stage run-stage" data-major-panel>
    <div className="stage-intro"><small>03 · RUN / ARTIFACTS</small><h2>运行并检查候选产物</h2><p>{model.datasetVersion}<br/>{model.family} · {model.splitPlan}</p><TruthMark detail="Deterministic runs"/></div>
    <div className="run-comparison primary-canvas" data-primary-canvas>
      <div className="section-head"><div><small>RUNS / ARTIFACTS</small><h2>Study S-014 · Candidate runs</h2></div><b>{model.selectedRunIds.length} selected</b></div>
      <div className="grid-head run"><span></span><span>RUN</span><span>FAMILY</span><span>RANK IC</span><span>STATUS</span><span>DURATION</span></div>
      {runs.map((run) => <button className={`run-row ${model.selectedRunIds.includes(run.id) ? "selected" : ""}`} onClick={() => toggle(run.id)} key={run.id}><span>{model.selectedRunIds.includes(run.id) ? "●" : "○"}</span><b>{run.id}</b><span>{run.family}</span><span>{run.score}</span><span className={run.state === "BEST" ? "ok" : ""}>{run.state}</span><span>{run.duration}</span></button>)}
      <div className="run-detail"><div><small>SELECTED RUN</small><h3>{model.selectedRunIds[0] ?? "No run selected"}</h3></div><dl><dt>Params</dt><dd>leaves=31 · lr=0.028 · depth=8</dd><dt>Artifacts</dt><dd>metrics.json · feature-importance</dd><dt>Available time</dt><dd>2026-06-30 18:42 CST</dd></dl><div className="detail-action"><button onClick={() => { setCompareReceipt(model.selectedRunIds.length ? `比较上下文已就绪 · ${model.selectedRunIds.length} selected` : "请先选择至少一个运行"); if (model.selectedRunIds.length) onCompare?.(); }} disabled={model.selectedRunIds.length === 0}>比较候选</button><span role="status" aria-live="polite">{compareReceipt}</span></div></div>
    </div>
  </div>;
}

function ModelComparePanel({ onVersion }: { onVersion: () => void }) {
  const model = useWorkbench((state) => state.model);
  const ids = model.selectedRunIds.length ? model.selectedRunIds : ["RUN-018", "RUN-017"];
  return <div className="model-stage compare-stage" data-major-panel><div className="stage-intro"><small>05 · CANDIDATE COMPARE</small><h2>用同一证据窗比较候选</h2><p>指标、稳定性、延迟与 lineage 使用统一尺度；比较不会产生正式模型版本。</p><TruthMark detail="Demo comparison"/></div><div className="compare-canvas primary-canvas" data-primary-canvas><div className="section-head"><div><small>RUN COMPARISON</small><h2>{ids.join("  /  ")}</h2></div><span>{ids.length} candidates</span></div><MetricRail items={[{ label: "Best Rank IC", value: "0.084", tone: "positive" }, { label: "Stability", value: "0.87" }, { label: "Coverage", value: "96.8%" }, { label: "Latency", value: "42 ms" }]}/><div className="compare-plot"><div className="radar-placeholder"><span>Rank IC</span><span>Stability</span><span>Coverage</span><span>Latency</span><i/></div><div className="compare-table"><div><span>Candidate</span><span>Rank IC</span><span>Drift</span><span>Decision</span></div>{ids.map((id,index) => <button key={id}><b>{id}</b><span>{index === 0 ? "0.084" : "0.079"}</span><span>{index === 0 ? "0.04" : "0.06"}</span><span className={index === 0 ? "ok" : "muted"}>{index === 0 ? "PROMOTE" : "RETAIN"}</span></button>)}</div></div><div className="stage-next"><span>RUN-018 满足 Demo promotion gates</span><button className="primary" onClick={onVersion}>审阅版本与信号 <Icon name="chevron" size={14}/></button></div></div></div>;
}

export function ModelStudyPanel() {
  const model = useWorkbench((state) => state.model);
  const setState = useWorkbench((state) => state.setModelState);
  const [view, setView] = useState("Trial History");
  const [receipt, setReceipt] = useState("ready");
  const act = async (name: "study.resume" | "study.pause" | "study.cancel" | "study.checkpoint", next: typeof model.studyState) => {
    const id = `${name}-checkpoint-${model.checkpoint}`;
    const result = await commandRegistry.execute(name, id);
    setReceipt(`${result.id} · ${result.duplicate ? "DUPLICATE SUPPRESSED" : "EXECUTED ONCE"} · count=${result.executionCount}`);
    if (!result.duplicate) setState(next);
  };
  const views = ["Trial History", "Importance", "Relationships", "Parallel Coordinates", "Pareto"];
  return <div className="study-workflow" data-testid="model-study" data-major-panel>
    <header className="study-head"><div><small>OPTUNA-STYLE STUDY / TRIAL / HPO</small><h2>Study S-014 · {model.family}</h2></div><span className={`state ${model.studyState}`}>{model.studyState.toUpperCase()}</span><span>checkpoint #{model.checkpoint}</span><div className="study-actions">{model.studyState === "running" ? <button className="primary" onClick={() => void act("study.pause", "paused")}>Ⅱ Pause</button> : <button className="primary" onClick={() => void act("study.resume", "running")}>▶ Resume</button>}<button onClick={() => void act("study.checkpoint", "checkpointed")} disabled={model.studyState === "cancelled"}>◆ Checkpoint</button><button className="danger" onClick={() => void act("study.cancel", "cancelled")} disabled={model.studyState === "cancelled"}>× Cancel</button></div></header>
    <div className="mini-tabs" role="tablist" aria-label="Study 分析视图">{views.map((item) => <button role="tab" aria-selected={item === view} className={item === view ? "active" : ""} onClick={() => setView(item)} key={item}>{item}</button>)}</div>
    <div className="study-viz primary-canvas" data-primary-canvas><div className="trial-chart">{Array.from({ length: 24 }, (_, index) => <i key={index} className={index > 17 ? "pending" : index === 17 ? "best" : ""} style={{ height: `${22 + ((index * 19) % 72)}%` }} title={`Trial ${index + 1}`} />)}</div><aside><span className="truth-line"><i /> DEMO HPO</span><h3>{view}</h3><p>24 Trials · 18 complete · 2 pruned · 1 checkpoint · 3 queued</p><dl><dt>Best Trial</dt><dd>T-018 / Rank IC 0.084</dd><dt>Primary importance</dt><dd>learning_rate · num_leaves</dd><dt>Pareto axes</dt><dd>Rank IC ↑ / latency ↓</dd></dl></aside></div>
    <div className="command-receipt" role="status" aria-live="polite"><b>CommandRegistry exactly-once</b><code>{receipt}</code></div>
  </div>;
}

export function ModelVersionPanel() {
  const model = useWorkbench((state) => state.model);
  const [tab, setTab] = useState<"ModelVersion" | "Signal">("ModelVersion");
  const [handoffReceipt, setHandoffReceipt] = useState("Backtest handoff 尚未创建");
  return <div className="version-workflow" data-major-panel>
    <div className="mini-tabs" role="tablist" aria-label="版本与信号视图"><button role="tab" aria-selected={tab === "ModelVersion"} data-model-version-tab="model" className={tab === "ModelVersion" ? "active" : ""} onClick={() => setTab("ModelVersion")}>Immutable ModelVersion</button><button role="tab" aria-selected={tab === "Signal"} data-model-version-tab="signal" className={tab === "Signal" ? "active" : ""} onClick={() => setTab("Signal")}>PredictionSignalVersion</button></div>
    {tab === "ModelVersion" ? <div className="version-review primary-canvas" data-primary-canvas><div className="version-identity"><span className="lock">◆ IMMUTABLE</span><small>MODEL VERSION</small><h2>{model.modelVersion}</h2><code>content-sha256: demo:8b32…7c91</code></div><div className="version-metrics"><Metric k="Rank IC" v="0.084"/><Metric k="Coverage" v="96.8%"/><Metric k="Leakage" v="PASS"/><Metric k="Family" v={model.family}/></div><div className="lineage-flow"><span>{model.datasetVersion}</span><i>→</i><span>{model.splitPlan}</span><i>→</i><span>RUN-018</span><i>→</i><span>{model.modelVersion}</span></div></div> : <div className="signal-review primary-canvas" data-primary-canvas><div><span className="truth-line"><i /> DEMO SIGNAL</span><small>PREDICTION SIGNAL VERSION</small><h2>{model.predictionSignalVersion}</h2><p>由不可变 ModelVersion 派生的版本化信号；质量守卫与来源链保持可见。</p></div><div className="quality-grid"><span><b>0.91</b>完整性</span><span><b>0.87</b>稳定性</span><span><b>0.04</b>漂移</span><span><b>96.8%</b>覆盖</span></div><div className="handoff-line"><span>{model.modelVersion}</span><i>→</i><span>{model.predictionSignalVersion}</span><i>→</i><button className="primary" onClick={() => setHandoffReceipt("BacktestHandoffDraft/demo-v8 已在前端 Demo 会话中就绪")}>交接到 BacktestHandoffDraft</button></div><span className="action-receipt handoff-receipt" role="status" aria-live="polite">{handoffReceipt}</span></div>}
  </div>;
}

function Metric({ k, v }: { k: string; v: string }) { return <div><small>{k}</small><b>{v}</b></div>; }
