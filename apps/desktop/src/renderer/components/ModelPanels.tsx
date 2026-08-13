import React, { useState } from "react";
import { modelFamilies, runs } from "../demo";
import { useWorkbench } from "../store";
import { commandRegistry } from "../commandRegistry";
import { Icon, MetricRail, TruthMark } from "./PresentationSystem";

type ModelPhase = "dataset" | "configure" | "run" | "study" | "compare" | "version";

export function ModelWorkflowPanel() {
  const [phase, setPhase] = useState<ModelPhase>("dataset");
  const phases: { id: ModelPhase; step: string; title: string; detail: string }[] = [
    { id: "dataset", step: "01", title: "数据集", detail: "数据与切分" },
    { id: "configure", step: "02", title: "配置", detail: "模型与守卫" },
    { id: "run", step: "03", title: "运行", detail: "运行与产物" },
    { id: "study", step: "04", title: "试验", detail: "Trial / HPO" },
    { id: "compare", step: "05", title: "比较", detail: "候选比较" },
    { id: "version", step: "06", title: "版本", detail: "信号与交接" }
  ];
  return <section className="panel-page model-workspace" data-primary-panel="model-workflow" data-major-panel>
    <header className="workflow-header"><div><small>模型实验室 · 分阶段工作流</small><h1>{phases.find((item) => item.id === phase)?.title}</h1><span>试验 · Study S-014 · {phase === "version" ? "发布审阅" : "工作会话"}</span></div><nav aria-label="模型工作流阶段" role="tablist">{phases.map((item) => <button key={item.id} role="tab" aria-selected={phase === item.id} aria-controls="model-active-phase" data-model-phase={item.id} className={phase === item.id ? "active" : ""} onClick={() => setPhase(item.id)}><i>{item.step}</i><span><b>{item.title}</b><small>{item.detail}</small></span></button>)}</nav><TruthMark detail="来源链受控 · lineage guarded"/></header>
    <div id="model-active-phase" role="tabpanel" className="model-phase" data-model-active-phase={phase}>{phase === "dataset" ? <ModelDatasetPanel onNext={() => setPhase("configure")}/> : phase === "configure" ? <ModelConfigurePanel onNext={() => setPhase("run")}/> : phase === "run" ? <ModelRunsContent onCompare={() => setPhase("compare")}/> : phase === "study" ? <ModelStudyPanel/> : phase === "compare" ? <ModelComparePanel onVersion={() => setPhase("version")}/> : <ModelVersionPanel/>}</div>
  </section>;
}

function ModelDatasetPanel({ onNext }: { onNext: () => void }) {
  const model = useWorkbench((state) => state.model);
  const focusContext = useWorkbench((state) => state.focusContext);
  const [split, setSplit] = useState(model.splitPlan);
  return <div className="model-stage dataset-stage" data-major-panel>
    <div className="stage-intro"><small>01 · 输入契约</small><h2>锁定可复现的数据边界</h2><p>先确认 DatasetVersion、标签与时序切分，再进入模型配置。当前阶段只展示输入契约和泄漏守卫。</p><TruthMark detail="开发数据集 · Demo dataset"/></div>
    <div className="dataset-contract primary-canvas" data-primary-canvas>
      <div className="section-head"><div><small>数据集 / 切分</small><h2>{model.datasetVersion}</h2></div><span className="version">可用时间 2026-06-30 15:05 CST</span></div>
      <div className="contract-fields"><label>数据集版本 · DatasetVersion<select defaultValue={model.datasetVersion}><option>{model.datasetVersion}</option><option>DatasetVersion/demo-cn-factor-v11</option></select></label><label>标签 · Label<select defaultValue={model.label}><option>{model.label}</option><option>next_5d_rank_return</option></select></label><label>切分方案 · SplitPlan<select value={split} onChange={(event) => setSplit(event.target.value as typeof split)}><option value="chronological">时序 · Chronological</option><option value="rolling">滚动 · Rolling</option><option value="expanding">扩展 · Expanding</option><option value="purge-embargo">清除 / 禁运 · Purge / Embargo</option><option value="walk-forward">前向步进 · Walk-forward</option></select></label></div>
      <div className="split-timeline"><div className="train"><span>训练 · TRAIN</span><b>2021-01 → 2024-12</b></div><i/><div className="validation"><span>验证 · VALIDATE</span><b>2025-01 → 2025-12</b></div><i/><div className="test"><span>测试 · TEST</span><b>2026-01 → 2026-06</b></div></div>
      <div className="leakage-audit"><div><small>时序守卫</small><h3>泄漏审计通过</h3></div><p><span className="ok">✓ 时序边界</span><span className="ok">✓ 标签延迟 20D</span><span>清除 purge 5D · 禁运 embargo 2D</span></p><button onClick={() => focusContext({ kind: "model-run", eyebrow: "泄漏审计 · LEAKAGE AUDIT", title: "数据集 / 切分时序守卫", summary: "时序边界、标签延迟、purge 与 embargo 证据已映射到当前输入契约。", facts: [{ label: "切分方案 · SplitPlan", value: split }, { label: "清除 · Purge", value: "5D" }, { label: "禁运 · Embargo", value: "2D" }], provenance: "DeterministicFrontendDemoProvider/v1", trace: "dataset.locked → split.guarded → inspector.explained" })}>检查证据</button></div>
      <div className="stage-next"><span>输入契约完整 · 可进入模型配置</span><button className="primary" onClick={onNext}>继续配置 <Icon name="chevron" size={14}/></button></div>
    </div>
  </div>;
}

function ModelConfigurePanel({ onNext }: { onNext: () => void }) {
  const model = useWorkbench((state) => state.model);
  const setFamily = useWorkbench((state) => state.setModelFamily);
  return <div className="model-stage configure-stage" data-major-panel>
    <div className="stage-intro"><small>02 · 运行配置</small><h2>选择模型族与训练守卫</h2><p>七类模型族共享相同的版本、审计与运行契约；参数只影响当前开发运行配置。</p><TruthMark detail="开发配置 · Demo configuration"/></div>
    <div className="configure-canvas primary-canvas" data-primary-canvas>
      <div className="family-selector"><small>模型族 · MODEL FAMILY</small><h3>{model.family}</h3><select aria-label="模型族" value={model.family} onChange={(event) => setFamily(event.target.value as typeof model.family)}>{modelFamilies.map((family) => <option data-model-family={family} key={family}>{family}</option>)}</select><div className="family-list">{modelFamilies.map((family, index) => <button key={family} className={model.family === family ? "active" : ""} onClick={() => setFamily(family)}><i>{String(index + 1).padStart(2,"0")}</i><span>{family}</span></button>)}</div></div>
      <div className="parameter-sheet"><div className="section-head"><div><small>训练契约</small><h2>{model.family} / demo-run-config-v5</h2></div><span className="state">草案 · DRAFT</span></div><div className="parameter-grid"><label>学习率 · learning_rate<input type="number" defaultValue="0.028" step="0.001"/></label><label>叶节点数 · num_leaves<input type="number" defaultValue="31"/></label><label>最大深度 · max_depth<input type="number" defaultValue="8"/></label><label>目标函数 · objective<select><option>rank_xendcg</option><option>regression_l2</option></select></label><label>随机种子 · seed<input type="number" defaultValue="20260809"/></label><label>提前停止 · early_stopping<input type="number" defaultValue="50"/></label></div><div className="guard-lines"><span className="ok">✓ 确定性种子</span><span className="ok">✓ 特征模式已锁定</span><span className="ok">✓ 运行预算 45 分钟</span></div><div className="config-lineage"><small>配置来源链 · CONFIG LINEAGE</small><code>{model.datasetVersion} → {model.splitPlan} → {model.family} → demo-run-config-v5</code></div><div className="stage-next"><span>配置守卫完整 · 尚未产生正式模型输出</span><button className="primary" onClick={onNext}>创建开发运行 <Icon name="chevron" size={14}/></button></div></div>
    </div>
  </div>;
}

export function ModelRunsPanel() { return <ModelRunsContent/>; }

function ModelRunsContent({ onCompare }: { onCompare?: () => void }) {
  const model = useWorkbench((state) => state.model);
  const toggle = useWorkbench((state) => state.toggleRun);
  const [compareReceipt, setCompareReceipt] = useState("选择运行后可进行上下文比较");
  return <div className="model-stage run-stage" data-major-panel>
    <div className="stage-intro"><small>03 · 运行 / 产物</small><h2>运行并检查候选产物</h2><p>{model.datasetVersion}<br/>{model.family} · {model.splitPlan}</p><TruthMark detail="确定性运行"/></div>
    <div className="run-comparison primary-canvas" data-primary-canvas>
      <div className="section-head"><div><small>运行 / 产物</small><h2>试验 · Study S-014 · 候选运行</h2></div><b>已选 {model.selectedRunIds.length}</b></div>
      <div className="grid-head run"><span></span><span>运行 · RUN</span><span>模型族</span><span>排序 IC</span><span>状态</span><span>耗时</span></div>
      {runs.map((run) => <button className={`run-row ${model.selectedRunIds.includes(run.id) ? "selected" : ""}`} onClick={() => toggle(run.id)} key={run.id}><span>{model.selectedRunIds.includes(run.id) ? "●" : "○"}</span><b>{run.id}</b><span>{run.family}</span><span>{run.score}</span><span className={run.state === "BEST" ? "ok" : ""}>{run.state}</span><span>{run.duration}</span></button>)}
      <div className="run-detail"><div><small>已选运行</small><h3>{model.selectedRunIds[0] ?? "未选择运行"}</h3></div><dl><dt>参数 · Params</dt><dd>leaves=31 · lr=0.028 · depth=8</dd><dt>产物 · Artifacts</dt><dd>metrics.json · feature-importance</dd><dt>可用时间</dt><dd>2026-06-30 18:42 CST</dd></dl><div className="detail-action"><button onClick={() => { setCompareReceipt(model.selectedRunIds.length ? `比较上下文已就绪 · 已选 ${model.selectedRunIds.length}` : "请先选择至少一个运行"); if (model.selectedRunIds.length) onCompare?.(); }} disabled={model.selectedRunIds.length === 0}>比较候选</button><span role="status" aria-live="polite">{compareReceipt}</span></div></div>
    </div>
  </div>;
}

function ModelComparePanel({ onVersion }: { onVersion: () => void }) {
  const model = useWorkbench((state) => state.model);
  const ids = model.selectedRunIds.length ? model.selectedRunIds : ["RUN-018", "RUN-017"];
  return <div className="model-stage compare-stage" data-major-panel><div className="stage-intro"><small>05 · 候选比较</small><h2>用同一证据窗比较候选</h2><p>指标、稳定性、延迟与来源链 · lineage 使用统一尺度；比较不会产生正式模型版本。</p><TruthMark detail="开发比较 · Demo comparison"/></div><div className="compare-canvas primary-canvas" data-primary-canvas><div className="section-head"><div><small>运行比较</small><h2>{ids.join("  /  ")}</h2></div><span>{ids.length} 个候选</span></div><MetricRail items={[{ label: "最佳排序 IC", value: "0.084", tone: "positive" }, { label: "稳定性", value: "0.87" }, { label: "覆盖率", value: "96.8%" }, { label: "延迟", value: "42 ms" }]}/><div className="compare-plot"><div className="radar-placeholder"><span>排序 IC</span><span>稳定性</span><span>覆盖率</span><span>延迟</span><i/></div><div className="compare-table"><div><span>候选</span><span>排序 IC</span><span>漂移</span><span>决策</span></div>{ids.map((id,index) => <button key={id}><b>{id}</b><span>{index === 0 ? "0.084" : "0.079"}</span><span>{index === 0 ? "0.04" : "0.06"}</span><span className={index === 0 ? "ok" : "muted"}>{index === 0 ? "晋级 · PROMOTE" : "保留 · RETAIN"}</span></button>)}</div></div><div className="stage-next"><span>RUN-018 满足开发晋级门槛</span><button className="primary" onClick={onVersion}>审阅版本与信号 <Icon name="chevron" size={14}/></button></div></div></div>;
}

export function ModelStudyPanel() {
  const model = useWorkbench((state) => state.model);
  const setState = useWorkbench((state) => state.setModelState);
  const [view, setView] = useState("Trial History");
  const [receipt, setReceipt] = useState("就绪 · ready");
  const act = async (name: "study.resume" | "study.pause" | "study.cancel" | "study.checkpoint", next: typeof model.studyState) => {
    const id = `${name}-checkpoint-${model.checkpoint}`;
    const result = await commandRegistry.execute(name, id);
    setReceipt(`${result.id} · ${result.duplicate ? "重复已抑制 · DUPLICATE SUPPRESSED" : "仅执行一次 · EXECUTED ONCE"} · 次数=${result.executionCount}`);
    if (!result.duplicate) setState(next);
  };
  const views = ["Trial History", "Importance", "Relationships", "Parallel Coordinates", "Pareto"];
  return <div className="study-workflow" data-testid="model-study" data-major-panel>
    <header className="study-head"><div><small>OPTUNA 风格试验 / Trial / HPO</small><h2>试验 · Study S-014 · {model.family}</h2></div><span className={`state ${model.studyState}`}>{studyStateLabel(model.studyState)}</span><span>检查点 #{model.checkpoint}</span><div className="study-actions">{model.studyState === "running" ? <button className="primary" onClick={() => void act("study.pause", "paused")}>Ⅱ 暂停</button> : <button className="primary" onClick={() => void act("study.resume", "running")}>▶ 继续</button>}<button onClick={() => void act("study.checkpoint", "checkpointed")} disabled={model.studyState === "cancelled"}>◆ 建立检查点</button><button className="danger" onClick={() => void act("study.cancel", "cancelled")} disabled={model.studyState === "cancelled"}>× 取消</button></div></header>
    <div className="mini-tabs" role="tablist" aria-label="试验分析视图">{views.map((item) => <button role="tab" aria-selected={item === view} className={item === view ? "active" : ""} onClick={() => setView(item)} key={item}>{studyViewLabel(item)}</button>)}</div>
    <div className="study-viz primary-canvas" data-primary-canvas><div className="trial-chart">{Array.from({ length: 24 }, (_, index) => <i key={index} className={index > 17 ? "pending" : index === 17 ? "best" : ""} style={{ height: `${22 + ((index * 19) % 72)}%` }} title={`试验 · Trial ${index + 1}`} />)}</div><aside><span className="truth-line"><i /> 开发 HPO</span><h3>{studyViewLabel(view)}</h3><p>24 个 Trial · 完成 18 · 剪枝 2 · 检查点 1 · 排队 3</p><dl><dt>最佳 Trial</dt><dd>T-018 / 排序 IC 0.084</dd><dt>主要重要性</dt><dd>learning_rate · num_leaves</dd><dt>Pareto 轴</dt><dd>排序 IC ↑ / 延迟 ↓</dd></dl></aside></div>
    <div className="command-receipt" role="status" aria-live="polite"><b>命令注册表仅执行一次 · CommandRegistry exactly-once</b><code>{receipt}</code></div>
  </div>;
}

export function ModelVersionPanel() {
  const model = useWorkbench((state) => state.model);
  const [tab, setTab] = useState<"ModelVersion" | "Signal">("ModelVersion");
  const [handoffReceipt, setHandoffReceipt] = useState("Backtest handoff 尚未创建");
  return <div className="version-workflow" data-major-panel>
    <div className="mini-tabs" role="tablist" aria-label="版本与信号视图"><button role="tab" aria-selected={tab === "ModelVersion"} data-model-version-tab="model" className={tab === "ModelVersion" ? "active" : ""} onClick={() => setTab("ModelVersion")}>不可变模型版本 · ModelVersion</button><button role="tab" aria-selected={tab === "Signal"} data-model-version-tab="signal" className={tab === "Signal" ? "active" : ""} onClick={() => setTab("Signal")}>预测信号版本 · PredictionSignalVersion</button></div>
    {tab === "ModelVersion" ? <div className="version-review primary-canvas" data-primary-canvas><div className="version-identity"><span className="lock">◆ 不可变 · IMMUTABLE</span><small>模型版本 · MODEL VERSION</small><h2>{model.modelVersion}</h2><code>content-sha256: demo:8b32…7c91</code></div><div className="version-metrics"><Metric k="排序 IC" v="0.084"/><Metric k="覆盖率" v="96.8%"/><Metric k="泄漏检查" v="通过 · PASS"/><Metric k="模型族" v={model.family}/></div><div className="lineage-flow"><span>{model.datasetVersion}</span><i>→</i><span>{model.splitPlan}</span><i>→</i><span>RUN-018</span><i>→</i><span>{model.modelVersion}</span></div></div> : <div className="signal-review primary-canvas" data-primary-canvas><div><span className="truth-line"><i /> 开发信号</span><small>预测信号版本 · PREDICTION SIGNAL VERSION</small><h2>{model.predictionSignalVersion}</h2><p>由不可变 ModelVersion 派生的版本化信号；质量守卫与来源链保持可见。</p></div><div className="quality-grid"><span><b>0.91</b>完整性</span><span><b>0.87</b>稳定性</span><span><b>0.04</b>漂移</span><span><b>96.8%</b>覆盖</span></div><div className="handoff-line"><span>{model.modelVersion}</span><i>→</i><span>{model.predictionSignalVersion}</span><i>→</i><button className="primary" onClick={() => setHandoffReceipt("BacktestHandoffDraft/demo-v8 已在前端开发会话中就绪")}>交接到回测草案 · BacktestHandoffDraft</button></div><span className="action-receipt handoff-receipt" role="status" aria-live="polite">{handoffReceipt}</span></div>}
  </div>;
}

function Metric({ k, v }: { k: string; v: string }) { return <div><small>{k}</small><b>{v}</b></div>; }

function studyViewLabel(value: string): string {
  return ({ "Trial History": "试验历史", Importance: "重要性", Relationships: "参数关系", "Parallel Coordinates": "平行坐标", Pareto: "帕累托" } as Record<string, string>)[value] ?? value;
}

function studyStateLabel(value: string): string {
  return ({ running: "运行中 · RUNNING", paused: "已暂停 · PAUSED", checkpointed: "已建立检查点 · CHECKPOINTED", cancelled: "已取消 · CANCELLED" } as Record<string, string>)[value] ?? value.toUpperCase();
}
